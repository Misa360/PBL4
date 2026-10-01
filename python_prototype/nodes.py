"""
nodes.py
Cac lop node cho 3 tang: Ground, Air (UAV), Space (Satellite).
Moi node co ham vi_tri(t) tra ve toa do ECI (m) tai thoi diem t (giay).
"""

import numpy as np
from orbital import (
    SatellitePropagator, latlon_to_ecef, ecef_to_eci, local_offset_to_latlon
)


class GroundNode:
    """Node mat dat: co dinh theo (vi do, kinh do). Vi tri trong khong gian (ECI)
    van thay doi theo thoi gian vi trai dat tu quay."""

    def __init__(self, node_id, lat_deg, lon_deg, alt_m=0.0):
        self.node_id = node_id
        self.lat = lat_deg
        self.lon = lon_deg
        self.alt = alt_m
        self._ecef = latlon_to_ecef(lat_deg, lon_deg, alt_m)

    def position_eci(self, t):
        return ecef_to_eci(self._ecef, t)


class UAVNode:
    """UAV bay tuan tra theo quy dao tron nho phia tren mot vung mat dat.
    - center_lat/lon: tam vung tuan tra
    - radius_m: ban kinh vong bay
    - altitude_m: do cao bay (thuong 1-5 km)
    - angular_speed: toc do goc bay quanh tam (rad/s)
    """

    def __init__(self, node_id, center_lat, center_lon, radius_m=3000.0,
                 altitude_m=2000.0, angular_speed=2 * np.pi / 900.0, phase0=0.0):
        self.node_id = node_id
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.radius_m = radius_m
        self.altitude_m = altitude_m
        self.omega = angular_speed  # 1 vong / 900s (15 phut) mac dinh
        self.phase0 = phase0

    def current_latlon(self, t):
        angle = self.phase0 + self.omega * t
        dx = self.radius_m * np.cos(angle)
        dy = self.radius_m * np.sin(angle)
        lat, lon = local_offset_to_latlon(self.center_lat, self.center_lon, dx, dy)
        return lat, lon

    def position_eci(self, t):
        lat, lon = self.current_latlon(t)
        ecef = latlon_to_ecef(lat, lon, self.altitude_m)
        return ecef_to_eci(ecef, t)


class SatelliteNode:
    """Wrapper mong quanh SatellitePropagator de dong bo interface voi cac node khac."""

    def __init__(self, node_id, altitude_km, inclination_deg, raan_deg, mean_anomaly0_deg):
        self.node_id = node_id
        self.prop = SatellitePropagator(
            node_id, altitude_km, inclination_deg, raan_deg, mean_anomaly0_deg
        )

    def position_eci(self, t):
        return self.prop.position_eci(t)


def build_ground_grid(rows, cols, center_lat, center_lon, spacing_m=2000.0):
    """Tao luoi node mat dat rows x cols, cach deu spacing_m (met), quanh tam cho truoc."""
    nodes = []
    for i in range(rows):
        for j in range(cols):
            dx = (j - (cols - 1) / 2.0) * spacing_m
            dy = (i - (rows - 1) / 2.0) * spacing_m
            lat, lon = local_offset_to_latlon(center_lat, center_lon, dx, dy)
            nodes.append(GroundNode(f"G_{i}_{j}", lat, lon, alt_m=0.0))
    return nodes
