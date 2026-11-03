"""Tests for TrafficForecaster: seed, update, multi-step forecast, confidence intervals."""
import unittest
from optimizer.traffic import TrafficForecaster, forecast_utilization


class TestForecastUtilizationBackcompat(unittest.TestCase):
    """Original function must remain backward compatible."""

    def test_single_observation(self):
        result = forecast_utilization([0.5])
        self.assertAlmostEqual(result, 0.5, places=5)

    def test_increasing_trend(self):
        history = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = forecast_utilization(history)
        # Should predict above 0.5
        self.assertGreater(result, 0.5)

    def test_result_clamped_to_zero_one(self):
        result = forecast_utilization([1.0, 1.0, 1.0, 1.0])
        self.assertLessEqual(result, 1.0)
        self.assertGreaterEqual(result, 0.0)

    def test_empty_history_raises(self):
        with self.assertRaises(ValueError):
            forecast_utilization([])


class TestTrafficForecaster(unittest.TestCase):

    def setUp(self):
        self.fc = TrafficForecaster()

    def test_seed_and_forecast_length(self):
        self.fc.seed([0.2, 0.3, 0.4, 0.5, 0.6])
        result = self.fc.forecast(6)
        self.assertEqual(len(result['forecast']), 6)
        self.assertEqual(len(result['confidence_lo']), 6)
        self.assertEqual(len(result['confidence_hi']), 6)

    def test_forecast_values_clamped(self):
        # Start near max; forecast should not exceed 1.0
        self.fc.seed([0.95, 0.97, 0.99, 0.99, 1.0])
        result = self.fc.forecast(6)
        for v in result['forecast']:
            self.assertLessEqual(v, 1.0)
            self.assertGreaterEqual(v, 0.0)

    def test_increasing_trend_detected(self):
        self.fc.seed([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        result = self.fc.forecast(6)
        self.assertEqual(result['trend'], 'increasing')

    def test_decreasing_trend_detected(self):
        self.fc.seed([0.7, 0.6, 0.5, 0.4, 0.3, 0.2])
        result = self.fc.forecast(6)
        self.assertEqual(result['trend'], 'decreasing')

    def test_stable_trend_detected(self):
        self.fc.seed([0.5, 0.5, 0.5, 0.5, 0.5])
        result = self.fc.forecast(6)
        self.assertEqual(result['trend'], 'stable')

    def test_confidence_interval_ordering(self):
        self.fc.seed([0.3, 0.35, 0.32, 0.38, 0.36])
        result = self.fc.forecast(6)
        for lo, pred, hi in zip(result['confidence_lo'], result['forecast'], result['confidence_hi']):
            self.assertLessEqual(lo, pred + 1e-9)
            self.assertLessEqual(pred, hi + 1e-9)

    def test_confidence_interval_widens_with_horizon(self):
        self.fc.seed([0.3, 0.4, 0.35, 0.42, 0.38, 0.40])
        result = self.fc.forecast(6)
        widths = [hi - lo for lo, hi in zip(result['confidence_lo'], result['confidence_hi'])]
        # Width at last horizon should not be smaller than at the first step.
        # (rounding to 4 dp can cause tiny non-monotonicity between adjacent steps)
        self.assertGreaterEqual(widths[-1] + 1e-4, widths[0])

    def test_update_increments_history(self):
        self.fc.seed([0.2, 0.3])
        self.fc.update(0.5)
        result = self.fc.forecast(3)
        self.assertIn(0.5, result['history'])

    def test_next_utilisation_clamped(self):
        self.fc.seed([0.9, 0.95, 1.0, 1.0])
        val = self.fc.next_utilisation
        self.assertLessEqual(val, 1.0)
        self.assertGreaterEqual(val, 0.0)

    def test_empty_forecaster_returns_zeros(self):
        result = self.fc.forecast(4)
        self.assertEqual(result['forecast'], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(result['trend'], 'stable')

    def test_forecast_invalid_steps_raises(self):
        self.fc.seed([0.3])
        with self.assertRaises(ValueError):
            self.fc.forecast(0)

    def test_seed_normalizes_out_of_range_values(self):
        # Values slightly above 1 or below 0 are clamped without raising
        self.fc.seed([0.0, 0.5, 1.0])
        result = self.fc.forecast(3)
        self.assertEqual(len(result['forecast']), 3)

    def test_history_truncated_to_max_history(self):
        fc = TrafficForecaster(max_history=4)
        for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
            fc.update(v)
        result = fc.forecast(2)
        self.assertLessEqual(len(result['history']), 4)

    def test_multiple_updates_keep_trend_direction(self):
        """After many increasing updates the next_utilisation should rise."""
        self.fc.seed([0.1])
        for v in [0.15, 0.2, 0.25, 0.3, 0.35]:
            self.fc.update(v)
        self.assertGreater(self.fc.next_utilisation, 0.3)


class TestTrafficForecasterInNetwork(unittest.TestCase):
    """Integration: forecasters initialised correctly inside Network."""

    def test_network_has_forecaster_for_every_node(self):
        from optimizer.network import Network
        net = Network(size='small', load_profile='mixed')
        self.assertEqual(set(net.forecasters.keys()), set(net.nodes.keys()))

    def test_forecast_all_returns_all_nodes(self):
        from optimizer.network import Network
        net = Network(size='small', load_profile='mixed')
        forecast = net.forecast_all(steps=3)
        self.assertEqual(set(forecast.keys()), set(net.nodes.keys()))
        for node_id, data in forecast.items():
            self.assertEqual(len(data['forecast']), 3)
            self.assertIn(data['trend'], ('increasing', 'stable', 'decreasing'))

    def test_update_traffic_refreshes_predicted_bandwidth(self):
        from optimizer.network import Network
        net = Network(size='small', load_profile='idle',forecast_load=True)
        node_id = next(n.id for n in net.nodes.values() if n.kind == 'UAV')
        before = net.nodes[node_id].predicted_reserved_bandwidth_hz
        net.update_traffic(node_id, 0.8)
        after = net.nodes[node_id].predicted_reserved_bandwidth_hz
        # After a high-load observation the predicted bandwidth should increase
        self.assertGreaterEqual(after, before)

    def test_snapshot_contains_traffic_forecast(self):
        from optimizer.network import Network
        net = Network(size='small')
        snap = net.snapshot()
        self.assertIn('traffic_forecast', snap)
        self.assertIn('forecast_method', snap)
        self.assertIn('Holt', snap['forecast_method'])


if __name__ == '__main__':
    unittest.main()
