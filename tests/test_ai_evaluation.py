import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai.evaluate import evaluate
from ai.report import enrich
from optimizer.models import Budget


class EvaluationTests(unittest.TestCase):
    def test_failed_runs_retained_profiles_separated_and_report_enriched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root/'test.jsonl'
            dataset.write_text('\n'.join(json.dumps(dict(scenario_id=str(i), config=dict(
                size='small', deployment='distributed', constellation=profile)))
                for i,profile in enumerate(('compact','dense'))))
            counter = [0]
            budgets=[]
            def search(network, demand, method, seed, budget, **kwargs):
                counter[0] += 1
                budgets.append(budget)
                feasible = seed == 0
                return dict(feasible=feasible, cost=2. if feasible else None,
                    duration_s=3. if feasible else None, energy_j=4. if feasible else None,
                    elapsed_ms=5., evaluations=10, ai=None)
            with patch('ai.evaluate.Policy.load', return_value=SimpleNamespace(metadata={})), \
                 patch('ai.evaluate.restore', return_value=SimpleNamespace(network=None,demand=None)), \
                 patch('ai.evaluate.optimize', side_effect=search):
                budget=Budget(ants=2,aco_iterations=3,particles=2,pso_iterations=5,candidates=2)
                report = evaluate([root], root/'evaluation', seeds=2, budget=budget)
            self.assertEqual(counter[0], 20)
            self.assertTrue(all(b.candidates==2 for b in budgets))
            self.assertEqual({b.aco_iterations for b in budgets},{1,3})
            self.assertEqual(len(report['profiles']), 10)
            for row in report['summary']:
                self.assertEqual((row['runs'],row['feasible']), (4,2))
                self.assertEqual(row['feasible_delay_s_mean'], 3.)
            result = enrich(root/'evaluation')
            self.assertEqual(result['summary'][1]['feasible_energy_j_mean'], 4.)
            self.assertEqual(result['summary'][1]['paired_energy_change_pct'], 0.)
            self.assertEqual(result['summary'][1]['ai_status_counts'], {})
            self.assertIn('CI 95%', (root/'evaluation/report.html').read_text(encoding='utf-8'))
            with patch('ai.evaluate.Policy.load', return_value=SimpleNamespace(metadata={})), \
                 patch('ai.evaluate.optimize', side_effect=AssertionError('Completed rows must not rerun')):
                resumed=evaluate([root],root/'evaluation',seeds=2,budget=budget,resume=True)
                self.assertEqual(resumed['summary'][1]['runs'],4)
                with self.assertRaises(ValueError):
                    evaluate([root],root/'evaluation',seeds=3,budget=budget,resume=True)

    def test_train_validation_leak_rejected_before_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'test.jsonl').write_text(json.dumps(dict(scenario_id='leaked')))
            with patch('ai.evaluate.Policy.load', return_value=SimpleNamespace(
                    metadata={'validation_scenario_ids':['leaked']})), \
                 patch('ai.evaluate.optimize', side_effect=AssertionError('Must not search leaked data')):
                with self.assertRaises(ValueError):
                    evaluate([root], root/'evaluation')
