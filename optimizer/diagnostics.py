"""Explain the final result once; keep diagnostics out of the search hot loops."""
from collections import defaultdict


def explain(problem, result):
    if result['feasible']:
        return []
    network,demand=problem.network,problem.demand
    path=result.get('path',[])
    if not path:
        seen={demand.source};pending=[demand.source]
        while pending:
            for target in problem.adjacency[pending.pop()]:
                if target not in seen:seen.add(target);pending.append(target)
        return [dict(kind='search_no_route',topology_connected=demand.target in seen)]
    if not result.get('segments'):
        return [dict(kind=result.get('reason','invalid_path'))]
    issues=[]
    achieved=result.get('rate_bps',0)/1e6
    if achieved < demand.required_mbps*(1-1e-9):
        issues.append(dict(kind='rate',actual_mbps=achieved,required_mbps=demand.required_mbps))
    usage=defaultdict(float);power=[]
    for segment in result['segments']:
        source,target=segment['source'],segment['target']
        usage[source]+=segment['bandwidth_hz'];usage[target]+=segment['bandwidth_hz']
        if segment['power_w']>network.nodes[source].p_max_w*(1+1e-9):power.append(source)
    bandwidth=[key for key,value in usage.items() if value>network.nodes[key].planning_bandwidth_hz*(1+1e-9)]
    battery=[]
    for key in path:
        node=network.nodes[key]
        if node.battery_j is not None:
            after=node.battery_j-result['energy_by_node_j'].get(key,0)
            if after < node.battery_capacity_j*network.reserve_fraction-1e-9:
                battery.append(key)
    if bandwidth:issues.append(dict(kind='bandwidth',nodes=bandwidth))
    if battery:issues.append(dict(kind='battery',nodes=battery))
    if power:issues.append(dict(kind='power',nodes=sorted(set(power))))
    if result.get('duration_s',0)>300:issues.append(dict(kind='duration',limit_s=300))
    return issues or [dict(kind='constraint_violation')]
