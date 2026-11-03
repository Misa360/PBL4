import copy
import math
import random
import unittest
from unittest.mock import patch
from collections import Counter

from optimizer.models import Budget, Demand, Node, EARTH_M, NOISE_W_HZ, capacity, line_of_sight, position
from legacy_fixtures import Network
from optimizer.problem import Problem
from optimizer.service import METHODS, optimize
from legacy_fixtures import OptimizerSession

FAST = Budget(ants=6, aco_iterations=8, particles=8, pso_iterations=8)


class OptimizerTests(unittest.TestCase):
    def test_shannon_noise_depends_on_bandwidth(self):
        self.assertAlmostEqual(capacity(1e6, 1, NOISE_W_HZ*1e6), 1e6)
        self.assertLess(capacity(2e6, 1, NOISE_W_HZ*1e6), 2e6)
        self.assertEqual(capacity(0, 1, 1), 0)

    def test_earth_occlusion_and_visible_uplink(self):
        self.assertFalse(line_of_sight(position(0, 0), position(0, 180, 550000)))
        self.assertTrue(line_of_sight(position(0, 0), position(0, 0, 550000)))

    def test_constellation_counts_and_geo_ecef_fixed(self):
        net = Network('full')
        self.assertEqual(Counter(n.kind for n in net.nodes.values()), {'ground':10, 'UAV':8, 'LEO':12, 'MEO':6, 'GEO':3})
        self.assertEqual(net.nodes['GEO1'].coordinates(0), net.nodes['GEO1'].coordinates(10000))
        self.assertNotEqual(net.nodes['LEO1'].coordinates(0), net.nodes['LEO1'].coordinates(100))
        periods = {n['kind']:n['period_s'] for n in net.snapshot()['nodes']}
        self.assertLess(periods['LEO'], periods['MEO'])

    def test_reserve_removes_node_and_incident_edges(self):
        net = Network()
        net.nodes['U1'].battery_j = 200
        self.assertTrue(all('U1' not in pair for pair in net.edges()))

    def test_baselines_and_aco_are_read_only_and_reproducible(self):
        net = Network(); before = net.snapshot()
        for method in METHODS:
            first = optimize(net, Demand(), method, 42, FAST)
            second = optimize(net, Demand(), method, 42, FAST)
            for key in ('elapsed_ms',):
                first.pop(key); second.pop(key)
            for result in (first, second):
                if result.get('ai'):
                    result['ai'].pop('inference_ms', None)
            self.assertEqual(first, second, method)
            self.assertEqual(before, net.snapshot())
        self.assertTrue(optimize(net, Demand(), 'aco_pso', 42, FAST)['feasible'])

    def test_half_duplex_rate_and_exact_energy_conservation(self):
        net = Network(); problem = Problem(net, Demand())
        result = problem.evaluate(['G1','U1','LEO1','U3','G3'])
        self.assertTrue(result['feasible'])
        self.assertAlmostEqual(result['rate_bps'], problem.demand.bits/result['duration_s'])
        self.assertLess(result['rate_bps'], min(s['rate_bps'] for s in result['segments']))
        extras = sum(s['tx_energy_j']+s['rx_energy_j'] for s in result['segments'])
        idle = sum(n.base_power_w for n in net.nodes.values())*result['duration_s']
        self.assertAlmostEqual(result['energy_j'], extras+idle)
        self.assertAlmostEqual(sum(result['energy_by_node_j'].values()), result['energy_j'])

    def test_resource_limits_and_cycle_are_rejected(self):
        problem = Problem(Network(), Demand())
        path = ['G1','U1','LEO1','U3','G3']
        self.assertFalse(problem.evaluate(path, [100]*4, [1e9]*4)['feasible'])
        self.assertFalse(problem.evaluate(['G1','U1','G1','U1','LEO1','U3','G3'])['feasible'])
        self.assertFalse(problem.evaluate(path, [math.nan]*4, [1e6]*4)['feasible'])

    def test_pso_projection_respects_each_node_budget(self):
        result = optimize(Network(), Demand(), 'aco_pso', 9, FAST)
        self.assertTrue(result['feasible'])
        usage = Counter()
        for s in result['segments']:
            usage[s['source']] += s['bandwidth_hz']; usage[s['target']] += s['bandwidth_hz']
        net = Network()
        for key, bw in usage.items():
            self.assertLessEqual(bw, net.nodes[key].bandwidth_hz+1e-6)
        for history in [result['aco_history']] + [h['history'] for h in result['pso_histories']]:
            scores = [h['score'] for h in history if h['score'] is not None]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_plan_commit_once_and_battery_debit(self):
        session = OptimizerSession()
        before = {k:n.battery_j for k,n in session.network.nodes.items()}
        plan = session.search(Demand(), 'aco_pso', 42, FAST)
        result = session.transmit(plan['plan_id'])
        self.assertEqual(result['state']['served'], 1)
        self.assertGreater(result['state']['time_s'], 0)
        for k,n in session.network.nodes.items():
            if n.battery_j is not None:
                self.assertAlmostEqual(n.battery_j, before[k]-plan['energy_by_node_j'][k])
        state = session.snapshot()
        with self.assertRaises(ValueError): session.transmit(plan['plan_id'])
        self.assertEqual(state, session.snapshot())

    def test_idle_advance_invalidates_plan_and_depletes_exactly(self):
        session = OptimizerSession()
        plan = session.search(Demand(), 'widest', 1, FAST)
        session.advance(10)
        self.assertAlmostEqual(session.network.nodes['U1'].battery_j, 998)
        with self.assertRaises(ValueError): session.transmit(plan['plan_id'])

    def test_no_route_and_impossible_demand_do_not_commit(self):
        session = OptimizerSession()
        plan = session.search(Demand(required_mbps=50), 'aco_pso', 1, FAST)
        self.assertFalse(plan['feasible'])
        before = session.snapshot()
        with self.assertRaises(ValueError): session.transmit(plan['plan_id'])
        self.assertEqual(before, session.snapshot())
        for node in session.network.nodes.values():
            if node.battery_j is not None: node.battery_j=0
        self.assertFalse(session.search(Demand(), 'aco', 1, FAST)['feasible'])

    def test_validation_and_failed_reset_do_not_accept_nonfinite_values(self):
        for kwargs in ({'data_mb':math.nan}, {'required_mbps':0}, {'energy_weight':2}):
            with self.assertRaises(ValueError): Demand(**kwargs)
        for kwargs in ({'ants':False}, {'particles':100}, {'candidates':0}):
            with self.assertRaises(ValueError): Budget(**kwargs)
        with self.assertRaises(ValueError): Network(uav_count=3)

    def test_coverage_failure_is_atomic(self):
        session=OptimizerSession()
        plan=session.search(Demand(), 'widest', 42, FAST)
        before=session.snapshot()
        original=session.network.edges
        with patch.object(session.network,'edges',side_effect=lambda t=None: {} if t is not None and t>.001 else original(t)):
            with self.assertRaisesRegex(ValueError,'coverage'): session.transmit(plan['plan_id'])
        self.assertEqual(before,session.snapshot())

    def test_pso_retains_feasible_fixed_allocation_as_incumbent(self):
        net=Network()
        baseline=optimize(net,Demand(),'widest',3,FAST)
        improved=optimize(net,Demand(),'widest_pso',3,FAST)
        self.assertEqual(baseline['path'],improved['path'])
        self.assertTrue(improved['feasible'])
        self.assertLessEqual(improved['cost'],baseline['cost']+1e-12)

    def test_distributed_stations_are_separated_and_use_different_satellite_routes(self):
        for size in ('small','full'):
            net=Network(size,deployment='distributed')
            grounds=[n for n in net.nodes.values() if n.kind=='ground']
            distances=[math.dist(a.coordinates(0),b.coordinates(0)) for i,a in enumerate(grounds) for b in grounds[i+1:]]
            self.assertGreater(min(distances),30000)
            self.assertEqual(net.snapshot()['deployment'],'distributed')
        net=Network('full',deployment='distributed')
        results=[optimize(net,Demand(source=a,target=b),'aco_pso',42,FAST) for a,b in [('G1','G10'),('G5','G8')]]
        self.assertTrue(all(r['feasible'] for r in results))
        satellites=[tuple(n for n in r['path'] if n.startswith(('LEO','MEO','GEO'))) for r in results]
        self.assertNotEqual(satellites[0],satellites[1])

    def test_distributed_transfer_debits_actual_batteries(self):
        session=OptimizerSession(size='full',deployment='distributed')
        plan=session.search(Demand(source='G1',target='G10'),'aco_pso',42,FAST)
        before={k:n.battery_j for k,n in session.network.nodes.items()}
        result=session.transmit(plan['plan_id'])
        self.assertEqual(result['state']['served'],1)
        for key,node in session.network.nodes.items():
            if node.battery_j is not None:self.assertAlmostEqual(node.battery_j,before[key]-plan['energy_by_node_j'][key])
        with self.assertRaises(ValueError):Network(deployment='unknown')


if __name__ == '__main__': unittest.main()
