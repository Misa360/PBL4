"""Conditional autoregressive MLP policy. Standard library, no runtime dependencies.

Samples next-hop and discrete radio actions; trains by imitation and REINFORCE.
This is a one-step contextual-bandit optimizer, not a temporal traffic RL model.
"""
import json
import math
import random
from collections import defaultdict
from collections import deque
from pathlib import Path

from optimizer.models import capacity

FEATURES = 21
HIDDEN = 16
POWER = (.15, .4, .7, 1.)
BANDWIDTH = (.25, .5, 1.)
MODEL_PATH = Path(__file__).resolve().parent / 'checkpoints' / 'policy.json'


def route_options(problem, path):
    """Mask dead ends: a candidate must still reach the target within 8 hops."""
    cache = getattr(problem, '_route_option_cache', None)
    if cache is None:
        cache = problem._route_option_cache = {}
    key = tuple(path)
    if key in cache:
        return cache[key]
    blocked = set(path)
    reverse = defaultdict(list)
    for a, neighbors in problem.adjacency.items():
        if a not in blocked:
            for b in neighbors:
                if b not in blocked:
                    reverse[b].append(a)
    target = problem.demand.target
    distance, queue = {target: 0}, deque([target])
    while queue:
        b = queue.popleft()
        for a in reverse[b]:
            if a not in distance:
                distance[a] = distance[b]+1
                queue.append(a)
    remaining = 8-len(path)
    options = [b for b in problem.adjacency[path[-1]]
               if b not in blocked and distance.get(b, 1000) <= remaining]
    if len(cache) > 2048:
        cache.clear()
    cache[key] = options
    return options


def softmax(values):
    top = max(values)
    weights = [math.exp(max(-60, v-top)) for v in values]
    return [v/sum(weights) for v in weights]


def features(problem, a, b):
    cache = getattr(problem, '_ai_feature_cache', None)
    if cache is None:
        cache = problem._ai_feature_cache = {}
    if (a,b) in cache:
        return cache[a,b]
    nodes, demand = problem.network.nodes, problem.demand
    src, dst = nodes[a], nodes[b]
    edge = problem.edges[a, b]
    target = nodes[demand.target].coordinates(problem.network.time_s)
    pos = dst.coordinates(problem.network.time_s)
    rate = capacity(min(src.planning_bandwidth_hz, dst.planning_bandwidth_hz)/2, src.p_max_w, edge.gain)
    result = [math.log10(max(1, edge.distance_m))/8,
            (math.log10(max(1e-30, edge.gain))+20)/20,
            math.log10(max(1, rate))/9, src.battery_fraction, dst.battery_fraction,
            math.dist(pos, target)/1e8, float(b == demand.target),
            float(dst.kind == 'UAV'), float(dst.kind == 'LEO'),
            float(dst.kind in ('MEO', 'GEO')), math.log10(demand.data_mb)/4,
            math.log10(demand.required_mbps)/3, demand.energy_weight,
            demand.latency_weight, problem.network.reserve_fraction,
            src.available_bandwidth_hz/src.bandwidth_hz,
            dst.available_bandwidth_hz/dst.bandwidth_hz,
            1. if src.battery_j is None else math.log10(1+src.battery_j)/7,
            1. if dst.battery_j is None else math.log10(1+dst.battery_j)/7,
            src.predicted_reserved_bandwidth_hz/src.bandwidth_hz,
            dst.predicted_reserved_bandwidth_hz/dst.bandwidth_hz]
    cache[a,b] = result
    return result


class Policy:
    def __init__(self, seed=1):
        rng = random.Random(seed)
        self.w = [[rng.uniform(-.15, .15) for _ in range(FEATURES)] for _ in range(HIDDEN)]
        self.b = [0.] * HIDDEN
        self.v = [[rng.uniform(-.15, .15) for _ in range(HIDDEN)] for _ in range(8)]
        self.c = [0.] * 8
        self.metadata = {}

    def forward(self, x):
        if len(x) != FEATURES or not all(math.isfinite(v) for v in x):
            raise ValueError('Invalid AI feature vector')
        h = [math.tanh(sum(a*b for a, b in zip(row, x))+bias)
             for row, bias in zip(self.w, self.b)]
        return [sum(a*b for a, b in zip(row, h))+bias for row, bias in zip(self.v, self.c)], h

    def update(self, x, gradients, lr):
        _, hidden = self.forward(x)
        dh = [sum(gradients[k]*self.v[k][j] for k in range(8))*(1-hidden[j]**2)
              for j in range(HIDDEN)]
        for k, gradient in enumerate(gradients):
            gradient = max(-5, min(5, gradient))
            for j in range(HIDDEN):
                self.v[k][j] -= lr*gradient*hidden[j]
            self.c[k] -= lr*gradient
        for j in range(HIDDEN):
            for i in range(FEATURES):
                self.w[j][i] -= lr*dh[j]*x[i]
            self.b[j] -= lr*dh[j]

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name+'.tmp')
        temporary.write_text(json.dumps(dict(version=2, architecture=[FEATURES, HIDDEN, 8],
                                            w=self.w, b=self.b, v=self.v, c=self.c,
                                            metadata=self.metadata), allow_nan=False), encoding='utf-8')
        temporary.replace(path)

    @classmethod
    def load(cls, path=MODEL_PATH):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data['version'] != 2 or data['architecture'] != [FEATURES, HIDDEN, 8]:
            raise ValueError('Incompatible AI checkpoint')
        obj = cls()
        for key, shape in [('w', (HIDDEN, FEATURES)), ('v', (8, HIDDEN))]:
            if len(data[key]) != shape[0] or any(len(row) != shape[1] for row in data[key]):
                raise ValueError('Invalid AI checkpoint shape')
        for key, length in [('b', HIDDEN), ('c', 8)]:
            if len(data[key]) != length:
                raise ValueError('Invalid AI checkpoint bias')
        for key in ('w', 'b', 'v', 'c'):
            values = data[key] if key in ('b', 'c') else [n for row in data[key] for n in row]
            if not all(isinstance(n, (float, int)) and math.isfinite(n) for n in values):
                raise ValueError('Nonfinite AI checkpoint')
            setattr(obj, key, data[key])
        obj.metadata = data.get('metadata', {})
        return obj

    def generate(self, problem, rng, count=8):
        results = []
        # Weights are fixed throughout this sampling batch; repeated edges
        # share logits. Never retain logits across training updates.
        logit_cache = {}
        for _ in range(count):
            path, powers, bandwidth, trace = [problem.demand.source], [], [], []
            while len(path) < 9 and path[-1] != problem.demand.target:
                a = path[-1]
                options = route_options(problem, path)
                if not options:
                    break
                xs = [features(problem, a, b) for b in options]
                logits = []
                for b, x in zip(options, xs):
                    if (a,b) not in logit_cache:
                        logit_cache[a,b] = self.forward(x)[0]
                    logits.append(logit_cache[a,b])
                route_probs = softmax([v[0] for v in logits])
                chosen = rng.choices(range(len(options)), route_probs)[0]
                pprobs, bprobs = softmax(logits[chosen][1:5]), softmax(logits[chosen][5:8])
                pi = rng.choices(range(4), pprobs)[0]
                bi = rng.choices(range(3), bprobs)[0]
                trace.append((xs, route_probs, chosen, pprobs, pi, bprobs, bi))
                b = options[chosen]
                powers.append(POWER[pi]*problem.network.nodes[a].p_max_w)
                bandwidth.append(BANDWIDTH[bi]*min(problem.network.nodes[a].planning_bandwidth_hz,
                                                   problem.network.nodes[b].planning_bandwidth_hz))
                path.append(b)
            incident = defaultdict(list)
            for i, (a, b) in enumerate(zip(path, path[1:])):
                incident[a].append(i)
                incident[b].append(i)
            for node, indexes in incident.items():
                factor = min(1, problem.network.nodes[node].planning_bandwidth_hz/sum(bandwidth[i] for i in indexes))
                for i in indexes:
                    bandwidth[i] *= factor
            results.append((problem.evaluate(path, powers, bandwidth), trace))
        return results

    def reinforce(self, trace, advantage, lr=.002):
        # Gradient descent on -advantage * log probability of sampled actions.
        for xs, probs, chosen, pp, pi, bp, bi in trace:
            for index, x in enumerate(xs):
                gradient = [0.] * 8
                gradient[0] = advantage*(probs[index]-int(index == chosen))
                if index == chosen:
                    gradient[1:5] = [advantage*(v-int(i == pi)) for i, v in enumerate(pp)]
                    gradient[5:8] = [advantage*(v-int(i == bi)) for i, v in enumerate(bp)]
                self.update(x, gradient, lr)


def hints(problem, seed, count=8, policy=None):
    try:
        policy = policy or Policy.load()
    except (OSError, ValueError, KeyError, TypeError):
        return [], {'status': 'fallback', 'reason': 'AI checkpoint missing or invalid'}
    generated = policy.generate(problem, random.Random(seed), count)
    feasible = [result for result, _ in generated if result['feasible']]
    distinct = {(tuple(r['path']),tuple(r['power']),tuple(r['bandwidth'])):r for r in feasible}
    valid = sorted(distinct.values(), key=lambda r: r['score'])
    return valid, {'status': 'ready' if valid else 'fallback', 'generated': count,
                   'feasible_samples':len(feasible), 'feasible_hints': len(valid), 'model': policy.metadata}
