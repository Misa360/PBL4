import random
import unittest
from types import SimpleNamespace
from optimizer.models import Node, Edge, Demand, Budget, NOISE_W_HZ
from optimizer.problem import Problem
from optimizer.pso import search
from optimizer.network import Network
from optimizer.traffic import capacity_advice
from optimizer.service import optimize


class OptimizationReviewTests(unittest.TestCase):
    def test_pso_does_not_discard_a_feasible_seed_for_a_smaller_penalty_score(self):
        nodes={key:Node(key,'ground',1.,1.,None,None) for key in ['G1','G2']}
        def evaluate(path,powers,bandwidth):
            feasible=powers[0]>=.999999 and bandwidth[0]>=.999999
            return dict(feasible=feasible,cost=10. if feasible else None,score=10. if feasible else 1.,
                        path=path,power=powers,bandwidth=bandwidth)
        p=SimpleNamespace(network=SimpleNamespace(nodes=nodes),resources=lambda path:([1.],[1.]),evaluate=evaluate)
        result,_,_=search(p,['G1','G2'],random.Random(42),Budget(particles=4,pso_iterations=2))
        self.assertTrue(result['feasible'])
        self.assertEqual(result['cost'],10.)

    def problem(self):
        nodes={key:Node(key,kind,4e6,2,1000 if kind=='UAV' else None,
            1000 if kind=='UAV' else None,base_power_w=0,tx_circuit_w=0,
            rx_power_w=0,amplifier_efficiency=1) for key,kind in [('G1','ground'),('U1','UAV'),('G2','ground')]}
        edges={(a,b):Edge(a,b,1000,NOISE_W_HZ*2e6) for a,b in [('G1','U1'),('U1','G2')]}
        net=SimpleNamespace(nodes=nodes,edges=lambda:edges,reserve_fraction=.2,time_s=0.,revision=0)
        return Problem(net,Demand(source='G1',target='G2',data_mb=.1,required_mbps=.1,
            energy_weight=1,latency_weight=0))

    def test_pso_reduces_power_when_energy_savings_are_physically_possible(self):
        p=self.problem();path=['G1','U1','G2'];initial=p.evaluate(path)
        budget=Budget(particles=8,pso_iterations=4)
        result,history,count=search(p,path,random.Random(42),budget)
        self.assertTrue(result['feasible'])
        self.assertLess(result['cost'],initial['cost']*.95)
        self.assertLess(sum(result['power']),sum(initial['power']))
        self.assertEqual(count,8*4+1)
        for node in p.network.nodes:
            used=sum(s['bandwidth_hz'] for s in result['segments'] if node in (s['source'],s['target']))
            self.assertLessEqual(used,p.network.nodes[node].bandwidth_hz+1e-6)

    def test_completed_own_traffic_does_not_become_background_reservation(self):
        net=Network(load_profile='idle',forecast_load=True)
        segment=dict(source='G1',target='U1',start_s=0.,end_s=1.,bandwidth_hz=10e6)
        net.observe_interval(1.,[segment])
        self.assertEqual(net.load_history['U1'][-1],1.)
        self.assertEqual(net.nodes['U1'].predicted_reserved_bandwidth_hz,0.)
        self.assertEqual(net.nodes['U1'].planning_bandwidth_hz,10e6)

    def test_refinement_diagnostics_describe_measured_cost_change(self):
        p=self.problem();budget=Budget(ants=2,aco_iterations=2,particles=8,pso_iterations=4,candidates=1)
        aco=optimize(p.network,p.demand,'aco',42,budget)
        refined=optimize(p.network,p.demand,'aco_pso',42,budget)
        self.assertTrue(refined['feasible'])
        info=refined['refinement']
        self.assertAlmostEqual(info['initial_cost'],aco['cost'])
        self.assertAlmostEqual(info['cost_improvement_pct'],100*(aco['cost']-refined['cost'])/aco['cost'])
        self.assertTrue(info['changed_power'])

    def test_alerts_require_headroom_risk_and_forecast_evidence(self):
        self.assertEqual(capacity_advice(.1,.95,0)['state'],'learning')
        self.assertEqual(capacity_advice(.1,.95,10,.2,.1)['state'],'unreliable')
        self.assertEqual(capacity_advice(.1,.95,10,.05,.1)['state'],'forecast_high')
        self.assertEqual(capacity_advice(.9,.5,0,enabled=False)['state'],'observed_high')
        self.assertEqual(capacity_advice(.1,.3,10,.05,.1)['state'],'normal')

    def test_poor_background_forecast_falls_back_to_last_observation(self):
        net=Network(load_profile='idle',forecast_load=True)
        for value in [.1]*6+[.8]*6:
            net.nodes['U1'].reserved_bandwidth_hz=value*10e6
            net.update_traffic('U1',value,value)
        data=net.forecast_all()['U1'];score=data['background_score']
        self.assertGreater(score['mae'],score['persistence_mae'])
        self.assertAlmostEqual(data['planning_fraction'],.8)
        self.assertEqual(data['capacity_advice']['state'],'unreliable')
