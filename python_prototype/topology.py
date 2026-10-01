"""
topology.py
Tai moi timestep: tinh vi tri tat ca node, kiem tra kha nang lien ket
(visibility + tam phu song), dung graph NetworkX voi trong so canh = do tre.
"""

import numpy as np
import networkx as nx

from orbital import elevation_angle_deg
from channel import ground_to_uav_link, uav_to_satellite_link


def build_topology(t, ground_nodes, uav_nodes, sat_nodes):
    """Dung graph tai thoi diem t (giay). Tra ve (graph, thong_tin_bo_sung)."""
    graph = nx.Graph()

    # Vi tri tat ca node tai thoi diem t (ECI, met)
    positions = {}
    for n in ground_nodes:
        positions[n.node_id] = n.position_eci(t)
        graph.add_node(n.node_id, layer="ground")
    for n in uav_nodes:
        positions[n.node_id] = n.position_eci(t)
        graph.add_node(n.node_id, layer="air")
    for n in sat_nodes:
        positions[n.node_id] = n.position_eci(t)
        graph.add_node(n.node_id, layer="space")

    link_info = []  # de ghi log / debug

    # --- Lien ket Ground <-> UAV (bang C) ---
    for g in ground_nodes:
        for u in uav_nodes:
            dist = np.linalg.norm(positions[g.node_id] - positions[u.node_id])
            rate, ok, delay = ground_to_uav_link(dist)
            if ok:
                graph.add_edge(g.node_id, u.node_id, weight=delay, rate=rate, kind="ground-uav")
            link_info.append(("ground-uav", g.node_id, u.node_id, dist, ok))

    # --- Lien ket UAV <-> Satellite (bang Ka), can goc nang ---
    for u in uav_nodes:
        for s in sat_nodes:
            dist = np.linalg.norm(positions[u.node_id] - positions[s.node_id])
            elev = elevation_angle_deg(positions[u.node_id], positions[s.node_id])
            rate, ok, delay = uav_to_satellite_link(dist, elev)
            if ok:
                graph.add_edge(u.node_id, s.node_id, weight=delay, rate=rate,
                                kind="uav-sat", elevation=elev)
            link_info.append(("uav-sat", u.node_id, s.node_id, dist, ok, elev))

    return graph, positions, link_info
