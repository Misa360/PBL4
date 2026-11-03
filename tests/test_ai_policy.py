import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.policy import Policy, features, softmax, route_options, FEATURES
from ai.train import imitate, reward
from ai.train import train
from ai.dataset import generate
from ai.evaluate import evaluate
from optimizer.models import Budget, Demand
from legacy_fixtures import Network
from optimizer.problem import Problem
from optimizer.service import optimize
from legacy_fixtures import OptimizerSession


class PolicyTests(unittest.TestCase):
    def test_decoder_masks_dead_ends_and_excess_hops(self):
        from types import SimpleNamespace
        problem = SimpleNamespace(demand=SimpleNamespace(target='T'), adjacency={
            'S':['dead','A'], 'dead':[], 'A':['S','B'], 'B':['T'], 'T':[]})
        self.assertEqual(route_options(problem, ['S']), ['A'])
        self.assertEqual(route_options(problem, ['S','A']), ['B'])
        self.assertEqual(route_options(problem, ['p1','p2','p3','p4','p5','p6','S','A']), [])

    def test_training_and_held_out_evaluation_end_to_end(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dataset = directory/'dataset'
            generate(dataset, samples=32, teacher_restarts=1,
                     budget=Budget(ants=2, aco_iterations=2, particles=2, pso_iterations=2))
            trained = train(dataset, directory/'checkpoint.json', epochs=1, rl_epochs=1)
            self.assertEqual(trained.metadata['rl_epochs'], 1)
            with patch('ai.policy.Policy.load', return_value=trained):
                result = evaluate([dataset], directory/'evaluation', seeds=1, quick=True)
            self.assertEqual(len(result['summary']), 5)
            self.assertTrue((directory/'evaluation'/'runs.csv').is_file())
            # Test IDs cannot appear in train or validation checkpoint provenance.
            first = json.loads((dataset/'test.jsonl').read_text().splitlines()[0])
            trained.metadata['train_scenario_ids'].append(first['scenario_id'])
            with patch('ai.policy.Policy.load', return_value=trained):
                with self.assertRaises(ValueError):
                    evaluate([dataset], directory/'leaked', seeds=1, quick=True)

    def test_imitation_increases_expert_next_hop_probability(self):
        network = Network()
        network.nodes['U2'].battery_j = .35*network.nodes['U2'].battery_capacity_j
        problem = Problem(network, Demand(latency_weight=.5))
        expert = optimize(problem.network, problem.demand, 'aco_pso', 42,
                          Budget(ants=4, aco_iterations=4, particles=4, pso_iterations=4))
        self.assertTrue(expert['feasible'])
        policy = Policy()
        source, chosen = expert['path'][:2]
        options = problem.adjacency[source]
        def probability():
            return softmax([policy.forward(features(problem, source, b))[0][0] for b in options])[options.index(chosen)]
        before = probability()
        for _ in range(30):
            imitate(policy, problem, expert)
        self.assertGreater(probability(), before)

    def test_sampling_serialization_and_constraints(self):
        policy = Policy()
        problem = Problem(Network(), Demand(latency_weight=.5))
        samples = policy.generate(problem, random.Random(42), 20)
        for result, trace in samples:
            path = result['path']
            self.assertEqual(len(path), len(set(path)))
            self.assertLessEqual(len(path), 9)
            if result['feasible']:
                self.assertTrue(problem.evaluate(path, result['power'], result['bandwidth'])['feasible'])
            policy.reinforce(trace, reward(result))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'model.json'
            policy.save(path)
            restored = Policy.load(path)
            self.assertEqual(policy.forward([0.]*FEATURES), restored.forward([0.]*FEATURES))
            data = json.loads(path.read_text())
            data['w'][0][0] = float('nan')
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                Policy.load(path)

    def test_reinforce_increases_likelihood_of_rewarded_action(self):
        policy = Policy()
        problem = Problem(Network(), Demand())
        _, trace = policy.generate(problem, random.Random(9), 1)[0]
        xs, _, chosen, _, pi, _, bi = trace[0]
        def likelihood():
            logits = [policy.forward(x)[0] for x in xs]
            return (softmax([v[0] for v in logits])[chosen]
                    * softmax(logits[chosen][1:5])[pi]
                    * softmax(logits[chosen][5:8])[bi])
        before = likelihood()
        for _ in range(10):
            policy.reinforce([trace[0]], 1)
        self.assertGreater(likelihood(), before)

    def test_missing_model_exact_baseline_fallback(self):
        net, demand = Network(), Demand()
        budget = Budget(ants=4, aco_iterations=4, particles=4, pso_iterations=4)
        baseline = optimize(net, demand, 'aco_pso', 42, budget)
        with patch('ai.policy.Policy.load', side_effect=FileNotFoundError):
            result = optimize(net, demand, 'ai_aco_pso', 42, budget)
        self.assertEqual(result['ai']['status'], 'fallback')
        for key in ('path', 'power', 'bandwidth', 'cost', 'evaluations'):
            self.assertEqual(result[key], baseline[key])

    def test_latency_objective_and_ai_transaction(self):
        net = Network()
        request = Demand(latency_weight=1)
        budget = Budget(ants=4, aco_iterations=4, particles=4, pso_iterations=4)
        result = optimize(net, request, 'ai_aco_pso', 42, budget)
        self.assertTrue(result['feasible'])
        self.assertAlmostEqual(result['cost'], result['duration_s']/(request.bits/(request.required_mbps*1e6)))
        session = OptimizerSession()
        before = session.snapshot()
        plan = session.search(request, 'ai_aco_pso', 42, budget)
        self.assertEqual(before, session.snapshot())
        session.transmit(plan['plan_id'])
        self.assertEqual(session.served, 1)
        with self.assertRaises(ValueError):
            session.transmit(plan['plan_id'])
