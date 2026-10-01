/**
 * earth.js – Module Trái Đất thực tế nhiều lớp cho SAGIN Simulator
 *
 * Kiến trúc group:
 *   scene
 *   └── earthGroup  (KHÔNG xoay – chỉ là container)
 *       ├── surfaceMesh   (xoay Y – bề mặt ngày)
 *       │   └── nightMesh (con của surface → xoay đồng bộ)
 *       ├── cloudMesh     (xoay Y riêng – tốc độ khác)
 *       └── atmosMesh     (KHÔNG xoay – luôn thẳng với world space)
 *
 * Trạm mặt đất / debug markers gắn vào surfaceMesh → tự xoay theo Trái Đất.
 * Vệ tinh gắn thẳng vào scene → không bị ảnh hưởng.
 *
 * 1 đơn vị = 1 bán kính Trái Đất = 6371 km
 */
export function createEarth(renderer, scene, options = {}) {

  // ── Options với giá trị mặc định ──────────────────────────────
  const R              = options.radius          ?? 1;
  const EARTH_ROT_SPD  = options.rotationSpeed   ?? 0.00015;   // rad/frame × simSpeed
  const CLOUD_SPD      = options.cloudSpeed      ?? 0.00022;   // rad/frame × simSpeed
  const showAtmosphere = options.showAtmosphere  ?? true;
  const showClouds     = options.showClouds      ?? true;
  const showNightLights= options.showNightLights ?? true;
  const texFolder      = options.textureFolder   ?? 'textures/';
  const debug          = options.debug           ?? false;

  // ── Kiểm tra thiết bị ─────────────────────────────────────────
  const maxTexSize    = renderer.capabilities.maxTextureSize;
  const maxAniso      = renderer.capabilities.getMaxAnisotropy();
  const isNewThree    = parseInt(THREE.REVISION) >= 152;
  if (maxTexSize < 8192)
    console.warn(`[Earth] maxTextureSize=${maxTexSize} < 8192 – ảnh 8K có thể bị scale.`);

  // ── Group gốc (KHÔNG xoay, chỉ là container) ──────────────────
  const earthGroup = new THREE.Group();
  earthGroup.name  = 'earthGroup';
  scene.add(earthGroup);

  // ── sunDir – dùng chung cho light + tất cả shader uniform ─────
  // Tất cả uniform.value đều trỏ vào CÙNG object → setSunDirection() đủ 1 lần
  const sunDir = new THREE.Vector3(1, 0.3, 0.5).normalize();
  console.log('[Earth] sunDir khởi tạo:', sunDir);

  // ── Texture Loader ────────────────────────────────────────────
  const texLoader = new THREE.TextureLoader(THREE.DefaultLoadingManager);

  function loadTex(name, sRGB = false) {
    const url = texFolder + name;
    return texLoader.load(
      url,
      (tex) => {
        tex.generateMipmaps = true;
        tex.minFilter       = THREE.LinearMipmapLinearFilter;
        tex.anisotropy      = maxAniso;
        if (sRGB) {
          if (isNewThree) tex.colorSpace = THREE.SRGBColorSpace;
          else            tex.encoding   = THREE.sRGBEncoding;
        }
      },
      undefined,
      () => console.error(`[Earth] Thiếu texture: ${url} – lớp này sẽ bị bỏ qua.`)
    );
  }

  const dayTex    = loadTex('8k_earth_daymap.jpg',      true);
  const nightTex  = loadTex('8k_earth_nightmap.jpg',    true);
  const cloudTex  = loadTex('8k_earth_clouds.jpg',      false);
  const normalTex = loadTex('8k_earth_normal_map.png',  false);
  const specTex   = loadTex('8k_earth_specular_map.jpg',false);

  // ══════════════════════════════════════════════════════════════
  // LỚP 1 – BỀ MẶT (Day map)
  // earthGroup → surfaceMesh (xoay Y)
  // ══════════════════════════════════════════════════════════════
  const surfaceGeo = new THREE.SphereGeometry(R, 128, 128);
  const surfaceMat = new THREE.MeshPhongMaterial({
    map:         dayTex,
    normalMap:   normalTex,
    normalScale: new THREE.Vector2(0.85, 0.85),
    specularMap: specTex,
    specular:    new THREE.Color(0x335577),
    shininess:   20,
  });
  const surfaceMesh = new THREE.Mesh(surfaceGeo, surfaceMat);
  surfaceMesh.name  = 'earthSurface';
  earthGroup.add(surfaceMesh);

  // ══════════════════════════════════════════════════════════════
  // LỚP 2 – ĐÈN ĐÊM (Night lights)
  // Con của surfaceMesh → tự xoay theo bề mặt
  // ══════════════════════════════════════════════════════════════
  let nightMesh = null;
  if (showNightLights) {
    const nightGeo = new THREE.SphereGeometry(R * 1.001, 128, 128);
    const nightMat = new THREE.ShaderMaterial({
      uniforms: {
        uNight: { value: nightTex },
        uSun:   { value: sunDir   },   // trỏ vào CÙNG object sunDir
      },
      vertexShader: /* glsl */`
        varying vec2  vUv;
        varying vec3  vWorldNormal;
        void main() {
          vUv         = uv;
          // Pháp tuyến trong world space (bề mặt đang xoay)
          vWorldNormal = normalize(mat3(modelMatrix) * normal);
          gl_Position  = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */`
        uniform sampler2D uNight;
        uniform vec3      uSun;
        varying vec2 vUv;
        varying vec3 vWorldNormal;
        void main() {
          // dot < 0 → phía tối; smoothstep(a,b) tạo vùng chuyển tiếp mượt
          // Dải (-0.35..0.15) rộng hơn → đường ranh giới sáng/tối mềm hơn
          float night = smoothstep(0.15, -0.35, dot(vWorldNormal, uSun));
          vec3  col   = texture2D(uNight, vUv).rgb * vec3(1.0, 0.85, 0.55) * 1.6 * night;
          gl_FragColor = vec4(col, 1.0);
        }
      `,
      blending:    THREE.AdditiveBlending,
      transparent: true,
      depthWrite:  false,
    });
    nightMesh      = new THREE.Mesh(nightGeo, nightMat);
    nightMesh.name = 'earthNight';
    surfaceMesh.add(nightMesh);   // con của surface → xoay đồng bộ
  }

  // ══════════════════════════════════════════════════════════════
  // LỚP 3 – MÂY
  // earthGroup → cloudMesh (xoay Y riêng)
  // ══════════════════════════════════════════════════════════════
  let cloudMesh = null;
  if (showClouds) {
    const cloudGeo = new THREE.SphereGeometry(R * 1.012, 128, 128);
    const cloudMat = new THREE.MeshPhongMaterial({
      color:       0xffffff,
      alphaMap:    cloudTex,
      transparent: true,
      opacity:     0.90,
      depthWrite:  false,
    });
    cloudMesh      = new THREE.Mesh(cloudGeo, cloudMat);
    cloudMesh.name = 'earthClouds';
    earthGroup.add(cloudMesh);    // KHÔNG phải con của surface → xoay độc lập
  }

  // ══════════════════════════════════════════════════════════════
  // LỚP 4 – KHÍ QUYỂN (Fresnel + sun-side brighter)
  //
  // QUAN TRỌNG:
  //   • atmosMesh KHÔNG là con của surfaceMesh hay cloudMesh
  //   • earthGroup không xoay → atmosMesh luôn căn chỉnh với world
  //   • side: BackSide → gl_FragCoord nhìn từ bên trong hình cầu
  //     → normal trong view space hướng ra ngoài camera
  //   • Dùng vN (view-space normal) và vW (world-space pos) riêng biệt
  // ══════════════════════════════════════════════════════════════
  let atmosMesh = null;
  if (showAtmosphere) {
    const atmosGeo = new THREE.SphereGeometry(R * 1.06, 128, 128);
    const atmosMat = new THREE.ShaderMaterial({
      uniforms: {
        uSun: { value: sunDir },   // trỏ cùng object sunDir
      },
      vertexShader: /* glsl */`
        varying vec3 vN;   // normal trong view space (để tính rim)
        varying vec3 vW;   // position trong world space (để tính lit)
        void main() {
          // vN: pháp tuyến view-space – dùng để đo độ nghiêng so với camera
          vN = normalize(normalMatrix * normal);
          // vW: vị trí world-space – dùng để đo hướng về phía mặt trời
          vW = (modelMatrix * vec4(position, 1.0)).xyz;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */`
        uniform vec3 uSun;
        varying vec3 vN;
        varying vec3 vW;
        void main() {
          // --- Rim (Fresnel) ---
          // BackSide: normal hướng vào trong → dot với (0,0,1) tạo hiệu ứng rìa
          // clamp tránh pow() âm
          float rim = pow(clamp(0.72 - dot(normalize(vN), vec3(0.0, 0.0, 1.0)), 0.0, 1.0), 3.0);

          // --- Lit: chỉ sáng ở phía hướng về mặt trời ---
          float lit = smoothstep(-0.25, 0.4, dot(normalize(vW), normalize(uSun)));

          // --- Màu khí quyển xanh lam ---
          vec3 col = vec3(0.25, 0.55, 1.0) * rim * lit * 0.9;

          // Giới hạn max để tránh over-exposure
          gl_FragColor = vec4(min(col, vec3(0.8)), 1.0);
        }
      `,
      side:        THREE.BackSide,
      blending:    THREE.AdditiveBlending,
      transparent: true,
      depthWrite:  false,
    });
    atmosMesh      = new THREE.Mesh(atmosGeo, atmosMat);
    atmosMesh.name = 'earthAtmos';
    earthGroup.add(atmosMesh);   // KHÔNG xoay vì earthGroup không xoay
  }

  // ══════════════════════════════════════════════════════════════
  // HÀM TỌA ĐỘ ĐỊA LÝ
  // Equirectangular: kinh độ 0 ở giữa ảnh, khớp SphereGeometry Three.js
  // Công thức: phi=(90-lat)*PI/180, theta=(lon+180)*PI/180
  //   x = -r·sin(phi)·cos(theta)
  //   y =  r·cos(phi)
  //   z =  r·sin(phi)·sin(theta)
  // ══════════════════════════════════════════════════════════════
  function latLonToVec3(latDeg, lonDeg, radius = R) {
    const phi   = (90 - latDeg) * Math.PI / 180;
    const theta = (lonDeg + 180) * Math.PI / 180;
    return new THREE.Vector3(
      -radius * Math.sin(phi) * Math.cos(theta),
       radius * Math.cos(phi),
       radius * Math.sin(phi) * Math.sin(theta)
    );
  }

  // ── Debug markers ──────────────────────────────────────────────
  if (debug) {
    const mkGeo = new THREE.SphereGeometry(0.012, 8, 8);
    const mkMat = new THREE.MeshBasicMaterial({ color: 0xff2222 });
    const pts   = [
      { lat: 16.05,  lon: 108.20,  name: 'Đà Nẵng'   },
      { lat: 21.03,  lon: 105.85,  name: 'Hà Nội'     },
      { lat: 51.48,  lon:   0.00,  name: 'Greenwich'  },
      { lat: 40.71,  lon: -74.00,  name: 'New York'   },
      { lat:-33.87,  lon: 151.21,  name: 'Sydney'     },
    ];
    pts.forEach(({ lat, lon, name }) => {
      const mk = new THREE.Mesh(mkGeo, mkMat);
      mk.position.copy(latLonToVec3(lat, lon, R * 1.003));
      mk.name = `debug_${name}`;
      surfaceMesh.add(mk);   // gắn vào surface → xoay theo Trái Đất
    });
    console.log('[Earth] Debug markers: Đà Nẵng, Hà Nội, Greenwich, New York, Sydney');
  }

  // ══════════════════════════════════════════════════════════════
  // UPDATE – gọi mỗi frame từ vòng animate()
  // @param simSpeed  hệ số tốc độ mô phỏng (1 / 2 / 5 / 10)
  // ══════════════════════════════════════════════════════════════
  function update(simSpeed) {
    // Bề mặt xoay
    surfaceMesh.rotation.y += EARTH_ROT_SPD * simSpeed;
    // Mây xoay độc lập (hơi nhanh hơn bề mặt)
    if (cloudMesh) cloudMesh.rotation.y += CLOUD_SPD * simSpeed;
    // atmosMesh KHÔNG xoay → earthGroup không xoay → OK
  }

  // ══════════════════════════════════════════════════════════════
  // SET SUN DIRECTION
  // Vì tất cả uniform.value đều trỏ vào CÙNG object sunDir,
  // chỉ cần copy() một lần là toàn bộ shader cập nhật ngay.
  // ══════════════════════════════════════════════════════════════
  function setSunDirection(v) {
    sunDir.copy(v).normalize();
    console.log('[Earth] setSunDirection →', sunDir.x.toFixed(2), sunDir.y.toFixed(2), sunDir.z.toFixed(2));
  }

  // ── Dispose ───────────────────────────────────────────────────
  function dispose() {
    [surfaceGeo, surfaceMat, dayTex, normalTex, specTex].forEach(o => o.dispose());
    if (nightMesh)  { nightMesh.geometry.dispose();  nightMesh.material.dispose();  nightTex.dispose(); }
    if (cloudMesh)  { cloudMesh.geometry.dispose();  cloudMesh.material.dispose();  cloudTex.dispose(); }
    if (atmosMesh)  { atmosMesh.geometry.dispose();  atmosMesh.material.dispose();  }
  }

  // ── API ───────────────────────────────────────────────────────
  return {
    group:        earthGroup,   // thêm vào scene bởi module này
    surface:      surfaceMesh,  // gắn trạm mặt đất / debug vào đây
    update,
    setSunDirection,
    latLonToVec3,
    dispose,
  };
}
