import vpython as vp
import numpy as np

from simulation import SAGINSimulation
from topology import build_topology
from orbital import EARTH_ROT_RATE

# Thiet lap cac thong so mo phong
CENTER_LAT = 16.0544
CENTER_LON = 108.2022
DURATION = 11800 
DT = 30         

sim = SAGINSimulation(
    center_lat=CENTER_LAT, center_lon=CENTER_LON,
    n_ground_rows=2, n_ground_cols=2, ground_spacing_m=2000.0,
    n_uav=4, uav_radius_m=3000.0, uav_altitude_m=2000.0,
    n_sat=3, sat_altitude_km=550.0, sat_inclination_deg=53.0,
    duration_s=DURATION, dt_s=DT
)

RE_km = 6371.0

# 1. KHOI TAO GIAO DIEN VPYTHON (Mo trong trinh duyet)
vp.scene.title = "<b>Mo phong SAGIN (Earth & Space) - VPython</b>"
vp.scene.width = 1200
vp.scene.height = 800
vp.scene.background = vp.color.black
vp.scene.camera.pos = vp.vector(RE_km + 4000, RE_km + 4000, 3000)
vp.scene.camera.axis = -vp.scene.camera.pos

# 2. LOAD TRAI DAT (Su dung hinh anh map Trai Dat thuc te)
# VPython ho tro san thu vien texture trai dat rat dep
earth = vp.sphere(pos=vp.vector(0, 0, 0), radius=RE_km, texture=vp.textures.earth)

# 3. KHOI TAO DOI TUONG (NODE)
sat_objs = {}
uav_objs = {}
ground_objs = {}
link_curves = []

# Ve tinh (Mau do, co duong base trail theo sau)
for sat in sim.sat_nodes:
    sat_objs[sat.node_id] = vp.sphere(radius=150, color=vp.color.red, 
                                      make_trail=True, trail_radius=20, 
                                      trail_color=vp.color.white, retain=200)

# UAV (Mau vang, day do cao len 1 xiu de nhin ro hon mat dat)
for uav in sim.uav_nodes:
    uav_objs[uav.node_id] = vp.cone(radius=80, axis=vp.vector(0,0,150), color=vp.color.yellow)

# Mat dat (Hinh vuong mau xanh)
for g in sim.ground_nodes:
    ground_objs[g.node_id] = vp.box(length=120, width=120, height=120, color=vp.color.green)

time_label = vp.label(pos=vp.vector(0, RE_km + 3000, 0), text='Time: 0s', box=False, height=20)

print("Dang chay mo phong VPython... Vui long mo trinh duyet de xem!")

# 4. VONG LAP MO PHONG
t = 0
while t <= DURATION:
    vp.rate(20) # Chay toi da 20 khung hinh / giay (Tang giam de thay doi toc do xem)
    
    # Xoay Trai Dat (Quay quanh truc Z) de mat map khop voi he toa do ECI
    # Trai dat quay 1 goc bang EARTH_ROT_RATE * DT moi khung hinh
    earth.rotate(angle=EARTH_ROT_RATE * DT, axis=vp.vector(0, 0, 1), origin=vp.vector(0, 0, 0))
    
    time_label.text = f'Time: {t}s (+{t/60:.1f} mins)'
    
    # Tinh toan mang
    graph, positions, link_info = build_topology(
        t, sim.ground_nodes, sim.uav_nodes, sim.sat_nodes
    )
    
    # Cap nhat vi tri cac node (He toa do cua VPython la (x, y, z))
    for n_id, pos in positions.items():
        x, y, z = pos[0]/1000.0, pos[1]/1000.0, pos[2]/1000.0
        v_pos = vp.vector(x, y, z)
        
        if "G_" in n_id:
            ground_objs[n_id].pos = v_pos
            # Dat box huong thang len troi
            ground_objs[n_id].axis = v_pos
        elif "UAV" in n_id:
            # Day len 200km giong truoc de nhin tach biet mat dat
            norm = np.sqrt(x**2 + y**2 + z**2)
            scale = (norm + 200.0) / norm
            uav_objs[n_id].pos = vp.vector(x*scale, y*scale, z*scale)
            uav_objs[n_id].axis = uav_objs[n_id].pos # Huong mui nhon ra ngoai
        elif "SAT" in n_id:
            sat_objs[n_id].pos = v_pos

    # Xoa cac duong link cu
    for curve in link_curves:
        curve.visible = False
    link_curves.clear()
    
    # Ve cac duong link moi
    for edge in graph.edges():
        n1, n2 = edge
        pos1 = ground_objs[n1].pos if "G_" in n1 else (uav_objs[n1].pos if "UAV" in n1 else sat_objs[n1].pos)
        pos2 = ground_objs[n2].pos if "G_" in n2 else (uav_objs[n2].pos if "UAV" in n2 else sat_objs[n2].pos)
        
        # Ground <-> UAV: Xanh la, UAV <-> SAT: Do
        line_color = vp.color.green if ("G_" in n1 or "G_" in n2) else vp.color.red
        c = vp.curve(pos=[pos1, pos2], color=line_color, radius=15)
        link_curves.append(c)
        
    t += DT
