"""Seeded ant-colony routing. No energy mutation occurs during search."""
from .baselines import path_for
from .models import capacity
from .problem import result_key


def search(problem, rng, budget, hints=None):
    pheromone = {key: 1.0 for key in problem.edges}
    candidates = {}
    evaluations = 0
    history = []
    # Topology, demand and batteries are frozen for this search. Compute radio
    # heuristics once, rather than repeating Shannon/logarithms for every ant.
    heuristic = {}
    for a, b in problem.edges:
        node, nxt = problem.network.nodes[a], problem.network.nodes[b]
        rate = capacity(min(node.planning_bandwidth_hz, nxt.planning_bandwidth_hz)/2,
                        node.p_max_w, problem.edges[a,b].gain)
        joules = problem.demand.bits/rate*(node.p_max_w/node.amplifier_efficiency+node.tx_circuit_w+nxt.rx_power_w)
        heuristic[a,b] = (rate/1e6)*max(.001,nxt.battery_fraction)/max(1e-9,joules)

    def remember(path):
        nonlocal evaluations
        if not path:
            return None
        key = tuple(path)
        if key not in candidates:
            candidates[key] = problem.evaluate(path)
            evaluations += 1
        return candidates[key]

    # Deterministic seeds make search robust, but remain visible in the documentation.
    for method in ('widest', 'energy'):
        remember(path_for(problem, method, rng))
    for hint in hints or []:
        remember(hint['path'])
        for edge in zip(hint['path'], hint['path'][1:]):
            if edge in pheromone:
                pheromone[edge] = min(10, pheromone[edge]+2)
    initial=min(candidates.values(),key=result_key) if candidates else None
    history.append(dict(iteration=0,cost=initial['cost'] if initial else None,
                        score=initial['score'] if initial else None,routes_seen=len(candidates)))
    for iteration in range(1,budget.aco_iterations+1):
        colony = []
        for _ant in range(budget.ants):
            path = [problem.demand.source]
            while len(path) < 9 and path[-1] != problem.demand.target:
                a = path[-1]
                options = [n for n in problem.adjacency[a] if n not in path]
                if not options:
                    break
                if problem.demand.target in options:
                    path.append(problem.demand.target); break
                values = [heuristic[a,b] for b in options]
                scale = max(values)
                weights = [pheromone[a, b]*(eta/scale)**2 for b, eta in zip(options, values)]
                choice = rng.choices(options, weights=weights, k=1)[0]
                path.append(choice)
            if path[-1] == problem.demand.target:
                result = remember(path)
                colony.append(result)
        for edge in pheromone:
            pheromone[edge] = max(1e-6, pheromone[edge]*.7)
        ranked = sorted(candidates.values(), key=result_key)
        for result in ranked[:budget.candidates]:
            deposit = 1/max(.01, result['score'])
            for edge in zip(result['path'], result['path'][1:]):
                pheromone[edge] = min(100, pheromone[edge]+deposit)
        best = ranked[0] if ranked else None
        history.append({'iteration': iteration, 'cost': best['cost'] if best else None,
                        'score': best['score'] if best else None,'routes_seen':len(candidates)})
    ranked = sorted(candidates.values(), key=result_key)
    return ranked[:budget.candidates], history, [
        {'source': a, 'target': b, 'value': value} for (a, b), value in pheromone.items()], evaluations
