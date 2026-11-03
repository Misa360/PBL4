"""Bounded PSO with bandwidth projection and exact final feasibility checks."""
from collections import defaultdict
import math
from .problem import result_key


def search(problem, path, rng, budget, hint=None):
    h = len(path)-1
    nodes = problem.network.nodes
    edge_caps = [min(nodes[a].planning_bandwidth_hz, nodes[b].planning_bandwidth_hz) for a, b in zip(path, path[1:])]
    fixed_p, fixed_b = problem.resources(path)
    initial = [1.0]*h + [b/cap for b, cap in zip(fixed_b, edge_caps)]
    incident = defaultdict(list)
    for i, (a,b) in enumerate(zip(path,path[1:])):
        incident[a].append(i); incident[b].append(i)
    node_caps={key:nodes[key].planning_bandwidth_hz for key in incident}

    def decode(x):
        powers = [max(.005, min(1, x[i]))*nodes[path[i]].p_max_w for i in range(h)]
        bandwidth = [max(.005, min(1, x[h+i]))*edge_caps[i] for i in range(h)]
        for node, indexes in incident.items():
            total = sum(bandwidth[i] for i in indexes)
            factor = min(1, node_caps[node]/total)
            for i in indexes:
                bandwidth[i] *= factor
        return powers, bandwidth

    baseline=problem.evaluate(path,fixed_p,fixed_b)
    # Search near the known allocation as well as globally. Independent random
    # coordinates rarely improve an already feasible high-dimensional boundary seed.
    durations=[s['duration_s'] for s in baseline.get('segments',[])]
    anchors=[]
    if h and len(durations)==h:
        mean=sum(durations)/h
        anchors.append([1.]*h+[min(1.,initial[h+i]*math.sqrt(t/mean)) for i,t in enumerate(durations)])
    anchors.extend([[scale]*h+initial[h:] for scale in (.8,.6,.4,.2)])
    for i in range(h):
        local=initial[:];local[i]=.5;anchors.append(local)
    count=min(len(anchors),(budget.particles-1)//2)
    swarm=[initial]+anchors[:count]+[[rng.uniform(.02,1) for _ in range(2*h)]
                                    for _ in range(budget.particles-1-count)]
    if hint is not None and hint['path'] == path:
        warm = [p/nodes[a].p_max_w for a, p in zip(path, hint['power'])] + [b/c for b, c in zip(hint['bandwidth'], edge_caps)]
        for i in range(1, min(len(swarm), max(2, budget.particles//3))):
            swarm[i] = warm[:] if i == 1 else [max(.005, min(1, x+rng.uniform(-.05, .05))) for x in warm]
    velocity = [[0.0]*(2*h) for _ in swarm]
    personal = [x[:] for x in swarm]
    scores = [(True,float('inf'))]*len(swarm)
    best = baseline
    if hint is not None and hint['path'] == path:
        checked = problem.evaluate(path, hint['power'], hint['bandwidth'])
        if result_key(checked) < result_key(best):
            best = checked
    global_x = initial[:]
    if hint is not None and hint['path'] == path and best is checked:
        global_x = warm[:]
    history = [dict(iteration=0,cost=best['cost'],score=best['score'])]
    for iteration in range(budget.pso_iterations):
        for i, x in enumerate(swarm):
            p, b = decode(x)
            result = problem.evaluate(path, p, b)
            if result_key(result) < scores[i]:
                scores[i] = result_key(result); personal[i] = x[:]
            if result_key(result) < result_key(best):
                best, global_x = result, x[:]
        history.append({'iteration': iteration+1, 'cost': best['cost'], 'score': best['score']})
        for i, x in enumerate(swarm):
            for j in range(2*h):
                v = .7*velocity[i][j] + 1.5*rng.random()*(personal[i][j]-x[j]) + 1.5*rng.random()*(global_x[j]-x[j])
                velocity[i][j] = max(-.25, min(.25, v))
                x[j] = max(.005, min(1, x[j]+velocity[i][j]))
    return best, history, budget.particles*budget.pso_iterations+1+int(hint is not None and hint['path'] == path)
