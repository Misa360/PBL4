/**
 * eclipse.js – Phát hiện vệ tinh trong bóng Trái Đất
 *
 * Mô hình bóng hình TRỤ (cylindrical shadow):
 *   - Đơn giản, đủ chính xác cho SAGIN (sai số ~2% so với mô hình hình nón)
 *   - Điều kiện vào bóng (p = vị trí vệ tinh, s = sunDir chuẩn hóa, R = R_Earth):
 *
 *     d    = dot(p, s)                // chiếu p lên trục Trái Đất → Mặt Trời
 *     perp = | p − d·s |             // khoảng cách vuông góc với trục
 *     inEclipse = (d < 0) && (perp < R)
 *
 *   Chú ý: sunDir trỏ TỪ Trái Đất sang Mặt Trời.
 *     d < 0 → vệ tinh ở phía đối diện mặt trời (phía tối)
 *     perp < R → nằm trong bóng hình trụ
 */

/**
 * Kiểm tra vệ tinh có đang trong bóng tối không.
 *
 * @param {THREE.Vector3} satPos  - Vị trí vệ tinh (world, đơn vị R_Earth=1)
 * @param {THREE.Vector3} sunDir  - Hướng Trái Đất → Mặt Trời (world, normalized)
 * @param {number}        [R=1.0] - Bán kính Trái Đất (mặc định 1 đơn vị)
 * @returns {boolean}             - true = đang trong bóng
 */
export function checkEclipse(satPos, sunDir, R = 1.0) {
  // Chiếu vị trí vệ tinh lên trục mặt trời
  const d = satPos.dot(sunDir);

  // Nếu d >= 0 → vệ tinh ở phía có ánh sáng → không trong bóng
  if (d >= 0) return false;

  // Tính khoảng cách vuông góc tới trục Trái Đất-Mặt Trời
  // perp_vec = satPos - d * sunDir
  const perp = satPos.clone().addScaledVector(sunDir, -d).length();

  // Vào bóng nếu khoảng cách vuông góc < bán kính Trái Đất
  return perp < R;
}

/**
 * EclipseTracker – Theo dõi thống kê bóng tối per-vệ tinh.
 *
 * Cung cấp API getSatelliteEnergyState() để module tối ưu hóa năng lượng
 * (pin, sạc) dùng trong tương lai mà không cần sửa file này.
 */
export class EclipseTracker {
  constructor() {
    // Map: satId → { inEclipse, eclipseSeconds, totalSeconds }
    this._stats = new Map();
  }

  /**
   * Cập nhật trạng thái vệ tinh mỗi frame.
   * @param {string|number} id         - ID vệ tinh (duy nhất)
   * @param {boolean}       inEclipse  - Có đang trong bóng không
   * @param {number}        simDtSec   - Thời gian mô phỏng frame này (giây)
   */
  update(id, inEclipse, simDtSec) {
    if (!this._stats.has(id)) {
      this._stats.set(id, { inEclipse: false, eclipseSeconds: 0, totalSeconds: 0 });
    }
    const s = this._stats.get(id);
    s.inEclipse = inEclipse;
    if (simDtSec > 0) {
      s.totalSeconds   += simDtSec;
      if (inEclipse) s.eclipseSeconds += simDtSec;
    }
  }

  /**
   * Trả về trạng thái năng lượng của vệ tinh.
   * API chính cho module tối ưu hóa (PBL4 Phase 2).
   *
   * @param {string|number} id
   * @returns {{ inEclipse: boolean, sunlitFraction: number, eclipseSeconds: number }}
   */
  getSatelliteEnergyState(id) {
    const s = this._stats.get(id);
    if (!s) return { inEclipse: false, sunlitFraction: 1.0, eclipseSeconds: 0 };
    const sunlitFraction = s.totalSeconds > 0
      ? 1 - s.eclipseSeconds / s.totalSeconds
      : 1.0;
    return {
      inEclipse:      s.inEclipse,
      sunlitFraction: Math.max(0, Math.min(1, sunlitFraction)),
      eclipseSeconds: s.eclipseSeconds,
    };
  }

  /** Snapshot toàn bộ (cho log / export) */
  getAllStats() {
    const result = {};
    this._stats.forEach((_, k) => {
      result[k] = this.getSatelliteEnergyState(k);
    });
    return result;
  }

  /** Đặt lại thống kê */
  reset() { this._stats.clear(); }
}
