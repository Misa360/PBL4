/** Backend ECEF positions only. No independent orbit clock or synthetic battery. */
const colorByKind = { ground: 0x68dfb1, UAV: 0xffc278, LEO: 0x79caff, MEO: 0xba9aff, GEO: 0xf19db1 };
let libraries;
export async function loadThree() {
  if (globalThis.THREE?.OrbitControls) return;
  if (!libraries) libraries=(async()=>{
    for(const url of ['https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js','https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js']) {
      await new Promise((resolve,reject)=>{
        const script=document.createElement('script');script.src=url;
        const timer=setTimeout(()=>{script.remove();reject(Error('Tải 3D quá lâu. Sơ đồ vẫn hoạt động; kiểm tra Internet rồi thử lại.'));},12000);
        script.onload=()=>{clearTimeout(timer);resolve();};
        script.onerror=()=>{clearTimeout(timer);script.remove();reject(Error('Không tải được thư viện 3D. Sơ đồ vẫn hoạt động khi không có Internet.'));};
        document.head.append(script);
      });
    }
  })().catch(error=>{libraries=null;throw error;});
  return libraries;
}
export function createGlobe(container, selectNode) {
  if (!globalThis.THREE || !THREE.OrbitControls) throw new Error('Không tải được Three.js. Sơ đồ dễ đọc vẫn hoạt động; kiểm tra kết nối Internet để xem 3D.');
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#020a14');
  const camera = new THREE.PerspectiveCamera(45, 1, .001, 100);
  camera.position.set(-2.4, 1.7, -3.6);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); container.append(renderer.domElement);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.minDistance = 1.03; controls.maxDistance = 30;
  scene.add(new THREE.AmbientLight(0xffffff, 1.1));
  const sun = new THREE.DirectionalLight(0xc8e7ff, 1); sun.position.set(-4, 5, -4); scene.add(sun);
  const material = new THREE.MeshPhongMaterial({ color: 0x234d70, shininess: 8 });
  const earth = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), material); scene.add(earth);
  new THREE.TextureLoader().load('./assets/textures/8k_earth_daymap.jpg', texture => {
    texture.encoding = THREE.sRGBEncoding; material.map = texture; material.color.set(0xffffff); material.needsUpdate = true;
  }, undefined, () => {});
  const grid = new THREE.Mesh(new THREE.SphereGeometry(1.001, 24, 16), new THREE.MeshBasicMaterial({ color: 0x326a87, wireframe: true, transparent: true, opacity: .1 })); scene.add(grid);
  const geometry = new THREE.SphereGeometry(1, 12, 8);
  const meshes = new Map(); const labels = new Map(); const lines = new THREE.Group(); scene.add(lines);
  let state, plan, playback, frame;
  const vector = xyz => new THREE.Vector3(xyz[0]/6371000, xyz[2]/6371000, -xyz[1]/6371000);
  const raycaster = new THREE.Raycaster();
  renderer.domElement.addEventListener('pointerup', event => {
    if (Math.abs(event.movementX)+Math.abs(event.movementY) > 3) return;
    const rect = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1, -(event.clientY-rect.top)/rect.height*2+1), camera);
    const hit = raycaster.intersectObjects([...meshes.values()])[0];
    if (hit) selectNode(hit.object.userData.id);
  });
  const dot = new THREE.Mesh(new THREE.SphereGeometry(.009, 10, 8), new THREE.MeshBasicMaterial({ color: 0xffffff })); dot.visible = false; scene.add(dot);
  function clearLines() {
    for (const child of [...lines.children]) { lines.remove(child); child.geometry.dispose(); child.material.dispose(); }
  }
  function update(nextState, nextPlan, showLinks = false) {
    state = nextState; plan = nextPlan; clearLines();
    const current = new Set(state.nodes.map(n => n.id));
    for (const [id, mesh] of meshes) if (!current.has(id)) { scene.remove(mesh); mesh.material.dispose(); meshes.delete(id); labels.get(id)?.remove(); labels.delete(id); }
    for (const node of state.nodes) {
      let mesh = meshes.get(node.id);
      if (!mesh) {
        mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial()); mesh.userData.id = node.id; scene.add(mesh); meshes.set(node.id, mesh);
        const label = document.createElement('div'); label.className = 'node-label'; container.append(label); labels.set(node.id, label);
      }
      mesh.material.color.setHex(node.available ? colorByKind[node.kind] : 0x6a737c);
      mesh.position.copy(vector(node.position_m));
      // Marker sizes are exaggerated so local ground/UAV nodes remain visible.
      mesh.scale.setScalar(node.kind === 'ground' || node.kind === 'UAV' ? .006 : .025);
      const label = labels.get(node.id); label.replaceChildren(document.createTextNode(node.id));
      const battery = document.createElement('span'); battery.className = 'battery'; battery.style.width = `${node.battery_fraction*100}%`; battery.style.background = `hsl(${node.battery_fraction*120},70%,60%)`; label.append(battery);
    }
    if (showLinks) for (const edge of state.links) {
      if (edge.source > edge.target) continue;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([meshes.get(edge.source).position, meshes.get(edge.target).position]), new THREE.LineBasicMaterial({ color: 0x456b85, transparent: true, opacity: .16 })); lines.add(line);
    }
    if (plan?.segments) for (const segment of plan.segments) {
      const a=meshes.get(segment.source), b=meshes.get(segment.target);
      if (!a || !b) continue;
      const from = state.nodes.find(n => n.id === segment.source);
      const to = state.nodes.find(n => n.id === segment.target);
      const fraction = Math.min(from.battery_fraction, to.battery_fraction);
      const color = new THREE.Color().setHSL(fraction/3, .8, .55);
      const length = a.position.distanceTo(b.position);
      const tube = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, length, 6), new THREE.MeshBasicMaterial({ color }));
      tube.scale.x=tube.scale.z=.00001;tube.userData={linkLength:length,bandwidth:segment.bandwidth_hz};
      tube.position.copy(a.position).add(b.position).multiplyScalar(.5);
      tube.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), b.position.clone().sub(a.position).normalize()); lines.add(tube);
    }
  }
  function fit() {
    if (!state) return;
    const radius = Math.max(...state.nodes.map(n => vector(n.position_m).length()));
    camera.position.set(-radius*1.5, radius*.9, -radius*2.3); controls.target.set(0,0,0); controls.update();
  }
  function animate(now) {
    frame = requestAnimationFrame(animate);
    if (container.offsetWidth === 0) return;
    const w = container.clientWidth, h = container.clientHeight;
    if (renderer.domElement.width !== Math.round(w*renderer.getPixelRatio()) || renderer.domElement.height !== Math.round(h*renderer.getPixelRatio())) { renderer.setSize(w,h,false); camera.aspect=w/h; camera.updateProjectionMatrix(); }
    controls.update();
    for(const mesh of lines.children){if(!mesh.userData.linkLength)continue;const distance=camera.position.distanceTo(mesh.position),pixels=.8+1.5*Math.min(1,mesh.userData.bandwidth/20e6);mesh.scale.x=mesh.scale.z=Math.min(mesh.userData.linkLength*.025,distance*2*Math.tan(camera.fov*Math.PI/360)*pixels/Math.max(1,h));}
    for (const [id,label] of labels) {
      const mesh=meshes.get(id); const p=mesh.position.clone().project(camera);
      // Hide labels behind Earth (line segment camera -> node intersects unit sphere).
      const d=mesh.position.clone().sub(camera.position); const u=Math.max(0,Math.min(1,-camera.position.dot(d)/d.lengthSq()));
      const occluded=camera.position.clone().addScaledVector(d,u).length()<.999;
      label.hidden=occluded || p.z>1 || p.z < -1 || Math.abs(p.x)>1 || Math.abs(p.y)>1;
      label.style.left=`${(p.x+1)*w/2+7}px`; label.style.top=`${(1-p.y)*h/2-8}px`;
    }
    dot.visible=false;
    if (playback) {
      const progress=Math.max(0,Math.min(1,(now-playback.start)/playback.duration));
      const index=Math.min(playback.segments.length-1,Math.floor(progress*playback.segments.length));
      const segment=playback.segments[index], a=meshes.get(segment.source), b=meshes.get(segment.target);
      if (a && b && progress<1) {dot.visible=true;dot.position.lerpVectors(a.position,b.position,(progress*playback.segments.length)%1);}
      if(progress===1)playback=null;
    }
    renderer.render(scene,camera);
  }
  frame=requestAnimationFrame(animate);
  return {update,fit,replay(transfer){playback={segments:transfer.segments,start:performance.now(),duration:Math.max(3000,transfer.segments.length*800)};},clearReplay(){playback=null;dot.visible=false;},dispose(){cancelAnimationFrame(frame);controls.dispose();clearLines();geometry.dispose();renderer.dispose();}};
}
