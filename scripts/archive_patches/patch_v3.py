"""
patch_v3.py – Patch toàn diện earth_simulation.html với:
A. SimClock UI (đồng hồ mô phỏng)
B. Mặt trời theo giờ UTC thật
C. Eclipse detection
D. Quỹ đạo vật lý Kepler
0. Dọn dẹp (ambient light, night shader, depthTest)
"""
import re

with open('earth_simulation.html', encoding='utf-8') as f:
    c = f.read()

ok = []
fail = []

def rep(old, new, tag):
    global c
    if old in c:
        c = c.replace(old, new, 1)
        ok.append(f'✓ {tag}')
    else:
        fail.append(f'✗ {tag}  (not found)')

# ═════════════════════════════════════════════════════════════════
#  0. CSS mới (thêm trước </style>)
# ═════════════════════════════════════════════════════════════════
NEW_CSS = """
    /* ── SimClock panel ────────────────────────────────────── */
    #sim-clock {
      position: absolute;
      bottom: 64px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(0,8,30,.88);
      border: 1px solid rgba(0,200,255,.35);
      border-radius: 14px;
      padding: 14px 22px 12px;
      backdrop-filter: blur(10px);
      pointer-events: all;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      min-width: 420px;
      z-index: 20;
    }
    #sim-clock-display {
      font-family: 'Orbitron', sans-serif;
      font-size: .9rem;
      color: #00e5ff;
      letter-spacing: 3px;
      text-shadow: 0 0 12px #00e5ff88;
    }
    #sim-clock-row {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
    }
    #sim-clock-hour-wrap {
      display: flex;
      align-items: center;
      gap: 6px;
      flex: 1;
    }
    #sim-clock-hour-label {
      font-size: .7rem;
      color: #7ecfff;
      white-space: nowrap;
    }
    #sim-hour-slider {
      flex: 1;
      height: 3px;
      accent-color: #00e5ff;
      cursor: pointer;
    }
    #sim-clock-date {
      background: rgba(0,200,255,.1);
      border: 1px solid rgba(0,200,255,.3);
      border-radius: 6px;
      color: #00e5ff;
      font-family: 'Rajdhani', sans-serif;
      font-size: .75rem;
      padding: 3px 6px;
      cursor: pointer;
    }
    #sim-clock-btns {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .sc-btn {
      background: rgba(0,200,255,.12);
      border: 1px solid rgba(0,200,255,.3);
      border-radius: 8px;
      color: #00e5ff;
      font-family: 'Rajdhani', sans-serif;
      font-size: .75rem;
      letter-spacing: 1px;
      padding: 4px 12px;
      cursor: pointer;
      transition: all .2s;
    }
    .sc-btn:hover { background: rgba(0,200,255,.25); }
    .sc-btn.active { background: rgba(0,200,255,.3); border-color: #00e5ff; }
    #sim-speed-sel {
      background: rgba(0,8,30,.9);
      border: 1px solid rgba(0,200,255,.3);
      border-radius: 8px;
      color: #00e5ff;
      font-family: 'Rajdhani', sans-serif;
      font-size: .78rem;
      padding: 3px 8px;
      cursor: pointer;
    }

    /* ── Eclipse HUD ────────────────────────────────────────── */
    #eclipse-hud {
      position: absolute;
      top: 80px; right: 20px;
      margin-top: 8px;
      background: rgba(0,8,30,.75);
      border: 1px solid rgba(244,63,94,.35);
      border-radius: 12px;
      padding: 14px 18px;
      backdrop-filter: blur(8px);
      min-width: 200px;
      display: none; /* hiện khi có eclipse */
    }
    #eclipse-hud.visible { display: block; }
    #eclipse-hud h3 {
      font-family: 'Orbitron', sans-serif;
      font-size: .65rem;
      color: #f87171;
      letter-spacing: 2px;
      margin-bottom: 10px;
    }
    #eclipse-summary {
      font-size: .75rem;
      color: #fca5a5;
      margin-bottom: 8px;
    }
    #eclipse-list { font-size: .7rem; color: #fca5a5; line-height: 1.7; }
"""
rep('  </style>', NEW_CSS + '  </style>', 'CSS mới (SimClock + Eclipse HUD)')

# ═════════════════════════════════════════════════════════════════
#  1. HTML panels (thêm trước </div> đóng hud)
# ═════════════════════════════════════════════════════════════════
NEW_HTML_PANELS = """
  <!-- SimClock panel -->
  <div id="sim-clock">
    <div id="sim-clock-display">2024-01-01 12:00:00 UTC</div>
    <div id="sim-clock-row">
      <div id="sim-clock-hour-wrap">
        <span id="sim-clock-hour-label">0h</span>
        <input type="range" id="sim-hour-slider" min="0" max="24" step="0.01" value="12">
        <span id="sim-clock-hour-label-r">24h</span>
      </div>
      <input type="date" id="sim-clock-date">
    </div>
    <div id="sim-clock-btns">
      <button class="sc-btn active" id="sc-playpause">⏸ Pause</button>
      <button class="sc-btn" id="sc-now">⟳ Now</button>
      <select id="sim-speed-sel">
        <option value="1">1×</option>
        <option value="60">60×</option>
        <option value="600" selected>600×</option>
        <option value="3600">3600×</option>
        <option value="21600">21600×</option>
      </select>
    </div>
  </div>

  <!-- Eclipse HUD (top right, below legend) -->
  <div id="eclipse-hud">
    <h3>⬡ ECLIPSE STATUS</h3>
    <div id="eclipse-summary">In shadow: 0 / 0</div>
    <div id="eclipse-list"></div>
  </div>

"""
rep('  <div id="tooltip"></div>', NEW_HTML_PANELS + '  <div id="tooltip"></div>', 'HTML panels')

# ═════════════════════════════════════════════════════════════════
#  2. Imports module mới
# ═════════════════════════════════════════════════════════════════
rep(
    "import { createEarth } from './earth.js';",
    """import { createEarth }         from './earth.js';
import { SimClock }            from './simClock.js';
import { computeSunAndEarth }  from './sun.js';
import { checkEclipse, EclipseTracker } from './eclipse.js';""",
    'Imports'
)

# ═════════════════════════════════════════════════════════════════
#  3. Fix ambient light
# ═════════════════════════════════════════════════════════════════
rep(
    'const newAmbient = new THREE.AmbientLight(0x0a1a3a, 0.25);',
    '// Ambient yếu – phía đêm vẫn thấy mờ đường viền lục địa (0.4 đủ sáng nhưng không lấn át night lights)\nconst newAmbient = new THREE.AmbientLight(0x223355, 0.4);',
    'Ambient light 0x223355 / 0.4'
)

# ═════════════════════════════════════════════════════════════════
#  4. Thay SUN_DIR bằng biến mutable (sẽ cập nhật từ SimClock)
# ═════════════════════════════════════════════════════════════════
rep(
    """// Ánh sáng mặt trời chính (sunDir dùng chung với earth.js)
// earth.js khởi tạo sunDir = (1, 0.3, 0.5).normalize() – phải đồng bộ với sunLight
const SUN_DIR = new THREE.Vector3(1, 0.3, 0.5).normalize();
sunLight.position.copy(SUN_DIR.clone().multiplyScalar(50));
console.log('[Main] SUN_DIR:', SUN_DIR.x.toFixed(2), SUN_DIR.y.toFixed(2), SUN_DIR.z.toFixed(2));""",
    """// currentSunDir cập nhật mỗi frame từ computeSunAndEarth(simClock.date)
// Dùng chung cho DirectionalLight + earthModule.setSunDirection() + eclipse check
const currentSunDir = new THREE.Vector3(1, 0.3, 0).normalize();
sunLight.position.copy(currentSunDir.clone().multiplyScalar(50));""",
    'Replace SUN_DIR → currentSunDir'
)

# ═════════════════════════════════════════════════════════════════
#  5. Sau earthModule setup: thêm SimClock, EclipseTracker, debug marker
# ═════════════════════════════════════════════════════════════════
rep(
    """const earthGroup = earthModule.group;
earthModule.setSunDirection(SUN_DIR);""",
    """const earthGroup = earthModule.group;
earthModule.setSunDirection(currentSunDir);

// ── SimClock ──────────────────────────────────────────────────
const simClock   = new SimClock(new Date(), 600);
const eclTracker = new EclipseTracker();
let   cloudDrift = 0;   // offset tích lũy mây (rad) để drift nhẹ khỏi bề mặt

// ── Subsolar debug marker (chấm vàng dưới chân mặt trời) ──────
// Bật/tắt bằng: subSolarMarker.visible = true/false
const _ssmGeo = new THREE.SphereGeometry(0.018, 12, 12);
const _ssmMat = new THREE.MeshBasicMaterial({ color: 0xffdd00, depthWrite: false });
const subSolarMarker = new THREE.Mesh(_ssmGeo, _ssmMat);
subSolarMarker.name = 'subSolarMarker';
subSolarMarker.visible = true;  // đặt false để tắt
scene.add(subSolarMarker);""",
    'SimClock + EclipseTracker + subsolar marker'
)

# ═════════════════════════════════════════════════════════════════
#  6. Thay SAT_CONFIGS → thêm id, period Kepler, initialPhase
# ═════════════════════════════════════════════════════════════════
rep(
    """const SAT_CONFIGS = [
  // LEO constellation – cyan
  ...Array.from({length:18}, (_,i) => ({
    type: 'LEO', orbitIdx: i%3,
    phase: (i/18)*Math.PI*2,
    speed: 0.0008 + (i%3)*0.0001,
    color: 0x00e5ff, size: 0.018,
  })),
  // MEO – purple
  ...Array.from({length:6}, (_,i) => ({
    type: 'MEO', orbitIdx: 3,
    phase: (i/6)*Math.PI*2,
    speed: 0.0004,
    color: 0x7c3aed, size: 0.022,
  })),
  // GEO – red-pink
  ...Array.from({length:4}, (_,i) => ({
    type: 'GEO', orbitIdx: 4,
    phase: (i/4)*Math.PI*2,
    speed: 0.0001,
    color: 0xf43f5e, size: 0.026,
  })),
];""",
    """// ── Orbital mechanics ────────────────────────────────────────
// T = 2π√(a³/μ) với a (m), μ = 3.986004418e14 m³/s²
const MU_EARTH   = 3.986004418e14;
const R_EARTH_M  = 6.371e6;
function keplerPeriod(altKm) {
  const a = R_EARTH_M + altKm * 1e3;
  return 2 * Math.PI * Math.sqrt(a * a * a / MU_EARTH);
}
// Thời gian mô phỏng (giây) từ J2000 epoch (2000-01-01T12:00:00Z)
// simClock.simSec dùng cùng epoch

const SAT_CONFIGS = [
  // LEO 550km – T ≈ 5730s (≈95 phút)
  ...Array.from({length:18}, (_,i) => ({
    id: `LEO-${i+1}`, type: 'LEO', orbitIdx: i%3,
    initialPhase: (i/18)*Math.PI*2,
    period: keplerPeriod(550),       // ~5730s
    altKm: 550,
    color: 0x00e5ff, size: 0.018,
  })),
  // MEO 20200km – T ≈ 43082s (≈11.97h, GPS-like)
  ...Array.from({length:6}, (_,i) => ({
    id: `MEO-${i+1}`, type: 'MEO', orbitIdx: 3,
    initialPhase: (i/6)*Math.PI*2,
    period: keplerPeriod(20200),     // ~43082s
    altKm: 20200,
    color: 0x7c3aed, size: 0.022,
  })),
  // GEO 35786km – T = 86400s (solar day, đứng yên so với mặt đất trong model này)
  ...Array.from({length:4}, (_,i) => ({
    id: `GEO-${i+1}`, type: 'GEO', orbitIdx: 4,
    initialPhase: (i/4)*Math.PI*2,
    period: 86400,                   // solar day → geosynchronous trong model sunDir
    altKm: 35786,
    color: 0xf43f5e, size: 0.026,
  })),
];""",
    'SAT_CONFIGS: thêm id + period Kepler'
)

# ═════════════════════════════════════════════════════════════════
#  7. Thay satObjects push → thêm tracking fields
# ═════════════════════════════════════════════════════════════════
rep(
    "  satObjects.push({ mesh, cfg, od, tiltRad, angle: cfg.phase });",
    """  satObjects.push({
    mesh, cfg, od, tiltRad,
    inEclipse:   false,   // trạng thái eclipse hiện tại
    _wasEclipse: false,   // trạng thái eclipse frame trước (để cập nhật màu khi thay đổi)
  });""",
    'satObjects fields + eclipse tracking'
)

# ═════════════════════════════════════════════════════════════════
#  8. Thay updateSatellitePositions → dùng simSec tuyệt đối
# ═════════════════════════════════════════════════════════════════
rep(
    """function updateSatellitePositions(speed) {
  satObjects.forEach(so => {
    so.angle += so.cfg.speed * speed;
    const r    = so.od.radius;
    const x    = r * Math.cos(so.angle);
    const z    = r * Math.sin(so.angle);
    // apply tilt around Z axis
    const sinT = Math.sin(so.tiltRad);
    const cosT = Math.cos(so.tiltRad);
    so.mesh.position.set(
      x * cosT,
      z * sinT,
      x * sinT * (-1) + z * cosT * 0   // simplified planar orbit
    );
    // proper spherical orbit with inclination
    so.mesh.position.set(
      r * Math.cos(so.angle),
      r * Math.sin(so.angle) * Math.sin(so.tiltRad),
      r * Math.sin(so.angle) * Math.cos(so.tiltRad)
    );
  });
}""",
    """// Tính vị trí vệ tinh tuyệt đối từ thời gian mô phỏng (seconds từ J2000)
// angle = initialPhase + (2π/T) * simSec  →  time-scrubbing hoạt động đúng
function updateSatellitePositions(simSec) {
  const TWO_PI = Math.PI * 2;
  satObjects.forEach(so => {
    const angle = so.cfg.initialPhase + (TWO_PI / so.cfg.period) * simSec;
    const r = so.od.radius;
    // Quỹ đạo nghiêng: Y = sin(angle)*sin(tilt), Z = sin(angle)*cos(tilt)
    so.mesh.position.set(
      r * Math.cos(angle),
      r * Math.sin(angle) * Math.sin(so.tiltRad),
      r * Math.sin(angle) * Math.cos(so.tiltRad)
    );
  });
}""",
    'updateSatellitePositions: absolute from simSec'
)

# ═════════════════════════════════════════════════════════════════
#  9. HUD state: thay simSpeed bằng link qua simClock.timeScale
# ═════════════════════════════════════════════════════════════════
rep(
    "let simSpeed = 1;",
    "// simSpeed được thay bằng simClock.timeScale (set qua #sim-speed-sel)\n// Giữ lại biến để tương thích với btn-speed cũ\nlet simSpeed = 600;",
    'simSpeed → 600 default (compat)'
)

# ═════════════════════════════════════════════════════════════════
#  10. Thay btn-speed handler → link về simClock
# ═════════════════════════════════════════════════════════════════
rep(
    """document.getElementById('btn-speed').addEventListener('click', function() {
  const speeds = [1, 2, 5, 10];
  const cur  = speeds.indexOf(simSpeed);
  simSpeed   = speeds[(cur + 1) % speeds.length];
  this.textContent = `▶ ${simSpeed}×`;
});""",
    """// btn-speed cũ → chuyển sang dùng #sim-speed-sel trong SimClock UI
// Giữ lại để không lỗi, nhưng giờ chỉ hiển thị tốc độ hiện tại
document.getElementById('btn-speed').addEventListener('click', function() {
  // Mở SimClock panel nếu cần
  document.getElementById('sim-clock').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});""",
    'btn-speed → redirect'
)

# ═════════════════════════════════════════════════════════════════
#  11. Thêm SimClock UI handlers sau các handlers hiện có
# ═════════════════════════════════════════════════════════════════
rep(
    """// ════════════════════════════════════════════════════════════════
//  STATS HUD UPDATE
// ════════════════════════════════════════════════════════════════""",
    """// ════════════════════════════════════════════════════════════════
//  SIM CLOCK UI
// ════════════════════════════════════════════════════════════════
document.getElementById('sc-playpause').addEventListener('click', function() {
  simClock.togglePause();
  this.textContent = simClock.paused ? '▶ Play' : '⏸ Pause';
  this.classList.toggle('active', !simClock.paused);
});

document.getElementById('sc-now').addEventListener('click', () => {
  simClock.setNow();
  syncClockUI();
});

document.getElementById('sim-speed-sel').addEventListener('change', function() {
  simClock.timeScale = Number(this.value);
  simSpeed = simClock.timeScale;
  document.getElementById('btn-speed').textContent = `▶ ${this.value}×`;
});

document.getElementById('sim-hour-slider').addEventListener('input', function() {
  simClock.setHour(Number(this.value));
  syncClockUI();
});

document.getElementById('sim-clock-date').addEventListener('change', function() {
  simClock.setDateStr(this.value);
  syncClockUI();
});

function syncClockUI() {
  const h = simClock.utcHour;
  document.getElementById('sim-hour-slider').value = h;
  document.getElementById('sim-clock-date').value  = simClock.dateInputValue;
}

function updateSimClockUI() {
  document.getElementById('sim-clock-display').textContent = simClock.utcString;
  // Cập nhật slider giờ (không làm gián đoạn khi đang kéo)
  if (document.activeElement !== document.getElementById('sim-hour-slider')) {
    document.getElementById('sim-hour-slider').value = simClock.utcHour;
  }
}

function updateEclipseHUD() {
  const inEcl = satObjects.filter(so => so.inEclipse);
  const hud   = document.getElementById('eclipse-hud');
  if (inEcl.length === 0) {
    hud.classList.remove('visible');
    return;
  }
  hud.classList.add('visible');
  document.getElementById('eclipse-summary').textContent
    = `In shadow: ${inEcl.length} / ${satObjects.length}`;
  const top5 = inEcl.slice(0, 5);
  document.getElementById('eclipse-list').innerHTML
    = top5.map(so => {
        const e = eclTracker.getSatelliteEnergyState(so.cfg.id);
        const pct = (e.sunlitFraction * 100).toFixed(0);
        return `🌑 ${so.cfg.id} &nbsp; <span style="color:#6ee7b7">${pct}% lit</span>`;
      }).join('<br>');
}

// Khởi tạo UI giá trị ban đầu
syncClockUI();
document.getElementById('sim-clock-display').textContent = simClock.utcString;

// ════════════════════════════════════════════════════════════════
//  STATS HUD UPDATE
// ════════════════════════════════════════════════════════════════""",
    'SimClock UI handlers'
)

# ═════════════════════════════════════════════════════════════════
#  12. updateHUD: đổi clock để dùng simClock
# ═════════════════════════════════════════════════════════════════
rep(
    """  // Clock
  const now = new Date();
  const h = String(now.getUTCHours()).padStart(2,'0');
  const m = String(now.getUTCMinutes()).padStart(2,'0');
  const s = String(now.getUTCSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent = `${h}:${m}:${s} UTC`;""",
    """  // Clock (dùng simClock)
  const _hh = String(new Date(simClock._ms).getUTCHours()).padStart(2,'0');
  const _mm = String(new Date(simClock._ms).getUTCMinutes()).padStart(2,'0');
  const _ss = String(new Date(simClock._ms).getUTCSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent = `${_hh}:${_mm}:${_ss} UTC`;""",
    'updateHUD clock → simClock'
)

# ═════════════════════════════════════════════════════════════════
#  13. Thay toàn bộ animate() function
# ═════════════════════════════════════════════════════════════════
rep(
    """function animate() {
  requestAnimationFrame(animate);
  const dt = clock3.getDelta();
  const t  = clock3.getElapsedTime();

  // Cập nhật Trái Đất (xoay bề mặt, mây, và shader khí quyển)
  earthModule.update(simSpeed);

  // Satellites
  updateSatellitePositions(simSpeed);

  // UAVs
  uavObjects.forEach(uav => {
    uav.lon += uav.dLon * simSpeed;
    uav.lat += uav.dLat * simSpeed;
    if (Math.abs(uav.lat) > Math.PI / 2.5) uav.dLat *= -1;
    const pos = latLonToVec3(
      THREE.MathUtils.radToDeg(uav.lat),
      THREE.MathUtils.radToDeg(uav.lon),
      uav.alt
    );
    uav.mesh.position.copy(pos);
    uav.mesh.rotation.y += 0.02 * simSpeed;
  });

  // Ground station pulse (ring là con của surface nên scale/opacity vẫn đúng)
  gsObjects.forEach((gs, i) => {
    const p = gs.phase + t * 2;
    gs.ring.scale.setScalar(1 + 0.5 * Math.sin(p));
    gs.ringMat.opacity = 0.5 + 0.3 * Math.sin(p);
  });


  // Links (rebuild each frame for moving endpoints)
  if (showLinks) buildLinks();

  checkHover();
  controls.update();
  if (tick % 30 === 0) updateHUD();
  tick++;

  renderer.render(scene, camera);
}""",
    """function animate() {
  requestAnimationFrame(animate);
  const realDt = clock3.getDelta();
  const t      = clock3.getElapsedTime();

  // ── 1. Advance simulation clock ────────────────────────────────
  const simDt = simClock.update(realDt);

  if (!simClock.paused) {
    // ── 2. Sun + Earth rotation từ giờ UTC mô phỏng ─────────────
    const sunState = computeSunAndEarth(simClock.date);
    currentSunDir.copy(sunState.sunDir);

    // Cập nhật DirectionalLight
    sunLight.position.copy(sunState.sunDir.clone().multiplyScalar(50));

    // Cập nhật earthModule shaders (nightmap uSun, atmosphere uSun)
    earthModule.setSunDirection(sunState.sunDir);

    // Đặt góc quay bề mặt TUYỆT ĐỐI (không tích lũy) → time-scrub hoạt động
    earthModule.surface.rotation.y = sunState.earthRotY;

    // Mây drift nhẹ (cloudDrift tích lũy theo simDt)
    cloudDrift += 5e-6 * simDt;
    const _cloudMesh = earthGroup.getObjectByName('earthClouds');
    if (_cloudMesh) _cloudMesh.rotation.y = sunState.earthRotY + cloudDrift;

    // Subsolar marker (chấm vàng)
    subSolarMarker.position.copy(sunState.subsolarWorld);

    // ── 3. Satellites: vị trí từ simSec tuyệt đối ────────────────
    const simSec = simClock.simSec;
    updateSatellitePositions(simSec);

    // ── 4. Eclipse detection ──────────────────────────────────────
    satObjects.forEach(so => {
      const inEcl = checkEclipse(so.mesh.position, currentSunDir, 1.0);
      eclTracker.update(so.cfg.id, inEcl, simDt);

      // Chỉ cập nhật màu khi trạng thái thay đổi (tiết kiệm GPU)
      if (inEcl !== so._wasEclipse) {
        so._wasEclipse = inEcl;
        const baseCol = new THREE.Color(so.cfg.color);
        if (inEcl) baseCol.multiplyScalar(0.35);   // giảm 35% khi trong bóng
        so.mesh.material.color.copy(baseCol);
        // Cập nhật glow sprite opacity
        so.mesh.children.forEach(child => {
          if (child.isSprite) child.material.opacity = inEcl ? 0.12 : 0.6;
        });
      }
      so.inEclipse = inEcl;
    });

    // ── 5. UAVs (dùng realDt để tốc độ visual ổn định) ───────────
    uavObjects.forEach(uav => {
      uav.lon += uav.dLon;   // per-frame, không phụ thuộc simSpeed
      uav.lat += uav.dLat;
      if (Math.abs(uav.lat) > Math.PI / 2.5) uav.dLat *= -1;
      const pos = latLonToVec3(
        THREE.MathUtils.radToDeg(uav.lat),
        THREE.MathUtils.radToDeg(uav.lon),
        uav.alt
      );
      uav.mesh.position.copy(pos);
      uav.mesh.rotation.y += 0.02;
    });
  }

  // ── 6. Ground station pulse (chạy theo real time) ─────────────
  gsObjects.forEach((gs) => {
    const p = gs.phase + t * 2;
    gs.ring.scale.setScalar(1 + 0.5 * Math.sin(p));
    gs.ringMat.opacity = 0.5 + 0.3 * Math.sin(p);
  });

  // ── 7. Comm links ─────────────────────────────────────────────
  if (showLinks) buildLinks();

  // ── 8. Hover + controls + HUD ─────────────────────────────────
  checkHover();
  controls.update();
  if (tick % 30 === 0) {
    updateHUD();
    updateSimClockUI();
    updateEclipseHUD();
  }
  tick++;

  renderer.render(scene, camera);
}""",
    'animate() refactor toàn diện'
)

# ═════════════════════════════════════════════════════════════════
#  Ghi file
# ═════════════════════════════════════════════════════════════════
with open('earth_simulation.html', 'w', encoding='utf-8') as f:
    f.write(c)

print('\n'.join(ok))
if fail:
    print('\nFAILED:')
    print('\n'.join(fail))
print(f'\nTotal: {len(ok)} OK, {len(fail)} FAIL')
