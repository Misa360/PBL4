/**
 * sun.js – Tính hướng mặt trời và góc quay Trái Đất theo giờ UTC
 *
 * Hệ quy chiếu world (ECI – quán tính, không xoay theo Trái Đất):
 *   +X = hướng kinh độ 0° (Greenwich) khi surfaceMesh.rotation.y = 0
 *   +Y = hướng Bắc địa lý
 *   Trái Đất xoay theo Y (eastward)
 *
 * Công thức (sai số < 1°, đủ cho mô phỏng SAGIN):
 *   n      = ngày thứ trong năm (1..366)
 *   δ      = -23.44° × cos(2π/365 × (n + 10))     [Declination]
 *   L☉     = -15 × (utcH - 12)                     [Subsolar longitude, °E]
 *
 * Dẫn xuất earthRotY:
 *   Điểm bề mặt tại lat=0, lon=L trong body frame có vị trí local:
 *     (cos(L°), 0, -sin(L°))
 *   Sau khi surfaceMesh.rotation.y = θ (Three.js Y-rotation):
 *     world_pos = (cos(θ+L°), 0, -sin(θ+L°))
 *   Để điểm L☉ chỉ về sunDir (+X, decl=0):
 *     cos(θ + L☉) = 1  →  θ = -L☉  →  earthRotY = -subsolarLon_rad
 *   Kiểm tra: noon UTC (L☉=0°) → θ=0, lon=0° ở +X ✓
 *             06h UTC (L☉=90°E) → θ=-π/2, lon=90°E xoay ra +X ✓
 *             05h UTC (L☉=105°E) → Đà Nẵng 108.2°E cách 3.2° ≈ 13 phút ✓
 *
 * sunDir trong world space:
 *   sunDir = normalize(cos(δ), sin(δ), 0)
 *   [+Y component phản ánh declination; mặt trời luôn trong mặt phẳng XY]
 */

/**
 * Ngày thứ mấy trong năm (1-indexed, 1..366).
 * @param {Date} date
 * @returns {number}
 */
function getDayOfYear(date) {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  return Math.floor((date.getTime() - start) / 86400000);
}

/**
 * Tính hướng mặt trời và góc quay Trái Đất tuyệt đối từ thời gian UTC.
 *
 * @param {Date} date
 * @returns {{
 *   sunDir:          THREE.Vector3,  // hướng Trái Đất → Mặt Trời (world, normalized)
 *   earthRotY:       number,          // rotation.y tuyệt đối cho surfaceMesh (rad)
 *   decl_deg:        number,           // declination (độ)
 *   subsolarLon_deg: number,          // kinh độ dưới chân mặt trời (°E)
 *   subsolarWorld:   THREE.Vector3,   // vị trí world của điểm dưới chân (R=1.02)
 * }}
 */
export function computeSunAndEarth(date) {
  const n    = getDayOfYear(date);
  const utcH = date.getUTCHours()
             + date.getUTCMinutes() / 60
             + date.getUTCSeconds() / 3600;

  // 1. Declination của Mặt Trời
  const decl_deg = -23.44 * Math.cos(2 * Math.PI / 365 * (n + 10));
  const decl_rad = decl_deg * Math.PI / 180;

  // 2. Kinh độ dưới chân mặt trời (ECEF, °E)
  //    Tại 12:00 UTC → L☉ = 0°E (bỏ qua equation of time, sai lệch tối đa ±16 phút)
  const subsolarLon_deg = -15 * (utcH - 12);
  const subsolarLon_rad = subsolarLon_deg * Math.PI / 180;

  // 3. sunDir trong world space (mặt phẳng XY)
  //    Khi decl=0 (equinox): sunDir = (1, 0, 0) = +X
  //    Khi decl>0 (hè): sunDir nghiêng lên phía +Y
  const sunDir = new THREE.Vector3(
    Math.cos(decl_rad),
    Math.sin(decl_rad),
    0
  ).normalize();

  // 4. Góc quay Trái Đất tuyệt đối
  //    Dẫn xuất: earthRotY = -subsolarLon_rad (xem comment file đầu)
  const earthRotY = -subsolarLon_rad;

  // 5. Vị trí world của điểm dưới chân mặt trời (cho debug marker)
  //    Bởi construction, điểm này trùng với sunDir (sau khi Earth xoay đúng)
  const subsolarWorld = sunDir.clone().multiplyScalar(1.02);

  return { sunDir, earthRotY, decl_deg, subsolarLon_deg, subsolarWorld };
}
