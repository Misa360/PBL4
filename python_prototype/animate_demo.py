import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import networkx as nx

from simulation import SAGINSimulation
from topology import build_topology
from orbital import EARTH_ROT_RATE, latlon_to_ecef

# Thiet lap cac thong so mo phong
CENTER_LAT = 16.0544
CENTER_LON = 108.2022
DURATION = 11800 # ~197 phut (Hon 2 vong quy dao LEO)
DT = 30          # Moi step 30s de thoi gian troi nhanh hon tren hinh

sim = SAGINSimulation(
    center_lat=CENTER_LAT, center_lon=CENTER_LON,
    n_ground_rows=2, n_ground_cols=2, ground_spacing_m=2000.0,
    n_uav=4, uav_radius_m=3000.0, uav_altitude_m=2000.0,
    n_sat=3, sat_altitude_km=550.0, sat_inclination_deg=53.0,
    duration_s=DURATION, dt_s=DT
)

# Kich hoat che do tuong tac, Giao dien Vu tru (Space)
plt.style.use('dark_background')
fig = plt.figure(figsize=(10, 8))
fig.patch.set_facecolor('black')
ax = fig.add_subplot(111, projection='3d')
ax.set_facecolor('black')
ax.axis('off')

# Ban kinh Trai dat
RE_km = 6371.0
R_MAX = RE_km + 1500.0

# --- 1. VE BE MAT TRAI DAT (Solid sphere - dung yen) ---
u = np.linspace(0, 2 * np.pi, 50)
v = np.linspace(0, np.pi, 50)
x_earth = RE_km * np.outer(np.cos(u), np.sin(v))
y_earth = RE_km * np.outer(np.sin(u), np.sin(v))
z_earth = RE_km * np.outer(np.ones(np.size(u)), np.cos(v))

# Be mat Trai Dat nhan, khong ke vien (edgecolor='none')
ax.plot_surface(x_earth, y_earth, z_earth, color='#062b50', alpha=0.9, edgecolor='none')

# --- 2. TAO LUOI KINH/VI TUYEN TRAI DAT (De tao hieu ung quay) ---
grid_lines_ecef = []
# Vi tuyen (Latitudes)
for lat in range(-60, 61, 30):
    lat_rad = np.radians(lat)
    r = RE_km * np.cos(lat_rad)
    z = RE_km * np.sin(lat_rad)
    theta_arr = np.linspace(0, 2*np.pi, 60)
    x = r * np.cos(theta_arr)
    y = r * np.sin(theta_arr)
    grid_lines_ecef.append(np.vstack((x, y, np.full_like(x, z))))

# Kinh tuyen (Longitudes)
for lon in range(0, 360, 30):
    lon_rad = np.radians(lon)
    lat_arr = np.linspace(-np.pi/2, np.pi/2, 60)
    x = RE_km * np.cos(lat_arr) * np.cos(lon_rad)
    y = RE_km * np.cos(lat_arr) * np.sin(lon_rad)
    z = RE_km * np.sin(lat_arr)
    grid_lines_ecef.append(np.vstack((x, y, z)))

grid_lines_3d = []
for line_ecef in grid_lines_ecef:
    line_obj, = ax.plot(line_ecef[0], line_ecef[1], line_ecef[2], color='#1874cd', alpha=0.5, linewidth=0.8)
    grid_lines_3d.append(line_obj)

# --- 3. VE QUY DAO VE TINH (Orbit Rings - Co dinh) ---
for sat in sim.sat_nodes:
    period = sat.prop.period_s
    t_orb = np.linspace(0, period, 100)
    ox, oy, oz = [], [], []
    for to in t_orb:
        pos = sat.prop.position_eci(to)
        ox.append(pos[0]/1000.0)
        oy.append(pos[1]/1000.0)
        oz.append(pos[2]/1000.0)
    ax.plot(ox, oy, oz, color='white', alpha=0.2, linestyle='--')

ax.set_xlim([-R_MAX, R_MAX])
ax.set_ylim([-R_MAX, R_MAX])
ax.set_zlim([-R_MAX, R_MAX])
ax.view_init(elev=20, azim=110)

time_text = ax.text2D(0.02, 0.95, "", transform=ax.transAxes, fontsize=12, color='white', weight='bold')
ax.text2D(0.02, 0.90, "Mo Phong SAGIN (Real Earth Rotation)", transform=ax.transAxes, fontsize=14, color='white')

ax.scatter([], [], [], c='#00ff00', marker='s', s=40, label='Ground (Da Nang)')
ax.scatter([], [], [], c='#ffff00', marker='^', s=60, label='UAV (Elevated)')
ax.scatter([], [], [], c='#ff0000', marker='o', s=80, label='Satellite')
ax.legend(loc='upper right', facecolor='black', edgecolor='white', labelcolor='white')

dynamic_artists = []

def update(frame):
    for artist in dynamic_artists:
        artist.remove()
    dynamic_artists.clear()
    
    t = frame * DT
    time_text.set_text(f"Time: {t}s (+{t/60:.1f} mins)")
    
    # -- QUAY TRAI DAT --
    # Quay luoi kinh/vi tuyen de the hien Trai Dat dang tu quay
    theta = EARTH_ROT_RATE * t
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    for i, line_ecef in enumerate(grid_lines_ecef):
        x_eci = line_ecef[0] * cos_t - line_ecef[1] * sin_t
        y_eci = line_ecef[0] * sin_t + line_ecef[1] * cos_t
        z_eci = line_ecef[2]
        grid_lines_3d[i].set_data_3d(x_eci, y_eci, z_eci)
    
    graph, positions, link_info = build_topology(
        t, sim.ground_nodes, sim.uav_nodes, sim.sat_nodes
    )
    
    g_x, g_y, g_z = [], [], []
    u_x, u_y, u_z = [], [], []
    s_x, s_y, s_z = [], [], []
    plot_pos = {}
    
    for n_id, pos in positions.items():
        x, y, z = pos[0]/1000.0, pos[1]/1000.0, pos[2]/1000.0
        
        if "G_" in n_id:
            g_x.append(x); g_y.append(y); g_z.append(z)
            plot_pos[n_id] = (x, y, z)
        elif "UAV" in n_id:
            # TRUC QUAN HOA: Day UAV len cao +200km de khong bi trung mau voi mat dat
            norm = np.sqrt(x**2 + y**2 + z**2)
            scale = (norm + 200.0) / norm
            x, y, z = x * scale, y * scale, z * scale
            u_x.append(x); u_y.append(y); u_z.append(z)
            plot_pos[n_id] = (x, y, z)
        elif "SAT" in n_id:
            s_x.append(x); s_y.append(y); s_z.append(z)
            plot_pos[n_id] = (x, y, z)
            
    sc1 = ax.scatter(g_x, g_y, g_z, c='#00ff00', marker='s', s=40, edgecolors='black', linewidth=0.5, zorder=5)
    sc2 = ax.scatter(u_x, u_y, u_z, c='#ffff00', marker='^', s=60, edgecolors='black', linewidth=0.5, zorder=6)
    sc3 = ax.scatter(s_x, s_y, s_z, c='#ff0000', marker='o', s=100, edgecolors='white', linewidth=1.5, zorder=7)
    dynamic_artists.extend([sc1, sc2, sc3])
    
    for edge in graph.edges():
        n1, n2 = edge
        x1, y1, z1 = plot_pos[n1]
        x2, y2, z2 = plot_pos[n2]
        
        if ("G_" in n1 and "UAV" in n2) or ("G_" in n2 and "UAV" in n1):
            line, = ax.plot([x1, x2], [y1, y2], [z1, z2], c='#00ff00', alpha=0.8, linestyle='-', linewidth=1.5)
        else:
            line, = ax.plot([x1, x2], [y1, y2], [z1, z2], c='#ff0000', alpha=0.8, linestyle='-', linewidth=1.5)
        dynamic_artists.append(line)

num_frames = int(DURATION / DT)
ani = animation.FuncAnimation(fig, update, frames=num_frames, interval=50, blit=False)

plt.show()
