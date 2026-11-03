"""Paired held-out evaluation, with failures retained and inference included."""
import argparse
import csv
import json
import hashlib
import random
import statistics
from dataclasses import asdict
from html import escape
from pathlib import Path

from optimizer.models import Budget
from optimizer.service import optimize
from .policy import Policy, MODEL_PATH
from .train import restore


def interval(values):
    if not values:
        return None
    rng = random.Random(91)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(1000))
    return [means[25], means[974]]


def evaluate(datasets, output, seeds=2, quick=False, budget=None, resume=False):
    policy = Policy.load()
    seen = set(policy.metadata.get('train_scenario_ids', []) + policy.metadata.get('validation_scenario_ids', []))
    rows = [json.loads(line) for directory in datasets
            for line in (Path(directory)/'test.jsonl').read_text().splitlines()]
    if not rows or any(row['scenario_id'] in seen for row in rows):
        raise ValueError('Empty test set or train/validation leakage')
    if len({row['scenario_id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate test scenarios')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=resume)
    standard = budget or (Budget(ants=6, aco_iterations=8, particles=8, pso_iterations=8) if quick else Budget())
    reduced = Budget(ants=standard.ants, aco_iterations=max(1, standard.aco_iterations//2),
                     particles=standard.particles, pso_iterations=max(1, standard.pso_iterations//2),
                     candidates=standard.candidates)
    provenance = dict(seeds=seeds, quick=quick, budget=asdict(standard),
        checkpoint_sha256=hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
        test_files={str((Path(d)/'test.jsonl').resolve()):hashlib.sha256((Path(d)/'test.jsonl').read_bytes()).hexdigest() for d in datasets})
    manifest = output/'progress-metadata.json'
    progress = output/'progress.csv'
    if manifest.exists():
        if json.loads(manifest.read_text()) != provenance:
            raise ValueError('Cannot resume: checkpoint, data or evaluation configuration changed')
    else:
        if any(output.iterdir()):
            raise ValueError('Cannot resume unrecognized output directory')
        manifest.write_text(json.dumps(provenance, indent=2))
    results = []
    if progress.exists():
        with progress.open(newline='', encoding='utf-8') as handle:
            for record in csv.DictReader(handle):
                record['feasible'] = record['feasible']=='True'
                for key in ('seed','evaluations','aco_iterations','pso_iterations'):
                    record[key] = int(record[key])
                for key in ('cost','duration_s','energy_j','elapsed_ms','inference_ms'):
                    record[key] = float(record[key]) if record[key] else None
                results.append(record)
    completed = {(r['scenario_id'],r['seed'],r['variant']) for r in results}
    if len(completed) != len(results):
        raise ValueError('Duplicate rows in evaluation progress')
    variants = [('aco_pso', 'aco_pso', standard), ('ai_equal', 'ai_aco_pso', standard),
                ('ai_half_iterations', 'ai_aco_pso', reduced),
                ('untrained_warm_control', 'ai_aco_pso', standard),
                ('aco_half_iterations', 'aco_pso', reduced)]
    allowed={(r['scenario_id'],seed,name) for r in rows for seed in range(seeds) for name,_,_ in variants}
    if not completed <= allowed:
        raise ValueError('Evaluation progress contains unknown scenarios, seeds or variants')
    for index, row in enumerate(rows):
        for seed in range(seeds):
            # Rotate order to reduce systematic warm-cache/order effects.
            order = variants[index % len(variants):] + variants[:index % len(variants)]
            for name, method, budget in order:
                if (row['scenario_id'],seed,name) in completed:
                    continue
                problem = restore(row)
                control = Policy(seed+700) if name == 'untrained_warm_control' else None
                result = optimize(problem.network, problem.demand, method, seed, budget, hint_policy=control)
                record = dict(scenario_id=row['scenario_id'], size=row['config']['size'],
                                    deployment=row['config']['deployment'],
                                    constellation=row['config'].get('constellation','legacy'), seed=seed, variant=name,
                                    feasible=result['feasible'], cost=result['cost'],
                                    duration_s=result.get('duration_s'), energy_j=result.get('energy_j'),
                                    elapsed_ms=result['elapsed_ms'], evaluations=result['evaluations'],
                                    inference_ms=(result.get('ai') or {}).get('inference_ms', 0),
                                    ai_status=(result.get('ai') or {}).get('status'),
                                    aco_iterations=budget.aco_iterations, pso_iterations=budget.pso_iterations)
                with progress.open('a', newline='', encoding='utf-8') as handle:
                    writer=csv.DictWriter(handle,fieldnames=list(record))
                    if handle.tell()==0:
                        writer.writeheader()
                    writer.writerow(record)
                results.append(record)
        if (index+1) % 10 == 0:
            print(f'Evaluated {index+1}/{len(rows)} held-out scenarios', flush=True)
    if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != provenance['checkpoint_sha256']:
        raise ValueError('Checkpoint changed during evaluation; do not aggregate mixed runs')
    with (output/'runs.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    summary = []
    baseline = {(r['scenario_id'], r['seed']): r for r in results if r['variant'] == 'aco_pso'}
    for name, _, budget in variants:
        group = [r for r in results if r['variant'] == name]
        valid = [r for r in group if r['feasible']]
        paired = [(r, baseline[r['scenario_id'], r['seed']]) for r in group
                  if r['feasible'] and baseline[r['scenario_id'], r['seed']]['feasible']]
        cost_deltas = [(r['cost']/b['cost']-1)*100 for r, b in paired]
        delay_deltas = [(r['duration_s']/b['duration_s']-1)*100 for r, b in paired]
        # Cluster by scenario before resampling: seeds from one scenario are correlated.
        clustered = []
        delay_clusters = []
        for sid in sorted({r['scenario_id'] for r, _ in paired}):
            clustered.append(statistics.mean((r['cost']/b['cost']-1)*100 for r, b in paired if r['scenario_id'] == sid))
            delay_clusters.append(statistics.mean((r['duration_s']/b['duration_s']-1)*100 for r, b in paired if r['scenario_id'] == sid))
        summary.append(dict(variant=name, budget=asdict(budget), runs=len(group), feasible=len(valid),
                            success_rate=len(valid)/len(group),
                            feasible_cost_mean=statistics.mean(r['cost'] for r in valid) if valid else None,
                            feasible_delay_s_mean=statistics.mean(r['duration_s'] for r in valid) if valid else None,
                            all_runs_ms_mean=statistics.mean(r['elapsed_ms'] for r in group),
                            mean_evaluations=statistics.mean(r['evaluations'] for r in group),
                            joint_feasible_pairs=len(paired),
                            paired_cost_change_pct=statistics.mean(cost_deltas) if cost_deltas else None,
                            paired_delay_change_pct=statistics.mean(delay_deltas) if delay_deltas else None,
                            scenario_bootstrap_cost_change_pct_95ci=interval(clustered),
                            scenario_bootstrap_delay_change_pct_95ci=interval(delay_clusters),
                            paired_speedup=statistics.mean(b['elapsed_ms']/max(.001, r['elapsed_ms']) for r, b in paired) if paired else None))
    base_ms = summary[0]['all_runs_ms_mean']
    base_success = summary[0]['success_rate']
    for item in summary:
        item['all_runs_speedup_ratio_of_means'] = base_ms/item['all_runs_ms_mean']
        item['success_rate_change_pp'] = 100*(item['success_rate']-base_success)
    report = dict(checkpoint=str(MODEL_PATH), scenarios=len(rows), seeds=seeds, quick=quick,
                  datasets=[str(directory) for directory in datasets],
                  checkpoint_sha256=hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() if MODEL_PATH.exists() else None,
                  timing='Timed search includes checkpoint read, features, inference, candidate validation and ACO/PSO. Excludes common topology construction, API transport, dataset generation and training.',
                  limitations='Synthetic scenarios with a causal Holt background-load forecast; no arrival queues or significance/optimality claim. Paired quality excludes failures; success rates include all runs. Cluster bootstrap is exploratory.',
                  summary=summary)
    report['profiles'] = []
    for size, deployment, constellation in sorted({(r['size'], r['deployment'], r['constellation']) for r in results}):
        for name, _, _ in variants:
            group = [r for r in results if r['size'] == size and r['deployment'] == deployment and r['constellation'] == constellation and r['variant'] == name]
            valid = [r for r in group if r['feasible']]
            report['profiles'].append(dict(size=size, deployment=deployment, constellation=constellation, variant=name,
                runs=len(group), feasible=len(valid), success_rate=len(valid)/len(group),
                feasible_cost_mean=statistics.mean(r['cost'] for r in valid) if valid else None,
                feasible_delay_s_mean=statistics.mean(r['duration_s'] for r in valid) if valid else None,
                all_runs_ms_mean=statistics.mean(r['elapsed_ms'] for r in group)))
    (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    headings = ['variant', 'success_rate', 'feasible_cost_mean', 'feasible_delay_s_mean', 'all_runs_ms_mean', 'paired_speedup']
    table = '<tr>'+''.join('<th>'+k+'</th>' for k in headings)+'</tr>'
    table += ''.join('<tr>'+''.join('<td>'+escape(str(row[k]))+'</td>' for k in headings)+'</tr>' for row in summary)
    (output/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>AI held-out evaluation</title><h1>AI + ACO + PSO</h1><p>'+escape(report['timing'])+'</p><table border="1" cellpadding="8">'+table+'</table><p>'+escape(report['limitations'])+'</p>', encoding='utf-8')
    return report


def add_half_control(evaluation):
    """Supplement an existing four-arm run without repeating completed searches."""
    directory = Path(evaluation)
    destination = directory/'half-control.json'
    if destination.exists():
        raise FileExistsError(destination)
    report = json.loads((directory/'summary.json').read_text())
    if any(item['variant'] == 'aco_half_iterations' for item in report['summary']):
        raise ValueError('Half-iteration control is already included')
    if report['checkpoint_sha256'] != hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest():
        raise ValueError('Checkpoint changed since original evaluation')
    with (directory/'runs.csv').open(newline='') as handle:
        baseline = {(r['scenario_id'], int(r['seed'])): r for r in csv.DictReader(handle) if r['variant'] == 'aco_pso'}
    budget = Budget(**report['summary'][0]['budget'])
    budget = Budget(ants=budget.ants, particles=budget.particles,
                    aco_iterations=max(1, budget.aco_iterations//2),
                    pso_iterations=max(1, budget.pso_iterations//2), candidates=budget.candidates)
    rows, pairs, clustered = [], [], {}
    for source in report['datasets']:
        for line in (Path(source)/'test.jsonl').read_text().splitlines():
            row = json.loads(line)
            for seed in range(report['seeds']):
                problem = restore(row)
                result = optimize(problem.network, problem.demand, 'aco_pso', seed, budget)
                original = baseline[row['scenario_id'], seed]
                rows.append(dict(scenario_id=row['scenario_id'], seed=seed, feasible=result['feasible'],
                                 cost=result['cost'], duration_s=result.get('duration_s'),
                                 elapsed_ms=result['elapsed_ms'], evaluations=result['evaluations']))
                if result['feasible'] and original['feasible'] == 'True':
                    change = 100*(result['cost']/float(original['cost'])-1)
                    pairs.append(change)
                    clustered.setdefault(row['scenario_id'], []).append(change)
    valid = [r for r in rows if r['feasible']]
    summary = dict(variant='aco_half_iterations', runs=len(rows), feasible=len(valid),
                   success_rate=len(valid)/len(rows), budget=asdict(budget),
                   feasible_cost_mean=statistics.mean(r['cost'] for r in valid) if valid else None,
                   feasible_delay_s_mean=statistics.mean(r['duration_s'] for r in valid) if valid else None,
                   all_runs_ms_mean=statistics.mean(r['elapsed_ms'] for r in rows),
                   paired_cost_change_pct=statistics.mean(pairs) if pairs else None,
                   scenario_bootstrap_cost_change_pct_95ci=interval([statistics.mean(v) for v in clustered.values()]),
                   timing_note='Supplementary block on the same machine, not interleaved with the initial four arms.')
    with (directory/'half-control.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    destination.write_text(json.dumps(summary, indent=2))
    report['supplementary_controls'] = [summary]
    (directory/'summary.json').write_text(json.dumps(report, indent=2))
    html = directory/'report.html'
    html.write_text(html.read_text(encoding='utf-8') + '<h2>Supplementary half-iteration control</h2><pre>'
                    + escape(json.dumps(summary, indent=2)) + '</pre>', encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', nargs='+')
    parser.add_argument('--output')
    parser.add_argument('--append-half-control', help='Supplement an existing four-arm evaluation directory')
    parser.add_argument('--seeds', type=int, default=2)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--budget', choices=['standard','dataset'], default='standard')
    args = parser.parse_args()
    if args.append_half_control:
        print(json.dumps(add_half_control(args.append_half_control), indent=2))
        raise SystemExit(0)
    if not args.dataset or not args.output:
        parser.error('--dataset and --output are required for a new evaluation')
    if args.seeds < 1:
        parser.error('seeds must be positive')
    if args.quick and args.budget!='standard':
        parser.error('--quick and --budget dataset cannot be combined')
    budget=Budget(ants=10,aco_iterations=20,particles=12,pso_iterations=25,candidates=2) if args.budget=='dataset' else None
    print(json.dumps(evaluate(args.dataset, args.output, args.seeds, args.quick, budget, args.resume)['summary'], indent=2))
