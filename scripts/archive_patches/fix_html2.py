"""
Fix earth_simulation.html:
1. Đổi earthModule.update(simSpeed, camera.position) -> earthModule.update(simSpeed)
   (earth.js mới không cần cameraPos nữa vì dùng BackSide shader không cần viewVector)
2. Tắt scanline CSS (#scanline) – nó tạo vạch ngang phủ lên Trái Đất
3. Xoá bỏ earthGroup.userData.atmos.visible (không còn dùng userData)
4. Fix btn-atmo để toggle atmosMesh trực tiếp qua earthGroup.children
"""
import re

with open('earth_simulation.html', encoding='utf-8') as f:
    content = f.read()

changes = []

# ── 1. Tắt scanline (comment out display) ─────────────────────────────────────
OLD_SCANLINE_DIV = '<div id="scanline"></div>'
NEW_SCANLINE_DIV = '<!-- scanline đã tắt để không phủ vạch lên Trái Đất -->\n<!-- <div id="scanline"></div> -->'
if OLD_SCANLINE_DIV in content:
    content = content.replace(OLD_SCANLINE_DIV, NEW_SCANLINE_DIV, 1)
    changes.append('1. Đã tắt div#scanline')
else:
    changes.append('1. SKIP: không tìm thấy div#scanline')

# ── 2. Tắt scanline CSS (pointer-events none đã có, nhưng background tạo vạch) ─
OLD_SCANLINE_CSS = """    /* Scan line effect */
    #scanline {
      position: fixed;
      inset: 0;
      background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(0,0,0,.03) 2px,
        rgba(0,0,0,.03) 4px
      );
      pointer-events: none;
      z-index: 5;
    }"""
NEW_SCANLINE_CSS = """    /* Scan line effect – ĐÃ TẮT để không phủ vạch ngang lên Trái Đất */
    #scanline { display: none; }"""
if OLD_SCANLINE_CSS in content:
    content = content.replace(OLD_SCANLINE_CSS, NEW_SCANLINE_CSS, 1)
    changes.append('2. Đã tắt CSS #scanline')
else:
    changes.append('2. SKIP: không tìm thấy CSS #scanline (có thể đã bị đổi)')

# ── 3. Sửa earthModule.update() – bỏ tham số camera.position ────────────────
OLD_UPDATE = 'earthModule.update(simSpeed, camera.position);'
NEW_UPDATE = 'earthModule.update(simSpeed);'
if OLD_UPDATE in content:
    content = content.replace(OLD_UPDATE, NEW_UPDATE, 1)
    changes.append('3. Đã sửa earthModule.update() bỏ tham số camera.position')
else:
    changes.append('3. SKIP: không tìm thấy earthModule.update(simSpeed, camera.position)')

# ── 4. Fix btn-atmo: tìm con tên 'earthAtmos' thay vì userData ──────────────
OLD_ATMO_BTN = """\
  showAtmos = !showAtmos;
  // Ẩn/hiện lớp khí quyển (children index 2 trong earthGroup)
  earthGroup.children.forEach(child => {
    // Lớp atmosphere có geometry radius > 1.08
    if (child.geometry && child.geometry.parameters && child.geometry.parameters.radius >= 1.08) {
      child.visible = showAtmos;
    }
  });
  document.getElementById('btn-atmo').classList.toggle('active', showAtmos);\
"""
NEW_ATMO_BTN = """\
  showAtmos = !showAtmos;
  // Tìm mesh tên 'earthAtmos' trong earthGroup để toggle
  const _atm = earthGroup.getObjectByName('earthAtmos');
  if (_atm) _atm.visible = showAtmos;
  document.getElementById('btn-atmo').classList.toggle('active', showAtmos);\
"""
if OLD_ATMO_BTN in content:
    content = content.replace(OLD_ATMO_BTN, NEW_ATMO_BTN, 1)
    changes.append('4. Đã sửa btn-atmo dùng getObjectByName')
else:
    # fallback: tìm pattern rộng hơn
    changes.append('4. SKIP: không tìm thấy OLD_ATMO_BTN')

# ── 5. Đảm bảo SUN_DIR cũng update sunLight.position khi setSunDirection gọi ──
# Thêm setSunDirection call ngay sau khi sunLight được tạo (nếu chưa có)
OLD_SUN_DIR_SETUP = """// Ánh sáng mặt trời chính (sunDir dùng chung với earth.js)
const SUN_DIR = new THREE.Vector3(5, 3, 5).normalize();
sunLight.position.copy(SUN_DIR.clone().multiplyScalar(50));"""
NEW_SUN_DIR_SETUP = """// Ánh sáng mặt trời chính (sunDir dùng chung với earth.js)
// earth.js khởi tạo sunDir = (1, 0.3, 0.5).normalize() – phải đồng bộ với sunLight
const SUN_DIR = new THREE.Vector3(1, 0.3, 0.5).normalize();
sunLight.position.copy(SUN_DIR.clone().multiplyScalar(50));
console.log('[Main] SUN_DIR:', SUN_DIR.x.toFixed(2), SUN_DIR.y.toFixed(2), SUN_DIR.z.toFixed(2));"""
if OLD_SUN_DIR_SETUP in content:
    content = content.replace(OLD_SUN_DIR_SETUP, NEW_SUN_DIR_SETUP, 1)
    changes.append('5. Đã đồng bộ SUN_DIR với earth.js (1, 0.3, 0.5)')
else:
    changes.append('5. SKIP: không tìm thấy SUN_DIR setup')

# Ghi file
with open('earth_simulation.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('\n'.join(changes))
print('\nDone!')
