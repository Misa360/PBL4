import heapq
import math
from collections import deque
from .models import capacity, LIGHT_M_S


def path_for(problem, method, rng):
    source, target = problem.demand.source, problem.demand.target
    if method in ('random', 'greedy'):
        path = [source]
        # A random/nearest walk may fail; that failure is included in experiment results.
        while len(path) < 9 and path[-1] != target:
            options = [n for n in problem.adjacency[path[-1]] if n not in path]
            if not options:
                return []
            if target in options:
                nxt = target
            elif method == 'random':
                nxt = rng.choice(options)
            else:
                nxt = min(options, key=lambda n: problem.edges[path[-1], n].distance_m)
            path.append(nxt)
        return path if path[-1] == target else []
    if method == 'min_hops':
        queue = deque([[source]])
        visited = {source}
        while queue:
            path = queue.popleft()
            if path[-1] == target:
                return path
            for nxt in problem.adjacency[path[-1]]:
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(path + [nxt])
        return []
    if method not in ('widest', 'energy', 'shortest_distance', 'min_delay'):

        raise ValueError('Unknown baseline')
    widest = method == 'widest'
    best = {source: math.inf if widest else 0}
    previous = {}
    heap = [(-math.inf if widest else 0, source)]
    visited = set()
    while heap:
        _, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        if node == target:
            path = [target]
            while path[-1] != source:
                path.append(previous[path[-1]])
            return path[::-1]
        for nxt in problem.adjacency[node]:
            if nxt in visited:
                continue
            a, b = problem.network.nodes[node], problem.network.nodes[nxt]
            edge = problem.edges[node, nxt]
            bw = min(a.planning_bandwidth_hz, b.planning_bandwidth_hz)/2
            rate = capacity(bw, a.p_max_w, edge.gain)
            # Fixed-allocation surrogate; all final paths use the common evaluator.
            if widest:
                value = min(best[node], rate)
            elif method == 'shortest_distance':
                value = best[node] + edge.distance_m
            elif method == 'min_delay':
                value = best[node] + problem.demand.bits/rate + edge.distance_m/LIGHT_M_S
            else:
                value = best[node] + problem.demand.bits/rate*(a.p_max_w/a.amplifier_efficiency+a.tx_circuit_w+b.rx_power_w)
            if nxt not in best or (value > best[nxt] if widest else value < best[nxt]):
                best[nxt] = value; previous[nxt] = node
                heapq.heappush(heap, (-value if widest else value, nxt))
    return []
