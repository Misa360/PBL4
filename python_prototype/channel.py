"""
channel.py
Mo hinh keng truyen vat ly cho tung loai lien ket:
- Ground <-> UAV: bang C (6 GHz)
- UAV <-> Satellite: bang Ka (30 GHz)
Cong thuc: free-space path loss + SINR + Shannon capacity (giong huong tiep can
da hoc duoc tu repo tham khao SAGIN_Framework_Task_offloading_Content_caching).
"""

import numpy as np

C_LIGHT = 3e8  # m/s

# --- Tham so bang C (Ground-UAV) ---
C_BAND_FREQ = 6e9
B_GROUND_UAV = 5e6          # 5 MHz
P_GROUND = 0.5               # W - cong suat phat node mat dat
G_GROUND = 1.0
G_UAV_RX = 10.0
NOISE_C_BAND = 1e-12

# --- Tham so bang Ka (UAV-Satellite) ---
KA_BAND_FREQ = 30e9
B_UAV_SAT = 10e6             # 10 MHz
P_UAV = 5.0                  # W
G_UAV_TX = 100.0
G_SAT_RX = 10000.0
NOISE_KA_BAND = 1e-13

MIN_ELEVATION_DEG = 10.0     # goc nang toi thieu de ve tinh "nhin thay" duoc
MAX_GROUND_UAV_RANGE_M = 6000.0  # tam phu song toi da cua UAV xuong mat dat


def free_space_path_loss(distance_m, freq_hz, exponent=2.0):
    if distance_m <= 1.0:
        distance_m = 1.0
    wavelength = C_LIGHT / freq_hz
    return (4 * np.pi * distance_m / wavelength) ** exponent


def ground_to_uav_link(distance_m):
    """Tra ve (rate_bps, kha_dung, do_tre_lan_truyen_s)."""
    if distance_m > MAX_GROUND_UAV_RANGE_M:
        return 0.0, False, float("inf")
    path_loss = free_space_path_loss(distance_m, C_BAND_FREQ)
    channel_gain = G_GROUND * G_UAV_RX / path_loss
    sinr = (P_GROUND * channel_gain) / NOISE_C_BAND
    rate = B_GROUND_UAV * np.log2(1 + sinr)
    prop_delay = distance_m / C_LIGHT
    success = rate >= 1e5  # nguong toi thieu 100 kbps
    return rate, success, prop_delay


def uav_to_satellite_link(distance_m, elevation_deg):
    """Tra ve (rate_bps, kha_dung, do_tre_lan_truyen_s). Chi kha dung neu goc nang du lon."""
    if elevation_deg < MIN_ELEVATION_DEG:
        return 0.0, False, float("inf")
    path_loss = free_space_path_loss(distance_m, KA_BAND_FREQ)
    channel_gain = G_UAV_TX * G_SAT_RX / path_loss
    sinr = (P_UAV * channel_gain) / NOISE_KA_BAND
    rate = B_UAV_SAT * np.log2(1 + sinr)
    prop_delay = distance_m / C_LIGHT
    success = rate >= 1e6  # nguong toi thieu 1 Mbps
    return rate, success, prop_delay


def transmission_delay(rate_bps, size_mb):
    if rate_bps <= 0:
        return float("inf")
    bits = size_mb * 8 * 1e6
    return bits / rate_bps
