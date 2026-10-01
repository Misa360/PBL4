"""
rl_selector.py  –  Q-Learning Agent chọn điểm trên Pareto Front
────────────────────────────────────────────────────────────────────────────────
Đề bài yêu cầu: "GenAI tạo nhiều phương án, RL chọn phương án tốt nhất."

Pipeline hoàn chỉnh:
  [GenAI] → kịch bản lưu lượng
  [PSO]   → Pareto Front (delay, energy, -satisfaction, penalty)
  [QL]    → chọn điểm tốt nhất từ Pareto dựa trên trạng thái mạng
  [ResourceAllocator] → phân bổ BW/công suất và xuất số liệu

State (rời rạc hóa):
  - mode_idx: 0=bình_thường, 1=đông_đúc, 2=bão_tố, 3=đêm_vắng
  - load_bin: 0–3  (0-25%, 25-50%, 50-75%, 75-100%)
  - vessel_bin: 0–3 (1-5, 6-12, 13-20, 21+ tàu)
  → tổng cộng 4 × 4 × 4 = 64 states

Action (3):
  0 = ưu tiên delay thấp   (chọn điểm min delay trong Pareto)
  1 = cân bằng            (chọn điểm normalized-sum nhỏ nhất)
  2 = ưu tiên tiết kiệm năng lượng (chọn điểm min energy)

Reward:
  r = -avg_delay/200 + 2×satisfaction - 0.05×energy_factor + penalty_bonus
────────────────────────────────────────────────────────────────────────────────
"""

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Q-Learning Pareto Selector
# ─────────────────────────────────────────────────────────────────────────────
class QLearningParetoSelector:

    MODES       = ['binh_thuong', 'dong_duc', 'bao_to', 'dem_vang']
    N_LOAD_BINS = 4
    N_VES_BINS  = 4   # 1-5, 6-12, 13-20, 21+
    N_ACTIONS   = 3   # min_delay, balanced, min_energy
    VES_THRES   = [5, 12, 20]  # ngưỡng chia bin tàu thuyền

    def __init__(self, alpha=0.15, gamma=0.9, epsilon=0.3,
                 epsilon_decay=0.995, epsilon_min=0.05, seed=42):
        self.alpha         = alpha
        self.gamma         = gamma
        self.epsilon       = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min   = epsilon_min
        np.random.seed(seed)

        n_states = len(self.MODES) * self.N_LOAD_BINS * self.N_VES_BINS
        self.Q = np.zeros((n_states, self.N_ACTIONS))
        self.episode_log = []   # [(state, action, reward, next_state)]

    # ── Discretize state ────────────────────────────────────────────────────
    def _state_idx(self, scenario):
        mode     = scenario.get('mode', 'binh_thuong')
        mode_i   = self.MODES.index(mode) if mode in self.MODES else 0

        load     = float(np.clip(scenario.get('load', 0.4), 0.0, 0.9999))
        load_bin = min(int(load * self.N_LOAD_BINS), self.N_LOAD_BINS - 1)

        n_ves    = int(scenario.get('n_vessels', 5))
        v_bin    = sum(n_ves > t for t in self.VES_THRES)

        return (mode_i * self.N_LOAD_BINS * self.N_VES_BINS
                + load_bin * self.N_VES_BINS
                + v_bin)

    # ── Select from Pareto Front ─────────────────────────────────────────────
    def _pick_from_pareto(self, pareto_positions, pareto_costs, action):
        """Chọn 1 điểm trên Pareto Front theo action."""
        if not pareto_positions:
            return None, 0

        costs = np.array(pareto_costs, dtype=float)   # (M, 4)

        if action == 0:      # ưu tiên delay (cột 0)
            idx = int(np.argmin(costs[:, 0]))
        elif action == 2:    # ưu tiên energy (cột 1)
            idx = int(np.argmin(costs[:, 1]))
        else:                # balanced: normalized sum
            lo   = costs.min(axis=0)
            hi   = costs.max(axis=0)
            span = np.maximum(hi - lo, 1e-10)
            norm = (costs - lo) / span
            idx  = int(np.argmin(norm.sum(axis=1)))

        return pareto_positions[idx], idx

    # ── ε-greedy action selection ────────────────────────────────────────────
    def select_action(self, scenario):
        s = self._state_idx(scenario)
        if np.random.rand() < self.epsilon:
            return np.random.randint(self.N_ACTIONS)
        return int(np.argmax(self.Q[s]))

    # ── Reward ──────────────────────────────────────────────────────────────
    @staticmethod
    def compute_reward(result):
        """
        result: dict từ ResourceAllocator.allocate
        Reward thang [-2, +2] để Q-table ổn định.
        """
        delay_ms     = result.get('avg_delay_ms', 500.0)
        satisfaction = result.get('satisfaction_ratio', 0.0)
        energy_fac   = result.get('total_energy_J', 0.0) / 1e5   # ~0.1–2

        # Phạt nặng nếu delay vượt 200ms (target của đề bài)
        delay_penalty = min(delay_ms / 200.0, 2.5)
        sat_bonus     = 2.0 * satisfaction
        energy_cost   = 0.05 * energy_fac

        return -delay_penalty + sat_bonus - energy_cost

    # ── Q-Learning update ────────────────────────────────────────────────────
    def update(self, scenario, action, reward, next_scenario):
        s  = self._state_idx(scenario)
        s2 = self._state_idx(next_scenario)
        td_error = reward + self.gamma * np.max(self.Q[s2]) - self.Q[s, action]
        self.Q[s, action] += self.alpha * td_error
        self.episode_log.append((s, action, reward, s2))

    # ── Epsilon decay ────────────────────────────────────────────────────────
    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    # ── Full pipeline: select UAV positions ─────────────────────────────────
    def select_uav_positions(self, pareto_positions, pareto_costs, scenario):
        """
        Trả về (best_uav_positions, action_taken).
        best_uav_positions: np.ndarray shape (n_uavs, 3)
        """
        action = self.select_action(scenario)
        pos, pareto_idx = self._pick_from_pareto(pareto_positions, pareto_costs, action)
        return pos, action, pareto_idx

    # ── Q-table summary ─────────────────────────────────────────────────────
    def print_policy(self):
        ACTION_NAMES = ['min-delay', 'balanced', 'min-energy']
        MODE_LABELS  = ['bình_thường', 'đông_đúc', 'bão_tố', 'đêm_vắng']
        LOAD_LABELS  = ['0-25%', '25-50%', '50-75%', '75-100%']
        VES_LABELS   = ['1-5', '6-12', '13-20', '21+']

        print(f"\n{'─'*62}")
        print(f"  Q-Learning Policy Table  (ε={self.epsilon:.3f})")
        print(f"{'─'*62}")
        print(f"  {'Mode':<14} {'Load':<10} {'Vessels':<10} {'Best Action'}")
        print(f"{'─'*62}")
        for mi, ml in enumerate(MODE_LABELS):
            for li, ll in enumerate(LOAD_LABELS):
                for vi, vl in enumerate(VES_LABELS):
                    s  = mi * self.N_LOAD_BINS * self.N_VES_BINS + li * self.N_VES_BINS + vi
                    a  = int(np.argmax(self.Q[s]))
                    qv = self.Q[s, a]
                    print(f"  {ml:<14} {ll:<10} {vl:<10} {ACTION_NAMES[a]}  (Q={qv:.3f})")
        print(f"{'─'*62}")


# ─────────────────────────────────────────────────────────────────────────────
# Training loop: so sánh RL vs Baseline
# ─────────────────────────────────────────────────────────────────────────────
class BaselineSelector:
    """Baseline không dùng RL: chọn UAV tại centroid tàu thuyền."""

    @staticmethod
    def select_uav_positions(pareto_positions, pareto_costs, scenario, n_uavs=2):
        """Chọn điểm Pareto ngẫu nhiên (không có thông tin trạng thái)."""
        if not pareto_positions:
            return None, -1, -1
        idx = np.random.randint(len(pareto_positions))
        return pareto_positions[idx], -1, idx


def run_comparison(n_episodes=30, n_uavs=2, seed=42):
    """
    So sánh:  RL (Q-learning) vs Baseline (random Pareto selection).
    Trả về DataFrame kết quả.
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from genai_resource_allocator import (
        GenAI_TrafficGenerator, ResourceAllocator, SAGIN_ResourceOptimizationPipeline
    )
    from pso_sagin import QL_MOPSO_Optimizer
    import pandas as pd
    import numpy as np

    np.random.seed(seed)

    gen_ai    = GenAI_TrafficGenerator(area_km=5.0, rng_seed=seed)
    allocator = ResourceAllocator(total_bandwidth_mhz=200.0)
    rl_agent  = QLearningParetoSelector(seed=seed)
    baseline  = BaselineSelector()

    bounds_3d = (np.array([0.0, 0.0, 45.0]), np.array([5000.0, 5000.0, 100.0]))
    optimizer = QL_MOPSO_Optimizer(n_uavs=n_uavs, num_particles=25,
                                   max_iter=40, seed=seed, allocator=allocator)

    records = []
    scenarios = gen_ai.generate_batch(n_episodes)

    print(f"\n{'═'*65}")
    print(f"  RL vs Baseline Comparison  ({n_episodes} episodes, {n_uavs} UAVs)")
    print(f"{'═'*65}")

    for ep, scenario in enumerate(scenarios):
        # Centroid tàu thuyền → P_QL
        centroid = np.append(scenario['vessel_positions'].mean(axis=0), 70.0)

        # PSO tạo Pareto Front
        pareto_pos, pareto_costs = optimizer.optimize(bounds_3d, scenario,
                                                       P_QL_3d=centroid)

        if not pareto_pos:
            continue

        # ── RL chọn ──────────────────────────────────────────────────────
        rl_uav, rl_action, _ = rl_agent.select_uav_positions(
            pareto_pos, pareto_costs, scenario)
        rl_result = allocator.allocate(rl_uav, scenario['vessel_positions'],
                                       scenario['traffic_demand'])
        rl_reward = rl_agent.compute_reward(rl_result)

        # Update Q-table
        next_sc = gen_ai.generate_scenario()
        rl_agent.update(scenario, rl_action, rl_reward, next_sc)
        rl_agent.decay_epsilon()

        # ── Baseline chọn ────────────────────────────────────────────────
        bl_uav, _, _ = baseline.select_uav_positions(
            pareto_pos, pareto_costs, scenario, n_uavs=n_uavs)
        bl_result = allocator.allocate(bl_uav, scenario['vessel_positions'],
                                       scenario['traffic_demand'])

        records.append({
            'episode':          ep + 1,
            'mode':             scenario['mode'],
            'n_vessels':        scenario['n_vessels'],
            'rl_delay_ms':      rl_result['avg_delay_ms'],
            'bl_delay_ms':      bl_result['avg_delay_ms'],
            'rl_satisfaction':  rl_result['satisfaction_ratio'] * 100,
            'bl_satisfaction':  bl_result['satisfaction_ratio'] * 100,
            'rl_reward':        rl_reward,
            'rl_action':        ['min-delay','balanced','min-energy'][rl_action],
            'pareto_size':      len(pareto_pos),
            'epsilon':          rl_agent.epsilon,
        })

        if (ep + 1) % 5 == 0:
            rl_d  = np.mean([r['rl_delay_ms']     for r in records[-5:]])
            bl_d  = np.mean([r['bl_delay_ms']     for r in records[-5:]])
            rl_s  = np.mean([r['rl_satisfaction'] for r in records[-5:]])
            bl_s  = np.mean([r['bl_satisfaction'] for r in records[-5:]])
            print(f"  Ep {ep+1:3d} | RL: delay={rl_d:.0f}ms sat={rl_s:.1f}% "
                  f"| Base: delay={bl_d:.0f}ms sat={bl_s:.1f}% "
                  f"| ε={rl_agent.epsilon:.3f}")

    df = pd.DataFrame(records)
    print(f"\n{'─'*65}")
    print(f"  TỔNG KẾT:")
    print(f"  RL  Delay TB : {df['rl_delay_ms'].mean():.2f} ms  "
          f"| QoS TB: {df['rl_satisfaction'].mean():.1f}%")
    print(f"  Baseline Delay: {df['bl_delay_ms'].mean():.2f} ms  "
          f"| QoS TB: {df['bl_satisfaction'].mean():.1f}%")
    improvement = (df['bl_delay_ms'].mean() - df['rl_delay_ms'].mean()) / df['bl_delay_ms'].mean() * 100
    print(f"  RL giảm độ trễ: {improvement:.1f}% so với Baseline")
    print(f"{'═'*65}")

    rl_agent.print_policy()

    df.to_csv('rl_comparison_results.csv', index=False, encoding='utf-8-sig')
    print(f"\n  📄 Lưu: rl_comparison_results.csv")
    return df, rl_agent


# ─────────────────────────────────────────────────────────────────────────────
# CHẠY NHANH
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    df, agent = run_comparison(n_episodes=20, n_uavs=2, seed=42)
