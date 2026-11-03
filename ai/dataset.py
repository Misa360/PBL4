"""Generate reproducible, scenario-disjoint ACO+PSO teacher data (stdlib only)."""
import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from optimizer.models import Budget
from optimizer.service import optimize

from .scenarios import random_scenario, SCHEMA_VERSION
SPLITS = ('train', 'validation', 'test')


def scenario(master_seed, index, size='small', deployment='distributed', suite='balanced', constellation='balanced'):
    return random_scenario(master_seed, index, size, deployment, suite, constellation)


def generate(output, samples=100, seed=2026, size='small', deployment='distributed',
             budget=None, teacher_restarts=2, suite='balanced', resume=False, include_baselines=False, constellation='balanced'):
    if type(samples) is not int or samples < 1:
        raise ValueError('samples must be a positive integer')
    if type(teacher_restarts) is not int or teacher_restarts < 1:
        raise ValueError('teacher_restarts must be a positive integer')
    budget = budget or Budget()
    output = Path(output)
    # Refuse to overwrite an existing run, including a partially generated run.
    output.mkdir(parents=True, exist_ok=resume)
    metadata = dict(schema_version=SCHEMA_VERSION, seed=seed, samples=samples,
                    size=size, deployment=deployment, constellation=constellation, suite=suite, teacher='aco_pso',
                    teacher_restarts=teacher_restarts, budget=asdict(budget),
                    include_baselines=include_baselines,
                    split_policy='SHA256 scenario ID: 70% train / 15% validation / 15% test',
                    label_policy='best feasible teacher restart; infeasible rows have null label',
                    completed=False)
    manifest = output / 'metadata.json'
    counts = {split: dict(total=0, feasible=0) for split in SPLITS}
    existing = {}
    if resume and manifest.exists():
        previous = json.loads(manifest.read_text(encoding='utf-8'))
        for key in ('schema_version','seed','samples','size','deployment','constellation','suite','teacher_restarts','budget','include_baselines'):
            if previous.get(key) != metadata[key]:
                raise ValueError(f'Cannot resume with changed {key}')
        for split in SPLITS:
            path = output / f'{split}.jsonl'
            if path.exists():
                for line in path.read_text(encoding='utf-8').splitlines():
                    row = json.loads(line)
                    if row['scenario_id'] in existing or row['split'] != split:
                        raise ValueError('Duplicate or incorrectly split scenario in resumed data')
                    existing[row['scenario_id']] = row
                    counts[split]['total'] += 1
                    counts[split]['feasible'] += int(row['label'] is not None)
    manifest.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    started = time.perf_counter()
    for index in range(samples):
        sid, split, config, network, demand, rng = scenario(seed, index, size, deployment, suite, constellation)
        if sid in existing:
            del existing[sid]
            continue
        state = network.snapshot()
        trials = [optimize(network, demand, 'aco_pso', rng.randrange(2147483648), budget)
                  for _ in range(teacher_restarts)]
        valid = [trial for trial in trials if trial['feasible']]
        best = min(valid, key=lambda trial: trial['cost']) if valid else None
        label = None if best is None else {
            key: best[key] for key in ('path', 'power', 'bandwidth', 'cost', 'energy_j', 'rate_bps')}
        row = dict(schema_version=SCHEMA_VERSION, scenario_index=index, scenario_id=sid, split=split,
                   config=config, state=state, request=asdict(demand), label=label,
                   teacher_runs=[{k: trial[k] for k in ('seed', 'feasible', 'cost',
                                                       'elapsed_ms', 'evaluations', 'reason')}
                                 for trial in trials])
        if include_baselines:
            row['alternatives'] = []
            for method in ('random','greedy','min_delay','energy'):
                alternative = optimize(network, demand, method, trials[0]['seed'], budget)
                row['alternatives'].append({key:alternative.get(key) for key in
                    ('method','path','power','bandwidth','feasible','reason','cost','duration_s','energy_j','rate_bps')})
        with (output / f'{split}.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, allow_nan=False) + '\n')
        counts[split]['total'] += 1
        counts[split]['feasible'] += int(best is not None)
        if (index + 1) % 10 == 0:
            print(f'Generated {index + 1}/{samples} scenarios', flush=True)
    for split in SPLITS:
        (output / f'{split}.jsonl').touch(exist_ok=True)
    if existing:
        raise ValueError('Resumed data contains unknown scenario IDs')
    metadata.update(completed=True, counts=counts, elapsed_s=time.perf_counter() - started)
    manifest.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--samples', type=int, default=100)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--size', choices=('small', 'full'), default='small')
    parser.add_argument('--deployment', choices=('distributed',), default='distributed')
    parser.add_argument('--constellation', choices=('compact','balanced','dense'),default='balanced')
    parser.add_argument('--budget',choices=('standard','dataset','quick'),default='standard')
    parser.add_argument('--teacher-restarts', type=int, default=2)
    parser.add_argument('--suite', choices=('balanced','stress'), default='balanced')
    parser.add_argument('--resume', action='store_true', help='Continue a matching partial run without duplicating rows')
    parser.add_argument('--include-baselines', action='store_true', help='Save good, poor and infeasible routing alternatives for comparison')
    parser.add_argument('--quick', action='store_true', help='Smoke data only; not training-quality labels')
    args = parser.parse_args()
    mode = 'quick' if args.quick else args.budget
    budget = Budget(ants=6,aco_iterations=8,particles=8,pso_iterations=8) if mode=='quick' else Budget(ants=10,aco_iterations=20,particles=12,pso_iterations=25,candidates=2) if mode=='dataset' else Budget()
    result = generate(args.output, args.samples, args.seed, args.size, args.deployment,
                      budget, args.teacher_restarts, args.suite, args.resume, args.include_baselines,args.constellation)
    print(json.dumps(result['counts'], indent=2))


if __name__ == '__main__':
    main()
