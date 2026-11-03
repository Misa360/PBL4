"""Reproduce three cases where both baseline methods can actually transmit.

python -m examples.random_greedy_success --output outputs/examples/random-greedy-success.json
Each method starts from a fresh, identical session; no running web session is changed.
"""
import argparse
import json
from pathlib import Path

from optimizer.models import Demand
from optimizer.service import OptimizerSession

CASES = (
    ('small-regional-satellite', 'small', 'regional', 'G1', 'G3', 0),
    ('full-regional-satellite', 'full', 'regional', 'G1', 'G6', 2),
    ('full-distributed-local', 'full', 'distributed', 'G1', 'G2', 0),
)


def run():
    results = []
    for name, size, deployment, source, target, seed in CASES:
        config = dict(size=size, deployment=deployment, constellation='legacy', battery_j=1000,
                      reserve_fraction=.2, battery_profile='mixed', load_profile='mixed',
                      forecast_load=True, state_seed=42, uav_count=4 if size == 'small' else 8)
        request = dict(source=source, target=target, data_mb=.1, required_mbps=.2,
                       energy_weight=.5, latency_weight=.5)
        row = dict(name=name, config=config, request=request, algorithm_seed=seed,
                   snapshot_time_s=0, methods={})
        for method in ('greedy','random'):
            session = OptimizerSession(**config)
            before = session.snapshot()
            plan = session.search(Demand(**request),method,seed)
            if not plan['feasible']:
                raise RuntimeError(f'{name}/{method} is infeasible: {plan.get("reason")}')
            assert before == session.snapshot(), 'Search must not change state'
            committed = session.transmit(plan['plan_id'])
            assert committed['state']['served'] == 1
            assert committed['state']['time_s'] > 0
            row['methods'][method] = {key:plan[key] for key in
                ('path','hops','duration_s','rate_bps','energy_j','cost')}
            row['methods'][method]['transmission_verified'] = True
        results.append(row)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    args = parser.parse_args()
    result = run()
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
