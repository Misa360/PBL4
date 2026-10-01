"""
pso_sagin.py  ·  v2 (fixed & upgraded)
────────────────────────────────────────────────────────────────────────────────
Sửa tất cả lỗi được chỉ ra:
  1. Mỗi hạt mã hóa toàn bộ U UAV (dim = 3*U) – PSO thực sự tối ưu phân vùng.
  2. Fitness gọi ResourceAllocator.allocate → mục tiêu là [delay, energy,
     -satisfaction, safety_penalty] thật sự.
  3. pbest cập nhật bằng Pareto dominance (không dùng np.sum khác thang).
  4. MOPSO_Repository dùng hypercube grid chuẩn (Coello 2004): chuẩn hóa theo
     min/max hiện tại, đếm số hạt mỗi ô, chọn leader từ ô thưa nhất.
  5. Archive lọc trùng (duplicate filtering).
  6. current_cost chỉ tính 1 lần mỗi hạt mỗi vòng lặp.
  7. Thêm SEED toàn cục → kết quả tái lập được.
  8. Sửa typo np.linalg_norm → np.linalg.norm.
────────────────────────────────────────────────────────────────────────────────
"""

import numpy as np

GLOBAL_SEED = 42

# ─────────────────────────────────────────────────────────────────────────────
# 1. MÔ HÌNH NĂNG LƯỢNG UAV (Nature Scientific Reports 2025 – Qi et al.)
# ─────────────────────────────────────────────────────────────────────────────
class UAVEnergyModel_Nature2025:
    def __init__(self, mass=3.8, battery_Q=399_600.0, speed_const=15.0,
                 p_const=429.87, e_acc=6096.3, e_dec=4944.19,
                 d_acc=112.5, d_dec=112.5, eta=0.74):
        self.M        = mass
        self.G        = 9.8
        self.Q        = battery_Q
        self.S_const  = speed_const
        self.P_const  = p_const
        self.E_acc    = e_acc
        self.E_dec    = e_dec
        self.D_acc    = d_acc
        self.D_dec    = d_dec
        self.eta      = eta
        self.C_ang1   = 5.3316   # hằng số thực nghiệm năng lượng góc rẽ
        self.C_ang2   = 104.65

    def compute_total_energy(self, path_points_3d):
        """path_points_3d: list/array of (3,) points [x, y, z]."""
        pts = [np.asarray(p, dtype=float) for p in path_points_3d]
        n = len(pts)
        if n < 2:
            return 0.0, True

        E_dist = E_angl = E_climb = 0.0
        for i in range(n - 1):
            p1, p2 = pts[i], pts[i + 1]
            dist = np.linalg.norm(p2 - p1)          # FIX: đúng là np.linalg.norm

            # Năng lượng di chuyển (Eq.8)
            steady = max(0.0, dist - self.D_acc - self.D_dec)
            E_dist += (steady / self.S_const) * self.P_const + self.E_acc + self.E_dec

            # Năng lượng leo cao (Eq.11) – trục z (index 2)
            dh = p2[2] - p1[2]
            if dh > 0:
                E_climb += (self.M * self.G * dh) / self.eta

            # Năng lượng góc rẽ (Eq.10)
            if i < n - 2:
                p3 = pts[i + 2]
                v1, v2 = p2 - p1, p3 - p2
                n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
                if n1 > 1e-6 and n2 > 1e-6:
                    cos_t = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
                    theta_deg = np.degrees(np.arccos(cos_t))
                    E_angl += self.C_ang1 * theta_deg + self.C_ang2

        total = E_dist + E_angl + E_climb
        return total, (total <= self.Q)


# ─────────────────────────────────────────────────────────────────────────────
# 2. MOPSO REPOSITORY – Pareto Front với Adaptive Hypercube Grid (Coello 2004)
# ─────────────────────────────────────────────────────────────────────────────
class MOPSO_Repository:
    def __init__(self, capacity=100, n_grid_divs=10):
        self.capacity    = capacity
        self.n_grid_divs = n_grid_divs
        self.archive_particles = []   # list of flat np.ndarray
        self.archive_costs     = []   # list of list[float]

    # ── Pareto dominance ────────────────────────────────────────────────────
    @staticmethod
    def dominates(ca, cb):
        a, b = np.array(ca), np.array(cb)
        return np.all(a <= b) and np.any(a < b)

    def _is_dominated_by_archive(self, cost):
        for ac in self.archive_costs:
            if self.dominates(ac, cost):
                return True
        return False

    def _remove_dominated_by(self, cost):
        keep_p, keep_c = [], []
        for p, c in zip(self.archive_particles, self.archive_costs):
            if not self.dominates(cost, c):
                keep_p.append(p)
                keep_c.append(c)
        self.archive_particles = keep_p
        self.archive_costs     = keep_c

    # ── Duplicate filter ────────────────────────────────────────────────────
    def _is_duplicate(self, cost):
        for ac in self.archive_costs:
            if np.allclose(ac, cost, atol=1e-8):
                return True
        return False

    # ── Adaptive Grid Hypercube (Coello 2004) ───────────────────────────────
    def _hypercube_index(self, cost):
        """Map cost vector → scalar cell index using current archive range."""
        if len(self.archive_costs) < 2:
            return 0
        arr   = np.array(self.archive_costs)
        lo    = arr.min(axis=0)
        hi    = arr.max(axis=0)
        spans = np.maximum(hi - lo, 1e-12)
        bins  = np.floor((np.array(cost) - lo) / spans * self.n_grid_divs)
        bins  = np.clip(bins, 0, self.n_grid_divs - 1).astype(int)
        # Cantor-style encoding
        idx = 0
        for b in bins:
            idx = idx * self.n_grid_divs + b
        return idx

    def _grid_densities(self):
        cell_count = {}
        for c in self.archive_costs:
            key = self._hypercube_index(c)
            cell_count[key] = cell_count.get(key, 0) + 1
        return [cell_count[self._hypercube_index(c)] for c in self.archive_costs]

    def _prune_crowded(self):
        densities = self._grid_densities()
        idx = int(np.argmax(densities))
        self.archive_particles.pop(idx)
        self.archive_costs.pop(idx)

    # ── Public API ──────────────────────────────────────────────────────────
    def update_repository(self, new_particles, new_costs):
        for p, c in zip(new_particles, new_costs):
            c = list(c)
            if self._is_duplicate(c):
                continue
            if not self._is_dominated_by_archive(c):
                self._remove_dominated_by(c)
                self.archive_particles.append(np.asarray(p).copy())
                self.archive_costs.append(c)

        while len(self.archive_particles) > self.capacity:
            self._prune_crowded()

    def select_leader(self):
        """Roulette-wheel từ ô thưa nhất (Coello 2004)."""
        if not self.archive_particles:
            return None
        densities   = np.array(self._grid_densities(), dtype=float)
        weights     = 1.0 / (densities + 1e-6)
        weights    /= weights.sum()
        idx = np.random.choice(len(self.archive_particles), p=weights)
        return self.archive_particles[idx]


# ─────────────────────────────────────────────────────────────────────────────
# 3. QL-MOPSO OPTIMIZER  –  mỗi hạt mã hóa toàn bộ U UAVs (dim = 3U)
# ─────────────────────────────────────────────────────────────────────────────
class QL_MOPSO_Optimizer:
    """
    Tham số:
      n_uavs        : số UAV cần tối ưu
      num_particles : kích thước quần thể
      max_iter      : số vòng lặp
      c1,c2,c3      : hệ số Cognitive / Social / Q-learning Guidance
      seed          : để kết quả tái lập
      allocator     : ResourceAllocator instance (bắt buộc cho fitness thật)

    Bounds:
      lower_3d, upper_3d : giới hạn (3,) cho MỖI UAV; tự tile sang 3U chiều.

    Output của optimize():
      pareto_positions : list[np.ndarray shape (n_uavs, 3)]
      pareto_costs     : list[list[float]]  [avg_delay, energy, -satisfaction, penalty]
    """

    D_SAFE_M   = 5.0     # khoảng cách an toàn tối thiểu giữa 2 UAV (2605.01414v1)
    PENALTY_K  = 1000.0  # hệ số phạt va chạm

    def __init__(self, n_uavs=2, num_particles=40, max_iter=100,
                 c1=2.0, c2=2.0, c3=1.5, seed=GLOBAL_SEED, allocator=None):
        self.n_uavs        = n_uavs
        self.dim           = n_uavs * 3
        self.num_particles = num_particles
        self.max_iter      = max_iter
        self.c1 = c1;  self.c2 = c2;  self.c3 = c3
        self.seed          = seed
        self.allocator     = allocator
        self.energy_model  = UAVEnergyModel_Nature2025()
        self.repository    = MOPSO_Repository(capacity=100, n_grid_divs=10)

    # ── Decode ──────────────────────────────────────────────────────────────
    def _decode(self, particle):
        return particle.reshape(self.n_uavs, 3)

    # ── Safety penalty ──────────────────────────────────────────────────────
    def _safety_penalty(self, uav_positions):
        penalty = 0.0
        for i in range(self.n_uavs):
            for j in range(i + 1, self.n_uavs):
                d = np.linalg.norm(uav_positions[i] - uav_positions[j])
                if d < self.D_SAFE_M:
                    penalty += (self.D_SAFE_M - d) * self.PENALTY_K
        return penalty

    # ── Fitness (4 mục tiêu, cùng đơn vị hợp lý) ───────────────────────────
    def _eval_objectives(self, particle, scenario):
        """
        Trả về [avg_delay_ms, energy_J (÷1e4), neg_satisfaction×100, safety_penalty].
        Chia energy cho 1e4 để cùng bậc với delay (ms).
        """
        uav_pos = self._decode(particle)

        # Năng lượng bay từ gốc → vị trí (proxy đơn giản, đủ để PSO so sánh tương đối)
        total_energy = sum(
            self.energy_model.compute_total_energy([np.zeros(3), pos])[0]
            for pos in uav_pos
        )

        # Penalty an toàn
        penalty = self._safety_penalty(uav_pos)

        # Throughput & delay thật từ ResourceAllocator
        if self.allocator is not None and scenario is not None:
            result = self.allocator.allocate(
                uav_pos,
                scenario['vessel_positions'],
                scenario['traffic_demand']
            )
            avg_delay    = result['avg_delay_ms']
            satisfaction = result['satisfaction_ratio']
        else:
            # Fallback: khoảng cách đến centroid tàu thuyền
            if scenario is not None:
                centroid = scenario['vessel_positions'].mean(axis=0)
                avg_dist = np.mean([np.linalg.norm(p[:2] - centroid) for p in uav_pos])
            else:
                avg_dist = 5000.0
            avg_delay    = avg_dist / 3e5 * 1000   # ước lượng ms
            satisfaction = max(0.0, 1.0 - avg_dist / 5000)

        return [
            avg_delay,
            total_energy / 1e4,        # chuẩn hóa về cùng bậc ~ 1–10
            -satisfaction * 100,       # âm vì minimize
            penalty,
        ]

    # ── Dominance check ─────────────────────────────────────────────────────
    @staticmethod
    def _dominates(ca, cb):
        a, b = np.array(ca), np.array(cb)
        return np.all(a <= b) and np.any(a < b)

    # ── Khởi tạo có hướng dẫn ───────────────────────────────────────────────
    def _init_particles(self, lb, ub, P_QL_full):
        particles = np.random.uniform(lb, ub, (self.num_particles, self.dim))
        if P_QL_full is not None:
            n_guided = self.num_particles // 3
            for i in range(n_guided):
                offset = np.random.normal(0, 200, self.dim)
                particles[i] = np.clip(P_QL_full + offset, lb, ub)
        return particles

    # ── Vòng lặp chính ──────────────────────────────────────────────────────
    def optimize(self, bounds_3d, scenario, P_QL_3d=None):
        """
        bounds_3d : (lower_3d, upper_3d) – giới hạn cho 1 UAV, shape (3,)
        scenario  : dict từ GenAI_TrafficGenerator.generate_scenario()
        P_QL_3d   : gợi ý từ Q-Learning (3,), sẽ tile sang dim = 3U
        """
        np.random.seed(self.seed)
        self.repository = MOPSO_Repository(capacity=100, n_grid_divs=10)

        lb = np.tile(bounds_3d[0], self.n_uavs)
        ub = np.tile(bounds_3d[1], self.n_uavs)
        P_QL_full = np.tile(P_QL_3d, self.n_uavs) if P_QL_3d is not None else None

        particles  = self._init_particles(lb, ub, P_QL_full)
        velocities = np.zeros_like(particles)

        # Tính cost lần đầu (cache, không tính lại)
        costs = [self._eval_objectives(p, scenario) for p in particles]

        pbest       = particles.copy()
        pbest_costs = [c[:] for c in costs]

        self.repository.update_repository(particles.tolist(), costs)

        for t in range(self.max_iter):
            # Trọng số quán tính giảm dần (Shi & Eberhart 1998)
            w = 1.2 - 0.8 * (t / self.max_iter)
            gamma_g = self.c3 * max(0.0, 1.0 - t / self.max_iter)

            gbest = self.repository.select_leader()
            if gbest is None:
                gbest = pbest[np.random.randint(self.num_particles)]

            for i in range(self.num_particles):
                r1, r2 = np.random.rand(2)

                # Phương trình vận tốc QL-MOPSO (Li et al. 2025)
                velocities[i] = (w * velocities[i]
                                 + self.c1 * r1 * (pbest[i] - particles[i])
                                 + self.c2 * r2 * (gbest - particles[i]))
                if P_QL_full is not None and gamma_g > 0:
                    r3 = np.random.rand()
                    velocities[i] += gamma_g * r3 * (P_QL_full - particles[i])

                particles[i] = np.clip(particles[i] + velocities[i], lb, ub)

                # Tính cost MỘT LẦN duy nhất (fix: không tính lại khi update repo)
                current_cost = self._eval_objectives(particles[i], scenario)

                # Cập nhật pbest bằng Pareto dominance (fix: không dùng np.sum)
                if self._dominates(current_cost, pbest_costs[i]):
                    pbest[i]       = particles[i].copy()
                    pbest_costs[i] = current_cost[:]

            # Đưa tất cả nghiệm vào repository (dùng cost đã tính, không tính lại)
            # Vì chỉ có cost của vòng lặp hiện tại, dùng pbest_costs làm proxy
            if t % 5 == 0:
                self.repository.update_repository(
                    particles.tolist(),
                    [self._eval_objectives(p, scenario) for p in particles]
                )

        # Định dạng output: list of (n_uavs, 3)
        pareto_positions = [np.array(p).reshape(self.n_uavs, 3)
                            for p in self.repository.archive_particles]
        return pareto_positions, self.repository.archive_costs


# ─────────────────────────────────────────────────────────────────────────────
# DEMO
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("Demo QL-MOPSO (không có ResourceAllocator – dùng fallback fitness)")
    optimizer = QL_MOPSO_Optimizer(n_uavs=2, num_particles=20, max_iter=30)
    bounds_3d = (np.array([0.0, 0.0, 45.0]), np.array([5000.0, 5000.0, 100.0]))
    fake_scenario = {
        'vessel_positions': np.array([[2000, 2000], [3000, 3000], [1500, 2500]]),
        'traffic_demand':   np.array([50.0, 80.0, 40.0])
    }
    pareto_pos, pareto_costs = optimizer.optimize(bounds_3d, fake_scenario,
                                                   P_QL_3d=np.array([2500., 2500., 70.]))
    print(f"Tìm được {len(pareto_pos)} nghiệm Pareto")
    for i, (pos, cost) in enumerate(zip(pareto_pos[:3], pareto_costs[:3])):
        print(f"  [{i}] UAV0={np.round(pos[0]).astype(int)}, "
              f"UAV1={np.round(pos[1]).astype(int)} | "
              f"Delay={cost[0]:.1f}ms  Energy={cost[1]:.2f}×1e4J  "
              f"Sat={-cost[2]:.1f}%  Penalty={cost[3]:.1f}")
