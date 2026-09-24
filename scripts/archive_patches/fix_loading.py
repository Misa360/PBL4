"""
Fix loading overlay: đảm bảo onProgress/onLoad được set TRƯỚC khi earth.js ghi đè
"""
with open('earth_simulation.html', encoding='utf-8') as f:
    content = f.read()

# Xoá khối LOADING_JS cũ (set ở add_loading.py)
OLD_LOADING_JS = """
// ════════════════════════════════════════════════════════════════
//  LOADING OVERLAY LOGIC
// ════════════════════════════════════════════════════════════════
const _loadOverlay = document.getElementById('loading-overlay');
const _loadBar     = document.getElementById('loading-bar');
const _loadPct     = document.getElementById('loading-pct');

// Override THREE.LoadingManager ở mức global để bắt tiến trình của earth.js
const _origOnProgress = THREE.DefaultLoadingManager.onProgress;
THREE.DefaultLoadingManager.onProgress = function(url, loaded, total) {
  const pct = Math.round((loaded / total) * 100);
  _loadBar.style.width = pct + '%';
  _loadPct.textContent = pct + '%';
  if (_origOnProgress) _origOnProgress(url, loaded, total);
};
THREE.DefaultLoadingManager.onLoad = function() {
  setTimeout(() => {
    _loadOverlay.classList.add('hidden');
    setTimeout(() => _loadOverlay.remove(), 900);
  }, 300);
};

"""

NEW_LOADING_JS = """
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

"""

content = content.replace(OLD_LOADING_JS, NEW_LOADING_JS, 1)

if NEW_LOADING_JS not in content:
    print('ERROR: không tìm thấy khối cũ để thay!')
else:
    with open('earth_simulation.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK: Loading overlay JS đã được fix!')
