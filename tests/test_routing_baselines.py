import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from optimizer.baselines import path_for
from optimizer.models import Budget, Demand
from legacy_fixtures import Network
from optimizer.service import optimize


class RoutingBaselineTests(unittest.TestCase):
    def test_distinct_route_objectives_and_unreachable_target(self):
        # Direct: fewest hops; via A: shortest distance; via B: fastest radio.
        nodes = {k: SimpleNamespace(bandwidth_hz=2, available_bandwidth_hz=2, planning_bandwidth_hz=2, p_max_w=1)
                 for k in ('S', 'A', 'B', 'T')}
        edges = {('S', 'T'): (100, 1), ('S', 'A'): (1, 2),
                 ('A', 'T'): (1, 2), ('S', 'B'): (5, 100),
                 ('B', 'T'): (5, 100)}
        problem = SimpleNamespace(
            demand=SimpleNamespace(source='S', target='T', bits=100),
            network=SimpleNamespace(nodes=nodes),
            adjacency={'S': ['T', 'A', 'B'], 'A': ['T'], 'B': ['T'], 'T': []},
            edges={k: SimpleNamespace(distance_m=d, gain=g) for k, (d, g) in edges.items()})
        with patch('optimizer.baselines.capacity', side_effect=lambda bw, power, gain: gain):
            for method, expected in [('min_hops', ['S', 'T']),
                                     ('shortest_distance', ['S', 'A', 'T']),
                                     ('min_delay', ['S', 'B', 'T'])]:
                self.assertEqual(path_for(problem, method, random.Random(0)), expected)
                original = problem.adjacency
                problem.adjacency = {k: [] for k in nodes}
                self.assertEqual(path_for(problem, method, random.Random(0)), [])
                problem.adjacency = original

    def test_energy_pso_keeps_fixed_allocation_incumbent(self):
        net = Network()
        baseline = optimize(net, Demand(), 'energy', 42)
        result = optimize(net, Demand(), 'energy_pso', 42,
                          Budget(particles=8, pso_iterations=8))
        self.assertTrue(baseline['feasible'])
        self.assertTrue(result['feasible'])
        self.assertEqual(result['path'], baseline['path'])
        self.assertLessEqual(result['cost'], baseline['cost'])
        self.assertTrue(result['pso_histories'])
