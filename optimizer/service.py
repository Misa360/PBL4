"""Search is read-only; revision-bound plans are committed exactly once."""
import copy
import math
import random
import time
import uuid
from dataclasses import asdict
from .models import Budget, Demand, finite
from .network import Network
from .problem import Problem, result_key
from .diagnostics import explain
from .baselines import path_for
from .aco import search as aco_search
from .pso import search as pso_search

# pso is a backwards-compatible alias of widest_pso, excluded from comparisons.
METHODS = ('random', 'greedy', 'min_hops', 'shortest_distance', 'min_delay',
           'widest', 'energy', 'aco', 'widest_pso', 'energy_pso', 'aco_pso', 'ai_aco_pso')


def optimize(network, demand, method='aco', seed=42, budget=None, hint_policy=None):
    if method not in METHODS and method != 'pso':
        raise ValueError('Unknown optimization method')
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('seed must be integer in [0, 2147483647]')
    budget = budget or Budget()
    problem, rng = Problem(network, demand), random.Random(seed)
    started = time.perf_counter()
    aco_history, pso_histories, pheromone = [], [], []
    evaluations = 0
    hints, ai_info = [], None
    if method == 'ai_aco_pso':
        from ai.policy import hints as generate_hints
        hint_start = time.perf_counter()
        hints, ai_info = generate_hints(problem, seed, policy=hint_policy)
        ai_info['inference_ms'] = (time.perf_counter()-hint_start)*1000
        # Large training provenance stays in the checkpoint, not every API response.
        ai_info.pop('model', None)
    if method.startswith('aco') or method == 'ai_aco_pso':
        candidates, aco_history, pheromone, evaluations = aco_search(problem, rng, budget, hints)
        if hints:
            by_path = {tuple(r['path']): r for r in candidates}
            for hint in hints:
                key = tuple(hint['path'])
                if key not in by_path or result_key(hint) < result_key(by_path[key]):
                    by_path[key] = hint
            candidates = sorted(by_path.values(), key=result_key)[:budget.candidates]
        if ai_info is not None:
            evaluations += ai_info.get('generated', 0)
    else:
        path = path_for(problem, 'widest' if method == 'pso' else method.replace('_pso', ''), rng)
        candidates = [problem.evaluate(path)] if path else []
        evaluations = len(candidates)
    best = min(candidates, key=result_key) if candidates else problem.evaluate([])
    before_refinement=best
    search_history=[dict(phase='ACO',candidate=0,iteration=h['iteration'],cost=h['cost']) for h in aco_history]
    incumbent=best['cost']
    if hints:
        search_history.append(dict(phase='AI',candidate=0,iteration=0,cost=incumbent))
    if method == 'pso' or method.endswith('_pso'):
        for candidate in candidates:
            hint = next((h for h in hints if h['path'] == candidate['path']), None)
            result, history, count = pso_search(problem, candidate['path'], rng, budget, hint)
            evaluations += count
            pso_histories.append({'path': candidate['path'], 'history': history})
            for entry in history:
                if entry['cost'] is not None:
                    incumbent=entry['cost'] if incumbent is None else min(incumbent,entry['cost'])
                search_history.append(dict(phase='PSO',candidate=len(pso_histories),iteration=entry['iteration'],cost=incumbent))
            if result_key(result) < result_key(best):
                best = result
    initial_cost=before_refinement['cost']
    improvement=100*(initial_cost-best['cost'])/initial_cost if initial_cost and best['feasible'] else None
    refinement=dict(initial_cost=initial_cost,final_cost=best['cost'],cost_improvement_pct=improvement,
        changed_path=before_refinement['path']!=best['path'],
        changed_power=before_refinement.get('power')!=best.get('power'),
        changed_bandwidth=before_refinement.get('bandwidth')!=best.get('bandwidth'))
    if ai_info is not None:
        ai_info['final_path_matches_hint']=any(h['path']==best['path'] for h in hints)
    return {**best, 'method': method, 'seed': seed, 'request': asdict(demand),
            'revision': network.revision, 'snapshot_time_s': network.time_s,
            'elapsed_ms': (time.perf_counter()-started)*1000, 'evaluations': evaluations,
            'aco_history': aco_history, 'pso_histories': pso_histories,
            'pheromone': pheromone, 'budget': asdict(budget), 'ai': ai_info,
            'refinement':refinement,'search_history':search_history,'issues':explain(problem,best)}


class OptimizerSession:
    def __init__(self, **config):
        self.network = Network(**config)
        self.plans = {}
        self.log = []
        self.served = 0
        self.data_bits = 0
        self.first_reserve_s = None
        self.first_empty_s = None

    def snapshot(self):
        return {**self.network.snapshot(), 'served': self.served, 'data_bits': self.data_bits,
                'first_reserve_s': self.first_reserve_s, 'first_empty_s': self.first_empty_s,
                'transfers': self.log[-100:]}

    def search(self, demand, method='aco', seed=42, budget=None):
        result = optimize(self.network, demand, method, seed, budget)
        token = uuid.uuid4().hex
        result['plan_id'] = token
        self.plans[token] = copy.deepcopy(result)
        while len(self.plans) > 12:
            del self.plans[next(iter(self.plans))]
        return result

    def _debit(self, energy, elapsed):
        start = self.network.time_s
        for key, node in self.network.nodes.items():
            if node.battery_j is None:
                continue
            before = node.battery_j
            used = min(before, energy.get(key, 0))
            node.battery_j = max(0, before-used)
            # Batched transfer accounting: report the interval endpoint, not an invented exact crossing time.
            if before > node.battery_capacity_j*self.network.reserve_fraction >= node.battery_j:
                if self.first_reserve_s is None:
                    self.first_reserve_s = start+elapsed
            if before > 0 and node.battery_j == 0 and self.first_empty_s is None:
                self.first_empty_s = start+elapsed
        self.network.time_s += elapsed
        self.network.revision += 1
        self.plans.clear()

    def advance(self, seconds):
        finite(seconds, 'seconds', .001, 600)
        self._debit({k: n.base_power_w*seconds for k, n in self.network.nodes.items()}, seconds)
        self.network.observe_interval(seconds,evolve_background=True)
        return self.snapshot()

    def transmit(self, plan_id):
        if not isinstance(plan_id, str) or plan_id not in self.plans:
            raise ValueError('Plan is missing or already used; optimize again')
        plan = self.plans[plan_id]
        if plan['revision'] != self.network.revision or not plan['feasible']:
            raise ValueError('Plan is stale or infeasible; optimize again')
        problem = Problem(self.network, Demand(**plan['request']))
        result = problem.evaluate(plan['path'], plan['power'], plan['bandwidth'])
        if not result['feasible']:
            raise ValueError('Resources have changed; optimize again')
        # Validate each scheduled hop against moving topology every <=0.5 simulated second.
        for segment in result['segments']:
            duration = segment['arrival_s']-segment['start_s']
            steps = max(1, math.ceil(duration/.5))
            for i in range(steps+1):
                t = self.network.time_s+segment['start_s']+duration*i/steps
                if (segment['source'], segment['target']) not in self.network.edges(t):
                    raise ValueError('Link leaves coverage during transfer; reduce data size or optimize at a different time')
        before = {key:node.battery_j for key,node in self.network.nodes.items() if node.battery_j is not None}
        record = {'id': self.served+1, 'method': plan['method'], 'path': plan['path'],
                  'started_s': self.network.time_s, 'duration_s': result['duration_s'],
                  'data_bits': problem.demand.bits, 'energy_j': result['energy_j'], 'segments': result['segments']}
        self._debit(result['energy_by_node_j'], result['duration_s'])
        self.network.observe_interval(result['duration_s'],result['segments'])
        record['battery_changes']=[dict(id=key,before_j=value,after_j=self.network.nodes[key].battery_j,
            used_j=value-self.network.nodes[key].battery_j) for key,value in before.items()]
        record['battery_used_j']=sum(item['used_j'] for item in record['battery_changes'])
        self.served += 1; self.data_bits += problem.demand.bits; self.log.append(record)
        self.log = self.log[-100:]
        return {'state': self.snapshot(), 'transfer': record}
