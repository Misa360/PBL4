"""python -m experiments.run --repeats 30 --output outputs/experiments

All methods get identical network states and demand streams for each seed.
Timing is measured separately; infeasible results are never averaged as zero cost.
"""
import argparse
import csv
import json
import random
import statistics
from pathlib import Path
from optimizer.models import Budget, Demand
from optimizer.network import Network
from optimizer.service import METHODS, OptimizerSession, optimize
from .report import make_report

CONDITIONS = {
    'reference': {'data_mb': .1, 'required_mbps': .2},
    'high_rate': {'data_mb': .1, 'required_mbps': 5},
    'low_battery': {'battery_j': 10, 'data_mb': .5, 'required_mbps': .2},
    'few_uavs': {'uav_count': 2, 'data_mb': .1, 'required_mbps': .2},
    'high_reserve': {'reserve_fraction': .6, 'battery_j': 10, 'data_mb': .5, 'required_mbps': .2},
}


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def run(output, repeats=30, size='small', conditions=None, budget=None, lifetime_requests=20, methods=METHODS):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    budget = budget or Budget()
    conditions = list(conditions or CONDITIONS)
    rows, lifetime, histories = [], [], []
    for condition in conditions:
        parameters = CONDITIONS[condition]
        config = {k:v for k,v in parameters.items() if k not in ('data_mb', 'required_mbps')}
        demand = Demand(target='G3' if size == 'small' else 'G6', **{k:v for k,v in parameters.items() if k in ('data_mb', 'required_mbps')})
        for seed in range(repeats):
            for method in methods:
                net = Network(size=size, **config)
                result = optimize(net, demand, method, seed, budget)
                rows.append({'condition':condition, 'seed':seed, 'method':method, 'feasible':int(result['feasible']),
                             'cost':result['cost'], 'rate_mbps':result.get('rate_bps', 0)/1e6,
                             'energy_j':result.get('energy_j'), 'hops':result.get('hops'),
                             'compute_ms':result['elapsed_ms'], 'evaluations':result['evaluations']})
                if seed == 0:
                    histories.append({'condition':condition, 'method':method, 'aco':result['aco_history'], 'pso':result['pso_histories']})
        print(f'Completed {condition}: {repeats} paired seeds x {len(methods)} methods', flush=True)
    # Separate depleted-battery experiment, using the same exogenous request stream.
    # No-route failures still consume a fixed idle interval so time advances fairly.
    for seed in range(repeats):
        rng = random.Random(seed)
        pairs = [('G1','G3'), ('G2','G4')] if size == 'small' else [('G1','G6'), ('G2','G7')]
        stream = [(rng.choice(pairs), rng.uniform(.3, .7)) for _ in range(lifetime_requests)]
        for method in methods:
            session = OptimizerSession(size=size, battery_j=10)
            first_failure = None
            for index, ((source, target), data_mb) in enumerate(stream):
                demand = Demand(source=source, target=target, data_mb=data_mb)
                plan = session.search(demand, method, seed*1000+index, budget)
                if plan['feasible']:
                    try:
                        session.transmit(plan['plan_id'])
                    except ValueError:
                        if first_failure is None: first_failure = index+1
                elif first_failure is None:
                    first_failure = index+1
                session.advance(1)
            state = session.snapshot()
            lifetime.append({'seed':seed, 'method':method, 'attempted':lifetime_requests,
                             'served':state['served'], 'delivered_mb':state['data_bits']/8e6,
                             'first_failed_request':first_failure,
                             'first_reserve_s':state['first_reserve_s'], 'first_empty_s':state['first_empty_s'],
                             'final_time_s':state['time_s'],
                             'minimum_battery_fraction':min(n['battery_fraction'] for n in state['nodes'] if n['battery_j'] is not None)})
        if (seed+1)%5 == 0: print(f'Lifetime: {seed+1}/{repeats} seeds', flush=True)
    summary = []
    for condition in conditions:
        for method in methods:
            group = [r for r in rows if r['condition']==condition and r['method']==method]
            valid = [r for r in group if r['feasible']]
            record = {'condition':condition, 'method':method, 'runs':len(group),
                      'success_rate':len(valid)/len(group), 'feasible_runs':len(valid)}
            for key in ('cost', 'rate_mbps', 'energy_j', 'hops', 'compute_ms'):
                values = [r[key] for r in (group if key=='compute_ms' else valid)]
                record[key+'_mean'] = statistics.mean(values) if values else None
                record[key+'_std'] = statistics.stdev(values) if len(values)>1 else 0 if values else None
            summary.append(record)
    write_csv(output/'runs.csv', rows); write_csv(output/'summary.csv', summary); write_csv(output/'lifetime.csv', lifetime)
    metadata = {'repeats':repeats, 'size':size, 'deployment':'distributed','constellation':'balanced','conditions':conditions, 'methods':list(methods),
                'budget':budget.__dict__, 'lifetime_requests':lifetime_requests,
                'request_scheduling':'sequential, whole-message store-and-forward TDMA',
                'normalization':'reference_j = max(1, data_bits / required_bps * 20)',
                'radio_model':'2.4GHz AWGN, 290K, 5dB NF; gain G-U=4dB, U-S=50dB, S-S=60dB aggregate',
                'note':'Synthetic parameters. No measured hardware, fading, interference, solar charging or UAV propulsion. Failures excluded from quality means; success rate shown separately. No claim of global optimality.'}
    (output/'results.json').write_text(json.dumps({'metadata':metadata,'summary':summary,'runs':rows,'lifetime':lifetime,'histories':histories}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    make_report(output, metadata, summary, histories, lifetime)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='outputs/experiments')
    parser.add_argument('--repeats', type=int, default=30)
    parser.add_argument('--size', choices=['small','full'], default='small')
    parser.add_argument('--conditions', nargs='+', choices=list(CONDITIONS), default=list(CONDITIONS))
    parser.add_argument('--lifetime-requests', type=int, default=20)
    parser.add_argument('--quick', action='store_true', help='Reduced search budget for smoke tests; recorded in metadata')
    args = parser.parse_args()
    if not 2 <= args.repeats <= 100 or not 1 <= args.lifetime_requests <= 200:
        parser.error('repeats in [2,100], lifetime-requests in [1,200]')
    budget = Budget(ants=6,aco_iterations=8,particles=8,pso_iterations=8) if args.quick else Budget()
    run(args.output,args.repeats,args.size,args.conditions,budget,args.lifetime_requests)


if __name__ == '__main__': main()
