"""Discrete-event, store-and-forward packet network with half-duplex radios.

Topology is sampled at step boundaries. Packet serialization, propagation and
battery depletion use continuous simulation time inside each step.
"""

import heapq
import math
import random
from collections import Counter, deque
from dataclasses import asdict, dataclass

from .network_models import Packet
from .scenario import RegionalScenario


@dataclass
class SimulationConfig:
    duration_s: float = 120.0
    dt_s: float = 0.1
    packets_per_second: float = 40.0  # per flow
    packet_size_bytes: int = 1200
    packet_ttl_s: float = 10.0
    bandwidth_hz: float = 5e6
    battery_j: float = 1000.0
    buffer_packets: int = 64
    seed: int = 42
    routing_policy: str = 'delay'

    def __post_init__(self):
        for key in ('duration_s', 'dt_s', 'packet_ttl_s', 'bandwidth_hz', 'battery_j'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be a finite positive number')
        if not 0.01 <= self.dt_s <= 1 or not self.dt_s <= self.duration_s <= 600:
            raise ValueError('Use dt_s in [0.01, 1], duration_s in [dt_s, 600]')
        if (isinstance(self.packets_per_second, bool) or
                not isinstance(self.packets_per_second, (int, float)) or
                not math.isfinite(self.packets_per_second) or not 0 <= self.packets_per_second <= 500):
            raise ValueError('packets_per_second must be in [0, 500]')
        for key, maximum in (('packet_size_bytes', 65536), ('buffer_packets', 4096)):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{key} must be an integer in [1, {maximum}]')
        if type(self.seed) is not int or self.routing_policy not in ('delay', 'energy_aware'):
            raise ValueError('Invalid seed or routing policy')


class PacketSimulation:
    def __init__(self, config=None, scenario=None):
        self.config = config or SimulationConfig()
        self.scenario = scenario or RegionalScenario(
            self.config.battery_j, self.config.bandwidth_hz, self.config.buffer_packets)
        self.nodes = {n.node_id: n for n in self.scenario.nodes}
        if len(self.nodes) != len(self.scenario.nodes):
            raise ValueError('Node IDs must be unique')
        for source, destination in self.scenario.flows:
            if source not in self.nodes or destination not in self.nodes or source == destination:
                raise ValueError('Invalid traffic flow')
        self.time = 0.0
        self.rng = random.Random(self.config.seed)
        self.events = []
        self.sequence = 0
        self.packet_id = 0
        self.jobs = {}
        self.generated = self.delivered = self.delivered_bits = 0
        self.drop_reasons = Counter()
        self.delays = []
        self.packet_log = deque(maxlen=100)
        self.hop_log = deque(maxlen=200)
        self.hop_sequence = 0
        self.history = deque(maxlen=600)
        self.first_dead_at = None
        self.schedule_cursor = 0
        self._refresh_links()
        if self.config.packets_per_second:
            for flow in self.scenario.flows:
                self._event(self.rng.expovariate(self.config.packets_per_second), 'generate', flow)

    def _event(self, when, kind, data):
        self.sequence += 1
        heapq.heappush(self.events, (when, self.sequence, kind, data))

    def _refresh_links(self):
        self.links = {link.key: link for link in self.scenario.links_at(self.time)
                      if self.nodes[link.source].alive and self.nodes[link.target].alive}
        for job in list(self.jobs.values()):
            if job['stage'] == 'tx' and job['link'].key not in self.links:
                self._cancel(job, 'link_lost')
        fixed = {job['link'].key: job['bandwidth_hz'] for job in self.jobs.values()
                 if job['stage'] == 'tx'}
        reserved_tx, reserved_rx = Counter(), Counter()
        for key, bandwidth in fixed.items():
            reserved_tx[self.links[key].source] += bandwidth
            reserved_rx[self.links[key].target] += bandwidth
        outgoing, incoming = Counter(), Counter()
        for key, link in self.links.items():
            if key in fixed:
                continue
            outgoing[link.source] += 1
            incoming[link.target] += 1
        self.allocation = {
            key: fixed[key] if key in fixed else min(
                max(0, self.nodes[link.source].bandwidth_hz - reserved_tx[link.source]) / outgoing[link.source],
                max(0, self.nodes[link.target].bandwidth_hz - reserved_rx[link.target]) / incoming[link.target])
            for key, link in self.links.items()}

    def _validate_action(self, action):
        if not isinstance(action, dict) or set(action) != {'bandwidth_hz'}:
            raise ValueError('Action must contain only bandwidth_hz: {"source->target": Hz}')
        allocation = action['bandwidth_hz']
        if not isinstance(allocation, dict) or set(allocation) - set(self.links):
            raise ValueError('Allocation contains an unavailable link')
        tx, rx = Counter(), Counter()
        for key, bandwidth in allocation.items():
            if (isinstance(bandwidth, bool) or not isinstance(bandwidth, (int, float)) or
                    not math.isfinite(bandwidth) or bandwidth < 0):
                raise ValueError('Bandwidth must be finite and nonnegative')
            link = self.links[key]
            tx[link.source] += bandwidth
            rx[link.target] += bandwidth
        for totals in (tx, rx):
            if any(value > self.nodes[node].bandwidth_hz + 1e-6 for node, value in totals.items()):
                raise ValueError('Allocation exceeds a transmitter or receiver bandwidth budget')
        for job in self.jobs.values():
            if job['stage'] == 'tx' and allocation.get(job['link'].key, 0) != job['bandwidth_hz']:
                raise ValueError('Cannot change bandwidth of a frame already being serialized')
        return {key: allocation.get(key, 0.0) for key in self.links}

    def _route(self, source, destination, bits):
        heap = [(0.0, source, [source])]
        visited = set()
        while heap:
            cost, current, path = heapq.heappop(heap)
            if current == destination:
                return path
            if current in visited:
                continue
            visited.add(current)
            if current != source and self.nodes[current].layer == 'ground':
                continue  # endpoint stations do not act as transit routers
            for key, link in self.links.items():
                bandwidth = self.allocation[key]
                if link.source != current or bandwidth <= 0 or not self.nodes[link.target].alive:
                    continue
                weight = bits / (bandwidth * link.efficiency_bps_hz) + link.propagation_s
                target = self.nodes[link.target]
                if self.config.routing_policy == 'energy_aware' and target.remaining_j is not None:
                    weight *= 1 + 2 * (1 - target.remaining_j / target.battery_capacity_j)
                if link.target not in visited:
                    heapq.heappush(heap, (cost + weight, link.target, path + [link.target]))
        return None

    def _drop(self, packet, reason):
        self.drop_reasons[reason] += 1
        self.packet_log.append({'id': packet.packet_id, 'source': packet.source_id,
                                'destination': packet.destination_id, 'status': reason,
                                'time_s': self.time, 'path': packet.path[:]})

    def _enqueue(self, node, packet):
        if not node.alive:
            self._drop(packet, 'node_dead')
        elif self.time >= packet.expires_at:
            self._drop(packet, 'ttl_expired')
        elif len(node.queue) >= node.buffer_packets:
            self._drop(packet, 'buffer_full')
        else:
            node.queue.append(packet)

    def _cancel(self, job, reason):
        if self.jobs.pop(job['packet'].packet_id, None) is None:
            return
        if job['stage'] == 'tx':
            self.nodes[job['link'].source].busy = None
            self.nodes[job['link'].target].busy = None
        self._drop(job['packet'], reason)

    def _reap_dead(self):
        dead = {key for key, node in self.nodes.items() if not node.alive}
        if dead and self.first_dead_at is None:
            self.first_dead_at = self.time
        for key in dead:
            node = self.nodes[key]
            while node.queue:
                self._drop(node.queue.popleft(), 'node_dead')
            node.routing_table.clear()
        for job in list(self.jobs.values()):
            link = job['link']
            if link.target in dead or (job['stage'] == 'tx' and link.source in dead):
                self._cancel(job, 'node_dead')
        for key in list(self.links):
            link = self.links[key]
            if link.source in dead or link.target in dead:
                del self.links[key]
                self.allocation.pop(key, None)

    def _schedule(self):
        # Rotate service order so a low-ID sender cannot monopolize a shared radio.
        order = list(self.nodes.values())
        offset = self.schedule_cursor % len(order)
        self.schedule_cursor += 1
        for node in order[offset:] + order[:offset]:
            node.routing_table.clear()
            # Expire every queued packet, including those behind the FIFO head.
            kept = deque()
            while node.queue:
                packet = node.queue.popleft()
                if self.time >= packet.expires_at:
                    self._drop(packet, 'ttl_expired')
                else:
                    kept.append(packet)
            node.queue = kept
            if not node.alive or node.busy or not node.queue:
                continue
            packet = node.queue[0]
            route = self._route(node.node_id, packet.destination_id, packet.size_bits)
            if not route:
                continue  # store until a route appears, buffer overflows, or TTL expires
            target = self.nodes[route[1]]
            node.routing_table[packet.destination_id] = target.node_id
            if target.busy:
                continue
            link = self.links[f'{node.node_id}->{target.node_id}']
            bandwidth = self.allocation[link.key]
            tx_s = packet.size_bits / (bandwidth * link.efficiency_bps_hz)
            node.queue.popleft()
            node.busy, target.busy = 'tx', 'rx'
            self.jobs[packet.packet_id] = {
                'packet': packet, 'link': link, 'stage': 'tx',
                'bandwidth_hz': bandwidth, 'rate_bps': bandwidth * link.efficiency_bps_hz,
                'tx_end': self.time + tx_s}
            self._event(self.time + tx_s, 'tx_end', packet.packet_id)

    def _handle(self, kind, data):
        if kind == 'generate':
            source, destination = data
            self.packet_id += 1
            packet = Packet(self.packet_id, source, destination,
                            self.config.packet_size_bytes * 8, self.time,
                            self.time + self.config.packet_ttl_s, [source])
            self.generated += 1
            self._enqueue(self.nodes[source], packet)
            self._event(self.time + self.config.packet_ttl_s, 'expire', None)
            self._event(self.time + self.rng.expovariate(self.config.packets_per_second),
                        'generate', data)
        elif kind == 'tx_end':
            job = self.jobs.get(data)
            if job is None:
                return
            link = job['link']
            self.nodes[link.source].busy = self.nodes[link.target].busy = None
            self.nodes[link.source].transmitted += 1
            job['stage'] = 'propagation'
            self._event(self.time + link.propagation_s, 'arrival', data)
        elif kind == 'arrival':
            job = self.jobs.pop(data, None)
            if job is None:
                return
            packet, target = job['packet'], self.nodes[job['link'].target]
            self.hop_sequence += 1
            self.hop_log.append({'id': self.hop_sequence, 'packet_id': packet.packet_id,
                                 'source': job['link'].source, 'target': job['link'].target,
                                 'origin': packet.source_id, 'time_s': self.time})
            packet.path.append(target.node_id)
            target.received += 1
            if not target.alive:
                self._drop(packet, 'node_dead')
            elif self.time >= packet.expires_at:
                self._drop(packet, 'ttl_expired')
            elif target.node_id == packet.destination_id:
                self.delivered += 1
                self.delivered_bits += packet.size_bits
                delay = self.time - packet.created_at
                self.delays.append(delay)
                self.packet_log.append({'id': packet.packet_id, 'source': packet.source_id,
                                        'destination': packet.destination_id, 'status': 'delivered',
                                        'time_s': self.time, 'delay_ms': delay * 1000,
                                        'path': packet.path[:]})
            elif len(packet.path) >= 32:
                self._drop(packet, 'hop_limit')
            else:
                self._enqueue(target, packet)

    def step(self, action=None):
        """Advance one topology interval. Invalid actions leave simulation state unchanged."""
        if self.time >= self.config.duration_s:
            return self.snapshot()
        allocation = self._validate_action(action) if action is not None else None
        # Topology and equal allocation have already been refreshed at the last boundary.
        if allocation is not None:
            self.allocation = allocation
        self._schedule()
        end = min(self.config.duration_s, self.time + self.config.dt_s)
        while self.time < end - 1e-12:
            next_event = self.events[0][0] if self.events else math.inf
            death = min((self.time + n.remaining_j / n.power_w
                         for n in self.nodes.values()
                         if n.alive and n.remaining_j is not None and n.power_w > 0), default=math.inf)
            until = min(end, next_event, death)
            elapsed = max(0.0, until - self.time)
            for node in self.nodes.values():
                used = node.power_w * elapsed
                if node.remaining_j is not None:
                    used = min(used, node.remaining_j)
                node.energy_used_j += used
            self.time = until
            self._reap_dead()
            while self.events and self.events[0][0] <= self.time + 1e-12:
                _, _, kind, data = heapq.heappop(self.events)
                self._handle(kind, data)
            self._schedule()
        self._refresh_links()
        metrics = self.metrics()
        self.history.append(metrics)
        return self.snapshot()

    def metrics(self):
        dropped = sum(self.drop_reasons.values())
        ordered = sorted(self.delays)
        energy = sum(n.energy_used_j for n in self.nodes.values())
        return {
            'time_s': self.time, 'generated': self.generated, 'delivered': self.delivered,
            'dropped': dropped, 'queued': sum(len(n.queue) for n in self.nodes.values()),
            'in_flight': len(self.jobs),
            'delivery_ratio': self.delivered / self.generated if self.generated else 0,
            'drop_ratio': dropped / self.generated if self.generated else 0,
            'throughput_bps': self.delivered_bits / self.time if self.time else 0,
            'mean_delay_ms': sum(ordered) / len(ordered) * 1000 if ordered else None,
            'p95_delay_ms': ordered[max(0, math.ceil(.95 * len(ordered)) - 1)] * 1000 if ordered else None,
            'energy_used_j': energy,
            'energy_per_mbit_j': energy / (self.delivered_bits / 1e6) if self.delivered_bits else None,
            'first_node_dead_s': self.first_dead_at,
            'active_nodes': sum(n.alive for n in self.nodes.values()),
            'drop_reasons': dict(self.drop_reasons),
        }

    def snapshot(self):
        return {
            'config': asdict(self.config), 'done': self.time >= self.config.duration_s - 1e-9,
            'metrics': self.metrics(),
            'nodes': [{'id': n.node_id, 'layer': n.layer, 'alive': n.alive,
                       'battery_j': n.remaining_j, 'battery_capacity_j': n.battery_capacity_j,
                       'energy_used_j': n.energy_used_j, 'bandwidth_hz': n.bandwidth_hz,
                       'queue_packets': len(n.queue), 'buffer_packets': n.buffer_packets,
                       'tx_packets': n.transmitted, 'rx_packets': n.received, 'radio': n.busy,
                       'routing_table': dict(n.routing_table),
                       'position_m': list(getattr(self.scenario, 'coordinates', {}).get(n.node_id, []))}
                      for n in self.nodes.values()],
            'links': [{'id': k, 'source': l.source, 'target': l.target,
                       'bandwidth_hz': self.allocation[k],
                       'rate_bps': self.allocation[k] * l.efficiency_bps_hz,
                       'distance_m': l.distance_m, 'propagation_ms': l.propagation_s * 1000,
                       'transmitting': any(j['stage'] == 'tx' and j['link'].key == k for j in self.jobs.values())}
                      for k, l in self.links.items()],
            'packets': list(self.packet_log), 'history': list(self.history),
            'hops': list(self.hop_log),
            'flows': [{'source': a, 'destination': b} for a, b in self.scenario.flows],
        }

    def run(self):
        while self.time < self.config.duration_s - 1e-9:
            self.step()
        return self.snapshot()
