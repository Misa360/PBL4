"""Network state, in SI units. No machine-learning dependency."""

from collections import deque
from dataclasses import dataclass, field
from math import isfinite


@dataclass
class Packet:
    packet_id: int
    source_id: str
    destination_id: str
    size_bits: int
    created_at: float
    expires_at: float
    path: list = field(default_factory=list)


@dataclass
class NetworkNode:
    node_id: str
    layer: str
    bandwidth_hz: float = 5e6
    battery_capacity_j: float | None = 1000.0
    buffer_packets: int = 64
    base_power_w: float = 0.5
    tx_extra_power_w: float = 2.0
    rx_extra_power_w: float = 0.8
    queue: deque = field(default_factory=deque, init=False)
    routing_table: dict = field(default_factory=dict, init=False)
    transmitted: int = field(default=0, init=False)
    received: int = field(default=0, init=False)
    energy_used_j: float = field(default=0.0, init=False)
    busy: str | None = field(default=None, init=False)

    def __post_init__(self):
        if not self.node_id or self.layer not in ('ground', 'air', 'space'):
            raise ValueError('Invalid node ID or layer')
        for value in (self.bandwidth_hz, self.base_power_w,
                      self.tx_extra_power_w, self.rx_extra_power_w):
            if not isfinite(value) or value < 0:
                raise ValueError('Resources and power must be finite and nonnegative')
        if self.bandwidth_hz <= 0 or not isinstance(self.buffer_packets, int) or self.buffer_packets < 1:
            raise ValueError('Bandwidth and buffer capacity must be positive')
        if self.battery_capacity_j is not None and (
                not isfinite(self.battery_capacity_j) or self.battery_capacity_j <= 0):
            raise ValueError('Battery capacity must be positive, or None for mains power')

    @property
    def remaining_j(self):
        if self.battery_capacity_j is None:
            return None
        return max(0.0, self.battery_capacity_j - self.energy_used_j)

    @property
    def alive(self):
        return self.remaining_j is None or self.remaining_j > 1e-9

    @property
    def power_w(self):
        if not self.alive:
            return 0.0
        return self.base_power_w + (
            self.tx_extra_power_w if self.busy == 'tx' else
            self.rx_extra_power_w if self.busy == 'rx' else 0.0)


@dataclass(frozen=True)
class Link:
    """A directed link; rate = allocated bandwidth * spectral efficiency."""
    source: str
    target: str
    distance_m: float
    efficiency_bps_hz: float = 2.0

    def __post_init__(self):
        if self.source == self.target or not isfinite(self.distance_m) or self.distance_m < 0:
            raise ValueError('Invalid link endpoints or distance')
        if not isfinite(self.efficiency_bps_hz) or self.efficiency_bps_hz <= 0:
            raise ValueError('Spectral efficiency must be positive')

    @property
    def key(self):
        return f'{self.source}->{self.target}'

    @property
    def propagation_s(self):
        return self.distance_m / 299792458.0
