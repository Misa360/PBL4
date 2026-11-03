import math
import random
import unittest
from collections import defaultdict

from ai.policy import features, FEATURES, Policy
from ai.scenarios import random_scenario
from optimizer.models import Demand, Edge, channel_gain
from legacy_fixtures import Network
from optimizer.problem import Problem
from optimizer.traffic import forecast_utilization


class ResourceStateTests(unittest.TestCase):
    def test_wrong_feature_schema_does_not_silently_truncate_inputs(self):
        with self.assertRaises(ValueError):
            Policy().forward([0.]*15)
    def test_mixed_batteries_are_reproducible_and_below_reserve_is_offline(self):
        net = Network('full', battery_profile='mixed', load_profile='mixed', state_seed=17)
        self.assertEqual(net.snapshot(), Network('full', battery_profile='mixed', load_profile='mixed', state_seed=17).snapshot())
        self.assertEqual({n.battery_level for n in net.nodes.values() if n.battery_j is not None}, {'weak','medium','strong'})
        for node in net.nodes.values():
            if node.battery_level == 'weak':
                self.assertFalse(net.available(node))
                self.assertTrue(all(node.id not in edge for edge in net.edges()))

    def test_zero_reserve_does_not_allow_energy_overspend(self):
        net = Network(battery_j=1, reserve_fraction=0)
        problem = Problem(net, Demand(data_mb=10, required_mbps=.001))
        result = problem.evaluate(['G1','U1','LEO1','U3','G3'])
        self.assertGreater(result['energy_by_node_j']['U1'], net.nodes['U1'].battery_j)
        self.assertFalse(result['feasible'])

    def test_partial_allocation_is_rejected(self):
        problem = Problem(Network(), Demand())
        result = problem.evaluate(['G1','U1','LEO1','U3','G3'], powers=[1]*4)
        self.assertEqual(result['reason'], 'invalid_allocation')

    def test_reservations_and_forecasts_limit_allocation(self):
        net = Network()
        net.nodes['U1'].reserved_bandwidth_hz = 2e6
        net.nodes['U1'].predicted_reserved_bandwidth_hz = 7e6
        self.assertEqual(net.nodes['U1'].available_bandwidth_hz, 8e6)
        self.assertEqual(net.nodes['U1'].planning_bandwidth_hz, 3e6)
        problem = Problem(net, Demand(required_mbps=.001))
        path = ['G1','U1','LEO1','U3','G3']
        power, bandwidth = problem.resources(path)
        self.assertLessEqual(bandwidth[0]+bandwidth[1], 3e6)
        self.assertFalse(problem.evaluate(path, power, [5e6]*4)['feasible'])
        net.nodes['U1'].reserved_bandwidth_hz = net.nodes['U1'].bandwidth_hz
        self.assertFalse(net.available(net.nodes['U1']))

    def test_forecast_is_causal_bounded_and_responds_to_trend(self):
        self.assertAlmostEqual(forecast_utilization([.2]*6), .2)
        self.assertGreater(forecast_utilization([.1,.2,.3,.4]), .4)
        self.assertLess(forecast_utilization([.8,.7,.6,.5]), .5)
        self.assertLessEqual(forecast_utilization([0,0,1,1]), 1)
        for values in ([], [math.nan], [-.1], [1.1], [True]):
            with self.assertRaises(ValueError):
                forecast_utilization(values)

    def test_features_include_absolute_battery_residual_bandwidth_and_forecast(self):
        a, b = Network(battery_j=100), Network(battery_j=10000)
        fa, fb = features(Problem(a, Demand()), 'G1','U1'), features(Problem(b, Demand()), 'G1','U1')
        self.assertEqual(len(fa), FEATURES)
        self.assertEqual(fa[4], fb[4])
        self.assertNotEqual(fa[18], fb[18])
        a.nodes['U1'].reserved_bandwidth_hz = 3e6
        a.nodes['U1'].predicted_reserved_bandwidth_hz = 5e6
        new = features(Problem(a, Demand()), 'G1','U1')
        self.assertNotEqual(fa[16], new[16])
        self.assertNotEqual(fa[20], new[20])

    def test_longer_route_can_be_better_when_short_route_battery_is_weak(self):
        net = Network(reserve_fraction=.1)
        net.nodes['U1'].battery_j = 180
        net.nodes['U2'].battery_j = 900
        links = [('G1','U1',1000),('U1','G3',1000),('G1','U2',2000),('U2','G3',2000)]
        edges = {(a,b):Edge(a,b,d,channel_gain(d,4)) for a,b,d in links}
        net.edges = lambda time_s=None: edges
        problem = Problem(net, Demand(required_mbps=.001, energy_weight=0))
        short = problem.evaluate(['G1','U1','G3'])
        long = problem.evaluate(['G1','U2','G3'])
        self.assertTrue(short['feasible'] and long['feasible'])
        self.assertLess(long['cost'], short['cost'])

    def test_scenario_suite_changes_load_battery_and_priority_and_holds_out_stress(self):
        normal = [random_scenario(2026,i) for i in range(24)]
        self.assertGreater(len({r[2]['battery_profile'] for r in normal}), 3)
        self.assertEqual({r[2]['load_profile'] for r in normal}, {'idle','mixed','busy'})
        self.assertGreater(len({round(r[4].latency_weight,1) for r in normal}), 3)
        for profile in {r[2]['battery_profile'] for r in normal}:
            self.assertEqual({r[2]['load_profile'] for r in normal if r[2]['battery_profile'] == profile}, {'idle','mixed','busy'})
        for i in range(6):
            stress = random_scenario(2026,i,suite='stress')
            self.assertEqual(stress[1], 'test')
            self.assertNotEqual(stress[0], normal[i][0])
