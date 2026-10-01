/**
 * simClock.js – Đồng hồ mô phỏng SAGIN
 *
 * Quản lý thời gian mô phỏng UTC. Toàn bộ chuyển động (Trái Đất,
 * vệ tinh, mặt trời) dùng chung một SimClock để đảm bảo nhất quán.
 *
 * Cách dùng:
 *   const clk = new SimClock();
 *   clk.update(realDtSeconds);   // gọi mỗi frame
 *   clk.date                     // Date UTC hiện tại
 */
export class SimClock {
  /**
   * @param {Date}   [startDate=new Date()]  - Thời điểm bắt đầu (UTC)
   * @param {number} [timeScale=600]         - Hệ số tốc độ (600x mặc định)
   */
  constructor(startDate = new Date(), timeScale = 600) {
    this._ms        = startDate.getTime(); // milliseconds UTC
    this.timeScale  = timeScale;
    this.paused     = false;
    this._listeners = [];
  }

  // ── Getters ──────────────────────────────────────────────────

  /** Thời gian mô phỏng (Date object, UTC). Không sửa trực tiếp. */
  get date() { return new Date(this._ms); }

  /** Giờ UTC dạng thập phân 0-24 */
  get utcHour() {
    const d = new Date(this._ms);
    return d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600;
  }

  /** Chuỗi "YYYY-MM-DD HH:mm:ss UTC" */
  get utcString() {
    const d = new Date(this._ms);
    const p = n => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth()+1)}-${p(d.getUTCDate())} `
         + `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
  }

  /** Giá trị cho input[type="date"]: "YYYY-MM-DD" */
  get dateInputValue() {
    const d = new Date(this._ms);
    const p = n => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth()+1)}-${p(d.getUTCDate())}`;
  }

  // ── Cập nhật ─────────────────────────────────────────────────

  /**
   * Gọi mỗi frame từ animate().
   * @param {number} realDtSec - Thời gian thực trôi qua (giây)
   * @returns {number} simDtSec - Thời gian mô phỏng đã tăng (giây); 0 nếu paused
   */
  update(realDtSec) {
    if (this.paused || realDtSec <= 0) return 0;
    const simDt = realDtSec * this.timeScale;
    this._ms += simDt * 1000;
    // Giới hạn dt tối đa 1 giây thực để tránh nhảy vọt khi tab bị ẩn
    return Math.min(simDt, this.timeScale);
  }

  // ── Điều khiển ───────────────────────────────────────────────

  togglePause() { this.paused = !this.paused; }
  pause()       { this.paused = true; }
  resume()      { this.paused = false; }

  /** Đặt về giờ UTC thực ngay bây giờ */
  setNow() { this._ms = Date.now(); }

  /**
   * Đặt giờ trong ngày (UTC), giữ nguyên ngày.
   * @param {number} h - Giờ thập phân 0-24
   */
  setHour(h) {
    const d = new Date(this._ms);
    const hh = Math.floor(h);
    const mm = Math.floor((h - hh) * 60);
    const ss = Math.floor(((h - hh) * 60 - mm) * 60);
    d.setUTCHours(hh, mm, ss, 0);
    this._ms = d.getTime();
  }

  /**
   * Đặt ngày từ chuỗi "YYYY-MM-DD", giữ nguyên giờ.
   * @param {string} str
   */
  setDateStr(str) {
    const [y, mo, dy] = str.split('-').map(Number);
    const h = this.utcHour;
    const d = new Date(Date.UTC(y, mo - 1, dy, 0, 0, 0));
    this._ms = d.getTime();
    this.setHour(h);
  }

  // ── API cho module tối ưu: lấy simSec từ epoch ─────────────

  /**
   * Thời gian mô phỏng (giây) tính từ EPOCH J2000 (2000-01-01T12:00:00Z).
   * Dùng cho tính toán quỹ đạo tuyệt đối.
   */
  get simSec() {
    return (this._ms - 946728000000) / 1000; // 946728000000 = J2000 in ms
  }
}
