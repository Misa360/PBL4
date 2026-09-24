"""
orbital.py
Mo hinh quy dao ve tinh va vi tri node mat dat/UAV theo toa do thuc.

QUAN TRONG: Day la mo hinh quy dao TRON (circular Kepler orbit) don gian hoa,
dung cong thuc co hoc thien the that (GM trai dat, dinh luat Kepler, phep quay
RAAN/inclination). Khong dung TLE thuc tu Celestrak vi moi truong chay code
khong co internet de tai du lieu. Khi lam luan van chinh thuc, ban nen thay
the SatellitePropagator bang du lieu TLE that + thu vien sgp4/Skyfield de co
do chinh xac cao hon (quy dao thuc te co nhieu yeu to nhieu loan: J2, khang
khi quyen...). Phan API (position_eci, vi tri quan sat...) duoc thiet ke de
de dang thay the sau nay.
"""

import numpy as np

# ---- Hang so vat ly ----
GM_EARTH = 3.986004418e14       # m^3/s^2 - hang so hap dan trai dat
RE = 6371000.0                  # m - ban kinh trai dat trung binh
EARTH_ROT_RATE = 7.2921159e-5   # rad/s - toc do tu quay trai dat


class SatellitePropagator:
    """Ve tinh chuyen dong tren quy dao tron quanh trai dat (khung ECI)."""

    def __init__(self, sat_id, altitude_km, inclination_deg, raan_deg, mean_anomaly0_deg):
        self.sat_id = sat_id
        self.a = RE + altitude_km * 1000.0          # ban kinh quy dao (m)
        self.inc = np.radians(inclination_deg)       # goc nghieng quy dao
        self.raan = np.radians(raan_deg)              # right ascension of ascending node
        self.theta0 = np.radians(mean_anomaly0_deg)   # vi tri ban dau tren quy dao
        # Dinh luat Kepler thu 3: n = sqrt(GM / a^3) (quy dao tron -> mean motion = goc quet)
        self.n = np.sqrt(GM_EARTH / self.a ** 3)
        self.period_s = 2 * np.pi / self.n

    def position_eci(self, t):
        """Vi tri ve tinh trong khung ECI (m) tai thoi diem t (giay)."""
        theta = self.theta0 + self.n * t
        # Vi tri trong mat phang quy dao (perifocal, argument of perigee = 0)
        x_p = self.a * np.cos(theta)
        y_p = self.a * np.sin(theta)
        # Quay quanh truc x theo goc nghieng inclination
        x1 = x_p
        y1 = y_p * np.cos(self.inc)
        z1 = y_p * np.sin(self.inc)
        # Quay quanh truc z theo RAAN
        x_eci = x1 * np.cos(self.raan) - y1 * np.sin(self.raan)
        y_eci = x1 * np.sin(self.raan) + y1 * np.cos(self.raan)
        z_eci = z1
        return np.array([x_eci, y_eci, z_eci])


def latlon_to_ecef(lat_deg, lon_deg, alt_m=0.0):
    """Chuyen (vi do, kinh do, do cao) -> toa do ECEF (m). Gia dinh trai dat hinh cau."""
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    r = RE + alt_m
    x = r * np.cos(lat) * np.cos(lon)
    y = r * np.cos(lat) * np.sin(lon)
    z = r * np.sin(lat)
    return np.array([x, y, z])


def ecef_to_eci(pos_ecef, t):
    """Chuyen ECEF -> ECI tai thoi diem t, tinh den vong quay trai dat."""
    theta = EARTH_ROT_RATE * t
    x, y, z = pos_ecef
    x_eci = x * np.cos(theta) - y * np.sin(theta)
    y_eci = x * np.sin(theta) + y * np.cos(theta)
    return np.array([x_eci, y_eci, z])


def elevation_angle_deg(observer_eci, sat_eci):
    """Goc nang (elevation) cua ve tinh nhin tu observer, tinh bang do.
    >0 nghia la ve tinh o tren duong chan troi (co the nhin thay)."""
    los = sat_eci - observer_eci
    zenith = observer_eci / np.linalg.norm(observer_eci)
    cos_zenith_angle = np.dot(los, zenith) / np.linalg.norm(los)
    cos_zenith_angle = np.clip(cos_zenith_angle, -1.0, 1.0)
    zenith_angle = np.degrees(np.arccos(cos_zenith_angle))
    return 90.0 - zenith_angle


def local_offset_to_latlon(lat0_deg, lon0_deg, dx_m, dy_m):
    """Dich chuyen (dx, dy) met theo huong Dong/Bac tu diem (lat0, lon0) -> (lat, lon) moi.
    Xap xi phang, chi dung cho khu vuc nho (vai chuc km)."""
    lat0 = np.radians(lat0_deg)
    dlat = dy_m / RE
    dlon = dx_m / (RE * np.cos(lat0))
    return lat0_deg + np.degrees(dlat), lon0_deg + np.degrees(dlon)
