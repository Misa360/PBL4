"""Validate labels and summarize scenario coverage without changing the data."""
import argparse
import json
import math
from collections import Counter
from pathlib import Path
from .train import restore


def inspect(datasets, output):
    ids = {split:set() for split in ('train','validation','test')}
    profiles, battery_load, labels, alternatives = Counter(), Counter(), Counter(), Counter()
    ranges, manifests, total, missed = {}, [], 0, 0
    for directory in map(Path, datasets):
        manifest = json.loads((directory/'metadata.json').read_text())
        if not manifest['completed']:
            raise ValueError(f'Incomplete dataset: {directory}')
        manifests.append(manifest)
        count = 0
        for split in ids:
            for line in (directory/f'{split}.jsonl').read_text().splitlines():
                row = json.loads(line)
                sid = row['scenario_id']
                if row['split'] != split or any(sid in values for values in ids.values()):
                    raise ValueError('Duplicate scenario or split leakage')
                ids[split].add(sid)
                config, request = row['config'], row['request']
                profile = config['size']+' / '+config['deployment']+' / '+config.get('constellation','legacy')
                profiles[profile] += 1
                battery_load[profile+' / '+config.get('battery_profile','full')+' / '+config.get('load_profile','idle')] += 1
                for key, value in {**request, 'time_s':row['state']['time_s'],
                                   'battery_capacity_j':config['battery_j'], 'reserve_fraction':config['reserve_fraction']}.items():
                    if isinstance(value,(int,float)):
                        low, high = ranges.get(key,(value,value))
                        ranges[key] = [min(low,value),max(high,value)]
                label = row['label']
                labels['teacher_feasible' if label else 'teacher_no_feasible_plan'] += 1
                if label:
                    result = restore(row).evaluate(label['path'],label['power'],label['bandwidth'])
                    if not result['feasible'] or not math.isclose(result['cost'],label['cost'],rel_tol=1e-9,abs_tol=1e-12):
                        raise ValueError(f'Label cannot be reconstructed: {sid}')
                for candidate in row.get('alternatives',[]):
                    alternatives[candidate['method']+' / '+str(candidate['feasible'])] += 1
                if label is None and any(c['feasible'] for c in row.get('alternatives',[])):
                    missed += 1
                total += 1
                count += 1
        if count != manifest['samples']:
            raise ValueError('Manifest sample count does not match rows')
    report = dict(total_scenarios=total, splits={k:len(v) for k,v in ids.items()},
                  profiles=dict(profiles), battery_load_crosses=dict(battery_load),
                  label_counts=dict(labels), alternatives=dict(alternatives),
                  ranges=ranges, teacher_missed_known_feasible_alternative=missed,
                  label_validation='All non-null teacher labels reconstructed under the common evaluator',
                  note='Teacher failure does not prove that no feasible route exists; teacher labels are best found, not global optima.')
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',nargs='+',required=True)
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.dataset,args.output),indent=2))
