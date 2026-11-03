import csv
import json
import statistics
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from experiments.run import run
from experiments.report import chart
from optimizer.models import Budget


class ExperimentReportTests(unittest.TestCase):
    def test_paired_runs_summary_and_standalone_figures(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            run(output,repeats=2,conditions=['reference','high_rate'],
                budget=Budget(ants=4,aco_iterations=4,particles=4,pso_iterations=4),
                lifetime_requests=2,methods=('widest','aco_pso'))
            data=json.loads((output/'results.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['runs']),8)
            self.assertEqual(len(data['lifetime']),4)
            self.assertEqual(data['metadata']['budget']['ants'],4)
            for summary in data['summary']:
                group=[r for r in data['runs'] if r['condition']==summary['condition'] and r['method']==summary['method']]
                self.assertEqual({r['seed'] for r in group},{0,1})
                valid=[r for r in group if r['feasible']]
                self.assertEqual(summary['success_rate'],len(valid)/len(group))
                if valid:self.assertAlmostEqual(summary['cost_mean'],statistics.mean(r['cost'] for r in valid))
                else:self.assertIsNone(summary['cost_mean'])
            with (output/'runs.csv').open(encoding='utf-8-sig') as handle:
                self.assertEqual(len(list(csv.DictReader(handle))),8)
            self.assertIn('Mean', (output/'report.html').read_text(encoding='utf-8'))
            for path in output.glob('*.svg'):
                root=ET.parse(path).getroot()
                self.assertTrue(root.tag.endswith('svg'))
                self.assertNotIn('nan',path.read_text(encoding='utf-8').lower())

    def test_figure_without_feasible_data_is_valid_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'empty.svg'
            chart(path,'No feasible solution',[('ACO',[None,None])])
            ET.parse(path)


if __name__ == '__main__':unittest.main()
