import math
import unittest
from optimizer.flow import TrafficSource, FlowForecaster
from optimizer.network import Network
from optimizer.service import OptimizerSession
from optimizer.models import Demand, Budget


class FlowForecastTests(unittest.TestCase):
    def test_autoregression_learns_a_trend_and_predicts_beyond_the_last_sample(self):
        model=FlowForecaster(1)
        for rate in range(1,61):model.observe(rate)
        data=model.snapshot()
        self.assertEqual(data['strategies'][5],'ar')
        self.assertAlmostEqual(data['forecast_mbps'][5],66.,delta=.1)
        self.assertGreater(data['forecast_mbps'][5],data['history'][-1]['actual_mbps']+5)

    def test_packet_source_is_reproducible_and_varies_over_time(self):
        a=TrafficSource(42,'U1',10,'periodic');b=TrafficSource(42,'U1',10,'periodic')
        first=[a.sample() for _ in range(60)]
        self.assertEqual(first,[b.sample() for _ in range(60)])
        self.assertGreater(max(first)-min(first),5)
        self.assertTrue(all(abs(v/.524288-round(v/.524288))<1e-8 for v in first))

    def test_forecast_is_issued_before_observation_and_six_second_errors_are_real(self):
        fc=FlowForecaster(10)
        first=fc.snapshot()['forecast_mbps']
        for value in [12,14,16,18,20]:fc.observe(value)
        issued=fc.snapshot()['forecast_mbps'][0]
        fc.observe(100)
        data=fc.snapshot();row=data['history'][-1]
        self.assertEqual(row['predicted_h1'],issued)
        self.assertEqual(row['predicted_h6'],first[5])
        self.assertEqual(data['metrics']['6']['samples'],1)
        self.assertEqual(data['metrics']['6']['mae_mbps'],90)
        self.assertNotEqual(row['predicted_h1'],row['actual_mbps'])

    def test_background_advances_identically_in_one_batch_or_small_steps(self):
        a=OptimizerSession(load_profile='mixed',forecast_load=True,traffic_pattern='bursty')
        b=OptimizerSession(load_profile='mixed',forecast_load=True,traffic_pattern='bursty')
        a.advance(30)
        for _ in range(30):b.advance(1)
        self.assertEqual(a.network.forecast_all(),b.network.forecast_all())
        history=a.network.flow_forecasters['U1'].snapshot()['history']
        self.assertGreater(len({r['actual_mbps'] for r in history}),5)

    def test_steady_is_a_real_control_not_forced_to_vary(self):
        s=OptimizerSession(load_profile='mixed',traffic_pattern='steady')
        s.advance(20);data=s.network.flow_forecasters['U1'].snapshot()
        self.assertEqual(len({r['actual_mbps'] for r in data['history']}),1)
        self.assertAlmostEqual(data['metrics']['6']['mae_mbps'],0)

    def test_search_history_includes_initialization_and_all_pso_candidates(self):
        s=OptimizerSession();p=s.search(Demand(source='G1',target='G2'), 'aco_pso',42,
            Budget(ants=2,aco_iterations=3,particles=4,pso_iterations=3,candidates=2))
        self.assertEqual(p['aco_history'][0]['iteration'],0)
        self.assertEqual(p['aco_history'][-1]['iteration'],3)
        self.assertEqual(len(p['search_history']),4+sum(len(h['history']) for h in p['pso_histories']))
        self.assertTrue(all(h['history'][0]['iteration']==0 for h in p['pso_histories']))
        costs=[h['cost'] for h in p['search_history'] if h['cost'] is not None]
        self.assertAlmostEqual(costs[-1],p['cost'])

    def test_invalid_flow_sample_is_atomic(self):
        fc=FlowForecaster(1);before=fc.snapshot()
        for value in [math.nan,math.inf,-1,True]:
            with self.assertRaises(ValueError):fc.observe(value)
            self.assertEqual(fc.snapshot(),before)
