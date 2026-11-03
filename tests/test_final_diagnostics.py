import unittest
from unittest.mock import patch
from optimizer.network import Network
from optimizer.models import Demand, Budget
from optimizer.problem import Problem
from optimizer.service import optimize
from optimizer.diagnostics import explain


class FinalDiagnosticsTests(unittest.TestCase):
    def test_impossible_rate_reports_actual_and_required_rate(self):
        net=Network()
        demand=Demand(source='G1',target='G2',required_mbps=50)
        plan=optimize(net,demand,'aco',42,Budget(ants=2,aco_iterations=2))
        self.assertFalse(plan['feasible'])
        issue=next(i for i in plan['issues'] if i['kind']=='rate')
        self.assertEqual(issue['required_mbps'],50)
        self.assertAlmostEqual(issue['actual_mbps'],plan['rate_bps']/1e6)

    def test_reserve_failure_is_distinguished_from_rate(self):
        net=Network();demand=Demand(source='G1',target='G2')
        initial=optimize(net,demand,'widest')
        relay=next(key for key in initial['path'] if net.nodes[key].battery_j is not None)
        node=net.nodes[relay];node.battery_j=node.battery_capacity_j*.2+.00001
        problem=Problem(net,demand);result=problem.evaluate(initial['path'])
        self.assertFalse(result['feasible'])
        self.assertIn(relay,next(i for i in explain(problem,result) if i['kind']=='battery')['nodes'])

    def test_missing_walk_and_disconnected_network_have_different_diagnostics(self):
        net=Network();demand=Demand(source='G1',target='G2')
        problem=Problem(net,demand)
        self.assertTrue(explain(problem,problem.evaluate([]))[0]['topology_connected'])
        for node in net.nodes.values():
            if node.battery_j is not None:node.battery_j=0
        problem=Problem(net,demand)
        self.assertFalse(explain(problem,problem.evaluate([]))[0]['topology_connected'])

    def test_single_node_forecast_does_not_calculate_other_nodes(self):
        net=Network(size='full',traffic_pattern='bursty')
        with patch.object(net.flow_forecasters['U2'],'snapshot',side_effect=AssertionError('Unrequested node was calculated')):
            forecast=net.forecast_all(node_id='U1')
        self.assertEqual(set(forecast),{'U1'})
        self.assertEqual(forecast['U1']['flow']['unit'],'Mbps')
