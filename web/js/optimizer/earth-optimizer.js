/** Mount optimizer nodes in the original textured Earth scene, with no second renderer. */
import { buildNetworkConfig } from './network-config.js';
import { explainPlan } from './result-messages.js';
export function earthLinkRadius(distance,fov,height,bandwidth,length) {
  const pixels=.8+1.5*Math.max(0,Math.min(1,bandwidth/20e6));
  return Math.min(length*.025,Math.max(0,distance)*2*Math.tan(fov*Math.PI/360)*pixels/Math.max(1,height));
}

export function layoutEarthLabels(items,width,height,reserved=[]) {
  const result=[],occupied=[...reserved];
  const overlaps=(a,b)=>a.x<b.x+b.width+6&&a.x+a.width+6>b.x&&a.y<b.y+b.height+6&&a.y+a.height+6>b.y;
  for(const item of [...items].sort((a,b)=>a.priority-b.priority)){
    const w=item.width||120,h=item.height||42,options=[];
    for(const dx of [14,-w-14,40,-w-40])for(const dy of [-h-12,12,-h-65,65,-h-120,120])options.push({x:item.x+dx,y:item.y+dy,width:w,height:h});
    for(let y=110;y+h<height-12;y+=h+10)for(let x=8;x+w<width-8;x+=w+12)options.push({x,y,width:w,height:h});
    const fitting=options.filter(r=>r.x>=8&&r.y>=104&&r.x+r.width<=width-8&&r.y+r.height<=height-12&&!occupied.some(o=>overlaps(r,o)));
    fitting.sort((a,b)=>Math.hypot(a.x-item.x,a.y-item.y)-Math.hypot(b.x-item.x,b.y-item.y));
    if(fitting.length){const box={...fitting[0],id:item.id,anchorX:item.x,anchorY:item.y};result.push(box);occupied.push(box);}
  }
  return result;
}

export function mountEarthOptimizer({ scene, camera, controls, renderer, setMode }) {
  const $ = id => document.getElementById(id);
  const panel = $('earth-optimizer'), form = $('eo-form'), networkForm=$('eo-network-form');
  const group = new THREE.Group(); group.visible = false; scene.add(group);
  const nodes = new Map(), labels = new Map();
  const routes = new THREE.Group(), trails = new THREE.Group(); group.add(routes, trails);
  const colors = { ground:0x68dfb1,UAV:0xffc278,LEO:0x79caff,MEO:0xba9aff,GEO:0xf19db1 };
  const names = {ai_aco_pso:'AI + ACO + PSO','random': 'Random', 'greedy': 'Greedy', 'min_hops': 'BFS - ít chặng nhất', 'shortest_distance': 'Dijkstra - khoảng cách', 'min_delay': 'Dijkstra - độ trễ', 'widest': 'Widest path', 'energy': 'Energy path', 'aco': 'ACO', 'widest_pso': 'Widest + PSO', 'energy_pso': 'Energy + PSO', 'aco_pso': 'ACO + PSO', 'pso': 'Widest + PSO'};
  const descriptions = {ai_aco_pso:'Mạng nơ-ron sinh nhiều tuyến và phương án công suất/băng thông, ACO/PSO tinh chỉnh gợi ý hợp lệ. Nếu không có gợi ý phù hợp, dùng ACO/PSO thường.',
    min_hops:'BFS chọn tuyến ít chặng nhất.',
    shortest_distance:'Dijkstra tối thiểu tổng khoảng cách.',
    min_delay:'Dijkstra tối thiểu thời gian truyền và truyền lan với công suất cố định, nửa băng thông nút; kiểm tra lại bằng bộ đánh giá chung.',
    energy_pso:'Energy chọn tuyến, PSO tối ưu công suất và băng thông.',
    pso:'PSO tối ưu công suất và băng thông trên đường có dung lượng cổ chai lớn nhất được chọn trước. PSO hiện chưa tự tìm đường.',
    aco_pso:'ACO tìm các đường ứng viên; PSO điều chỉnh công suất và băng thông cho các đường đó. Đường sáng là phương án cuối.',
    aco:'Kiến ưu tiên đường có tốc độ tốt và nút còn pin; pheromone giúp tăng ưu tiên các cạnh có triển vọng. Tài nguyên phát cố định.',
    widest_pso:'Tìm đường có dung lượng cổ chai lớn, sau đó dùng PSO phân bổ công suất và băng thông.',
    widest:'Ưu tiên đường có dung lượng cổ chai lớn. Kết quả vẫn được kiểm tra tốc độ đầu cuối và pin.',
    energy:'Dijkstra ưu tiên chi phí năng lượng phát/nhận thấp với tài nguyên cố định.',
    random:'Đi ngẫu nhiên qua các nút khả dụng, không lặp nút. Có thể thất bại dù mạng còn đường khác.',
    greedy:'Ở mỗi bước ưu tiên nút gần nhất. Quyết định cục bộ có thể dẫn đến ngõ cụt.'
  };
  let active=false,busy=false,state=null,plan=null,playback=null,historyPlayback=null,geometry=null;
  let lastTransfer=null,closedVersion=0,selected=null,searchBudget={};
  const fmt=(v,d=3)=>v==null?'—':Number(v).toLocaleString('vi-VN',{maximumFractionDigits:d});
  const point=xyz=>new THREE.Vector3(xyz[0]/6371000,xyz[2]/6371000,-xyz[1]/6371000);
  const packet=new THREE.Mesh(new THREE.SphereGeometry(.004,12,8),new THREE.MeshBasicMaterial({color:0xffffff}));packet.visible=false;group.add(packet);
  function message(text,error=false){$('eo-message').textContent=text;$('eo-message').classList.toggle('error',error);}
  function buttons(){
    for(const field of form.querySelectorAll('input,select,button'))field.disabled=busy;
    for(const field of networkForm.querySelectorAll('input,select,button'))field.disabled=busy;
    $('eo-close').disabled=busy;$('eo-open').disabled=busy;
    $('eo-preview').disabled=busy||!plan?.feasible;
    $('eo-transmit').disabled=busy||!plan?.feasible||plan.revision!==state?.revision;
    $('eo-optimize').disabled=busy||!state;
    $('eo-optimize').textContent=busy?'Đang tính…':`✦ Chạy ${names[form.elements.method.value]||'phương pháp'} trên 3D`;
  }
  async function api(path,body){
    let response;
    try{response=await fetch(`/api/optimizer/${path}`,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});}
    catch{throw Error('Chưa kết nối Python. Chạy python server.py và mở http://127.0.0.1:8000/.');}
    let data;try{data=await response.json();}catch{throw Error('Máy chủ chưa có API tối ưu. Khởi động lại python server.py.');}
    if(!response.ok)throw Error(data.error||`Lỗi API ${response.status}`);
    return data;
  }
  async function task(fn){if(busy)return;busy=true;buttons();try{await fn();}catch(error){message(error.message,true);}finally{busy=false;buttons();}}
  function clearLines(target){for(const line of [...target.children]){target.remove(line);line.geometry.dispose();line.material.dispose();}}
  function cylinder(a,b,bandwidth,color){const d=b.clone().sub(a),length=d.length();const mesh=new THREE.Mesh(new THREE.CylinderGeometry(1,1,length,8),new THREE.MeshBasicMaterial({color}));mesh.scale.x=mesh.scale.z=.00001;mesh.userData={linkLength:length,bandwidth};mesh.position.copy(a).add(b).multiplyScalar(.5);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),d.normalize());return mesh;}
  function clearReplay(){playback=null;historyPlayback=null;packet.visible=false;}
  function nodeDetail(id){
    selected=id;const n=state?.nodes.find(n=>n.id===id);if(!n)return;
    const after=plan?.battery_after?.[id];
    $('eo-node').textContent=`${id} · ${n.kind} · ${n.battery_j==null?'Nguồn không giới hạn':`Pin ${fmt(n.battery_j,6)} / ${fmt(n.battery_capacity_j)} J (${fmt(n.battery_fraction*100,4)}%)`}${after!=null?` · Sau phương án: ${fmt(after)} J`:''}`;
    $('eo-node').textContent+=' · Băng thông còn '+fmt((n.available_bandwidth_hz??n.bandwidth_hz)/1e6)+' / '+fmt(n.bandwidth_hz/1e6)+' MHz';
  }
  function decorateLabel(node,label){
    const source=plan?.path?.[0]||form.elements.source.value,target=plan?.path?.at(-1)||form.elements.target.value;
    const role=node.id===source?'source':node.id===target?'target':'relay';
    label.setAttribute('data-role',role);
    label.replaceChildren(document.createTextNode(`${node.id}${role==='source'?' · GỬI':role==='target'?' · NHẬN':''} · ${node.battery_j==null?'∞':(node.battery_fraction<1 && Number((node.battery_fraction*100).toFixed(3))===100?'<100':fmt(node.battery_fraction*100,3))+'%'}`));
    if(node.battery_j!=null){
      label.title=`${fmt(node.battery_j,6)} / ${fmt(node.battery_capacity_j,6)} J`;
    }
    const bar=document.createElement('span');bar.style.width=`${node.battery_fraction*100}%`;bar.style.background=`hsl(${node.battery_fraction*120},70%,60%)`;label.append(bar);
    nodes.get(node.id)?.material.color.setHex(role==='source'?0x76e9ff:role==='target'?0xffbc72:node.available?colors[node.kind]:0x697581);
  }
  function drawRoute(){
    clearLines(routes);clearLines(trails);
    if(!state)return;
    for(const node of state.nodes)decorateLabel(node,labels.get(node.id));
    const summary=$('eo-route-summary'),hops=$('eo-hop-list');hops.replaceChildren();summary.hidden=!active||!plan?.path?.length;
    if(plan?.path?.length){
      $('eo-route-title').textContent=`${plan.path[0]} → ${plan.path.at(-1)} · ${plan.path.length-1} chặng${plan.feasible?'':' · chưa đáp ứng'}`;
      plan.path.forEach((id,index)=>{if(index){const arrow=document.createElement('span');arrow.textContent='→';hops.append(arrow);}const button=document.createElement('button');button.type='button';button.className=index===0?'source':index===plan.path.length-1?'target':'relay';button.textContent=`${id}${index===0?' · Gửi':index===plan.path.length-1?' · Nhận':''}`;button.addEventListener('click',()=>{nodeDetail(id);focus(false,[id]);});hops.append(button);});
    }
    if($('eo-pheromone').checked&&plan?.pheromone?.length){
      const pairs=new Map(),maximum=Math.max(...plan.pheromone.map(e=>e.value));
      for(const e of plan.pheromone){const key=[e.source,e.target].sort().join('|');if(!pairs.has(key)||pairs.get(key).value<e.value)pairs.set(key,e);}
      for(const e of pairs.values()){
        const a=nodes.get(e.source),b=nodes.get(e.target);if(!a||!b)continue;
        const material=new THREE.LineBasicMaterial({color:0xbc9aff,transparent:true,opacity:.05+.6*e.value/maximum});
        trails.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([a.position,b.position]),material));
      }
    }
    for(const edge of plan?.segments||[]){
      const a=nodes.get(edge.source),b=nodes.get(edge.target);if(!a||!b)continue;
      const fraction=Math.min(...[edge.source,edge.target].map(id=>state.nodes.find(n=>n.id===id).battery_fraction));
      const mesh=cylinder(a.position,b.position,edge.bandwidth_hz,new THREE.Color().setHSL(fraction/3,.8,.6));routes.add(mesh);
      const direction=b.position.clone().sub(a.position),length=direction.length();
      const arrow=new THREE.Mesh(new THREE.ConeGeometry(1,1,8),new THREE.MeshBasicMaterial({color:0xd8fff4}));arrow.scale.setScalar(.00001);arrow.userData={linkLength:length,arrow:true,bandwidth:edge.bandwidth_hz};
      arrow.position.copy(a.position).addScaledVector(direction,.7);arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),direction.normalize());routes.add(arrow);
    }
  }
  function showState(){
    if(!state)return;
    if(!geometry)geometry=new THREE.SphereGeometry(1,12,8);
    const current=new Set(state.nodes.map(n=>n.id));
    for(const[id,mesh]of nodes)if(!current.has(id)){group.remove(mesh);mesh.material.dispose();nodes.delete(id);labels.get(id)?.remove();labels.delete(id);}
    for(const node of state.nodes){
      let mesh=nodes.get(node.id);
      if(!mesh){mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());group.add(mesh);nodes.set(node.id,mesh);
        const label=document.createElement('button');label.type='button';label.className='earth-network-label';label.addEventListener('click',()=>nodeDetail(node.id));document.body.append(label);labels.set(node.id,label);}
      mesh.position.copy(point(node.position_m));mesh.scale.setScalar((node.kind==='ground'||node.kind==='UAV')?.001:.006);
      mesh.material.color.setHex(node.available?colors[node.kind]:0x697581);
    }
    const counts={sat:state.nodes.filter(n=>['LEO','MEO','GEO'].includes(n.kind)).length,uav:state.nodes.filter(n=>n.kind==='UAV').length,gs:state.nodes.filter(n=>n.kind==='ground').length};
    for(const[k,v]of Object.entries(counts)){$(`v-${k}`).textContent=v;$(`bar-${k}`).style.width=`${v/state.nodes.length*100}%`;}
    $('scene-note').textContent=state.nodes.length+' nút · '+counts.sat+' vệ tinh · '+counts.uav+' UAV · '+counts.gs+' trạm · mạng mô phỏng';
    $('clock').textContent=`T + ${fmt(state.time_s,2)} s`;
    const grounds=state.nodes.filter(n=>n.kind==='ground');
    $('eo-network-info').textContent=`Đang dùng ${state.nodes.length} nút · phân bố rộng · ${grounds.length} trạm gửi/nhận (${grounds[0].id}–${grounds.at(-1).id}). UAV và vệ tinh là trung chuyển.`;
    $('eo-route').textContent=plan?.path?.length?`${names[plan.method]}: ${plan.path.join(' → ')}`:'Chọn phương pháp và nhấn Chạy để thấy đường truyền.';
    $('eo-result').textContent=plan?`${plan.feasible?'Đáp ứng':'Chưa đáp ứng'} · ${fmt(plan.rate_bps==null?null:plan.rate_bps/1e6)} Mbps · ${fmt(plan.energy_j)} J · Cost ${fmt(plan.cost,5)} · tính trong ${fmt(plan.elapsed_ms,1)} ms`:'';
    if(plan){$('eo-result').textContent+=` · độ trễ ${fmt(plan.duration_s)} s`;if(plan.ai)$('eo-result').textContent+=plan.ai.status==='ready'?` · AI: ${plan.ai.feasible_hints}/${plan.ai.generated} gợi ý hợp lệ`:' · AI dùng phương án dự phòng ACO/PSO';}
    for(const key of ['battery_profile','load_profile','state_seed'])if(networkForm.elements[key])networkForm.elements[key].value=state[key]??(key==='state_seed'?42:key==='load_profile'?'idle':'full');
    if(networkForm.elements.forecast_load)networkForm.elements.forecast_load.value=state.forecast_load?'on':'off';
    if(selected)nodeDetail(selected);drawRoute();buttons();
  }
  function focus(all=false,requestedIds=null){
    if(!state)return;
    const ids=requestedIds||(all?state.nodes.map(n=>n.id):plan?.path?.length?plan.path:[...state.nodes.filter(n=>n.kind==='ground'||n.kind==='UAV').map(n=>n.id),'LEO1']);
    const box=new THREE.Box3();for(const id of ids){const mesh=nodes.get(id);if(mesh)box.expandByPoint(mesh.position);}
    if(all){box.expandByPoint(new THREE.Vector3(-1,-1,-1));box.expandByPoint(new THREE.Vector3(1,1,1));}
    const closeUp=requestedIds&&requestedIds.length<=2;
    const center=box.getCenter(new THREE.Vector3()),radius=Math.max(closeUp?.0003:.008,box.getSize(new THREE.Vector3()).length()/2);
    const distance=radius/Math.sin(THREE.MathUtils.degToRad(camera.fov/2))*1.4;
    const radial=center.clone().normalize();
    let direction=radial;
    if(!all){const first=nodes.get(ids[0])?.position,last=nodes.get(ids.at(-1))?.position;
      const tangent=first&&last?last.clone().sub(first):new THREE.Vector3(1,0,0);
      const side=radial.clone().cross(tangent);if(side.length()<1e-9)side.copy(new THREE.Vector3(-radial.z,0,radial.x));
      direction=radial.clone().multiplyScalar(.78).addScaledVector(side.normalize(),.63).normalize();}
    controls.target.copy(center);camera.position.copy(center).addScaledVector(direction,Math.max(closeUp?.003:.05,distance));
    resize();
    camera.near=.0005;camera.far=1000;camera.updateProjectionMatrix();controls.minDistance=.002;controls.maxDistance=30;controls.autoRotate=false;controls.update();
  }
  function fieldsFromState(incoming){
    networkForm.elements.size.value=state.size;
    if(networkForm.elements.constellation)networkForm.elements.constellation.value=state.constellation||'balanced';
    searchBudget=incoming?.budget||{};
    const grounds=state.nodes.filter(n=>n.kind==='ground');
    for(const key of ['source','target']){const input=form.elements[key];input.replaceChildren();for(const n of grounds){const option=document.createElement('option');option.value=n.id;option.textContent=n.name&&n.name!==n.id?`${n.id} · ${n.name}`:n.id;input.append(option);}
      const desired=incoming?.request?.[key];input.value=grounds.some(n=>n.id===desired)?desired:key==='source'?grounds[0].id:grounds[grounds.length/2].id;}
    if(incoming){if(Object.hasOwn(names, incoming.method))form.elements.method.value=incoming.method==='pso'?'widest_pso':incoming.method;
      for(const key of ['data_mb','required_mbps','energy_weight','latency_weight'])if(incoming.request?.[key]!=null)form.elements[key]&&(form.elements[key].value=incoming.request[key]);
      if(incoming.seed!=null)form.elements.seed.value=incoming.seed;}
    $('eo-explain').textContent=descriptions[form.elements.method.value];
  }
  function payload(){const value=key=>form.elements[key].value;return{request:{source:value('source'),target:value('target'),data_mb:Number(value('data_mb')),required_mbps:Number(value('required_mbps')),energy_weight:Number(value('energy_weight')),latency_weight:Number(form.elements.latency_weight?.value??0)},method:value('method'),seed:Number(value('seed')),budget:searchBudget};}
  async function solve(body){
    clearReplay();plan=null;message(`Đang chạy ${names[body.method]}…`);
    const latest=await api('state');state=latest;
    const result=await api('optimize',body);
    if(result.revision!==state.revision)throw Error('Mạng đã đổi ở trang khác. Chạy lại phương pháp để cập nhật.');
    plan=result;lastTransfer=null;showState();focus();
    const pso=plan.pso_histories?.find(h=>h.path.join('|')===plan.path.join('|'));
    const entries=[...(plan.aco_history||[]).map(h=>({...h,phase:'ACO'})),...(pso?.history||[]).map(h=>({...h,phase:'PSO'}))];
    historyPlayback=entries.length?{entries,start:performance.now(),duration:4500}:null;
    $('eo-history').textContent=entries.length?'Phát lại lịch sử Cost đã ghi nhận…':'Phương pháp này không có vòng lặp ACO/PSO.';
    message(plan.feasible?'Đường sáng là phương án cuối. Xem thử để theo dõi từng chặng; Truyền mới cập nhật pin.':explainPlan(plan),!plan.feasible);
  }
  function replay(committed=false){
    historyPlayback=null;
    const segments=committed?lastTransfer?.segments:plan?.segments;if(!segments?.length)return;
    playback={segments,start:performance.now(),duration:Math.max(6000,segments.length*1500),committed,lastIndex:-1};
    message(committed?'Đã truyền và trừ pin. Đang phát lại các chặng đã thực hiện, làm chậm để dễ nhìn.':'Đang xem thử đường đi, chưa truyền và chưa trừ pin. Chấm được làm chậm để quan sát.');
  }
  async function open(incoming=null,run=false){
    if(active||busy)return;
    active=true;panel.hidden=false;document.body.classList.add('earth-network-mode');group.visible=true;setMode(true);const version=++closedVersion;
    await task(async()=>{state=await api('state');if(version!==closedVersion)return;fieldsFromState(incoming);showState();focus();message('Đã đồng bộ nút và pin từ Python. Chọn phương pháp rồi nhấn Chạy.');if(run)await solve(payload());});
  }
  function close(){if(busy)return;active=false;closedVersion++;clearReplay();group.visible=false;panel.hidden=true;$('eo-route-summary').hidden=true;$('eo-label-lines').replaceChildren();document.body.classList.remove('earth-network-mode');for(const label of labels.values())label.hidden=true;setMode(false);}
  form.addEventListener('submit',e=>{e.preventDefault();const body=payload();task(()=>solve(body));});
  networkForm.addEventListener('submit',e=>{
    e.preventDefault();const config=buildNetworkConfig(state,Object.fromEntries(new FormData(networkForm)));
    const saved=payload();delete saved.request.source;delete saved.request.target;
    task(async()=>{
      const next=await api('reset',config);
      clearReplay();plan=null;lastTransfer=null;selected=null;state=next;
      fieldsFromState(saved);$('eo-history').textContent='';$('eo-node').textContent='Nhấn nhãn nút để xem pin.';
      showState();focus(true);
      message(`Đã tạo mạng ${state.nodes.length} nút. Bạn có thể chọn ${state.nodes.filter(n=>n.kind==='ground').length} trạm gửi/nhận ngay bên dưới; pin và lịch sử đã đặt lại.`);
    });
  });
  form.addEventListener('input',()=>{clearReplay();plan=null;lastTransfer=null;drawRoute();$('eo-route').textContent='Lựa chọn đã đổi. Nhấn Chạy để tính lại đường.';$('eo-result').textContent='';$('eo-history').textContent='';$('eo-explain').textContent=descriptions[form.elements.method.value];if(selected)nodeDetail(selected);buttons();});
  $('eo-open').addEventListener('click',()=>open());$('eo-close').addEventListener('click',close);
  $('eo-focus').addEventListener('click',()=>focus());$('eo-all').addEventListener('click',()=>focus(true));
  $('eo-pheromone').addEventListener('change',drawRoute);$('eo-preview').addEventListener('click',()=>replay(false));
  $('eo-transmit').addEventListener('click',()=>task(async()=>{
    if(!plan?.feasible||plan.revision!==state.revision)return;
    try{const result=await api('transmit',{plan_id:plan.plan_id});state=result.state;lastTransfer=result.transfer;showState();replay(true);}
    catch(error){plan=null;clearReplay();showState();throw error;}
  }));
  function tick(now){
    if(!active)return;
    if(camera.position.length()<1.003){camera.position.normalize().multiplyScalar(1.003);camera.lookAt(controls.target);}
    camera.updateMatrixWorld();
    const candidates=[],path=new Set(plan?.path||[]),onlyRoute=$('eo-route-only').checked&&path.size>0;
    for(const[id,mesh]of nodes){
      const projected=mesh.position.clone().project(camera),label=labels.get(id),d=mesh.position.clone().sub(camera.position);
      const u=Math.max(0,Math.min(1,-camera.position.dot(d)/d.lengthSq()));
      const occluded=camera.position.clone().addScaledVector(d,u).length()<.99999;
      mesh.visible=!onlyRoute||path.has(id);
      const labelWidth=Math.max(110,label.offsetWidth||0),labelHeight=Math.max(38,label.offsetHeight||0);label.hidden=true;
      if(mesh.visible&&!occluded&&projected.z<=1&&projected.z>=-1&&Math.abs(projected.x)<=1&&Math.abs(projected.y)<=1){
        candidates.push({id,x:(projected.x+1)*innerWidth/2,y:(1-projected.y)*innerHeight/2,width:labelWidth,height:labelHeight,priority:id===plan?.path?.[0]||id===plan?.path?.at(-1)?0:path.has(id)?1:2});}
      mesh.scale.setScalar(Math.max(.000025,Math.min(.025,camera.position.distanceTo(mesh.position)*.004)));
    }
    const panelRect=panel.getBoundingClientRect?.();
    const reserved=[panelRect?{x:panelRect.left,y:panelRect.top,width:panelRect.width,height:panelRect.height}:{x:innerWidth-360,y:112,width:340,height:innerHeight-202}];
    if(innerWidth>700)reserved.push({x:20,y:116,width:240,height:285});
    if(!$('eo-route-summary').hidden)reserved.push({x:0,y:innerHeight-115,width:innerWidth,height:115});
    const leaders=$('eo-label-lines');leaders.replaceChildren();
    for(const box of layoutEarthLabels(candidates,innerWidth,innerHeight,reserved)){
      const label=labels.get(box.id);label.hidden=false;label.style.left=`${box.x}px`;label.style.top=`${box.y}px`;
      const line=document.createElementNS('http://www.w3.org/2000/svg','line');
      for(const[k,v]of Object.entries({x1:box.anchorX,y1:box.anchorY,x2:box.x+box.width/2,y2:box.y+box.height/2,stroke:'#9ac8d2','stroke-width':1,opacity:.6}))line.setAttribute(k,v);leaders.append(line);
    }
    packet.visible=false;
    if(playback){const p=Math.max(0,Math.min(1,(now-playback.start)/playback.duration)),index=Math.min(playback.segments.length-1,Math.floor(p*playback.segments.length)),segment=playback.segments[index];
      const a=nodes.get(segment.source),b=nodes.get(segment.target);
      if(a&&b&&p<1){packet.visible=true;const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
        if(playback.lastIndex!==index){if($('eo-follow-hop').checked&&!reduced)focus(false,[segment.source,segment.target]);playback.lastIndex=index;}
        packet.position.lerpVectors(a.position,b.position,reduced?1:(p*playback.segments.length)%1);packet.scale.setScalar(Math.max(.03,camera.position.distanceTo(packet.position)*.9));
        $('eo-history').textContent=`${playback.committed?'Đã truyền':'Xem thử'} · chặng ${index+1}/${playback.segments.length}: ${segment.source} → ${segment.target} · ${fmt(segment.bandwidth_hz/1e6)} MHz · ${fmt(segment.power_w)} W`;}
      if(p===1){message(playback.committed?'Phát lại hoàn tất; pin đã cập nhật. Chạy lại phương pháp để gửi lượt tiếp.':'Xem thử hoàn tất; pin chưa thay đổi. Nhấn Truyền để thực hiện.');playback=null;if($('eo-follow-hop').checked)focus();}
    }
    if(historyPlayback&&!playback){const p=Math.max(0,Math.min(1,(now-historyPlayback.start)/historyPlayback.duration)),entry=historyPlayback.entries[Math.min(historyPlayback.entries.length-1,Math.floor(p*historyPlayback.entries.length))];
      $('eo-history').textContent=`Lịch sử ${entry.phase} · vòng ${entry.iteration} · Cost tốt nhất: ${fmt(entry.cost,5)}. Đường đang vẽ là phương án cuối.`;if(p===1)historyPlayback=null;}
    for(const mesh of routes.children){const style=mesh.userData;if(!style)continue;const distance=camera.position.distanceTo(mesh.position);
      if(style.arrow){const length=Math.min(style.linkLength*.2,distance*2*Math.tan(camera.fov*Math.PI/360)*7/Math.max(1,innerHeight));mesh.scale.y=length;mesh.scale.x=mesh.scale.z=length*.3;}
      else mesh.scale.x=mesh.scale.z=earthLinkRadius(distance,camera.fov,innerHeight,style.bandwidth,style.linkLength);}
  }
  // Only a demand crosses pages. State, plans and energy always come from the API.
  if(new URLSearchParams(location.search).get('optimizer')==='1'){
    let incoming=null;try{incoming=JSON.parse(sessionStorage.getItem('sagin-earth-request')||'null');sessionStorage.removeItem('sagin-earth-request');}catch{/* Default demand when storage is unavailable. */}
    open(incoming,Boolean(incoming));
  }
  function resize(){if(active&&camera.setViewOffset)camera.setViewOffset(innerWidth,innerHeight,Math.min(200,innerWidth*.23),0,innerWidth,innerHeight);}
  return{get active(){return active;},tick,open,close,resize};
}
