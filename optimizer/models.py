"""SI units throughout. Shannon AWGN and explicit transmitter/receiver accounting."""
import math
from dataclasses import dataclass

EARTH_M = 6371000.0
MU = 3.986004418e14
OMEGA = 2 * math.pi / 86164.0905
LIGHT_M_S = 299792458.0
NOISE_W_HZ = 1.380649e-23 * 290 * 10 ** (5 / 10)  # 290 K, noise figure 5 dB
FREQUENCY_HZ = 2.4e9


def finite(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number in [{low}, {high}]')
    return value


def capacity(bandwidth_hz, power_w, gain):
    if bandwidth_hz <= 0 or power_w <= 0:
        return 0.0
    return bandwidth_hz * math.log2(1 + power_w * gain / (NOISE_W_HZ * bandwidth_hz))


def channel_gain(distance_m, antenna_gain_db):
    return 10 ** (antenna_gain_db / 10) * (LIGHT_M_S / (4 * math.pi * FREQUENCY_HZ * max(1, distance_m))) ** 2


def position(lat, lon, altitude=0):
    lat, lon = math.radians(lat), math.radians(lon)
    radius = EARTH_M + altitude
    return (radius * math.cos(lat) * math.cos(lon), radius * math.cos(lat) * math.sin(lon), radius * math.sin(lat))


def line_of_sight(a, b):
    d = tuple(y - x for x, y in zip(a, b))
    norm = sum(x*x for x in d)
    if norm == 0:
        return False
    u = max(0, min(1, -sum(x*y for x, y in zip(a, d)) / norm))
    return sum((x + u*y)**2 for x, y in zip(a, d)) >= (EARTH_M - .01)**2


def elevation(a, b):
    d = tuple(y-x for x, y in zip(a, b))
    return math.degrees(math.asin(max(-1, min(1, sum(x*y for x, y in zip(a, d)) / (math.dist(a, (0, 0, 0)) * math.dist(a, b))))))


@dataclass
class Node:
    id: str
    kind: str
    bandwidth_hz: float
    p_max_w: float
    battery_capacity_j: float | None
    battery_j: float | None
    lat: float = 0
    lon: float = 108
    altitude_m: float = 0
    phase: float = 0
    inclination: float = 0
    base_power_w: float = .2
    tx_circuit_w: float = .5
    rx_power_w: float = .4
    amplifier_efficiency: float = .4
    reserved_bandwidth_hz: float = 0.0
    predicted_reserved_bandwidth_hz: float = 0.0

    @property
    def available_bandwidth_hz(self):
        return max(0.0, self.bandwidth_hz-self.reserved_bandwidth_hz)

    @property
    def planning_bandwidth_hz(self):
        return max(0.0, self.bandwidth_hz-max(self.reserved_bandwidth_hz, self.predicted_reserved_bandwidth_hz))

    @property
    def battery_level(self):
        if self.battery_j is None:
            return 'unlimited'
        return 'weak' if self.battery_fraction < .2 else 'medium' if self.battery_fraction < .7 else 'strong'

    def coordinates(self, time_s):
        if self.kind in ('LEO', 'MEO'):
            angle = self.phase + math.sqrt(MU / (EARTH_M + self.altitude_m)**3) * time_s
            inc = math.radians(self.inclination)
            x, y, z = math.cos(angle), math.sin(angle)*math.cos(inc), math.sin(angle)*math.sin(inc)
            rotation = math.radians(self.lon) - OMEGA*time_s
            r = EARTH_M + self.altitude_m
            return (r*(x*math.cos(rotation)-y*math.sin(rotation)), r*(x*math.sin(rotation)+y*math.cos(rotation)), r*z)
        # ECEF: ground and GEO stay at fixed longitudes; UAVs follow small local circles.
        if self.kind == 'UAV':
            return position(self.lat + .002*math.sin(time_s/90+self.phase), self.lon+.002*math.cos(time_s/90+self.phase), self.altitude_m)
        return position(self.lat, self.lon, self.altitude_m)

    @property
    def battery_fraction(self):
        return 1.0 if self.battery_j is None else self.battery_j / self.battery_capacity_j


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    distance_m: float
    gain: float


@dataclass(frozen=True)
class Demand:
    source: str = 'G1'
    target: str = 'G3'
    data_mb: float = .1
    required_mbps: float = .2
    energy_weight: float = .5
    latency_weight: float = 0.0

    def __post_init__(self):
        if not isinstance(self.source, str) or not isinstance(self.target, str) or self.source == self.target:
            raise ValueError('Choose two different ground stations')
        finite(self.data_mb, 'data_mb', .001, 10)
        finite(self.required_mbps, 'required_mbps', .001, 50)
        finite(self.energy_weight, 'energy_weight', 0, 1)
        finite(self.latency_weight, 'latency_weight', 0, 1)

    @property
    def bits(self):
        return self.data_mb * 8e6


@dataclass(frozen=True)
class Budget:
    ants: int = 20
    aco_iterations: int = 50
    particles: int = 20
    pso_iterations: int = 50
    candidates: int = 3

    def __post_init__(self):
        for name, hi in [('ants', 30), ('aco_iterations', 100), ('particles', 40), ('pso_iterations', 100), ('candidates', 5)]:
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= hi:
                raise ValueError(f'{name} must be integer in [1, {hi}]')
