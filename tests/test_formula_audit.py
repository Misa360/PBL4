import math
import unittest
from types import SimpleNamespace

from optimizer.models import Node, Edge, Demand, NOISE_W_HZ, LIGHT_M_S, capacity
from optimizer.problem import Problem
from simulator.channel import free_space_path_loss, transmission_delay, ground_to_uav_link, uav_to_satellite_link


class FormulaAuditTests(unittest.TestCase):
    def problem(self):
        nodes={key:Node(key,kind,4e6,2,1000 if kind=='UAV' else None,
            1000 if kind=='UAV' else None,base_power_w=.2,tx_circuit_w=.25,
            rx_power_w=.1,amplifier_efficiency=.5) for key,kind in [('G1','ground'),('U1','UAV'),('G2','ground')]}
        edges={(a,b):Edge(a,b,LIGHT_M_S*.1,NOISE_W_HZ*1e6) for a,b in [('G1','U1'),('U1','G2')]}
        net=SimpleNamespace(nodes=nodes,edges=lambda:edges,reserve_fraction=.2)
        return Problem(net,Demand(source='G1',target='G2',data_mb=1,required_mbps=.4,
                                  energy_weight=.5,latency_weight=.25))

    def test_hand_calculated_two_hop_delay_energy_and_cost(self):
        # Each hop: SNR=1, 1 MHz => 1 Mbps; 8 Mbit => 8 seconds + .1s propagation.
        result=self.problem().evaluate(['G1','U1','G2'],[1.,1.],[1e6,1e6])
        self.assertTrue(result['feasible'])
        self.assertAlmostEqual(result['duration_s'],16.2)
        self.assertAlmostEqual(result['rate_bps'],8e6/16.2)
        # Radio: 2*(2.25+.1)*8=37.6 J. Three nodes idle: 3*.2*16.2=9.72 J.
        self.assertAlmostEqual(result['energy_j'],47.32)
        self.assertAlmostEqual(result['battery_after']['U1'],977.96)
        self.assertAlmostEqual(result['cost'],.2551275)

    def test_resource_constraints_reject_oversubscription_and_reserve_violation(self):
        problem=self.problem()
        problem.network.nodes['U1'].bandwidth_hz=1.5e6
        self.assertFalse(problem.evaluate(['G1','U1','G2'],[1.,1.],[1e6,1e6])['feasible'])
        problem=self.problem();problem.network.nodes['U1'].battery_j=210
        self.assertFalse(problem.evaluate(['G1','U1','G2'],[1.,1.],[1e6,1e6])['feasible'])

    def test_fspl_and_units_independent_of_numpy(self):
        self.assertAlmostEqual(free_space_path_loss(1000,299792458.),(4000*math.pi)**2)
        self.assertEqual(transmission_delay(2e6,1),4.)
        self.assertEqual(capacity(1e6,1,NOISE_W_HZ*1e6),1e6)

    def test_invalid_channel_inputs_do_not_produce_negative_delay_or_nan(self):
        for value in (-1,math.nan,math.inf,True):
            with self.assertRaises(ValueError):ground_to_uav_link(value)
        with self.assertRaises(ValueError):free_space_path_loss(1,0)
        with self.assertRaises(ValueError):transmission_delay(1e6,-1)
        with self.assertRaises(ValueError):uav_to_satellite_link(1e6,math.nan)
