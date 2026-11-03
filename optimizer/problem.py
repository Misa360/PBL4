"""Frozen topology. Serialize all hops of one request: conservative half-duplex TDMA.

Bandwidth is reserved per incident path edge (Tx and Rx combined). Requests are
served sequentially, never overlapping. This deliberately makes scheduling explicit.
"""
import math
from collections import defaultdict
from .models import LIGHT_M_S, NOISE_W_HZ, capacity


def result_key(result):
    """A feasible allocation always outranks a constraint-violating allocation."""
    return (not result['feasible'],result['score'])


class Problem:
    def __init__(self, network, demand):
        self.network, self.demand = network, demand
        for key in (demand.source, demand.target):
            if key not in network.nodes or network.nodes[key].kind != 'ground':
                raise ValueError('source and target must be existing ground stations')
        self.edges = network.edges()
        self.adjacency = defaultdict(list)
        for a, b in self.edges:
            if network.nodes[b].kind != 'ground' or b == demand.target:
                self.adjacency[a].append(b)
        # Fixed, algorithm-independent normalization for the given request.
        self.energy_reference_j = max(1, demand.bits / (demand.required_mbps*1e6) * 20)

    def resources(self, path):
        degree = defaultdict(int)
        for a, b in zip(path, path[1:]):
            degree[a] += 1; degree[b] += 1
        bandwidth, powers = [], []
        for a, b in zip(path, path[1:]):
            bandwidth.append(min(self.network.nodes[a].planning_bandwidth_hz/degree[a], self.network.nodes[b].planning_bandwidth_hz/degree[b]))
            powers.append(self.network.nodes[a].p_max_w)
        return powers, bandwidth

    def evaluate(self, path, powers=None, bandwidth=None):
        invalid = lambda reason: {'feasible': False, 'reason': reason, 'path': list(path), 'cost': None, 'score': 1e9}
        if len(path) < 2 or path[0] != self.demand.source or path[-1] != self.demand.target or len(set(path)) != len(path):
            return invalid('invalid_path')
        if any((a, b) not in self.edges for a, b in zip(path, path[1:])):
            return invalid('no_link')
        if any(self.network.nodes[n].kind == 'ground' for n in path[1:-1]):
            return invalid('ground_is_not_a_relay')
        if powers is None and bandwidth is None:
            powers, bandwidth = self.resources(path)
        elif powers is None or bandwidth is None:
            return invalid('invalid_allocation')
        if len(powers) != len(path)-1 or len(bandwidth) != len(powers):
            return invalid('invalid_allocation')
        usage = defaultdict(float)
        energy = defaultdict(float)
        segments = []
        elapsed = 0.0
        violation = 0.0
        for a, b, p, bw in zip(path, path[1:], powers, bandwidth):
            source, target = self.network.nodes[a], self.network.nodes[b]
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0 for x in (p, bw)):
                return invalid('invalid_allocation')
            violation += max(0, p/source.p_max_w - 1)
            usage[a] += bw; usage[b] += bw
            edge = self.edges[a, b]
            rate = capacity(bw, p, edge.gain)
            duration = self.demand.bits / rate
            tx = (p/source.amplifier_efficiency + source.tx_circuit_w) * duration
            rx = target.rx_power_w * duration
            energy[a] += tx; energy[b] += rx
            propagation = edge.distance_m / LIGHT_M_S
            segments.append({'source': a, 'target': b, 'power_w': p, 'bandwidth_hz': bw,
                             'rate_bps': rate, 'snr': p*edge.gain/(NOISE_W_HZ*bw),
                             'tx_energy_j': tx, 'rx_energy_j': rx, 'duration_s': duration,
                             'start_s': elapsed, 'end_s': elapsed+duration, 'arrival_s': elapsed+duration+propagation})
            elapsed += duration + propagation
        for key, bw in usage.items():
            violation += max(0, bw/self.network.nodes[key].planning_bandwidth_hz-1)
        # Every node pays idle/base power for elapsed simulation time; radio extras above.
        for key, node in self.network.nodes.items():
            energy[key] += node.base_power_w * elapsed
        peak = 0.0
        after = {}
        for key, node in self.network.nodes.items():
            after[key] = None if node.battery_j is None else max(0, node.battery_j-energy[key])
            if node.battery_j is not None:
                floor = node.battery_capacity_j*self.network.reserve_fraction
                # Nodes already at reserve are offline and pay idle until fully empty.
                if key in path:
                    violation += max(0, (floor+energy[key]-node.battery_j)/node.battery_capacity_j)
                else:
                    energy[key] = min(energy[key], node.battery_j)
                peak = max(peak, energy[key]/max(1e-9, node.battery_j))
        achieved = self.demand.bits/elapsed
        deficit = max(0, 1-achieved/(self.demand.required_mbps*1e6))
        violation += deficit
        if elapsed > 300:
            violation += elapsed/300-1
        total_energy = sum(energy.values())
        w = self.demand.energy_weight
        energy_cost = w*total_energy/self.energy_reference_j + (1-w)*peak
        latency_cost = elapsed / (self.demand.bits / (self.demand.required_mbps*1e6))
        cost = (1-self.demand.latency_weight)*energy_cost + self.demand.latency_weight*latency_cost
        feasible = violation <= 1e-9
        return {'feasible': feasible, 'reason': None if feasible else 'rate_or_resource_or_reserve',
                'path': list(path), 'cost': cost if feasible else None,
                'score': cost+1e4*violation, 'rate_bps': achieved, 'energy_j': total_energy,
                'peak_battery_fraction_used': peak, 'duration_s': elapsed, 'hops': len(path)-1,
                'energy_by_node_j': dict(energy), 'battery_after': after, 'segments': segments,
                'bandwidth': list(bandwidth), 'power': list(powers)}
