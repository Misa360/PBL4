import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from experiments.dynamic import arrivals, serve, update_load, load_at, run
from optimizer.models import Budget
from optimizer.network import Network
from optimizer.service import OptimizerSession
from optimizer.traffic import forecast_utilization


class DynamicTrafficTests(unittest.TestCase):
    def test_resume_preserves_completed_streams_and_rejects_changed_budget(self):
        budget=Budget(ants=2,aco_iterations=2,particles=2,pso_iterations=2)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'dynamic'
            first=run(directory,seeds=1,requests=2,budget=budget)
            original=(directory/'progress.jsonl').read_text()
            with patch('experiments.dynamic.serve',side_effect=AssertionError('Must not rerun completed streams')):
                second=run(directory,seeds=1,requests=2,budget=budget,resume=True)
                self.assertEqual(first['summary'],second['summary'])
                self.assertEqual(original,(directory/'progress.jsonl').read_text())
                with self.assertRaises(ValueError):
                    run(directory,seeds=2,requests=2,budget=budget,resume=True)

    def test_real_search_and_transmission_in_queued_stream(self):
        stream = arrivals(0, 2, 'bursty')
        for event in stream:
            event['request'].update(source='G1', target='G2', data_mb=.01, required_mbps=.1)
        rows = serve(stream, 'aco_pso', 0, 'light',
                     Budget(ants=2, aco_iterations=2, particles=2, pso_iterations=2))
        valid = [r for r in rows if r['delivered']]
        self.assertEqual(len(valid), 2)
        self.assertGreater(rows[1]['wait_s'], 0)
        for row in valid:
            self.assertGreater(row['energy_j'], 0)
            self.assertAlmostEqual(row['end_to_end_s'], row['wait_s']+row['service_s'])

    def test_same_arrivals_and_simultaneous_bursts(self):
        first = arrivals(7, 16, 'bursty')
        self.assertEqual(first, arrivals(7, 16, 'bursty'))
        self.assertNotEqual(first, arrivals(8, 16, 'bursty'))
        self.assertEqual(first[0]['arrival_s'], first[7]['arrival_s'])
        self.assertGreater(first[8]['arrival_s'], first[7]['arrival_s'])

    def test_forecast_uses_only_past_and_current_observations(self):
        net = Network(size='small')
        net.time_s = 8.9
        before = {k:n.battery_j for k,n in net.nodes.items()}
        def guarded(seed, key, tick, profile):
            self.assertLessEqual(tick, 8)
            return load_at(seed, key, tick, profile)
        with patch('experiments.dynamic.load_at', side_effect=guarded):
            update_load(net, 2, 'bursty')
        node = net.nodes['U1']
        history = [load_at(2, 'U1', t, 'bursty') for t in range(1, 9)]
        self.assertAlmostEqual(node.reserved_bandwidth_hz, history[-1]*node.bandwidth_hz)
        self.assertAlmostEqual(node.predicted_reserved_bandwidth_hz,
                               forecast_utilization(history)*node.bandwidth_hz)
        self.assertEqual(before, {k:n.battery_j for k,n in net.nodes.items()})
        update_load(net, 2, 'bursty', False)
        self.assertEqual(node.predicted_reserved_bandwidth_hz, 0)

    def test_fcfs_wait_and_latency_for_overlapping_arrivals(self):
        stream = arrivals(0, 3)
        for event, at in zip(stream, [0., 0., 1.]):
            event['arrival_s'] = at
        def search(session, *args):
            return dict(feasible=True, elapsed_ms=10., cost=1., plan_id='fixture')
        def transmit(session, token):
            session._debit({}, 2.)
            return {'transfer': dict(duration_s=2., energy_j=1.)}
        # Fixed two-second service lets queue accounting be checked analytically.
        with patch.object(OptimizerSession, 'search', search), patch.object(OptimizerSession, 'transmit', transmit):
            rows = serve(stream, 'aco_pso', 0, 'light', Budget())
        self.assertEqual([r['wait_s'] for r in rows], [0., 2., 3.])
        self.assertEqual([r['end_to_end_s'] for r in rows], [2., 4., 5.])

    def test_rejected_requests_are_retained_and_never_zero_latency_successes(self):
        with patch.object(OptimizerSession, 'search', return_value=dict(
                feasible=False, reason='no_route', elapsed_ms=1., cost=None)):
            rows = serve(arrivals(0, 3), 'aco_pso', 0, 'light', Budget())
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(not r['delivered'] and r['end_to_end_s'] is None for r in rows))
