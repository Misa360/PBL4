"""Small deterministic spherical-Earth scenario, using only Python's standard library."""

import math

from .network_models import Link, NetworkNode

R_EARTH = 6371000.0
MU = 3.986004418e14
ROTATION = 7.2921159e-5


def position(lat, lon, altitude=0):
    lat, lon = math.radians(lat), math.radians(lon)
    r = R_EARTH + altitude
    return (r * math.cos(lat) * math.cos(lon),
            r * math.cos(lat) * math.sin(lon), r * math.sin(lat))


def elevation(observer, target):
    delta = tuple(b - a for a, b in zip(observer, target))
    norm = math.dist(observer, (0, 0, 0)) * math.dist(delta, (0, 0, 0))
    return math.degrees(math.asin(max(-1, min(1, sum(a*b for a, b in zip(observer, delta)) / norm))))


class RegionalScenario:
    """Two ground clusters ~27 km apart; local UAV relays need a satellite bridge.

    Satellite 1 starts overhead in a circular equatorial orbit. The scenario is
    synthetic and its resource settings are pedagogical, not measured hardware.
    """

    def __init__(self, battery_j=1000.0, bandwidth_hz=5e6, buffer_packets=64):
        self.nodes = [NetworkNode(f'G{i+1}', 'ground', bandwidth_hz,
                                  None, buffer_packets) for i in range(4)]
        self.nodes += [NetworkNode(f'U{i+1}', 'air', bandwidth_hz,
                                   battery_j, buffer_packets) for i in range(4)]
        self.nodes += [NetworkNode(f'S{i+1}', 'space', bandwidth_hz,
                                   battery_j * 3, buffer_packets) for i in range(2)]
        self.coordinates = {}
        self.flows = [('G1', 'G3'), ('G2', 'G4')]

    def links_at(self, t):
        coords = {}
        for i, (lat, lon) in enumerate(((0, 108), (.012, 108), (0, 108.24), (.012, 108.24))):
            coords[f'G{i+1}'] = position(lat, lon + math.degrees(ROTATION*t))
        for i in range(4):
            lon = 108 + (i // 2) * .24 + .006 * math.cos(t / 90 + i * math.pi)
            lat = .006 + .006 * math.sin(t / 90 + i * math.pi)
            coords[f'U{i+1}'] = position(lat, lon + math.degrees(ROTATION*t), 2000)
        angular_rate = math.sqrt(MU / (R_EARTH + 550000)**3)
        for i in range(2):
            coords[f'S{i+1}'] = position(0, 108 + i*12 + math.degrees(angular_rate*t), 550000)
        self.coordinates = coords
        links = []
        for i, a in enumerate(self.nodes):
            for b in self.nodes[i+1:]:
                layers = {a.layer, b.layer}
                distance = math.dist(coords[a.node_id], coords[b.node_id])
                if layers == {'ground', 'air'}:
                    allowed = distance <= 6000
                    efficiency = 2.0
                elif layers == {'air', 'space'}:
                    uav, sat = (a, b) if a.layer == 'air' else (b, a)
                    allowed = elevation(coords[uav.node_id], coords[sat.node_id]) >= 10
                    efficiency = 1.0
                else:
                    allowed = False
                    efficiency = 1.0
                if allowed:
                    links += [Link(a.node_id, b.node_id, distance, efficiency),
                              Link(b.node_id, a.node_id, distance, efficiency)]
        return links
