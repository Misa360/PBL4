import { createEarth }         from './visualization/earth.js';
import { SimClock }            from './visualization/simClock.js';
import { computeSunAndEarth }  from './visualization/sun.js';
import { checkEclipse, EclipseTracker } from './visualization/eclipse.js';
import { mountEarthOptimizer } from './optimizer/earth-optimizer.js';

let earthOptimizer = null;

// ════════════════════════════════════════════════════════════════
//  SCENE SETUP
// ════════════════════════════════════════════════════════════════
const W = window.innerWidth, H = window.innerHeight;
const scene    = new THREE.Scene();
const camera   = new THREE.PerspectiveCamera(45, W/H, 0.1, 1000);
camera.position.set(0, 0, 3.2);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(W, H);
renderer.toneMapping    = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.2;
document.getElementById('canvas-container').appendChild(renderer.domElement);

const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping   = true;
controls.dampingFactor   = 0.04;
controls.minDistance     = 1.8;
controls.maxDistance     = 8;
controls.autoRotate      = true;
controls.autoRotateSpeed = 0.35;

// ════════════════════════════════════════════════════════════════
//  LIGHTING
// ════════════════════════════════════════════════════════════════
const ambientLight = new THREE.AmbientLight(0x111133, 0.5);
scene.add(ambientLight);

const sunLight = new THREE.DirectionalLight(0xfff0e0, 2.5);
sunLight.position.set(5, 3, 5);
scene.add(sunLight);

const rimLight = new THREE.DirectionalLight(0x3366ff, 0.4);
rimLight.position.set(-5, 0, -3);
scene.add(rimLight);

// ════════════════════════════════════════════════════════════════
//  STARS (Background)
// ════════════════════════════════════════════════════════════════
function buildStarField() {
  const geo  = new THREE.BufferGeometry();
  const count = 8000;
  const pos  = new Float32Array(count * 3);
  const col  = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const r = 400 + Math.random() * 400;
    const theta = Math.random() * Math.PI * 2;
    const phi   = Math.acos(2 * Math.random() - 1);
    pos[i*3]   = r * Math.sin(phi) * Math.cos(theta);
    pos[i*3+1] = r * Math.sin(phi) * Math.sin(theta);
    pos[i*3+2] = r * Math.cos(phi);
    // slight color variation
    const t = Math.random();
    col[i*3]   = 0.8 + t * 0.2;
    col[i*3+1] = 0.85 + t * 0.1;
    col[i*3+2] = 1.0;
  }
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color',    new THREE.BufferAttribute(col, 3));
  const mat  = new THREE.PointsMaterial({ size: 0.22, vertexColors: true, sizeAttenuation: true });
  scene.add(new THREE.Points(geo, mat));
}
buildStarField();

// ════════════════════════════════════════════════════════════════
//  EARTH – dùng module earth.js (texture thực từ ảnh vệ tinh)
//  1 đơn vị = 1 bán kính Trái Đất (R = 6371 km)
// ════════════════════════════════════════════════════════════════

// Xoá ánh sáng cũ – sẽ do earth.js quản lý sunDir
scene.remove(ambientLight);
scene.remove(rimLight);

// currentSunDir cập nhật mỗi frame từ computeSunAndEarth(simClock.date)
// Dùng chung cho DirectionalLight + earthModule.setSunDirection() + eclipse check
const currentSunDir = new THREE.Vector3(1, 0.3, 0).normalize();
sunLight.position.copy(currentSunDir.clone().multiplyScalar(50));

// Ambient rất yếu – phía đêm không đen hoàn toàn
// Ambient yếu – phía đêm vẫn thấy mờ đường viền lục địa (0.4 đủ sáng nhưng không lấn át night lights)
const newAmbient = new THREE.AmbientLight(0x223355, 0.4);
scene.add(newAmbient);


// ════════════════════════════════════════════════════════════════
//  LOADING OVERLAY LOGIC
//  Phải set TRƯỚC khi createEarth() gọi – earth.js sẽ dùng chung
//  THREE.DefaultLoadingManager, nên onLoad/onProgress ở đây sẽ bị
//  earth.js ghi đè một phần. Giải pháp: earth.js gọi lại origProgress.
// ════════════════════════════════════════════════════════════════
const _loadOverlay = document.getElementById('loading-overlay');
const _loadBar     = document.getElementById('loading-bar');
const _loadPct     = document.getElementById('loading-pct');

// Set onProgress TRƯỚC – earth.js sẽ wrap thêm, nhưng vẫn gọi lại hàm này
THREE.DefaultLoadingManager.onProgress = function(url, loaded, total) {
  const pct = Math.round((loaded / total) * 100);
  _loadBar.style.width = pct + '%';
  _loadPct.textContent = pct + '%';
};

// Set onLoad TRƯỚC – earth.js KHÔNG ghi đè onLoad nên an toàn
THREE.DefaultLoadingManager.onLoad = function() {
  console.log('[Loading] Tất cả texture đã tải xong!');
  setTimeout(() => {
    _loadOverlay.classList.add('hidden');
    setTimeout(() => { if(_loadOverlay.parentNode) _loadOverlay.remove(); }, 900);
  }, 400);
};

// Tạo Trái Đất từ module
const earthModule = createEarth(renderer, scene, {
  radius:         1,           // 1 đơn vị = R Trái Đất
  rotationSpeed:  0.00015,     // tốc độ quay mặc định (~1 vòng/24 phút sim)
  cloudSpeed:     0.00022,     // mây quay nhanh hơn bề mặt một chút
  showAtmosphere: true,
  showClouds:     true,
  showNightLights: true,
  textureFolder:  './assets/textures/',  // thư mục chứa file 8K
  debug:          true         // đặt false để tắt chấm đỏ debug
});
const earthGroup = earthModule.group;
earthModule.setSunDirection(currentSunDir);

// ── SimClock ──────────────────────────────────────────────────
const simClock   = new SimClock(new Date(), 1);
const eclTracker = new EclipseTracker();
let   cloudDrift = 0;   // offset tích lũy mây (rad) để drift nhẹ khỏi bề mặt

// ── Subsolar debug marker (chấm vàng dưới chân mặt trời) ──────
// Bật/tắt bằng: subSolarMarker.visible = true/false
const _ssmGeo = new THREE.SphereGeometry(0.018, 12, 12);
const _ssmMat = new THREE.MeshBasicMaterial({ color: 0xffdd00, depthWrite: false });
const subSolarMarker = new THREE.Mesh(_ssmGeo, _ssmMat);
subSolarMarker.name = 'subSolarMarker';
subSolarMarker.visible = true;  // đặt false để tắt
scene.add(subSolarMarker);

// ════════════════════════════════════════════════════════════════
//  ORBITAL RINGS
// ════════════════════════════════════════════════════════════════
const ORBIT_DATA = [
  { radius: 1.30, tilt:  0,   color: 0x00e5ff, opacity: 0.15 },  // LEO 1
  { radius: 1.45, tilt:  28,  color: 0x00e5ff, opacity: 0.12 },  // LEO 2
  { radius: 1.60, tilt:  53,  color: 0x00e5ff, opacity: 0.10 },  // LEO 3
  { radius: 1.75, tilt:  97,  color: 0x7c3aed, opacity: 0.12 },  // MEO
  { radius: 2.10, tilt:  10,  color: 0xf43f5e, opacity: 0.10 },  // GEO
];

const orbitLines = [];
function buildOrbitRings() {
  ORBIT_DATA.forEach(od => {
    const curve = new THREE.EllipseCurve(0,0, od.radius, od.radius, 0, Math.PI*2, false, 0);
    const pts   = curve.getPoints(256);
    const geo   = new THREE.BufferGeometry().setFromPoints(pts);
    const mat   = new THREE.LineBasicMaterial({ color: od.color, transparent: true, opacity: od.opacity });
    const ring  = new THREE.Line(geo, mat);
    ring.rotation.x = Math.PI / 2;
    ring.rotation.z = THREE.MathUtils.degToRad(od.tilt);
    scene.add(ring);
    orbitLines.push(ring);
  });
}
buildOrbitRings();

// ════════════════════════════════════════════════════════════════
//  SATELLITES
// ════════════════════════════════════════════════════════════════
// ── Orbital mechanics ────────────────────────────────────────
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
];

const satObjects = [];

function makeSatMesh(cfg) {
  const geo  = new THREE.SphereGeometry(cfg.size, 8, 8);
  const mat  = new THREE.MeshBasicMaterial({ color: cfg.color });
  const mesh = new THREE.Mesh(geo, mat);

  // Glow sprite
  const sprite = buildGlowSprite(cfg.color, 0.12);
  mesh.add(sprite);
  return mesh;
}

let glowTexture;
function buildGlowSprite(color, size) {
  if (!glowTexture) {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 64;
    const context = canvas.getContext('2d');
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(.2, 'rgba(255,255,255,.5)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, 64, 64);
    glowTexture = new THREE.CanvasTexture(canvas);
  }
  const spriteMat = new THREE.SpriteMaterial({
    map: glowTexture,
    color,
    transparent: true,
    opacity: 0.6,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(spriteMat);
  sprite.scale.setScalar(size);
  return sprite;
}

SAT_CONFIGS.forEach(cfg => {
  const od   = ORBIT_DATA[cfg.orbitIdx];
  const mesh = makeSatMesh(cfg);
  scene.add(mesh);

  const tiltRad = THREE.MathUtils.degToRad(od.tilt);
  satObjects.push({
    mesh, cfg, od, tiltRad,
    inEclipse:   false,   // trạng thái eclipse hiện tại
    _wasEclipse: false,   // trạng thái eclipse frame trước (để cập nhật màu khi thay đổi)
  });
});

// ════════════════════════════════════════════════════════════════
//  UAVs (floating between ground & LEO)
// ════════════════════════════════════════════════════════════════
const UAV_COUNT = 8;
const uavObjects = [];
for (let i = 0; i < UAV_COUNT; i++) {
  const geo  = new THREE.OctahedronGeometry(0.015, 0);
  const mat  = new THREE.MeshBasicMaterial({ color: 0xf59e0b, wireframe: false });
  const mesh = new THREE.Mesh(geo, mat);
  const glow = buildGlowSprite(0xf59e0b, 0.09);
  mesh.add(glow);
  scene.add(mesh);

  const lat = (Math.random() - 0.5) * Math.PI;
  const lon = Math.random() * Math.PI * 2;
  const alt = 1 + 2 / 6371; // UAV reference altitude: 2 km; marker size is exaggerated.
  uavObjects.push({
    mesh,
    lat, lon, alt,
    dLon: (Math.random() - 0.5) * 0.001,
    dLat: (Math.random() - 0.5) * 0.0003,
  });
}

// ════════════════════════════════════════════════════════════════
//  GROUND STATIONS
// ════════════════════════════════════════════════════════════════
const GS_POSITIONS = [
  { lat:  40.7, lon: -74.0,  name: 'New York'    },
  { lat:  51.5, lon:  -0.1,  name: 'London'      },
  { lat:  35.7, lon: 139.7,  name: 'Tokyo'       },
  { lat: -33.9, lon:  18.4,  name: 'Cape Town'   },
  { lat:  28.6, lon:  77.2,  name: 'New Delhi'   },
  { lat: -23.5, lon: -46.6,  name: 'São Paulo'   },
  { lat:  55.8, lon:  37.6,  name: 'Moscow'      },
  { lat:  31.2, lon: 121.5,  name: 'Shanghai'    },
  { lat: -33.9, lon: 151.2,  name: 'Sydney'      },
  { lat:  37.8, lon: -122.4, name: 'San Francisco'},
];

const gsObjects = [];
// Dùng latLonToVec3 từ earthModule để đảm bảo đồng nhất hệ tọa độ
const latLonToVec3 = earthModule.latLonToVec3;

GS_POSITIONS.forEach(gs => {
  const pos  = latLonToVec3(gs.lat, gs.lon, 1.012);
  const geo  = new THREE.CylinderGeometry(0, 0.014, 0.04, 4);
  const mat  = new THREE.MeshBasicMaterial({ color: 0x10b981 });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.copy(pos);
  mesh.lookAt(new THREE.Vector3(0,0,0));
  mesh.rotateX(Math.PI / 2);
  const glow = buildGlowSprite(0x10b981, 0.08);
  mesh.add(glow);

  // pulse ring – gắn vào surface để xoay cùng Trái Đất
  const ringGeo = new THREE.RingGeometry(0.01, 0.025, 16);
  const ringMat = new THREE.MeshBasicMaterial({ color: 0x10b981, transparent: true, opacity: 0.7, side: THREE.DoubleSide });
  const ring    = new THREE.Mesh(ringGeo, ringMat);
  ring.position.copy(pos);
  ring.lookAt(new THREE.Vector3(0,0,0));
  // Gắn vào earthModule.surface để tự xoay theo Trái Đất
  earthModule.surface.add(ring);
  earthModule.surface.add(mesh);
  gsObjects.push({ mesh, ring, ringMat, gs, phase: Math.random() * Math.PI * 2 });
});

// ════════════════════════════════════════════════════════════════
//  COMM LINKS
// ════════════════════════════════════════════════════════════════
const linkLines = [];
let showLinks = false;

function buildLinks() {
  linkLines.forEach(l => { scene.remove(l); l.geometry.dispose(); l.material.dispose(); });
  linkLines.length = 0;
  if (!showLinks) return;

  // Sat-to-Sat (ISL) within same orbit group
  for (let i = 0; i < 18; i += 3) {
    const a = satObjects[i].mesh.position;
    const b = satObjects[i+1].mesh.position;
    addLink(a, b, 0x00e5ff, 0.12);
  }
  // Sat-to-Ground: dùng getWorldPosition vì GS là con của earthModule.surface
  const _tmpVec = new THREE.Vector3();
  gsObjects.forEach((gso, gi) => {
    const si = gi % satObjects.length;
    const a  = satObjects[si].mesh.position;
    gso.mesh.getWorldPosition(_tmpVec);
    addLink(a, _tmpVec.clone(), 0xa78bfa, 0.18);
  });
  // UAV-to-nearest-sat
  uavObjects.forEach((uav, ui) => {
    const si = ui % satObjects.length;
    addLink(uav.mesh.position, satObjects[si].mesh.position, 0xf59e0b, 0.10);
  });
}

function addLink(a, b, color, opacity) {
  const pts = [a.clone(), b.clone()];
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
  const line = new THREE.Line(geo, mat);
  scene.add(line);
  linkLines.push(line);
}

// ════════════════════════════════════════════════════════════════
//  SATELLITE POSITION UPDATE
// ════════════════════════════════════════════════════════════════
// Tính vị trí vệ tinh tuyệt đối từ thời gian mô phỏng (seconds từ J2000)
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
}


// ════════════════════════════════════════════════════════════════
//  HUD STATE
// ════════════════════════════════════════════════════════════════
let showOrbits = true;
let showAtmos  = true;
let autoRotate = true;

document.getElementById('btn-auto').addEventListener('click', () => {
  autoRotate = !autoRotate;
  controls.autoRotate = autoRotate;
  document.getElementById('btn-auto').classList.toggle('active', autoRotate);
});
document.getElementById('btn-orbits').addEventListener('click', () => {
  showOrbits = !showOrbits;
  orbitLines.forEach(l => l.visible = showOrbits);
  document.getElementById('btn-orbits').classList.toggle('active', showOrbits);
});
document.getElementById('btn-links').addEventListener('click', () => {
  showLinks = !showLinks;
  document.getElementById('btn-links').classList.toggle('active', showLinks);
  buildLinks();
});
document.getElementById('btn-atmo').addEventListener('click', () => {
  showAtmos = !showAtmos;
  // Tìm mesh tên 'earthAtmos' trong earthGroup để toggle
  const _atm = earthGroup.getObjectByName('earthAtmos');
  if (_atm) _atm.visible = showAtmos;
  document.getElementById('btn-atmo').classList.toggle('active', showAtmos);
});


// ════════════════════════════════════════════════════════════════
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
// ════════════════════════════════════════════════════════════════
let tick = 0;
function updateHUD() {
  if (earthOptimizer?.active) return;
  tick++;

  const counts={sat:satObjects.length,uav:uavObjects.length,gs:gsObjects.length};
  const total=counts.sat+counts.uav+counts.gs;
  for(const [key,value] of Object.entries(counts)){
    document.getElementById('v-'+key).textContent=value;
    document.getElementById('bar-'+key).style.width=(total?value/total*100:0)+'%';
  }
  document.getElementById('scene-note').textContent=counts.sat+' vệ tinh · '+counts.uav+' UAV · '+counts.gs+' trạm · chỉ cảnh minh họa';

  // Clock (dùng simClock)
  const _hh = String(new Date(simClock._ms).getUTCHours()).padStart(2,'0');
  const _mm = String(new Date(simClock._ms).getUTCMinutes()).padStart(2,'0');
  const _ss = String(new Date(simClock._ms).getUTCSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent = `${_hh}:${_mm}:${_ss} UTC`;
}

// ════════════════════════════════════════════════════════════════
//  RAYCASTER for tooltip
// ════════════════════════════════════════════════════════════════
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
const tooltip = document.getElementById('tooltip');

window.addEventListener('mousemove', e => {
  mouse.x = (e.clientX / window.innerWidth)  * 2 - 1;
  mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
  tooltip.style.left = (e.clientX + 15) + 'px';
  tooltip.style.top  = (e.clientY - 20) + 'px';
});

let hoveredNode = null;
function checkHover() {
  if (earthOptimizer?.active) { tooltip.style.display='none'; hoveredNode=null; return; }
  raycaster.setFromCamera(mouse, camera);
  const allMeshes = [
    ...satObjects.map(s => ({ mesh: s.mesh, label: `${s.cfg.type} Satellite`, type: s.cfg.type, id: s.cfg.id, color: '#00e5ff', altKm: s.cfg.altKm })),
    ...uavObjects.map((u, i) => ({ mesh: u.mesh, label: 'UAV minh họa', type: 'UAV', id: `UAV-${i+1}`, color: '#f59e0b', altKm: 2 })),
    ...gsObjects.map((g, i)  => ({ mesh: g.mesh, label: `Trạm mặt đất`, type: 'GND', name: g.gs.name, id: `GND-0${i+1}`, color: '#10b981', altKm: 0 })),
  ];
  const meshes   = allMeshes.map(o => o.mesh);
  const hits     = raycaster.intersectObjects(meshes, true);
  if (hits.length > 0) {
    const obj  = hits[0].object.parent || hits[0].object;
    hoveredNode = allMeshes.find(o => o.mesh === obj || o.mesh === hits[0].object);
    if (hoveredNode) {
      tooltip.style.display = 'block';
      tooltip.innerHTML = `<strong>${hoveredNode.label}</strong><br>${hoveredNode.name || hoveredNode.id}<br>Đối tượng minh họa · chưa có trạng thái mạng`;
      document.body.style.cursor = 'pointer';
      return;
    }
  }
  hoveredNode = null;
  tooltip.style.display = 'none';
  document.body.style.cursor = 'default';
}

renderer.domElement.addEventListener('click', () => {
  checkHover();
  if (!hoveredNode) return;
  document.getElementById('node-info').style.display = 'block';
  document.getElementById('ni-title').textContent = hoveredNode.name || hoveredNode.id;
  document.getElementById('ni-subtitle').textContent = hoveredNode.label + ' · ' + hoveredNode.id;
  document.getElementById('ni-alt').textContent = Number(hoveredNode.altKm).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' km';
});


// ════════════════════════════════════════════════════════════════
//  ANIMATE
// ════════════════════════════════════════════════════════════════
const clock3 = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const realDt = clock3.getDelta();
  const t      = clock3.getElapsedTime();

  // ── 1. Advance simulation clock ────────────────────────────────
  const simDt = earthOptimizer?.active ? 0 : simClock.update(realDt);

  if (!simClock.paused && !earthOptimizer?.active) {
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
      uav.lon += uav.dLon * realDt * 60;   // per-frame, không phụ thuộc simSpeed
      uav.lat += uav.dLat * realDt * 60;
      if (Math.abs(uav.lat) > Math.PI / 2.5) uav.dLat *= -1;
      const pos = latLonToVec3(
        THREE.MathUtils.radToDeg(uav.lat),
        THREE.MathUtils.radToDeg(uav.lon),
        uav.alt
      );
      uav.mesh.position.copy(pos);
      uav.mesh.rotation.y += 1.2 * realDt;
    });
  }

  // ── 6. Ground station pulse (chạy theo real time) ─────────────
  gsObjects.forEach((gs) => {
    const p = gs.phase + t * 2;
    gs.ring.scale.setScalar(1 + 0.5 * Math.sin(p));
    gs.ringMat.opacity = 0.5 + 0.3 * Math.sin(p);
  });

  // ── 7. Comm links ─────────────────────────────────────────────

  if (showLinks && !earthOptimizer?.active) buildLinks();


  // ── 8. Hover + controls + HUD ─────────────────────────────────
  checkHover();
  controls.update();
  earthOptimizer?.tick(performance.now());
  if (tick % 30 === 0) {
    updateHUD();
    updateSimClockUI();
    updateEclipseHUD();
  }
  tick++;

  renderer.render(scene, camera);
}

// ════════════════════════════════════════════════════════════════
//  RESIZE
// ════════════════════════════════════════════════════════════════
window.addEventListener('resize', () => {
  const w = window.innerWidth, h = window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  earthOptimizer?.resize();
});

// Initial HUD
let illustrationState = null;
earthOptimizer = mountEarthOptimizer({ scene, camera, controls, renderer, setMode(active) {
  const objects=[...satObjects.map(o=>o.mesh),...uavObjects.map(o=>o.mesh),...gsObjects.flatMap(o=>[o.mesh,o.ring]),...orbitLines,...linkLines,subSolarMarker,...earthModule.surface.children.filter(o=>o.name.startsWith('debug_'))];
  const clouds=earthGroup.getObjectByName('earthClouds');
  if(active){
    illustrationState={paused:simClock.paused,position:camera.position.clone(),target:controls.target.clone(),autoRotate:controls.autoRotate,
      minDistance:controls.minDistance,maxDistance:controls.maxDistance,near:camera.near,far:camera.far,view:camera.view?{...camera.view}:null,
      surfaceRotation:earthModule.surface.rotation.y,cloudRotation:clouds?.rotation.y,
      sceneNote:document.getElementById('scene-note').textContent,subtitle:document.querySelector('#topbar .subtitle').textContent,
      statsTitle:document.querySelector('#stats-panel h3').textContent,uavLabel:document.querySelectorAll('.stat-label')[1].textContent,
      objects:objects.map(object=>[object,object.visible])};
    simClock.paused=true;controls.autoRotate=false;objects.forEach(object=>object.visible=false);
    earthModule.surface.rotation.y=0;if(clouds)clouds.rotation.y=0;
    document.querySelector('#topbar .subtitle').textContent='Đường truyền và pin · đồng bộ mạng mô phỏng';
    document.querySelector('#stats-panel h3').textContent='Thành phần mạng mô phỏng';document.querySelectorAll('.stat-label')[1].textContent='UAV trung chuyển';
    document.getElementById('node-info').style.display='none';
  }else if(illustrationState){
    const saved=illustrationState;saved.objects.forEach(([object,visible])=>object.visible=visible);
    simClock.paused=saved.paused;camera.position.copy(saved.position);controls.target.copy(saved.target);controls.autoRotate=saved.autoRotate;
    controls.minDistance=saved.minDistance;controls.maxDistance=saved.maxDistance;camera.near=saved.near;camera.far=saved.far;camera.updateProjectionMatrix();
    if(saved.view?.enabled){const v=saved.view;camera.setViewOffset(v.fullWidth,v.fullHeight,v.offsetX,v.offsetY,v.width,v.height);}else camera.clearViewOffset();
    earthModule.surface.rotation.y=saved.surfaceRotation;if(clouds)clouds.rotation.y=saved.cloudRotation;
    document.getElementById('scene-note').textContent=saved.sceneNote;document.querySelector('#topbar .subtitle').textContent=saved.subtitle;
    document.querySelector('#stats-panel h3').textContent=saved.statsTitle;document.querySelectorAll('.stat-label')[1].textContent=saved.uavLabel;
    controls.update();updateHUD();
  }
} });
updateHUD();
animate();
