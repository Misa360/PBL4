"""Imitation pretraining followed by contextual-bandit policy gradients."""
import argparse
import copy
import json
import math
import random
import time
from pathlib import Path

from optimizer.models import Demand
from optimizer.network import Network
from optimizer.problem import Problem
from .policy import Policy, MODEL_PATH, POWER, BANDWIDTH, features, softmax, route_options


def restore(row):
    config = dict(row['config'])
    config.setdefault('constellation','legacy')
    net = Network(**config)
    net.time_s = row['state']['time_s']
    for node in row['state']['nodes']:
        net.nodes[node['id']].battery_j = node['battery_j']
        net.nodes[node['id']].reserved_bandwidth_hz = node.get('reserved_bandwidth_hz', 0)
        net.nodes[node['id']].predicted_reserved_bandwidth_hz = node.get('predicted_reserved_bandwidth_hz', 0)
    return Problem(net, Demand(**row['request']))


def reward(result):
    return 1/(1+result['cost']) if result['feasible'] else -1.


def imitate(policy, problem, label, lr=.01):
    path = label['path']
    if len(path) > 9:
        return
    for i, (a, chosen) in enumerate(zip(path, path[1:])):
        options = route_options(problem, path[:i+1])
        xs = [features(problem, a, b) for b in options]
        outputs = [policy.forward(x)[0] for x in xs]
        probs = softmax([v[0] for v in outputs])
        for b, x, out, prob in zip(options, xs, outputs, probs):
            gradient = [prob-int(b == chosen)] + [0.] * 7
            if b == chosen:
                cap = min(problem.network.nodes[a].planning_bandwidth_hz, problem.network.nodes[b].planning_bandwidth_hz)
                pi = min(range(4), key=lambda k: abs(POWER[k]-label['power'][i]/problem.network.nodes[a].p_max_w))
                bi = min(range(3), key=lambda k: abs(BANDWIDTH[k]-label['bandwidth'][i]/cap))
                gradient[1:5] = [v-int(k == pi) for k, v in enumerate(softmax(out[1:5]))]
                gradient[5:8] = [v-int(k == bi) for k, v in enumerate(softmax(out[5:8]))]
            policy.update(x, gradient, lr)


def train(dataset, checkpoint=MODEL_PATH, epochs=15, rl_epochs=8, seed=17):
    started = time.perf_counter()
    directories = [Path(dataset)] if isinstance(dataset, (str, Path)) else [Path(d) for d in dataset]
    manifests = [json.loads((d/'metadata.json').read_text()) for d in directories]
    if any(m.get('suite') == 'stress' for m in manifests):
        raise ValueError('Stress suite is held out and cannot be used for training')
    if not all(m['completed'] for m in manifests):
        raise ValueError('Dataset is incomplete')
    rows = {split: [json.loads(line) for directory in directories
                    for line in (directory/f'{split}.jsonl').read_text().splitlines()]
            for split in ('train', 'validation')}
    if not rows['train'] or not rows['validation'] or not any(r['label'] for r in rows['train']):
        raise ValueError('Need train/validation scenarios and feasible training labels')
    if {r['scenario_id'] for r in rows['train']} & {r['scenario_id'] for r in rows['validation']}:
        raise ValueError('Leaked scenario across splits')
    for split, values in rows.items():
        if len({r['scenario_id'] for r in values}) != len(values):
            raise ValueError(f'Duplicate scenario in {split}')
    prepared = {split: [(restore(row), row['label']) for row in values] for split, values in rows.items()}
    policy, rng = Policy(seed), random.Random(seed)
    best, best_score, history, best_epoch = None, -math.inf, [], 0
    for epoch in range(epochs+rl_epochs):
        rng.shuffle(prepared['train'])
        for problem, label in prepared['train']:
            if epoch < epochs:
                if label:
                    imitate(policy, problem, label)
            else:
                samples = policy.generate(problem, rng, 6)
                rewards = [reward(result) for result, _ in samples]
                for value, (_, trace) in zip(rewards, samples):
                    # Leave-one-out baseline is independent of the sampled action.
                    baseline = (sum(rewards)-value)/(len(rewards)-1)
                    policy.reinforce(trace, value-baseline)
        validation = []
        for index, (problem, _) in enumerate(prepared['validation']):
            samples = policy.generate(problem, random.Random(seed+index), 8)
            validation.append(max(reward(result) for result, _ in samples))
        score = sum(validation)/len(validation)
        history.append(dict(epoch=epoch+1, phase='imitation' if epoch < epochs else 'reinforce', validation_reward=score))
        if score > best_score:
            best, best_score = copy.deepcopy(policy), score
            best_epoch = epoch+1
        print(f'Epoch {epoch+1}: validation reward {score:.4f}', flush=True)
    best.metadata = dict(feature_schema='resources-v3+traffic', training='MLP imitation + REINFORCE contextual bandit', seed=seed,
                         dataset_seeds=[m['seed'] for m in manifests],
                         dataset_schemas=[m['schema_version'] for m in manifests],
                         dataset_samples=sum(m['samples'] for m in manifests),
                         teacher_budgets=[m['budget'] for m in manifests], best_validation_reward=best_score,
                         epochs=epochs, rl_epochs=rl_epochs,
                         selected_epoch=best_epoch,
                         selected_phase='imitation' if best_epoch <= epochs else 'reinforce',
                         route_decoder='reachability mask within 8 hops',
                         training_s=time.perf_counter()-started,
                         train_scenario_ids=[r['scenario_id'] for r in rows['train']],
                         validation_scenario_ids=[r['scenario_id'] for r in rows['validation']])
    best.save(checkpoint)
    Path(str(checkpoint)+'.training.json').write_text(json.dumps(history, indent=2))
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', nargs='+', required=True)
    parser.add_argument('--checkpoint', default=str(MODEL_PATH))
    parser.add_argument('--epochs', type=int, default=15)
    parser.add_argument('--rl-epochs', type=int, default=8)
    args = parser.parse_args()
    if args.epochs < 1 or args.rl_epochs < 1:
        parser.error('epochs and rl-epochs must be positive')
    train(args.dataset, args.checkpoint, args.epochs, args.rl_epochs)


if __name__ == '__main__':
    main()
