"""
Thêm loading overlay và đảm bảo sunLight được khai báo trước khi createEarth()
Chạy sau patch_html.py
"""
with open('earth_simulation.html', encoding='utf-8') as f:
    content = f.read()

# ──────────────────────────────────────────────────────────────
# 1. Thêm CSS loading overlay (sau thẻ đóng </style> cuối cùng)
# ──────────────────────────────────────────────────────────────
LOADING_CSS = """
    /* ── Loading overlay ── */
    #loading-overlay {
      position: fixed;
      inset: 0;
      background: #000010;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      z-index: 999;
      transition: opacity 0.8s ease;
    }
    #loading-overlay.hidden {
      opacity: 0;
      pointer-events: none;
    }
    #loading-title {
      font-family: 'Orbitron', sans-serif;
      font-size: 1.4rem;
      color: #00e5ff;
      letter-spacing: 4px;
      text-shadow: 0 0 30px #00e5ff;
      margin-bottom: 12px;
    }
    #loading-sub {
      font-family: 'Rajdhani', sans-serif;
      font-size: 0.85rem;
      color: #4a8aaa;
      letter-spacing: 2px;
      margin-bottom: 32px;
    }
    #loading-bar-wrap {
      width: 280px;
      height: 4px;
      background: rgba(0,200,255,0.12);
      border-radius: 4px;
      overflow: hidden;
      border: 1px solid rgba(0,200,255,0.2);
    }
    #loading-bar {
      height: 100%;
      background: linear-gradient(90deg, #0088cc, #00e5ff);
      width: 0%;
      border-radius: 4px;
      transition: width 0.3s ease;
      box-shadow: 0 0 10px #00e5ff;
    }
    #loading-pct {
      font-family: 'Orbitron', sans-serif;
      font-size: 0.7rem;
      color: #00e5ff;
      margin-top: 10px;
      letter-spacing: 2px;
    }
"""

LOADING_HTML = """
<div id="loading-overlay">
  <div id="loading-title">SAGIN NETWORK</div>
  <div id="loading-sub">LOADING EARTH TEXTURES ...</div>
  <div id="loading-bar-wrap"><div id="loading-bar"></div></div>
  <div id="loading-pct">0%</div>
</div>
"""

# Chèn CSS vào cuối </style>
content = content.replace('  </style>', LOADING_CSS + '  </style>', 1)

# Chèn HTML overlay ngay sau <body>
content = content.replace('<div id="scanline">', LOADING_HTML + '\n<div id="scanline">', 1)

# ──────────────────────────────────────────────────────────────
# 2. Thêm JS loading logic vào ngay trước dòng "const earthModule = createEarth"
# ──────────────────────────────────────────────────────────────
LOADING_JS = """
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
content = content.replace(
    '// Tạo Trái Đất từ module',
    LOADING_JS + '// Tạo Trái Đất từ module',
    1
)

with open('earth_simulation.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('Loading overlay added successfully!')
