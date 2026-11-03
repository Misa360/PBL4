import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.dataset import generate, scenario, SPLITS
from ai.inspect_dataset import inspect
from optimizer.models import Budget, Demand
from legacy_fixtures import Network
from optimizer.problem import Problem


class DatasetTests(unittest.TestCase):
    def test_resume_keeps_completed_scenarios_and_rejects_configuration_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'run'
            budget = Budget(ants=2,aco_iterations=2,particles=2,pso_iterations=2)
            generate(output,samples=6,budget=budget,teacher_restarts=1,include_baselines=True)
            original = {p.name:p.read_text() for p in output.glob('*.jsonl')}
            with patch('ai.dataset.optimize',side_effect=AssertionError('Must not relabel completed rows')):
                result = generate(output,samples=6,budget=budget,teacher_restarts=1,
                                  include_baselines=True,resume=True)
            self.assertEqual(sum(v['total'] for v in result['counts'].values()),6)
            self.assertEqual(original,{p.name:p.read_text() for p in output.glob('*.jsonl')})
            rows = [json.loads(line) for value in original.values() for line in value.splitlines()]
            self.assertTrue(all(len(row['alternatives']) == 4 for row in rows))
            coverage = inspect([output],output/'coverage.json')
            self.assertEqual(coverage['total_scenarios'],6)
            self.assertEqual(sum(coverage['alternatives'].values()),24)
            with self.assertRaises(ValueError):
                generate(output,samples=6,seed=123,budget=budget,teacher_restarts=1,
                         include_baselines=True,resume=True)
    def test_scenario_reproducible_and_splits_disjoint(self):
        groups = {split: set() for split in SPLITS}
        for index in range(100):
            a = scenario(2026, index)
            b = scenario(2026, index)
            self.assertEqual(a[:3], b[:3])
            self.assertEqual(a[3].snapshot(), b[3].snapshot())
            self.assertEqual(a[4], b[4])
            groups[a[1]].add(a[0])
        self.assertTrue(all(groups.values()))
        self.assertEqual(sum(map(len, groups.values())), 100)
        self.assertFalse(groups['train'] & groups['test'])

    def test_export_reconstructs_labels_and_preserves_existing_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'dataset'
            meta = generate(output, samples=12, teacher_restarts=1,
                            budget=Budget(ants=2, aco_iterations=2, particles=2, pso_iterations=2))
            self.assertTrue(meta['completed'])
            self.assertEqual(sum(v['total'] for v in meta['counts'].values()), 12)
            valid = 0
            for split in SPLITS:
                for line in (output / f'{split}.jsonl').read_text().splitlines():
                    row = json.loads(line)
                    self.assertEqual(row['split'], split)
                    if row['label'] is None:
                        self.assertFalse(any(r['feasible'] for r in row['teacher_runs']))
                        continue
                    valid += 1
                    net = Network(**row['config'])
                    net.time_s = row['state']['time_s']
                    for node in row['state']['nodes']:
                        net.nodes[node['id']].battery_j = node['battery_j']
                    label = row['label']
                    result = Problem(net, Demand(**row['request'])).evaluate(
                        label['path'], label['power'], label['bandwidth'])
                    self.assertTrue(result['feasible'])
                    self.assertAlmostEqual(result['cost'], label['cost'])
            self.assertGreater(valid, 0)
            with self.assertRaises(FileExistsError):
                generate(output, samples=1)
