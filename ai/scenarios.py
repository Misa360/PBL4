"""Seeded resource scenarios: mixed batteries, residual bandwidth and hard demands."""
import hashlib
import random
from dataclasses import replace

from optimizer.baselines import path_for
from optimizer.models import Demand
from optimizer.network import Network, CONSTELLATIONS
from optimizer.problem import Problem

SCHEMA_VERSION = 5


def random_scenario(master_seed, index, size='small', deployment='distributed', suite='balanced', constellation='balanced'):
    if type(master_seed) is not int or type(index) is not int or index < 0:
        raise ValueError('seed and nonnegative scenario index must be integers')
    if suite not in ('balanced', 'stress'):
        raise ValueError('suite must be balanced or stress')
    if deployment != 'distributed':
        raise ValueError('New scenarios use distributed station placement only')
    if constellation not in ('compact','balanced','dense'):
        raise ValueError('Choose compact, balanced or dense constellation')
    digest = hashlib.sha256(f'global-v5:{suite}:{master_seed}:{index}:{size}:{constellation}'.encode()).hexdigest()
    rng = random.Random(int(digest, 16))
    # Mixed networks have weak (<20%), medium (35-65%) and strong (80-100%)
    # nodes together. Other profiles cover uniformly charged/depleted networks.
    profile = ('full','mixed','strong','medium','mixed','weak')[index % 6]
    # Cross the battery and load factors. Using index % 3 here would make all
    # weak batteries busy and all full batteries idle, creating a shortcut.
    load = ('idle','mixed','busy')[(index//6+index%3) % 3]
    base_uavs = CONSTELLATIONS[constellation][size][1]
    uavs = rng.choice([max(2,base_uavs-2),base_uavs,min(32,base_uavs+2)])
    config = dict(size=size, deployment='distributed', constellation=constellation,
                  battery_j=10 ** rng.uniform(1.5, 3.7), reserve_fraction=rng.uniform(.1, .3),
                  battery_profile=profile, load_profile=load, state_seed=rng.randrange(2147483648),
                  forecast_load=True, uav_count=uavs)
    if suite == 'stress':
        # Deliberately outside the balanced training distribution. Never train on this suite.
        config.update(battery_j=10 ** rng.uniform(0, 1.2), reserve_fraction=rng.uniform(.35,.6),
                      battery_profile='mixed', load_profile='busy')
    network = Network(**config)
    network.time_s = rng.uniform(0, 600) if rng.random() < .35 else rng.uniform(0, 9000)
    stations = [key for key, node in network.nodes.items() if node.kind == 'ground']
    source, target = rng.sample(stations, 2)
    demand = Demand(source, target, data_mb=10 ** rng.uniform(-3, .7),
                    required_mbps=10 ** rng.uniform(-1.5, .8),
                    energy_weight=rng.uniform(.05, .95), latency_weight=rng.uniform(0, 1))
    if rng.random() < .25:
        # Demand near a physically evaluated fixed-allocation route capacity;
        # not an arbitrary high rate labelled "hard" without a reference.
        probe = Problem(network, replace(demand, required_mbps=.001))
        path = path_for(probe, 'min_delay', rng)
        reference = probe.evaluate(path)
        if reference.get('rate_bps'):
            rate = reference['rate_bps']/1e6*rng.uniform(.85, 1.15)
            demand = replace(demand, required_mbps=max(.001, min(50, rate)))
    bucket = int(digest[:8], 16) % 100
    split = 'test' if suite == 'stress' else 'train' if bucket < 70 else 'validation' if bucket < 85 else 'test'
    return digest, split, config, network, demand, rng
