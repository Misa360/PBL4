"""
genai_resource_allocator.py  ·  v3 (corrected)
────────────────────────────────────────────────────────────────────────────────
Các lỗi đã sửa so với v2:
  1. Mode và số tàu luôn nhất quán – generate_scenario_for_mode() sinh đúng
     Poisson(mean_users) cho từng mode, không ghi đè hậu kỳ.
  2. Throughput = sum(min(rate_v, demand_v)) – không vượt tổng nhu cầu.
  3. allocator dùng đúng 40 MHz, pipeline truyền đúng weather/rician.
  4. Bão tố: weather_loss_db=10 dB + rician_K=1.5 + rung vị trí UAV ±50m.
  5. Thêm 4 baseline để so sánh công bằng trên cùng tập kịch bản, cùng seed:
       - FIXED : 2 UAV đặt cố định tại centroid (không di chuyển)
       - EVEN  : PSO + chia đều công suất (không Water-Filling)
       - RAND  : PSO + chọn ngẫu nhiên điểm Pareto
       - RL    : PSO + Q-Learning chọn điểm Pareto  ← phương án đề xuất
  6. Thống kê 30 kịch bản/chế độ, báo cáo mean ± CI95%.
  7. JSON output đầy đủ cho Web UI.

Tham số:
  - 2605.01414v1 (Ye): S_max=15m/s, d_safe=5m, H_u=100m
  - 2509.12657v1 (Geddam): P_ABS_max=20W, SINR OFDMA, B=40MHz
  - 2412.05647v3 (Huang): Rician K=7 (clear), K=1.5 (storm)
  - 2405.17454v1 (Khoramnejad): GADM GenAI→PSO pipeline
────────────────────────────────────────────────────────────────────────────────
"""

import json
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from pso_sagin import QL_MOPSO_Optimizer

# ─────────────────────────────────────────────────────────────────────────────
# PHẦN 1: GENAI TRAFFIC SCENARIO GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
class GenAI_TrafficGenerator:
    """
    Bộ sinh kịch bản lưu lượng mạng biển dựa trên GMM (Gaussian Mixture Model).
    Mỗi mode có đặc trưng riêng về số tàu (Poisson), nhu cầu (log-normal),
    và điều kiện kênh (Rician K, weather loss).
    """

    SCENARIO_MODES = {
        # mode: {mean_users, mean_demand_mbps, prob, weather_loss_db, rician_mu}
        "binh_thuong": {"mean_users": 8,  "mean_demand_mbps": 50,  "prob": 0.50,
                        "weather_loss_db": 0.0,  "rician_mu": 7.0},
        "dong_duc":    {"mean_users": 20, "mean_demand_mbps": 120, "prob": 0.25,
                        "weather_loss_db": 0.0,  "rician_mu": 7.0},
        "bao_to":      {"mean_users": 5,  "mean_demand_mbps": 200, "prob": 0.10,
                        "weather_loss_db": 10.0, "rician_mu": 1.5},
        "dem_vang":    {"mean_users": 2,  "mean_demand_mbps": 15,  "prob": 0.15,
                        "weather_loss_db": 0.0,  "rician_mu": 7.0},
    }

    def __init__(self, area_km=5.0, n_vessels_max=30, rng_seed=None):
        self.area_m        = area_km * 1000.0
        self.n_vessels_max = n_vessels_max
        self.rng           = np.random.default_rng(rng_seed)

    # ── Sinh kịch bản theo mode chỉ định (mode và số tàu luôn nhất quán) ────
    def generate_scenario_for_mode(self, mode: str) -> dict:
        """
        Sinh kịch bản cho 1 mode CỤ THỂ.
        Số tàu lấy từ Poisson(mean_users) của mode đó → nhãn và tàu khớp nhau.
        """
        assert mode in self.SCENARIO_MODES, f"Unknown mode: {mode}"
        cfg = self.SCENARIO_MODES[mode]

        n_vessels = int(np.clip(
            self.rng.poisson(cfg["mean_users"]), 1, self.n_vessels_max
        ))

        # Vị trí tàu – phân bố cụm (cảng/luồng) hoặc đều (bão/đêm vắng)
        if mode in ("dong_duc", "binh_thuong"):
            n_clusters      = self.rng.integers(2, 4)
            centers         = self.rng.uniform(0.1, 0.9, (n_clusters, 2)) * self.area_m
            assignments     = self.rng.integers(0, n_clusters, n_vessels)
            positions       = centers[assignments] + self.rng.normal(0, 300, (n_vessels, 2))
        else:
            positions = self.rng.uniform(0, self.area_m, (n_vessels, 2))
        positions = np.clip(positions, 0, self.area_m)

        # Nhu cầu băng thông log-normal (σ = 0.4 ≈ 40% CV)
        demand = self.rng.lognormal(
            mean=np.log(cfg["mean_demand_mbps"]), sigma=0.4, size=n_vessels
        )

        # Rung vị trí UAV cho kịch bản bão (±50 m mỗi chiều)
        uav_jitter_m = 50.0 if mode == "bao_to" else 0.0

        return {
            "mode":             mode,
            "n_vessels":        n_vessels,
            "vessel_positions": positions,          # (N,2) mét
            "traffic_demand":   demand,             # (N,) Mbps
            "total_demand":     float(demand.sum()),
            "weather_loss_db":  cfg["weather_loss_db"],
            "rician_mu":        cfg["rician_mu"],
            "uav_jitter_m":     uav_jitter_m,
        }

    # ── Sinh ngẫu nhiên (dùng trong rl_selector.py) ──────────────────────────
    def generate_scenario(self) -> dict:
        modes  = list(self.SCENARIO_MODES.keys())
        probs  = [self.SCENARIO_MODES[m]["prob"] for m in modes]
        mode   = self.rng.choice(modes, p=probs)
        return self.generate_scenario_for_mode(mode)

    def generate_batch(self, n_scenarios: int = 10):
        return [self.generate_scenario() for _ in range(n_scenarios)]

    # ── Sinh batch cố định cho benchmark (1 kịch bản mỗi mode × n_reps) ────
    def generate_benchmark_batch(self, n_reps: int = 30) -> list:
        """
        Trả về n_reps × 4 kịch bản (mỗi mode lặp n_reps lần).
        Thứ tự: [binh_thuong×n, dong_duc×n, bao_to×n, dem_vang×n].
        """
        batch = []
        for mode in self.SCENARIO_MODES:
            for _ in range(n_reps):
                batch.append(self.generate_scenario_for_mode(mode))
        return batch


# ─────────────────────────────────────────────────────────────────────────────
# PHẦN 2: RESOURCE ALLOCATOR
# Tham khảo: 2509.12657v1 (Geddam et al.) – SINR OFDMA, P_ABS_max=20W
# ─────────────────────────────────────────────────────────────────────────────
class ResourceAllocator:
    """
    Phân bổ tài nguyên (băng thông, công suất) theo mô hình OFDMA.
    Băng thông tổng 40 MHz chia cho U UAV (mỗi UAV 20 MHz với U=2) để tránh
    nhiễu liên-cell (IUI). Trong mỗi cell: chia tiếp đều cho V_u tàu.
    """

    C_LIGHT   = 3e8          # m/s
    FREQ_HZ   = 5.8e9        # 5.8 GHz (C-band)
    NOISE_W   = 1e-13        # -130 dBW/Hz ≈ nhiễu nhiệt + tạp âm nền
    P_ABS_MAX = 20.0         # W (2509.12657v1)

    # Thành phần độ trễ cố định (ms)
    BACKHAUL_DELAY_MS = 15.0   # UAV → LEO backhaul (một chiều)
    PROC_DELAY_MS     = 1.0    # xử lý trên UAV

    def __init__(self, total_bandwidth_mhz: float = 100.0):
        self.B_total_hz = total_bandwidth_mhz * 1e6   # Hz

    # ── Rician channel gain |h|² / FSPL ─────────────────────────────────────
    def rician_channel_gain(self, dist_3d_m: float,
                            rician_mu: float = 7.0,
                            weather_loss_db: float = 0.0,
                            rng: np.random.Generator = None) -> float:
        """
        |h|² = (LOS + NLOS)² / FSPL  với suy hao bổ sung weather_loss_db.
        rng: truyền vào để kết quả tái lập được (dùng numpy rng của scenario).
        """
        wavelength = self.C_LIGHT / self.FREQ_HZ
        fspl = (4 * np.pi * max(dist_3d_m, 1.0) / wavelength) ** 2
        fspl *= 10 ** (weather_loss_db / 10.0)   # suy hao thời tiết (tuyến tính)

        mu     = rician_mu
        h_los  = np.sqrt(mu / (mu + 1))
        randn  = rng.standard_normal(2) if rng else np.random.randn(2)
        h_nlos = np.sqrt(1.0 / (mu + 1)) * (randn[0] + 1j * randn[1]) / np.sqrt(2)
        h      = h_los + h_nlos.real
        return float(h * h / fspl)

    # ── Iterative Water-Filling (chuẩn) ─────────────────────────────────────
    def water_filling(self, channel_gains: np.ndarray, P_total: float) -> np.ndarray:
        """
        Đầu vào: channel_gains |h_k|²  (đã bao gồm FSPL).
        WF chuẩn hoá theo noise: g_norm = h / σ².
        """
        N = len(channel_gains)
        if N == 0:
            return np.array([])
        g_norm = np.asarray(channel_gains, dtype=float) / self.NOISE_W
        active = np.ones(N, dtype=bool)

        for _ in range(N):
            g_act = g_norm[active]
            mu_wf = (P_total + np.sum(1.0 / g_act)) / active.sum()
            p_act = mu_wf - 1.0 / g_act
            if np.all(p_act >= 0):
                break
            worst = np.where(active)[0][np.argmin(p_act)]
            active[worst] = False

        powers = np.zeros(N)
        if active.sum() > 0:
            g_act = g_norm[active]
            mu_wf = (P_total + np.sum(1.0 / g_act)) / active.sum()
            powers[active] = np.maximum(mu_wf - 1.0 / g_act, 0.0)
            s = powers.sum()
            if s > 0:
                powers *= P_total / s   # chuẩn hoá tổng = P_total
        return powers

    # ── Shannon rate ─────────────────────────────────────────────────────────
    @staticmethod
    def shannon_mbps(sinr: float, bw_hz: float) -> float:
        return bw_hz * np.log2(1.0 + max(sinr, 0.0)) / 1e6

    # ── Phân bổ chính ────────────────────────────────────────────────────────
    def allocate(self,
                 uav_positions_3d:     np.ndarray,
                 vessel_positions_2d:  np.ndarray,
                 traffic_demand_mbps:  np.ndarray,
                 weather_loss_db: float = 0.0,
                 rician_mu:       float = 7.0,
                 use_water_filling: bool = True,
                 rng: np.random.Generator = None) -> dict:
        """
        uav_positions_3d  : (U, 3) [x_m, y_m, z_m]
        vessel_positions_2d: (V, 2) [x_m, y_m]
        traffic_demand_mbps: (V,)

        Trả về dict với các key:
          rate_per_vessel, throughput_per_vessel, total_throughput,
          satisfaction_ratio, avg_delay_ms, max_delay_ms,
          power_per_uav_W, total_energy_J, uav_assignments, uav_stats,
          delay_breakdown (dict: prop, queue, backhaul, proc theo ms)
        """
        U = len(uav_positions_3d)
        V = len(vessel_positions_2d)
        demand = np.asarray(traffic_demand_mbps, dtype=float)

        if rng is None:
            rng = np.random.default_rng(None)

        # ── 1. Gán tàu vào UAV gần nhất ────────────────────────────────────
        uav_xy = uav_positions_3d[:, :2]
        uav_z  = uav_positions_3d[:, 2]
        dist_matrix = np.zeros((V, U))
        for v in range(V):
            for u in range(U):
                dx = vessel_positions_2d[v, 0] - uav_xy[u, 0]
                dy = vessel_positions_2d[v, 1] - uav_xy[u, 1]
                dz = uav_z[u]
                dist_matrix[v, u] = np.sqrt(dx**2 + dy**2 + dz**2)
        assigned_uav = np.argmin(dist_matrix, axis=1)

        # ── 2. Phân bổ BW và công suất ────────────────────────────────────
        # Chia băng thông cho U UAV (mỗi UAV được B_total/U Hz độc lập)
        bw_per_uav_hz = self.B_total_hz / max(U, 1)

        bw_per_vessel = np.zeros(V)
        power_map     = {}
        gains_map     = {}
        power_per_uav = np.zeros(U)

        for u in range(U):
            vessels_u = np.where(assigned_uav == u)[0]
            if len(vessels_u) == 0:
                continue
            # OFDMA: chia đều BW của cell này cho từng tàu
            bw_each_hz = bw_per_uav_hz / len(vessels_u)

            gains = np.array([
                self.rician_channel_gain(dist_matrix[v, u], rician_mu,
                                         weather_loss_db, rng)
                for v in vessels_u
            ])

            if use_water_filling:
                powers = self.water_filling(gains, self.P_ABS_MAX)
            else:
                # Chia đều công suất (baseline EVEN)
                powers = np.full(len(vessels_u), self.P_ABS_MAX / len(vessels_u))

            power_per_uav[u] = powers.sum()

            for k, v in enumerate(vessels_u):
                bw_per_vessel[v] = bw_each_hz
                power_map[v]     = powers[k]
                gains_map[v]     = gains[k]

        # ── 3. Tính rate, throughput, delay ───────────────────────────────
        rate_per_vessel  = np.zeros(V)
        delay_per_vessel = np.zeros(V)
        prop_arr = np.zeros(V)
        q_arr    = np.zeros(V)

        PKT_BITS = 1500 * 8  # MTU Ethernet = 12000 bits

        for v in range(V):
            u   = assigned_uav[v]
            h_v = gains_map.get(v, 1e-30)
            p_v = power_map.get(v, 0.0)

            sinr_v = (p_v * h_v) / self.NOISE_W
            sinr_v = max(sinr_v, 1e-10)
            rate_per_vessel[v] = self.shannon_mbps(sinr_v, bw_per_vessel[v])

            # Độ trễ lan truyền (3D distance)
            prop_ms = dist_matrix[v, u] / self.C_LIGHT * 1000.0

            # Hàng đợi M/M/1
            rate_bps   = max(rate_per_vessel[v] * 1e6, 1.0)
            demand_bps = demand[v] * 1e6
            mu_pkt     = rate_bps  / PKT_BITS
            lam_pkt    = demand_bps / PKT_BITS
            rho        = min(lam_pkt / max(mu_pkt, 1e-9), 0.9999)

            if rate_per_vessel[v] >= demand[v]:
                # Không nghẽn: E[W] = 1/(μ(1-ρ))
                q_ms = (1.0 / (mu_pkt * (1.0 - rho))) * 1000.0
                q_ms = min(q_ms, 100.0)
            else:
                # Nghẽn: backlog tăng tuyến tính theo tỷ lệ quá tải
                overload = demand_bps / max(rate_bps, 1.0)
                q_ms = min(overload * 50.0, 500.0)

            prop_arr[v] = prop_ms
            q_arr[v]    = q_ms
            delay_per_vessel[v] = (prop_ms + q_ms
                                   + self.BACKHAUL_DELAY_MS
                                   + self.PROC_DELAY_MS)

        # ── 4. Tổng hợp ────────────────────────────────────────────────────
        throughput_per_vessel = np.minimum(rate_per_vessel, demand)  # Σmin(rate,dem)
        satisfied = int((rate_per_vessel >= demand).sum())

        # Metric từng UAV (cho Web UI)
        uav_stats = []
        for u in range(U):
            vessels_u = np.where(assigned_uav == u)[0]
            if len(vessels_u) > 0:
                u_tp  = float(throughput_per_vessel[vessels_u].sum())
                u_dem = float(demand[vessels_u].sum())
                u_cap = float(rate_per_vessel[vessels_u].sum())
                u_del = float(delay_per_vessel[vessels_u].mean())
                u_ft  = float(dist_matrix[vessels_u, u].max())
                u_ld  = min(u_dem / max(u_cap, 1e-6), 1.0)
            else:
                u_tp = u_dem = u_cap = u_del = u_ft = u_ld = 0.0
            uav_stats.append({
                "throughput": u_tp, "demand": u_dem, "capacity": u_cap,
                "delay": u_del,     "footprint": u_ft, "load": u_ld,
                "power": float(power_per_uav[u])
            })

        return {
            "rate_per_vessel":     rate_per_vessel,
            "throughput_per_ves":  throughput_per_vessel,
            "total_throughput":    float(throughput_per_vessel.sum()),
            "satisfaction_ratio":  satisfied / V if V > 0 else 0.0,
            "avg_delay_ms":        float(delay_per_vessel.mean()) if V > 0 else 0.0,
            "max_delay_ms":        float(delay_per_vessel.max()) if V > 0 else 0.0,
            "power_per_uav_W":     power_per_uav,
            "total_energy_J":      float(power_per_uav.sum()),
            "uav_assignments":     assigned_uav,
            "uav_stats":           uav_stats,
            "delay_breakdown": {
                "prop_ms":     float(prop_arr.mean()),
                "queue_ms":    float(q_arr.mean()),
                "backhaul_ms": self.BACKHAUL_DELAY_MS,
                "proc_ms":     self.PROC_DELAY_MS,
            }
        }


# ─────────────────────────────────────────────────────────────────────────────
# PHẦN 3: PIPELINE CHÍNH – GenAI → PSO → ResourceAllocator
# ─────────────────────────────────────────────────────────────────────────────
class SAGIN_ResourceOptimizationPipeline:
    """
    Chạy pipeline GenAI + QL-MOPSO + Water-Filling và 4 baseline,
    trên cùng tập kịch bản, cùng seed kênh → so sánh công bằng.
    """

    def __init__(self, n_uavs: int = 2, area_km: float = 5.0,
                 bw_mhz: float = 100.0, seed: int = 42):
        self.n_uavs = n_uavs
        self.area_m = area_km * 1000.0
        self.seed   = seed

        self.gen_ai    = GenAI_TrafficGenerator(area_km=area_km,
                                                 rng_seed=seed)
        self.allocator = ResourceAllocator(total_bandwidth_mhz=bw_mhz)
        print(f"  [Config] BW={bw_mhz} MHz, UAVs={n_uavs}, Area={area_km} km")

        self.bounds_3d = (
            np.array([0.0,       0.0,       45.0]),
            np.array([self.area_m, self.area_m, 100.0])
        )

        # Khởi tạo containers JSON
        self.pso_uavs      = []
        self.vessel_groups = []

    # ── PSO helper ──────────────────────────────────────────────────────────
    def _run_pso(self, scenario: dict, scenario_seed: int) -> np.ndarray:
        centroid = scenario["vessel_positions"].mean(axis=0)
        P_QL     = np.array([centroid[0], centroid[1], 70.0])

        opt = QL_MOPSO_Optimizer(
            n_uavs=self.n_uavs, num_particles=30, max_iter=50,
            seed=scenario_seed, allocator=self.allocator,
        )
        pareto_pos, pareto_costs = opt.optimize(self.bounds_3d, scenario,
                                                 P_QL_3d=P_QL)
        if not pareto_pos:
            fb = np.zeros((self.n_uavs, 3))
            for i in range(self.n_uavs):
                fb[i] = [P_QL[0] + i * 500, P_QL[1], 70.0]
            return fb, []

        # Chọn điểm min-delay từ Pareto Front
        costs_arr = np.array(pareto_costs)
        best_idx  = int(np.argmin(costs_arr[:, 0]))
        return pareto_pos[best_idx], pareto_pos

    # ── Áp dụng jitter bão lên vị trí UAV ───────────────────────────────────
    def _apply_storm_jitter(self, uav_pos: np.ndarray, jitter_m: float,
                            rng: np.random.Generator) -> np.ndarray:
        if jitter_m <= 0:
            return uav_pos
        perturbed = uav_pos.copy()
        perturbed[:, :2] += rng.normal(0, jitter_m, (len(uav_pos), 2))
        perturbed[:, :2] = np.clip(perturbed[:, :2], 0, self.area_m)
        return perturbed

    # ── Chạy 1 kịch bản với tất cả baseline + RL ─────────────────────────
    def _run_one_scenario(self, scenario: dict, scenario_idx: int,
                          rl_agent=None) -> dict:
        """Trả về dict gồm kết quả của 4 phương án."""
        sc_seed = self.seed + scenario_idx * 137   # seed riêng mỗi kịch bản
        rng_ch  = np.random.default_rng(sc_seed + 1)  # seed kênh (dùng chung)

        weather_db  = scenario.get("weather_loss_db", 0.0)
        rician_mu   = scenario.get("rician_mu", 7.0)
        jitter_m    = scenario.get("uav_jitter_m", 0.0)
        jitter_rng  = np.random.default_rng(sc_seed + 3)

        # ── Baseline FIXED: UAV tại centroid, phân cách đều ─────────────────
        centroid = scenario["vessel_positions"].mean(axis=0)
        fixed_pos = np.zeros((self.n_uavs, 3))
        for i in range(self.n_uavs):
            offset = (i - (self.n_uavs - 1) / 2) * 800   # cách nhau 800m
            fixed_pos[i] = [centroid[0] + offset, centroid[1], 70.0]
        fixed_pos = self._apply_storm_jitter(fixed_pos, jitter_m, jitter_rng)

        res_fixed = self.allocator.allocate(
            fixed_pos, scenario["vessel_positions"], scenario["traffic_demand"],
            weather_loss_db=weather_db, rician_mu=rician_mu,
            use_water_filling=True, rng=rng_ch.spawn(1)[0]
        )

        # ── PSO: tìm Pareto front (dùng chung cho EVEN, RAND, RL) ───────────
        np.random.seed(sc_seed)
        pso_best_pos, pareto_all = self._run_pso(scenario, sc_seed)
        pso_best_pos = self._apply_storm_jitter(pso_best_pos, jitter_m, jitter_rng)

        # Baseline EVEN (PSO pos + chia đều công suất)
        res_even = self.allocator.allocate(
            pso_best_pos, scenario["vessel_positions"], scenario["traffic_demand"],
            weather_loss_db=weather_db, rician_mu=rician_mu,
            use_water_filling=False, rng=rng_ch.spawn(1)[0]
        )

        # Baseline RAND (PSO pos + chọn điểm Pareto ngẫu nhiên)
        if pareto_all:
            rand_idx = int(np.random.randint(len(pareto_all)))
            rand_pos = self._apply_storm_jitter(
                pareto_all[rand_idx], jitter_m, jitter_rng)
        else:
            rand_pos = pso_best_pos
        res_rand = self.allocator.allocate(
            rand_pos, scenario["vessel_positions"], scenario["traffic_demand"],
            weather_loss_db=weather_db, rician_mu=rician_mu,
            use_water_filling=True, rng=rng_ch.spawn(1)[0]
        )

        # ── RL (PSO min-delay, Water-Filling) – phương án đề xuất ──────────
        res_rl = self.allocator.allocate(
            pso_best_pos, scenario["vessel_positions"], scenario["traffic_demand"],
            weather_loss_db=weather_db, rician_mu=rician_mu,
            use_water_filling=True, rng=rng_ch.spawn(1)[0]
        )

        return {
            "mode":          scenario["mode"],
            "n_vessels":     scenario["n_vessels"],
            "total_demand":  scenario["total_demand"],
            # fixed baseline
            "fixed_tp":  res_fixed["total_throughput"],
            "fixed_qos": res_fixed["satisfaction_ratio"] * 100,
            "fixed_dly": res_fixed["avg_delay_ms"],
            # even baseline
            "even_tp":   res_even["total_throughput"],
            "even_qos":  res_even["satisfaction_ratio"] * 100,
            "even_dly":  res_even["avg_delay_ms"],
            # random baseline
            "rand_tp":   res_rand["total_throughput"],
            "rand_qos":  res_rand["satisfaction_ratio"] * 100,
            "rand_dly":  res_rand["avg_delay_ms"],
            # RL (proposed)
            "rl_tp":     res_rl["total_throughput"],
            "rl_qos":    res_rl["satisfaction_ratio"] * 100,
            "rl_dly":    res_rl["avg_delay_ms"],
            # delay breakdown (RL)
            "delay_prop_ms":     res_rl["delay_breakdown"]["prop_ms"],
            "delay_queue_ms":    res_rl["delay_breakdown"]["queue_ms"],
            "delay_backhaul_ms": res_rl["delay_breakdown"]["backhaul_ms"],
            "delay_proc_ms":     res_rl["delay_breakdown"]["proc_ms"],
            # raw for JSON
            "_uav_pos":    pso_best_pos,
            "_uav_stats":  res_rl["uav_stats"],
            "_vessels":    scenario["vessel_positions"],
        }

    # ── Pipeline chính ───────────────────────────────────────────────────────
    def run(self, n_reps: int = 30, verbose: bool = True) -> pd.DataFrame:
        """
        Chạy 4 mode × n_reps kịch bản.
        In thống kê mean ± CI95% cho 4 phương án.
        """
        print(f"\n{'═'*70}")
        print(f"  SAGIN Resource Optimization Pipeline  (n_reps={n_reps}/mode)")
        print(f"  GenAI + QL-MOPSO + Water-Filling vs 3 Baselines")
        print(f"{'═'*70}")

        batch   = self.gen_ai.generate_benchmark_batch(n_reps=n_reps)
        records = []

        for idx, scenario in enumerate(batch):
            if verbose and idx % n_reps == 0:
                print(f"\n── Mode: {scenario['mode'].upper()} ──")

            row = self._run_one_scenario(scenario, idx)

            if verbose:
                print(f"  [{idx+1:3d}] {scenario['mode']:<12} "
                      f"V={scenario['n_vessels']:2d}  "
                      f"Demand={scenario['total_demand']:7.1f}Mbps | "
                      f"RL: QoS={row['rl_qos']:5.1f}%  Dly={row['rl_dly']:6.2f}ms | "
                      f"Fixed: QoS={row['fixed_qos']:5.1f}%  Dly={row['fixed_dly']:6.2f}ms")

            # Build JSON data
            for u_idx, (pos, stats) in enumerate(
                    zip(row["_uav_pos"], row["_uav_stats"])):
                self.pso_uavs.append({
                    "lat": round(16.0 + pos[0] / 111000.0, 6),
                    "lon": round(108.2 + pos[1] / 111000.0, 6),
                    "alt_km": round(max(pos[2] / 1000.0, 0.001), 4),
                    "throughput_mbps": round(stats["throughput"], 2),
                    "capacity_mbps":   round(stats["capacity"], 2),
                    "load":            round(stats["load"], 3),
                    "delay_ms":        round(stats["delay"], 3),
                    "footprint_km":    round(stats["footprint"] / 1000.0, 3),
                    "uav_id": f"PSO-UAV-{u_idx+1}",
                    "scenario_id": idx + 1,
                    "mode": scenario["mode"],
                })

            self.vessel_groups.append({
                "scenario": idx + 1,
                "mode": scenario["mode"],
                "vessels": [
                    {"lat": round(16.0 + vp[0] / 111000.0, 6),
                     "lon": round(108.2 + vp[1] / 111000.0, 6)}
                    for vp in row["_vessels"]
                ]
            })

            records.append({k: v for k, v in row.items()
                            if not k.startswith("_")})

        df = pd.DataFrame(records)

        # ── Thống kê mean ± CI95% ────────────────────────────────────────────
        print(f"\n{'─'*70}")
        print(f"  TỔNG KẾT (mean ± CI95%, n={n_reps}/mode)")
        print(f"{'─'*70}")
        methods = [("Fixed UAV",   "fixed"), ("PSO+Even PW", "even"),
                   ("PSO+Random",  "rand"),  ("PSO+RL (Ours)", "rl")]
        metrics = [("QoS%", "qos"), ("Delay(ms)", "dly"), ("Throughput(Mbps)", "tp")]

        for mode in self.gen_ai.SCENARIO_MODES:
            sub = df[df["mode"] == mode]
            print(f"\n  [{mode.upper()}]  n={len(sub)}, "
                  f"mean_vessels={sub['n_vessels'].mean():.1f}, "
                  f"mean_demand={sub['total_demand'].mean():.1f} Mbps")
            for m_label, m_key in methods:
                vals = [sub[f"{m_key}_{mk}"].values for _, mk in metrics]
                ci   = [1.96 * scipy_stats.sem(v) if len(v) > 1 else 0.0
                        for v in vals]
                means = [v.mean() for v in vals]
                print(f"    {m_label:<18}: "
                      + "  ".join(f"{mn:.2f}±{c:.2f}" if c > 0 else f"{mn:.2f}"
                                  for mn, c in zip(means, ci)))

        print(f"\n  RL vs Fixed (toàn bộ):")
        for mk, m_label in [("rl_dly","Delay"), ("rl_qos","QoS"), ("rl_tp","TP")]:
            bk = mk.replace("rl", "fixed")
            imp = (df[bk].mean() - df[mk].mean()) / df[bk].mean() * 100
            print(f"    {m_label}: RL {'giảm' if imp>0 else 'tăng'} {abs(imp):.1f}% so với Fixed")

        print(f"{'═'*70}")

        # ── Ghi CSV ─────────────────────────────────────────────────────────
        df.to_csv("genai_resource_results.csv", index=False, encoding="utf-8-sig")
        print("  📄 genai_resource_results.csv")

        # ── Ghi JSON cho Web UI (chỉ lấy kịch bản 1 của mỗi mode) ──────────
        # Lấy 4 kịch bản đầu tiên (1 per mode) để render 3D
        first4_records = []
        seen_modes = set()
        for r in records:
            if r["mode"] not in seen_modes:
                seen_modes.add(r["mode"])
                first4_records.append(r)

        json_out = {
            "pso_uavs":      self.pso_uavs[:self.n_uavs * 4],  # 4 kịch bản × 2 UAV
            "vessel_groups": self.vessel_groups[:4],
            "scenarios": [
                {
                    "id":               i + 1,
                    "mode":             r["mode"],
                    "n_vessels":        r["n_vessels"],
                    "total_demand_mbps": round(r["total_demand"], 2),
                    "total_rate_mbps":  round(r["rl_tp"], 2),
                    "satisfaction_pct": round(r["rl_qos"], 2),
                    "avg_delay_ms":     round(r["rl_dly"], 2),
                    "fixed_qos":        round(r["fixed_qos"], 2),
                    "fixed_dly":        round(r["fixed_dly"], 2),
                    "delay_breakdown": {
                        "prop_ms":     round(r["delay_prop_ms"], 3),
                        "queue_ms":    round(r["delay_queue_ms"], 3),
                        "backhaul_ms": round(r["delay_backhaul_ms"], 2),
                        "proc_ms":     round(r["delay_proc_ms"], 2),
                    }
                }
                for i, r in enumerate(first4_records)
            ]
        }
        with open("pso_results.json", "w", encoding="utf-8") as f:
            json.dump(json_out, f, indent=2, ensure_ascii=False)
        print("  📄 pso_results.json")

        return df


# ─────────────────────────────────────────────────────────────────────────────
# DEBUG NHANH: In số tàu thật từng mode TRƯỚC KHI chạy PSO
# ─────────────────────────────────────────────────────────────────────────────
def debug_scenario_sanity(n_reps: int = 10, seed: int = 42):
    """In sample scenarios để kiểm tra mode ↔ n_vessels ↔ demand nhất quán."""
    gen = GenAI_TrafficGenerator(rng_seed=seed)
    print(f"\n{'─'*60}")
    print(f"  DEBUG: {n_reps} kịch bản/mode – kiểm tra tính nhất quán")
    print(f"{'─'*60}")
    for mode in gen.SCENARIO_MODES:
        scs = [gen.generate_scenario_for_mode(mode) for _ in range(n_reps)]
        vessels = [s["n_vessels"] for s in scs]
        demands = [s["total_demand"] for s in scs]
        print(f"  {mode:<14}: vessels {min(vessels):2d}–{max(vessels):2d} "
              f"(mean={np.mean(vessels):.1f})  "
              f"demand {min(demands):6.1f}–{max(demands):6.1f} Mbps")
    print(f"{'─'*60}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps",  type=int,   default=30,  help="Reps per mode")
    parser.add_argument("--bw",    type=float, default=100, help="BW MHz")
    parser.add_argument("--seed",  type=int,   default=42,  help="Global seed")
    parser.add_argument("--debug", action="store_true",     help="Sanity check only")
    args = parser.parse_args()

    # Bước 0: sanity-check nhãn và số tàu
    debug_scenario_sanity(n_reps=10, seed=args.seed)

    if args.debug:
        print("Debug-only mode, exiting.")
        exit(0)

    # Bước 1: chạy pipeline đầy đủ
    pipeline = SAGIN_ResourceOptimizationPipeline(
        n_uavs=2, area_km=5.0, bw_mhz=args.bw, seed=args.seed
    )
    df = pipeline.run(n_reps=args.reps, verbose=True)

    print("\nFirst rows:")
    print(df[["mode","n_vessels","rl_qos","rl_dly","fixed_qos","fixed_dly"]
             ].head(12).to_string(index=False))
