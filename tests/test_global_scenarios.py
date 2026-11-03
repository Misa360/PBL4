import unittest
from optimizer.network import Network
from app import scenarios


class GlobalScenariosTests(unittest.TestCase):
    def test_global_coverage_with_healthy_resources(self):
        for profile, count in [('compact', 41), ('balanced', 69), ('dense', 109)]:
            network = Network(size='full', constellation=profile)
            self.assertEqual(len(network.nodes), count)
            for node in network.nodes.values():
                if node.battery_j is not None:
                    node.battery_j = node.battery_capacity_j
                node.reserved_bandwidth_hz = 0
                node.predicted_reserved_bandwidth_hz = 0
            for time in (0, 1800, 5400):
                network.time_s = time
                coverage = network.coverage()
                self.assertEqual(coverage['connected_pairs'], 45, (profile, time, coverage))

    def test_catalog_replay_is_exact_and_does_not_return_teacher(self):
        if not (scenarios.ROOT/'index.json').is_file():
            self.skipTest('Generated catalog is not installed')
        page = scenarios.listing('random', limit=1)
        self.assertGreater(page['total'], 0)
        entry = page['scenarios'][0]
        session, info = scenarios.load(entry['scenario_id'])
        self.assertEqual(session.network.deployment, 'distributed')
        self.assertEqual(len(session.network.nodes), entry['nodes'])
        self.assertAlmostEqual(session.network.time_s, entry['time_s'], places=2)
        self.assertNotIn('label', info)
        self.assertNotIn('path', info)
        with self.assertRaises(ValueError):
            scenarios.load('../outside')

    def test_invalid_catalog_filters(self):
        for args in [('unknown', 0, 10), ('', -1, 10), ('', 0, 101)]:
            with self.assertRaises(ValueError):
                scenarios.listing(*args)
