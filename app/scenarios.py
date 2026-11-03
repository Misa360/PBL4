"""Bounded read-only catalog access and validated scenario replay."""
import json
from pathlib import Path
from optimizer.models import Demand, finite
from optimizer.network import Network
from optimizer.problem import Problem
from optimizer.service import OptimizerSession

ROOT = Path(__file__).resolve().parent.parent/'outputs/global-scenarios'
_cache = None


def records():
    global _cache
    path = ROOT/'index.json'
    if not path.is_file():
        return []
    stamp = (str(path.resolve()),path.stat().st_mtime_ns,path.stat().st_size)
    if _cache is None or _cache[0] != stamp:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != 1:
            raise ValueError('Unsupported scenario index')
        _cache = (stamp,data['scenarios'])
    return _cache[1]


def listing(method='',offset=0,limit=50):
    if method not in ('','random','greedy','min_delay','energy','aco_pso'):
        raise ValueError('Unknown scenario method filter')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid scenario page')
    selected = [r for r in records() if not method or method in r['methods']]
    fields = ('scenario_id','id','network','nodes','battery','load','pair','mb','mbps','time_s','methods')
    return dict(total=len(selected),scenarios=[{k:r[k] for k in fields} for r in selected[offset:offset+limit]])


def load(scenario_id):
    if not isinstance(scenario_id,str) or len(scenario_id) != 64:
        raise ValueError('Choose a valid scenario')
    entry = next((r for r in records() if r['scenario_id']==scenario_id),None)
    if entry is None:
        raise ValueError('Scenario not found in current distributed catalog')
    source = (ROOT/entry['file']).resolve()
    if not source.is_relative_to(ROOT.resolve()) or source.suffix != '.jsonl':
        raise ValueError('Invalid scenario source')
    offset = entry['offset']
    if type(offset) is not int or not 0 <= offset < source.stat().st_size:
        raise ValueError('Invalid scenario offset')
    with source.open('rb') as stream:
        stream.seek(offset)
        row = json.loads(stream.readline(8*1024*1024))
    if row['scenario_id'] != scenario_id:
        raise ValueError('Scenario index is stale; regenerate the catalog')
    config = row['config']
    if config.get('deployment') != 'distributed' or config.get('constellation') not in ('compact','balanced','dense'):
        raise ValueError('Only current distributed scenarios can be loaded')
    session = OptimizerSession(**config)
    network = session.network
    network.time_s = finite(row['state']['time_s'],'time_s',0,86400)
    nodes = {n['id']:n for n in row['state']['nodes']}
    if len(nodes) != len(row['state']['nodes']) or set(nodes) != set(network.nodes):
        raise ValueError('Scenario node set does not match its configuration')
    for key,node in network.nodes.items():
        saved = nodes[key]
        if node.battery_j is None:
            if saved['battery_j'] is not None:
                raise ValueError('Invalid battery on grid-powered node')
        else:
            node.battery_j = finite(saved['battery_j'],'battery_j',0,node.battery_capacity_j)
        for field in ('reserved_bandwidth_hz','predicted_reserved_bandwidth_hz'):
            setattr(node,field,finite(saved.get(field,0),field,0,node.bandwidth_hz))
    demand = Demand(**row['request'])
    Problem(network,demand)  # Validate station identities before replacing the active session.
    seed = row['teacher_runs'][0]['seed']
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('Invalid scenario algorithm seed')
    return session,dict(scenario_id=scenario_id,request=row['request'],seed=seed,split=row['split'])
