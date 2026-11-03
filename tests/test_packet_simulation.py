import math
import unittest
from collections import Counter

from simulator.network_models import Link, NetworkNode
from simulator.packet_simulation import PacketSimulation, SimulationConfig


class StaticScenario:
    def __init__(self, nodes, links, flows=()):
        self.nodes, self.links, self.flows = nodes, links, flows

    def links_at(self, time):
        return self.links


def ground(name, **kwargs):
    return NetworkNode(name, 'ground', battery_capacity_j=None, **kwargs)


class PacketNetworkTests(unittest.TestCase):
    def assert_conservation(self, sim):
        metrics = sim.metrics()
        self.assertEqual(metrics['generated'], metrics['delivered'] + metrics['dropped'] +
                         metrics['queued'] + metrics['in_flight'])
        for node in sim.nodes.values():
            self.assertLessEqual(len(node.queue), node.buffer_packets)
            if node.remaining_j is not None:
                self.assertGreaterEqual(node.remaining_j, 0)
        for direction in ('source', 'target'):
            total = Counter()
            for key, link in sim.links.items():
                total[getattr(link, direction)] += sim.allocation[key]
            for node, bandwidth in total.items():
                self.assertLessEqual(bandwidth, sim.nodes[node].bandwidth_hz + 1e-6)

    def test_store_and_forward_has_exact_serialization_and_propagation(self):
        # Two 0.1s serializations and two 1ms propagations, no queueing.
        from simulator.network_models import Packet
        scenario = StaticScenario(
            [ground('A', bandwidth_hz=8000), NetworkNode('R', 'air', bandwidth_hz=8000),
             ground('B', bandwidth_hz=8000)],
            [Link('A', 'R', 299792.458, 1), Link('R', 'B', 299792.458, 1)])
        sim = PacketSimulation(SimulationConfig(duration_s=.5, packets_per_second=0), scenario)
        sim.nodes['A'].queue.append(Packet(1, 'A', 'B', 800, 0, 5, ['A']))
        sim.generated = 1
        sim.run()
        self.assertEqual(sim.delivered, 1)
        self.assertAlmostEqual(sim.delays[0], .202, places=8)
        self.assertEqual(sim.packet_log[0]['path'], ['A', 'R', 'B'])
        hops = sim.snapshot()['hops']
        self.assertEqual([(h['source'], h['target']) for h in hops], [('A', 'R'), ('R', 'B')])
        self.assertEqual([h['id'] for h in hops], [1, 2])
        self.assertAlmostEqual(hops[0]['time_s'], .101, places=8)
        self.assertAlmostEqual(hops[1]['time_s'], .202, places=8)
        self.assertTrue(all(h['packet_id'] == 1 and h['origin'] == 'A' for h in hops))
        self.assert_conservation(sim)

    def test_seed_is_reproducible_and_packets_are_conserved_each_step(self):
        first = PacketSimulation(SimulationConfig(duration_s=3))
        second = PacketSimulation(SimulationConfig(duration_s=3))
        while not first.snapshot()['done']:
            first.step()
            second.step()
            self.assert_conservation(first)
        self.assertEqual(first.snapshot(), second.snapshot())
        self.assertGreater(first.delivered, 0)
        self.assertTrue(any('S1' in p['path'] for p in first.packet_log))

    def test_queue_overflow(self):
        sim = PacketSimulation(SimulationConfig(duration_s=1, packets_per_second=500,
                                                 buffer_packets=1, bandwidth_hz=10000))
        sim.run()
        self.assertGreater(sim.drop_reasons['buffer_full'], 0)
        self.assert_conservation(sim)

    def test_no_route_expires_without_creating_fake_deliveries(self):
        scenario = StaticScenario([ground('A'), ground('B')], [], [('A', 'B')])
        sim = PacketSimulation(SimulationConfig(duration_s=1, packet_ttl_s=.1), scenario)
        sim.run()
        self.assertEqual(sim.delivered, 0)
        self.assertGreater(sim.drop_reasons['ttl_expired'], 0)
        self.assert_conservation(sim)

    def test_idle_battery_depletion_is_at_exact_time(self):
        node = NetworkNode('U', 'air', battery_capacity_j=.125, base_power_w=.5)
        sim = PacketSimulation(SimulationConfig(duration_s=1, packets_per_second=0),
                               StaticScenario([node], []))
        sim.run()
        self.assertAlmostEqual(sim.first_dead_at, .25)
        self.assertAlmostEqual(node.energy_used_j, .125)
        self.assertFalse(node.alive)

    def test_death_during_transmission_releases_radios_and_drops_once(self):
        from simulator.network_models import Packet
        source = NetworkNode('U', 'air', bandwidth_hz=1000, battery_capacity_j=.1,
                             base_power_w=.5, tx_extra_power_w=2)
        destination = ground('B', bandwidth_hz=1000)
        sim = PacketSimulation(SimulationConfig(duration_s=.5, packets_per_second=0),
                               StaticScenario([source, destination], [Link('U', 'B', 0, 1)]))
        source.queue.append(Packet(1, 'U', 'B', 1000, 0, 5, ['U']))
        sim.generated = 1
        sim.run()
        self.assertAlmostEqual(sim.first_dead_at, .04)
        self.assertEqual(sim.drop_reasons['node_dead'], 1)
        self.assertIsNone(destination.busy)
        self.assertEqual(sim.delivered, 0)
        self.assert_conservation(sim)

    def test_topology_loss_cancels_incomplete_frame(self):
        from simulator.network_models import Packet
        class Disconnect(StaticScenario):
            def links_at(self, time):
                return self.links if time < .1 else []
        scenario = Disconnect([ground('A', bandwidth_hz=1000), ground('B', bandwidth_hz=1000)],
                              [Link('A', 'B', 0, 1)])
        sim = PacketSimulation(SimulationConfig(duration_s=.5, packets_per_second=0), scenario)
        sim.nodes['A'].queue.append(Packet(1, 'A', 'B', 1000, 0, 5, ['A']))
        sim.generated = 1
        sim.run()
        self.assertEqual(sim.drop_reasons['link_lost'], 1)
        self.assertEqual(sim.snapshot()['hops'], [])
        self.assertTrue(all(n.busy is None for n in sim.nodes.values()))
        self.assert_conservation(sim)

    def test_idle_energy_and_transmit_receive_energy_are_accounted(self):
        from simulator.network_models import Packet
        source, target = ground('A', bandwidth_hz=1000), ground('B', bandwidth_hz=1000)
        sim = PacketSimulation(SimulationConfig(duration_s=1, packets_per_second=0),
                               StaticScenario([source, target], [Link('A', 'B', 0, 1)]))
        source.queue.append(Packet(1, 'A', 'B', 100, 0, 5, ['A']))
        sim.generated = 1
        sim.run()
        self.assertAlmostEqual(source.energy_used_j, .5 + 2 * .1)
        self.assertAlmostEqual(target.energy_used_j, .5 + .8 * .1)
        self.assert_conservation(sim)

    def test_invalid_allocations_do_not_mutate_simulation(self):
        sim = PacketSimulation()
        link = next(iter(sim.links))
        before = sim.snapshot()
        for allocation in ({link: -1}, {link: math.nan}, {link: 1e20}, {'X->Y': 1}, {link: True}):
            with self.assertRaises(ValueError):
                sim.step({'bandwidth_hz': allocation})
            self.assertEqual(sim.snapshot(), before)

    def test_zero_bandwidth_action_blocks_transmission(self):
        sim = PacketSimulation(SimulationConfig(duration_s=.1))
        sim.step({'bandwidth_hz': {}})
        self.assertEqual(sim.delivered, 0)
        self.assertEqual(len(sim.jobs), 0)
        self.assertGreater(sim.generated, 0)
        self.assert_conservation(sim)

    def test_bad_config(self):
        for config in ({'dt_s': 0}, {'battery_j': -1}, {'duration_s': math.inf},
                       {'seed': 1.5}, {'packets_per_second': math.nan}, {'buffer_packets': 1.1}):
            with self.assertRaises(ValueError):
                SimulationConfig(**config)

    def test_routing_avoids_depleted_relay_with_energy_policy(self):
        nodes = [ground('A'), ground('B'), NetworkNode('R1', 'air'), NetworkNode('R2', 'air')]
        nodes[2].energy_used_j = 950
        links = [Link('A', 'R1', 1000), Link('R1', 'B', 1000),
                 Link('A', 'R2', 1000), Link('R2', 'B', 1000)]
        sim = PacketSimulation(SimulationConfig(routing_policy='energy_aware'), StaticScenario(nodes, links))
        self.assertEqual(sim._route('A', 'B', 9600), ['A', 'R2', 'B'])


if __name__ == '__main__':
    unittest.main()
