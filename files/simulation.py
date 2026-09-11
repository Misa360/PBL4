"""
simulation.py
Vong lap mo phong chinh: tai moi buoc thoi gian, cap nhat vi tri, dung lai
topology, tinh duong di ngan nhat (Dijkstra dong) tu 1 node mat dat toi lop
ve tinh, va ghi lai cac metric (connectivity, do tre, so ve tinh nhin thay).
"""

import numpy as np
import pandas as pd
import networkx as nx

from nodes import build_ground_grid, UAVNode, SatelliteNode
from topology import build_topology


class SAGINSimulation:
    def __init__(self, center_lat, center_lon,
                 n_ground_rows=2, n_ground_cols=2, ground_spacing_m=2000.0,
                 n_uav=4, uav_radius_m=3000.0, uav_altitude_m=2000.0,
                 n_sat=3, sat_altitude_km=550.0, sat_inclination_deg=53.0,
                 duration_s=1800.0, dt_s=30.0):
        self.duration_s = duration_s
        self.dt_s = dt_s

        # --- Lop Ground: luoi nho quanh toa do trung tam ---
        self.ground_nodes = build_ground_grid(
            n_ground_rows, n_ground_cols, center_lat, center_lon, ground_spacing_m
        )

        # --- Lop Air: UAV tuan tra vong tron, moi UAV lech pha nhau ---
        self.uav_nodes = []
        for i in range(n_uav):
            phase0 = 2 * np.pi * i / n_uav
            self.uav_nodes.append(UAVNode(
                f"UAV_{i}", center_lat, center_lon,
                radius_m=uav_radius_m, altitude_m=uav_altitude_m,
                angular_speed=2 * np.pi / 900.0, phase0=phase0
            ))

        # --- Lop Space: ve tinh LEO, RAAN va vi tri ban dau lech nhau ---
        self.sat_nodes = []
        for i in range(n_sat):
            raan = 360.0 * i / n_sat
            mean_anomaly0 = 360.0 * i / n_sat
            self.sat_nodes.append(SatelliteNode(
                f"SAT_{i}", sat_altitude_km, sat_inclination_deg, raan, mean_anomaly0
            ))

        self.records = []  # log theo tung timestep

    def run(self, source_ground_id=None, verbose=False):
        if source_ground_id is None:
            source_ground_id = self.ground_nodes[0].node_id

        n_steps = int(self.duration_s // self.dt_s)
        sat_ids = {s.node_id for s in self.sat_nodes}

        for step in range(n_steps):
            t = step * self.dt_s
            graph, positions, link_info = build_topology(
                t, self.ground_nodes, self.uav_nodes, self.sat_nodes
            )

            # So ve tinh dang duoc it nhat 1 UAV nhin thay tai thoi diem nay
            visible_sats = {v for (u, v) in graph.edges() if v in sat_ids or u in sat_ids}
            visible_sats = {n for n in visible_sats if n in sat_ids}
            n_visible_sats = len(visible_sats)

            # Duong di ngan nhat tu node mat dat nguon toi BAT KY ve tinh nao
            connected = False
            delay_s = np.nan
            hops = np.nan
            try:
                lengths = nx.single_source_dijkstra_path_length(graph, source_ground_id, weight="weight")
                reachable_sats = [sid for sid in sat_ids if sid in lengths]
                if reachable_sats:
                    best_sat = min(reachable_sats, key=lambda sid: lengths[sid])
                    delay_s = lengths[best_sat]
                    path = nx.dijkstra_path(graph, source_ground_id, best_sat, weight="weight")
                    hops = len(path) - 1
                    connected = True
            except nx.NodeNotFound:
                pass

            self.records.append({
                "t_s": t,
                "n_visible_sats": n_visible_sats,
                "n_edges": graph.number_of_edges(),
                "connected_to_space": connected,
                "end_to_end_delay_s": delay_s,
                "hops": hops,
            })

            if verbose:
                print(f"t={t:6.0f}s | ve_tinh_nhin_thay={n_visible_sats} | "
                      f"canh={graph.number_of_edges():3d} | "
                      f"ket_noi_toi_space={connected} | delay={delay_s}")

        return pd.DataFrame(self.records)

    def summary(self, df):
        connected_frac = df["connected_to_space"].mean()
        avg_delay_ms = df.loc[df["connected_to_space"], "end_to_end_delay_s"].mean() * 1000
        avg_visible = df["n_visible_sats"].mean()
        return {
            "ty_le_thoi_gian_ket_noi_(%)": round(connected_frac * 100, 1),
            "do_tre_trung_binh_khi_ket_noi_(ms)": round(avg_delay_ms, 2) if not np.isnan(avg_delay_ms) else None,
            "so_ve_tinh_nhin_thay_trung_binh": round(avg_visible, 2),
            "tong_so_buoc_thoi_gian": len(df),
        }
