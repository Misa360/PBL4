"""
run_demo.py
Chay demo mo phong SAGIN 3 lop: 3 ve tinh, 4 UAV, luoi ground 2x2 (4 node),
quanh toa do Da Nang. Xuat CSV + bieu do PNG.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from simulation import SAGINSimulation

# Toa do trung tam (Da Nang) - co the doi sang khu vuc khac
CENTER_LAT = 16.0544
CENTER_LON = 108.2022

sim = SAGINSimulation(
    center_lat=CENTER_LAT, center_lon=CENTER_LON,
    n_ground_rows=2, n_ground_cols=2, ground_spacing_m=2000.0,
    n_uav=4, uav_radius_m=3000.0, uav_altitude_m=2000.0,
    n_sat=3, sat_altitude_km=550.0, sat_inclination_deg=53.0,
    duration_s=11800.0,  # ~2 chu ky quy dao LEO (~197 phut) de thay ro tinh gian doan
    dt_s=20.0,            # cap nhat moi 20 giay
)

df = sim.run(verbose=False)
summary = sim.summary(df)

print("=== TOM TAT KET QUA ===")
for k, v in summary.items():
    print(f"{k}: {v}")

df.to_csv("sim_log.csv", index=False)

# ------- Bieu do 1: so ve tinh nhin thay theo thoi gian -------
fig, ax = plt.subplots(figsize=(9, 3.2))
ax.plot(df["t_s"] / 60.0, df["n_visible_sats"], drawstyle="steps-post", color="#0F6E56")
ax.set_xlabel("Thoi gian (phut)")
ax.set_ylabel("So ve tinh nhin thay")
ax.set_title("So ve tinh trong tam nhin cua he thong UAV theo thoi gian")
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("chart_visible_satellites.png", dpi=150)
plt.close(fig)

# ------- Bieu do 2: do tre end-to-end theo thoi gian -------
fig, ax = plt.subplots(figsize=(9, 3.2))
ax.plot(df["t_s"] / 60.0, df["end_to_end_delay_s"] * 1000, color="#185FA5")
ax.set_xlabel("Thoi gian (phut)")
ax.set_ylabel("Do tre end-to-end (ms)")
ax.set_title("Do tre tu node mat dat toi ve tinh gan nhat qua UAV")
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("chart_delay.png", dpi=150)
plt.close(fig)

# ------- Bieu do 3: ket noi (connectivity) theo thoi gian -------
fig, ax = plt.subplots(figsize=(9, 2.2))
ax.fill_between(df["t_s"] / 60.0, df["connected_to_space"].astype(int),
                 step="post", color="#0F6E56", alpha=0.5)
ax.set_xlabel("Thoi gian (phut)")
ax.set_yticks([0, 1])
ax.set_yticklabels(["Mat ket noi", "Co ket noi"])
ax.set_title("Trang thai ket noi tu mat dat len lop khong gian")
fig.tight_layout()
fig.savefig("chart_connectivity.png", dpi=150)
plt.close(fig)

print("\nDa luu: sim_log.csv, chart_visible_satellites.png, chart_delay.png, chart_connectivity.png")
