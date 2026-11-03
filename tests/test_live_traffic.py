import math
import unittest
from optimizer.network import Network
from optimizer.service import OptimizerSession
from optimizer.models import Demand, Budget
from optimizer.traffic import TrafficForecaster


class LiveTrafficTests(unittest.TestCase):
    def test_forecast_errors_are_scored_before_learning_the_observation(self):
        net=Network(load_profile='idle',forecast_load=True)
        net.update_traffic('U1',.8)
        net.update_traffic('U1',.2)
        score=net.forecast_all()['U1']
        self.assertEqual(score['scored_samples'],2)
        self.assertAlmostEqual(score['mae'],.588)
        self.assertAlmostEqual(score['persistence_mae'],.7)

    def test_airtime_is_integrated_once_per_node_per_second(self):
        net=Network(load_profile='idle',forecast_load=True)
        segments=[dict(source='G1',target='U1',start_s=0.,end_s=.25,bandwidth_hz=5e6),
                  dict(source='U1',target='G2',start_s=.25,end_s=.5,bandwidth_hz=5e6)]
        net.observe_interval(.5,segments)
        self.assertEqual(net.traffic_observations,0)
        net.observe_interval(.5)
        self.assertEqual(net.traffic_observations,1)
        self.assertAlmostEqual(net.load_history['U1'][-1],.25)
        self.assertAlmostEqual(net.load_history['G1'][-1],.125)
        self.assertEqual(net.load_history['G3'][-1],0.)
        self.assertEqual(len(net.load_history['U1']),7)

    def test_off_means_predictions_never_reserve_bandwidth(self):
        net=Network(forecast_load=False)
        net.update_traffic('U1',.9)
        net.observe_interval(3.)
        self.assertTrue(all(n.predicted_reserved_bandwidth_hz==0 for n in net.nodes.values()))
        self.assertEqual(net.traffic_observations,3)

    def test_invalid_observation_is_atomic_and_horizon_is_bounded(self):
        fc=TrafficForecaster();fc.seed([.2,.4]);before=fc.forecast()
        for value in (math.nan,math.inf,-1,True):
            with self.assertRaises(ValueError):fc.update(value)
            self.assertEqual(fc.forecast(),before)
        for value in (True,1.5,0,25):
            with self.assertRaises(ValueError):fc.forecast(value)
            with self.assertRaises(ValueError):Network(forecast_horizon=value)

    def test_transmission_ledger_matches_actual_battery_and_commit_once(self):
        session=OptimizerSession(size='small',forecast_load=False)
        before={k:n.battery_j for k,n in session.network.nodes.items() if n.battery_j is not None}
        plan=session.search(Demand(source='G1',target='G2',data_mb=.01,required_mbps=.1),
            'aco_pso',42,Budget(ants=2,aco_iterations=2,particles=2,pso_iterations=2))
        self.assertTrue(plan['feasible'])
        result=session.transmit(plan['plan_id']);transfer=result['transfer']
        for item in transfer['battery_changes']:
            self.assertEqual(item['before_j'],before[item['id']])
            self.assertEqual(item['after_j'],session.network.nodes[item['id']].battery_j)
            self.assertAlmostEqual(item['used_j'],plan['energy_by_node_j'][item['id']])
        self.assertAlmostEqual(transfer['battery_used_j'],sum(i['used_j'] for i in transfer['battery_changes']))
        self.assertLess(transfer['battery_used_j'],transfer['energy_j'])
        final=session.snapshot()
        with self.assertRaises(ValueError):session.transmit(plan['plan_id'])
        self.assertEqual(final,session.snapshot())
        session.advance(1.)
        self.assertGreaterEqual(session.network.traffic_observations,1)
