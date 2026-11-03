import { createGlobe, loadThree } from './globe.js';
import { buildNetworkConfig } from './network-config.js';
import { explainPlan } from './result-messages.js';

const $ = id => document.getElementById(id);
const names = {ai_aco_pso:'AI + ACO + PSO',min_hops:'BFS · ít chặng',shortest_distance:'Dijkstra · khoảng cách',min_delay:'Dijkstra · độ trễ',energy_pso:'Energy + PSO', pso:'Widest + PSO', random:'Random', greedy:'Greedy', widest:'Widest path', energy:'Energy path', aco:'ACO', widest_pso:'Widest + PSO', aco_pso:'ACO + PSO' };
const colors = { ground:'#68dfb1', UAV:'#ffc278', LEO:'#79caff', MEO:'#ba9aff', GEO:'#f19db1' };
const methods = ['random','greedy','min_hops','shortest_distance','min_delay','widest','energy','aco','widest_pso','energy_pso','aco_pso','ai_aco_pso'];
const methodNotes = {
  aco:'ACO tìm tuyến với mức cấp phát tài nguyên cố định.',
  aco_pso:'ACO tìm tuyến; PSO tinh chỉnh công suất và băng thông.',
  ai_aco_pso:'AI gợi ý tuyến và tài nguyên để ACO/PSO tinh chỉnh. Hiệu quả phụ thuộc kịch bản; có cơ chế dự phòng.',
  widest_pso:'Chọn tuyến theo dung lượng, rồi dùng PSO phân bổ tài nguyên.',
  energy_pso:'Chọn tuyến theo năng lượng, rồi dùng PSO phân bổ tài nguyên.',
  random:'Đi ngẫu nhiên trên các liên kết khả dụng; có thể bỏ lỡ tuyến hợp lệ.',
  greedy:'Chọn nút gần nhất ở mỗi bước; có thể đi vào nhánh cụt.',
  min_hops:'BFS tìm tuyến ít chặng nhất, chưa ưu tiên năng lượng hay độ trễ.',
  shortest_distance:'Dijkstra tìm tuyến có tổng khoảng cách nhỏ nhất.',
  min_delay:'Dijkstra ưu tiên thời gian truyền và truyền lan với cấp phát cố định.',
  widest:'Ưu tiên tuyến có dung lượng cổ chai lớn.',
  energy:'Dijkstra ưu tiên năng lượng phát và nhận với cấp phát cố định.'
};
const fmt = (v,d=3) => v == null ? '—' : Number(v).toLocaleString('vi-VN',{maximumFractionDigits:d});
let state, plan=null, results=[], selected, busy=false, connected=false, clockRunning=false, globe=null;
let positions={}, replayFrame=null, automaticCount=0, requestVersion=0;
let forecastNode=null;
let lastBatterySnapshot={};  // tracks battery_j before transmit for flash diff
const ns='http://www.w3.org/2000/svg';
function svg(tag,attrs={},text) { const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;return e; }
function notice(text,error=false) { $('notice').textContent=text;$('notice').classList.toggle('error',error); }
async function api(path,body) {
  let response;
  try {response=await fetch(`/api/optimizer/${path}`,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});}
  catch {connected=false;$('help').hidden=false;throw Error('Không kết nối được máy chủ Python. Kiểm tra python server.py rồi nhấn Kết nối lại.');}
  const text=await response.text();let data;
  try {data=JSON.parse(text);}catch {connected=false;$('help').hidden=false;throw Error('Máy chủ hiện tại không trả API tối ưu. Chạy lại python server.py và mở đúng cổng.');}
  if(!response.ok)throw Error(data.error||`Lỗi máy chủ ${response.status}`);
  return data;
}
function controls() {
  for(const id of ['optimize','compare','next-request','simulate-traffic','observe-traffic','clock-toggle'])$(id).disabled=busy||!connected;
  $('refresh-state').disabled=busy;
  $('view-on-earth').setAttribute('aria-disabled',String(busy||!connected));
  $('transmit').disabled=busy||!connected||!plan?.feasible||plan.revision!==state?.revision;
  $('export').disabled=!state;
  for(const field of document.querySelectorAll('#request-form input,#request-form select,#network-form input,#network-form select,#network-form button'))field.disabled=busy;
  $('clock-toggle').textContent=clockRunning?'Ⅱ Dừng quỹ đạo':'▶ Chạy quỹ đạo';
  $('connection').textContent=!connected?'Chưa kết nối':busy?'Đang tính…':clockRunning?'Quỹ đạo 60×':'Đã kết nối · tạm dừng';
  $('connection').setAttribute('data-state',!connected?'offline':busy?'busy':'ready');
}
function clearReplay() {if(replayFrame!==null)cancelAnimationFrame(replayFrame);replayFrame=null;$('network-map').querySelector('.packet')?.remove();globe?.clearReplay();}
function invalidate() {lastBatterySnapshot={};requestVersion++;plan=null;results=[];clockRunning=false;$('auto-requests').checked=false;clearReplay();render();}
function requestData() {
  const form=$('request-form');if(!form.checkValidity()){for(const d of form.querySelectorAll('details'))d.open=true;form.reportValidity();return null;}
  const v=Object.fromEntries(new FormData(form));
  return {request:{source:v.source,target:v.target,data_mb:Number(v.data_mb),required_mbps:Number(v.required_mbps),energy_weight:Number(v.energy_weight),latency_weight:Number(v.latency_weight??0)},method:v.method,seed:Number(v.seed),budget:v.budget==='quick'?{ants:6,aco_iterations:8,particles:8,pso_iterations:8}:v.budget==='half'?{aco_iterations:25,pso_iterations:25}: {}};
}
async function task(fn) {if(busy)return;busy=true;clockRunning=false;controls();try{await fn();}catch(error){$('auto-requests').checked=false;notice(error.message,true);}finally{busy=false;controls();}}
function fillStations(reset=false) {
  const grounds=state.nodes.filter(n=>n.kind==='ground');
  for(const id of ['source','target']) {
    const previous=reset?'':$(id).value;$(id).replaceChildren();
    for(const n of grounds){const e=document.createElement('option');e.value=n.id;e.textContent=n.name&&n.name!==n.id?`${n.id} · ${n.name}`:n.id;$(id).append(e);}
    $(id).value=grounds.some(n=>n.id===previous)?previous:id==='source'?'G1':grounds[grounds.length/2].id;
  }
  if($('source').value===$('target').value)$('target').value=grounds[grounds.length/2].id;
}
function map() {
  const root=$('network-map');root.replaceChildren();positions={};
  const defs=svg('defs');const marker=svg('marker',{id:'arrow',viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:4,markerHeight:4,orient:'auto-start-reverse'});marker.append(svg('path',{d:'M0 0L10 5L0 10z',fill:'#bceee1'}));defs.append(marker);root.append(defs);
  const small=state.size==='small';
  const largest=Math.max(...['GEO','MEO','LEO','UAV','ground'].map(k=>state.nodes.filter(n=>n.kind===k).length));
  const width=Math.max(1000,largest*48+140);root.setAttribute('viewBox','0 0 '+width+' 620');root.style.width=(width*.8)+'px';root.style.minWidth='100%';root.style.height='496px';
  const groups=[['GEO',70,'GEO · CỐ ĐỊNH SO VỚI MẶT ĐẤT'],['MEO',170,'MEO · QUỸ ĐẠO TRUNG'],['LEO',290,'LEO · QUỸ ĐẠO THẤP'],['UAV',420,'UAV · TRUNG CHUYỂN'],['ground',555,'TRẠM GỬI / NHẬN']];
  for(const [kind,y,label] of groups){const nodes=state.nodes.filter(n=>n.kind===kind);if(!nodes.length)continue;
    root.append(svg('text',{x:20,y:y-40,class:'layer-label'},label));
    nodes.forEach((node,i)=>{positions[node.id]=[nodes.length===1?width/2:70+i*(width-140)/(nodes.length-1),y];});
  }
  if($('show-links').checked)for(const l of state.links){if(l.source>l.target)continue;const a=positions[l.source],b=positions[l.target];root.append(svg('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:'edge'}));}
  if($('show-pheromone').checked&&plan?.pheromone?.length){const maximum=Math.max(...plan.pheromone.map(e=>e.value));const pairs=new Map();for(const e of plan.pheromone){const key=[e.source,e.target].sort().join('|');if(!pairs.has(key)||pairs.get(key).value<e.value)pairs.set(key,e);}for(const e of pairs.values()){const a=positions[e.source],b=positions[e.target];if(a&&b)root.append(svg('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:'#bf98ff','stroke-width':1+4*e.value/maximum,opacity:.1+.5*e.value/maximum}));}}
  if(plan?.segments)for(const s of plan.segments){const a=positions[s.source],b=positions[s.target];if(!a||!b)continue;const fraction=Math.min(...[s.source,s.target].map(id=>state.nodes.find(n=>n.id===id).battery_fraction));root.append(svg('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:'path-edge',stroke:`hsl(${fraction*120},70%,65%)`,'stroke-width':2+6*s.bandwidth_hz/20e6,'marker-end':'url(#arrow)'}));}
  for(const n of state.nodes){const [x,y]=positions[n.id];const g=svg('g',{class:'node',role:'button',tabindex:0,'aria-label':`${n.id}: ${n.battery_j==null?'điện lưới':fmt(n.battery_fraction*100)+'% pin'}`});
    const prevJ=lastBatterySnapshot[n.id];
    const battChanged=prevJ!=null&&n.battery_j!=null&&Math.abs(n.battery_j-prevJ)>0.001;
    const strokeColor=battChanged?'#ffdd55':selected===n.id?'white':'#10202e';
    const strokeW=battChanged?3:selected===n.id?3:1;
    g.append(svg('circle',{cx:x,cy:y,r:n.kind==='ground'||n.kind==='UAV'?17:12,fill:n.available?colors[n.kind]:'#5d6c7a',stroke:strokeColor,'stroke-width':strokeW}));
    g.append(svg('text',{x,y:y+31},n.id));g.append(svg('rect',{x:x-18,y:y+38,width:36,height:4,fill:'#2c4054',rx:2}));g.append(svg('rect',{x:x-18,y:y+38,width:36*n.battery_fraction,height:4,fill:`hsl(${n.battery_fraction*120},70%,60%)`,rx:2}));
    if(battChanged){const delta=n.battery_j-prevJ;g.append(svg('text',{x:x+20,y:y-2,fill:delta<0?'#ff8888':'#88ff88','font-size':9,'font-weight':'bold'},`${delta>0?'+':''}${delta.toFixed(1)}J`));g.classList.add('batt-changed');}
    const choose=()=>{selected=n.id;detail();map();$('forecast-node-select').value=n.id;loadForecast(n.id);};g.addEventListener('click',choose);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}});root.append(g);
  }
}
function detail() {
  const n=state.nodes.find(n=>n.id===selected)||state.nodes.find(n=>n.kind==='UAV');if(!n)return;selected=n.id;
  $('node-title').textContent=`${n.id} · ${n.kind==='ground'?'Trạm mặt đất':n.kind}`;
  const box=$('node-detail');box.replaceChildren();const track=document.createElement('div');track.className='battery-track';const fill=document.createElement('span');fill.style.width=`${n.battery_fraction*100}%`;fill.style.background=`hsl(${n.battery_fraction*120},70%,60%)`;track.append(fill);box.append(track);
  const dl=document.createElement('dl');for(const [key,value] of [['Trạng thái',n.available?'Sẵn sàng':'Không đủ pin hoặc băng thông'],['Pin hiện tại',n.battery_j==null?'Nguồn không giới hạn':`${fmt(n.battery_j)} / ${fmt(n.battery_capacity_j)} J`],['Băng thông tối đa',`${fmt(n.bandwidth_hz/1e6)} MHz`],['Băng thông còn',fmt((n.available_bandwidth_hz??n.bandwidth_hz)/1e6)+' MHz'],['Ngân sách sau dự báo',fmt((n.planning_bandwidth_hz??n.bandwidth_hz)/1e6)+' MHz'],['Công suất phát tối đa',`${fmt(n.p_max_w)} W`],['Chu kỳ quỹ đạo',n.period_s?`${fmt(n.period_s/60,1)} phút`:'—'],['Pin sau phương án',plan?.battery_after?.[n.id]!=null?`${fmt(plan.battery_after[n.id])} J`:'—']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=value;dl.append(dt,dd);}box.append(dl);
}
function chart() {
  const root=$('convergence');root.replaceChildren();const W=Math.max(280,Math.round(root.getBoundingClientRect().width||680));root.setAttribute('viewBox','0 0 '+W+' 270');root.style.height='270px';
  const history=plan?.search_history||[];
  const valid=history.filter(h=>Number.isFinite(h.cost));
  if(!valid.length){$('convergence-summary').textContent=plan?'Phương pháp này chưa có lịch sử Cost hợp lệ; đối chứng không lặp sẽ không có đường hội tụ.':'Chưa có kết quả tìm kiếm.';return;}
  const start=valid[0].cost,end=valid.at(-1).cost;
  const gain=start>0?100*(start-end)/start:0;
  const seen=plan?.aco_history?.at(-1)?.routes_seen;
  $('convergence-summary').textContent='Cost đầu '+fmt(start,8)+' → cuối '+fmt(end,8)+'; giảm '+fmt(gain,6)+'%.'+(Math.abs(gain)<1e-6?' Không ghi nhận cải thiện sau khởi tạo.':'')+(seen!=null?' ACO đã xét '+seen+' tuyến khác nhau.':'')+($('chart-zero').checked?' Trục Y bắt đầu từ 0.':' Trục Y phóng đại theo dải Cost, không bắt đầu từ 0.');
  const costs=valid.map(h=>h.cost),top=Math.max(...costs),bottom=Math.min(...costs);
  const pad=Math.max((top-bottom)*.15,Math.abs(top)*.002,1e-8);
  const low=$('chart-zero').checked?0:Math.max(0,bottom-pad),high=top+pad;
  const x=i=>72+(W-90)*i/Math.max(1,history.length-1),y=v=>218-170*(v-low)/(high-low);
  for(let i=0;i<5;i++){const value=low+(high-low)*i/4,py=y(value);root.append(svg('line',{x1:72,y1:py,x2:W-18,y2:py,stroke:'#28414f'}));root.append(svg('text',{x:3,y:py+4,fill:'#9ab8c8','font-size':11},fmt(value,7)));}
  let begin=0;
  while(begin<history.length){
    const key=history[begin].phase+history[begin].candidate;let endIndex=begin;
    while(endIndex+1<history.length&&history[endIndex+1].phase+history[endIndex+1].candidate===key)endIndex++;
    const phase=history[begin].phase,color=phase==='ACO'?'#7de4cf':phase==='AI'?'#c6a2ff':'#ffc278';
    const points=history.slice(begin,endIndex+1).map((h,j)=>h.cost==null?null:[x(begin+j),y(h.cost)]);
    let segment=[];
    const flush=()=>{if(segment.length)root.append(svg('polyline',{points:segment.map(p=>p.join(',')).join(' '),fill:'none',stroke:color,'stroke-width':2.5}));segment=[];};
    for(const point of points){if(point)segment.push(point);else flush();}flush();
    const first=history[begin],last=history[endIndex];
    root.append(svg('text',{x:x(begin),y:phase==='AI'?27:16,fill:color,'font-size':11},(phase==='PSO'?'PSO #'+first.candidate:phase)));
    if(begin)root.append(svg('line',{x1:x(begin),y1:35,x2:x(begin),y2:220,stroke:'#50707b','stroke-dasharray':'3 4'}));
    begin=endIndex+1;
  }
  for(let i=0;i<=4;i++){const index=Math.round((history.length-1)*i/4);root.append(svg('text',{x:x(index),y:240,fill:'#9ab8c8','font-size':11,'text-anchor':'middle'},index));}
  root.append(svg('text',{x:72,y:261,fill:'#9ab8c8','font-size':11},'Bước lưu kết quả · có điểm khởi tạo (vòng 0) cho từng giai đoạn'));
}
function table(id,rows,highlightFirst=false){const root=$(id);root.replaceChildren();if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.setAttribute('colspan',id==='comparison-body'?9:id==='allocation-body'?5:6);td.className='empty-state';td.textContent=id==='comparison-body'?'Chua co ket qua so sanh. Chon phuong phap va chay cung mot yeu cau.':'Chua co luot truyen. Lich su se xuat hien sau khi thuc hien phuong an.';tr.append(td);root.append(tr);return;}for(let i=0;i<rows.length;i++){const row=rows[i];const tr=document.createElement('tr');if(highlightFirst&&i===0)tr.className='newest-transfer';for(const value of row){const td=document.createElement('td');td.textContent=value;if(value==='Khong dat')td.className='failure';tr.append(td);}root.append(tr);}}
function render() {
  if(!state)return;
  $('network-summary').textContent=`${state.nodes.length} nút · phân bố rộng · mở để điều chỉnh`;
  $('method-description').textContent=methodNotes[$('request-form').elements.method.value]||'Tìm tuyến và kiểm tra tài nguyên theo yêu cầu hiện tại.';
  $('time').textContent=`${fmt(state.time_s,2)} s`;$('counts').textContent=`${state.nodes.length} nút · ${state.links.length/2} liên kết · ngưỡng pin ${fmt(state.reserve_fraction*100)}%`;
  const levels=state.nodes.filter(n=>n.battery_j!=null).reduce((a,n)=>{const level=n.battery_level||(n.battery_fraction<.2?'weak':n.battery_fraction<.7?'medium':'strong');a[level]++;return a;},{weak:0,medium:0,strong:0});$('counts').textContent+=' · Pin: '+levels.weak+' yếu / '+levels.medium+' trung bình / '+levels.strong+' mạnh';
  if(state.coverage)$('counts').textContent+=' · Kết nối '+state.coverage.connected_pairs+'/'+state.coverage.total_pairs+' cặp trạm';
  $('route').textContent=plan?.path?.length?`${plan.feasible?'Phương án':'Chưa đáp ứng'}: ${plan.path.join(' → ')}`:'Đường truyền sẽ xuất hiện sau khi tìm phương án.';
  $('plan-status').textContent=!plan?'Chưa có phương án. Hoàn thành bước 2 trước.':!plan.feasible?explainPlan(plan):plan.committed?'Đã truyền và cập nhật pin. Tìm lại phương án trước lượt tiếp.':plan.revision!==state.revision?'Phương án đã thực hiện hoặc mạng đã đổi. Tìm lại trước lượt tiếp.':`${names[plan.method]} · ${fmt(plan.duration_s)} giây mô phỏng · sẵn sàng truyền.`;
  $('metrics').replaceChildren();for(const [label,value,note] of [['Độ trễ truyền',plan?.duration_s!=null?`${fmt(plan.duration_s)} s`:'—','Truyền toàn khối và truyền lan'],['Tốc độ đầu cuối',plan?.rate_bps!=null?`${fmt(plan.rate_bps/1e6)} Mbps`:'—',`Yêu cầu: ${fmt(plan?.request?.required_mbps)} Mbps`],[plan?.committed?'Năng lượng đã dùng':'Năng lượng dự kiến',plan?.energy_j!=null?`${fmt(plan.energy_j)} J`:'—','Gồm điện nền và phát / nhận'],['Cost của phương án',fmt(plan?.cost,5),plan?.feasible?'Đáp ứng các ràng buộc':'Chỉ báo Cost khi hợp lệ'],['Thời gian tính',plan?`${fmt(plan.elapsed_ms,1)} ms`:'—',plan?`${plan.evaluations} lần đánh giá`:'Chưa chạy thuật toán']]){const div=document.createElement('div');div.className='metric';for(const[tag,text]of[['span',label],['strong',value],['small',note]]){const e=document.createElement(tag);e.textContent=text;div.append(e);}$('metrics').append(div);}
  detail();map();chart();globe?.update(state,plan,$('show-links').checked);
  if(plan?.ai)$('plan-status').textContent+=plan.ai.status==='ready'?` AI: ${plan.ai.feasible_hints}/${plan.ai.generated} gợi ý hợp lệ.`:' AI không có gợi ý hợp lệ; đã dùng ACO/PSO thường.';
  const baseline=results.find(r=>r.method==='aco');
  table('comparison-body',results.map(r=>[names[r.method],r.feasible?'Đạt':'Không đạt',fmt(r.cost,6),baseline?.feasible&&r.feasible?fmt((r.cost/baseline.cost-1)*100,6):'—',fmt(r.duration_s,6),fmt(r.rate_bps==null?null:r.rate_bps/1e6,6),fmt(r.energy_j,6),r.hops??'—',fmt(r.elapsed_ms,1)]));
  for(const [index,row] of [...$('comparison-body').children].entries())if(results[index]){
    row.tabIndex=0;row.setAttribute('role','button');row.title='Chọn phương án để xem phân bổ và truyền';
    const choose=()=>{if(busy||!results[index]||results[index].revision!==state.revision)return;plan=results[index];$('request-form').elements.method.value=plan.method;render();notice('Đã chọn '+names[plan.method]+'. Mở Phân bổ trên từng chặng để xem công suất và băng thông.');};
    row.addEventListener('click',choose);row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}});
  }
  table('allocation-body',(plan?.segments||[]).map(s=>[s.source,s.target,fmt(s.power_w,6),fmt(s.bandwidth_hz/1e6,6),fmt(s.rate_bps/1e6,6)]));
  const gain=plan?.refinement?.cost_improvement_pct;
  $('refinement-note').textContent=plan?.pso_histories?.length?(gain==null?'PSO đã kiểm tra lại cấp phát trên tuyến ứng viên.':gain>1e-6?'PSO giảm Cost '+fmt(gain,6)+'% so với phương án trước tinh chỉnh trong lượt này.':'PSO giữ mức Cost của phương án khởi tạo; xem các thông số để đối chiếu.'):'ACO dùng cấp phát cố định; PSO tìm công suất và băng thông trên tuyến.';

  const hasNewTransfer=Object.keys(lastBatterySnapshot).length>0&&state.transfers.length>0;
  table('transfers-body',state.transfers.slice().reverse().map(t=>[t.id,names[t.method],t.path.join(' > '),fmt(t.data_bits/8e6),fmt(t.duration_s),fmt(t.energy_j)]),hasNewTransfer);
  $('lifetime').textContent=`Đã phục vụ ${state.served} yêu cầu · ${fmt(state.data_bits/8e6)} MB. ${state.first_reserve_s==null?'Chưa có nút chạm ngưỡng dự trữ.':`Nút đầu chạm ngưỡng dự trữ: ${fmt(state.first_reserve_s)} s (cuối khoảng cập nhật).`} ${state.first_empty_s==null?'':`Nút đầu hết pin: ${fmt(state.first_empty_s)} s.`}`;
  const last=state.transfers.at(-1);
  const changes=(last?.battery_changes||[]).filter(n=>last.path.includes(n.id));
  $('battery-result').hidden=!changes.length;
  if(changes.length){
    table('battery-changes',changes.map(n=>[n.id,fmt(n.before_j,6),fmt(n.after_j,6),fmt(n.used_j,6)]));
    $('battery-summary').textContent='Lượt '+last.id+' · Tổng pin đã dùng: '+fmt(last.battery_used_j,6)+' J; năng lượng toàn mạng (kể cả nguồn điện lưới): '+fmt(last.energy_j,6)+' J. Nút ngoài tuyến chỉ tiêu thụ điện nền.';
  }
  fillForecastNodeSelect();
  if(forecastNode)loadForecast(forecastNode);
  controls();
}
function replay(transfer){clearReplay();if(!transfer.segments?.length)return;const dot=svg('circle',{r:6,fill:'white',stroke:'#7de4cf','stroke-width':3,class:'packet'});$('network-map').append(dot);const started=performance.now(),duration=Math.max(3000,transfer.segments.length*800);const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  $('playback-status').textContent=`Đã truyền ${fmt(transfer.data_bits/8e6)} MB, cập nhật pin. Đang phát lại ${transfer.segments.length} chặng (làm chậm, không theo tốc độ thực).`;
  globe?.replay(transfer);
  function frame(now){const p=Math.max(0,Math.min(1,(now-started)/duration)),i=Math.min(transfer.segments.length-1,Math.floor(p*transfer.segments.length)),s=transfer.segments[i];const a=positions[s.source],b=positions[s.target];if(!a||!b){clearReplay();return;}const u=reduced?1:(p*transfer.segments.length)%1;dot.setAttribute('cx',a[0]+(b[0]-a[0])*u);dot.setAttribute('cy',a[1]+(b[1]-a[1])*u);if(p<1)replayFrame=requestAnimationFrame(frame);else{dot.remove();replayFrame=null;$('playback-status').textContent='Đã phát lại xong. Nhấn Gửi yêu cầu tiếp để xem pin giảm qua nhiều lượt.';}}
  replayFrame=requestAnimationFrame(frame);
}
async function find(body,compare=false) {
  clearReplay();const version=requestVersion;
  if(compare){results=[];for(const method of [...new Set([...methods,body.method])]){notice(`Đang so sánh: ${names[method]}…`);const result=await api('optimize',{...body,method});if(result.revision!==state.revision){results=[];plan=null;throw Error('Mạng đã thay đổi ở cửa sổ khác. Nhấn Kết nối lại rồi so sánh lại.');}results.push(result);}plan=results.find(r=>r.method===body.method)||results[0];$('comparison-note').textContent=`Cùng revision ${state.revision}, seed ${body.seed}. Δ Cost âm là giảm so với ACO. Nhấn một dòng để xem phân bổ; các phương pháp có thể hội tụ cùng nghiệm.`;}
  else {plan=await api('optimize',body);if(plan.revision!==state.revision){plan=null;throw Error('Mạng đã thay đổi ở cửa sổ khác. Nhấn Kết nối lại trước khi tìm phương án.');}}
  if(version!==requestVersion){plan=null;return;}
  render();notice(plan.feasible?'Đã tìm được phương án. Nhấn Truyền dữ liệu để thực hiện và cập nhật pin.':explainPlan(plan));
}
$('request-form').addEventListener('submit',e=>{e.preventDefault();const body=requestData();if(body)task(()=>find(body));});
$('configure-network').addEventListener('click',()=>{$('network-settings').open=true;});
$('compare').addEventListener('click',()=>{const body=requestData();if(body)task(()=>find(body,true));});
$('view-on-earth').addEventListener('click',event=>{
  if(busy||!connected){event.preventDefault();return;}
  const body=requestData();if(!body){event.preventDefault();return;}
  try{sessionStorage.setItem('sagin-earth-request',JSON.stringify(body));}
  catch{event.preventDefault();notice('Không lưu được lựa chọn giữa hai trang. Mở Trái Đất 3D và chọn phương pháp trực tiếp tại đó.',true);}
});
$('request-form').addEventListener('input',()=>{if(state)invalidate();$('weight-label').textContent=Number($('request-form').elements.energy_weight.value).toFixed(2);});
$('network-form').addEventListener('submit',e=>{e.preventDefault();if(!e.currentTarget.checkValidity()){for(const details of e.currentTarget.querySelectorAll('details'))details.open=true;e.currentTarget.reportValidity();return;}const values=Object.fromEntries(new FormData(e.currentTarget));task(async()=>{const config=buildNetworkConfig(state,values);state=await api('reset',config);invalidate();automaticCount=0;fillStations(true);render();globe?.fit();notice('Đã tạo mạng mới. Chọn yêu cầu rồi tìm phương án.');});});
$('network-form').elements.size.addEventListener('change',()=>{$('network-form').elements.uav_count.value='';});
async function send(){
  if(!plan?.feasible||plan.committed||plan.revision!==state?.revision)return;
  // Snapshot battery before transmit so map() can flash changed nodes
  lastBatterySnapshot={};
  for(const n of (state?.nodes||[]))if(n.battery_j!=null)lastBatterySnapshot[n.id]=n.battery_j;
  let response;
  try{response=await api('transmit',{plan_id:plan.plan_id});}
  catch(error){plan=null;lastBatterySnapshot={};try{state=await api('state');render();}catch{}throw error;}
  const transfer=response.transfer;
  state=response.state;
  plan={...plan,committed:true};
  results=[];
  render();
  replay(transfer);
  const changes=transfer.battery_changes||state.nodes.filter(n=>n.battery_j!=null&&lastBatterySnapshot[n.id]!=null).map(n=>({id:n.id,used_j:lastBatterySnapshot[n.id]-n.battery_j}));
  const used=transfer.battery_used_j??changes.reduce((sum,n)=>sum+n.used_j,0);
  notice('Đã truyền '+fmt(transfer.data_bits/8e6,4)+' MB · '+fmt(transfer.duration_s)+' s · tiêu hao pin '+fmt(used,6)+' J. Tuyến và pin trước/sau được giữ bên dưới.');
  // Flash notice with success animation
  const noticeEl=$('notice');
  noticeEl.classList.remove('transmit-success');
  void noticeEl.offsetWidth; // force reflow to restart animation
  noticeEl.classList.add('transmit-success');
  setTimeout(()=>noticeEl.classList.remove('transmit-success'),3000);
  const committedRevision=state.revision;
  setTimeout(()=>{if(state?.revision===committedRevision){lastBatterySnapshot={};if(replayFrame===null)render();}},8000);
}
$('transmit').addEventListener('click',()=>task(send));
$('next-request').addEventListener('click',()=>{const body=requestData();if(body)task(async()=>{await find(body);if(plan?.feasible)await send();});});
$('auto-requests').addEventListener('change',()=>{automaticCount=0;clockRunning=false;controls();});
setInterval(()=>{if(!$('auto-requests').checked||busy||!connected||replayFrame!==null)return;if(automaticCount>=20){$('auto-requests').checked=false;notice('Đã hoàn tất tối đa 20 yêu cầu tự động.');return;}const body=requestData();if(!body){$('auto-requests').checked=false;return;}automaticCount++;task(async()=>{await find(body);if(plan?.feasible)await send();else $('auto-requests').checked=false;});},500);
$('clock-toggle').addEventListener('click',()=>{clockRunning=!clockRunning;$('auto-requests').checked=false;if(clockRunning){plan=null;results=[];clearReplay();render();}controls();});
setInterval(async()=>{if(!clockRunning||busy||!connected)return;busy=true;controls();try{state=await api('advance',{seconds:30});render();}catch(e){clockRunning=false;notice(e.message,true);}finally{busy=false;controls();}},500);
async function reconnect(){await task(async()=>{clearReplay();$('auto-requests').checked=false;state=await api('state');connected=true;$('help').hidden=true;plan=null;results=[];fillStations();const form=$('network-form');form.elements.size.value=state.size;if(form.elements.constellation)form.elements.constellation.value=state.constellation||'balanced';form.elements.reserve_percent.value=state.reserve_fraction*100;form.elements.battery_j.value=state.nodes.find(n=>n.kind==='UAV').battery_capacity_j;form.elements.uav_count.value=state.uav_count;if(form.elements.forecast_load)form.elements.forecast_load.value=state.forecast_load?'on':'off';for(const key of ['traffic_pattern','battery_profile','load_profile','state_seed'])if(form.elements[key])form.elements[key].value=state[key]??(key==='state_seed'?42:key==='load_profile'?'idle':'full');render();notice('Sẵn sàng. Chọn yêu cầu rồi tìm phương án. Có thể chọn chùm vệ tinh Tăng phủ để thử nhiều tuyến dự phòng.');});}
$('reconnect').addEventListener('click',reconnect);
$('refresh-state').addEventListener('click',reconnect);
$('view-logical').addEventListener('click',()=>{$('logical-view').hidden=false;$('globe-view').hidden=true;$('view-logical').classList.add('selected');$('view-globe').classList.remove('selected');});
$('view-globe').addEventListener('click',async()=>{$('logical-view').hidden=false;$('globe-view').hidden=false;$('view-globe').classList.add('selected');$('view-logical').classList.remove('selected');if(!globe){$('view-globe').disabled=true;try{await loadThree();globe=createGlobe($('globe-canvas'),id=>{selected=id;detail();map();});if(state){globe.update(state,plan,$('show-links').checked);globe.fit();}$('globe-status').textContent='Kéo để xoay · cuộn để phóng to · nhấn nút để xem pin. Vị trí theo tỷ lệ; kích thước dấu nút được phóng đại.';$('logical-view').hidden=!$('globe-view').hidden;}catch(e){$('globe-status').textContent=e.message;}finally{$('view-globe').disabled=false;}}else $('logical-view').hidden=true;});
$('globe-fit').addEventListener('click',()=>globe?.fit());
$('network-form').elements.constellation?.addEventListener('change',()=>{$('network-form').elements.uav_count.value='';});
for(const id of ['chart-zero','show-links','show-pheromone'])$(id).addEventListener('change',()=>{if(state)render();});
$('export').addEventListener('click',()=>{if(!state)return;const blob=new Blob([JSON.stringify({state,plan,comparison:results},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`sagin-${state.revision}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});

// ── Traffic Forecast ────────────────────────────────────────────────────────
function fillForecastNodeSelect() {
  if (!state) return;
  const sel = $('forecast-node-select');
  const prev = forecastNode || selected || sel.value;
  sel.replaceChildren();
  const empty = document.createElement('option'); empty.value=''; empty.textContent='— Chọn nút —'; sel.append(empty);
  for (const n of state.nodes) {
    const opt = document.createElement('option');
    opt.value = n.id;
    opt.textContent = n.name && n.name !== n.id ? `${n.id} · ${n.name}` : n.id;
    sel.append(opt);
  }
  if (prev && state.nodes.some(n => n.id === prev)){sel.value = prev;forecastNode=prev;}
}

function drawForecastChart(nodeId, data) {
  const root=$('forecast-chart');root.replaceChildren();const W=Math.max(260,Math.round(root.getBoundingClientRect().width||760));root.setAttribute('viewBox','0 0 '+W+' 270');root.style.height='270px';
  const flow=data.flow,history=flow?.history||[];
  if(!history.length){root.append(svg('text',{x:40,y:100,fill:'#a8c9d4','font-size':15},'Chưa có mẫu lưu lượng mới. Chọn kiểu biến thiên rồi quan sát 30 giây.'));return;}
  const horizon=Number($('forecast-horizon').value),key='predicted_h'+horizon;
  const future=flow.forecast_mbps,first=history[0].sample,last=history.at(-1).sample;
  const max=Math.max(1,...history.flatMap(r=>[r.actual_mbps,r[key]??0]),...future)*1.1;
  const x=s=>52+(s-first)/Math.max(1,last+future.length-first)*(W-68),y=v=>222-v/max*184;
  for(let i=0;i<5;i++){const v=max*i/4;root.append(svg('line',{x1:52,y1:y(v),x2:W-16,y2:y(v),class:'fc-grid'}));root.append(svg('text',{x:5,y:y(v)+4,class:'fc-label'},fmt(v,2)));}
  root.append(svg('text',{x:5,y:20,class:'fc-label'},'Mbps'));
  const line=(rows,field,css)=>{let points=[];const flush=()=>{if(points.length)root.append(svg('polyline',{points:points.join(' '),fill:'none',class:css}));points=[];};for(const row of rows){if(Number.isFinite(row[field]))points.push(x(row.sample)+','+y(row[field]));else flush();}flush();};
  line(history,'actual_mbps','fc-history');line(history,key,'fc-verified');
  line([{sample:last,value:history.at(-1).actual_mbps},...future.map((value,i)=>({sample:last+i+1,value}))],'value','fc-future');
  for(const row of history)root.append(svg('circle',{cx:x(row.sample),cy:y(row.actual_mbps),r:2.5,class:'fc-dot'}));
  future.forEach((v,i)=>root.append(svg('circle',{cx:x(last+i+1),cy:y(v),r:3,class:'fc-dot-forecast'})));
  root.append(svg('line',{x1:x(last),y1:30,x2:x(last),y2:225,class:'fc-divider'}));
  root.append(svg('text',{x:x(last)+5,y:30,class:'fc-label'},'tương lai →'));
  const ticks=W<450?3:5;for(let i=0;i<=ticks;i++){const sample=Math.round(first+(last+future.length-first)*i/ticks);root.append(svg('text',{x:x(sample),y:248,class:'fc-label','text-anchor':'middle'},sample+' s'));}
}
async function loadForecast(nodeId) {
  if (!nodeId || !connected) return;
  forecastNode = nodeId;
  const revision=state?.revision;
  try {
    let data;
    // Use cached forecast from state snapshot if available
    if (state?.traffic_forecast?.[nodeId]) {
      data = state.traffic_forecast[nodeId];
    } else {
      const resp = await fetch(`/api/optimizer/forecast?node=${encodeURIComponent(nodeId)}&steps=6`, {cache:'no-store'});
      const json = await resp.json();
      if (!resp.ok) { $('forecast-status').textContent = json.error || 'Lỗi API dự báo'; return; }
      data = json.nodes[nodeId];
    }
    if(forecastNode!==nodeId||state?.revision!==revision)return;
    if (!data) { $('forecast-status').textContent = 'Không có dữ liệu cho nút này.'; return; }
    drawForecastChart(nodeId, data);
    const badge=$('forecast-trend-badge'),flowData=data.flow,rows=flowData?.history||[];
    const h=Number($('forecast-horizon').value)||1,lastRate=rows.at(-1)?.actual_mbps??0;
    const delta=(flowData?.forecast_mbps?.[h-1]??lastRate)-lastRate,threshold=Math.max(.1,lastRate*.03);
    const trend=delta>threshold?'increasing':delta< -threshold?'decreasing':'stable';
    badge.textContent='Dự báo '+h+' giây: '+{increasing:'tăng',decreasing:'giảm',stable:'ổn định'}[trend]+' so với mẫu gần nhất';
    badge.setAttribute('data-trend',trend);badge.hidden=!rows.length;
    const advice=data.capacity_advice||{state:'learning',level:'info'};
    const messages={
      observed_high:'Tải nền hiện tại cao ('+fmt((data.background_fraction??0)*100,1)+'%). Còn ít băng thông cho yêu cầu mới; chưa đủ để kết luận nghẽn mạng.',
      forecast_high:'Dự báo tải nền giây tới đạt '+fmt((data.background_forecast??0)*100,1)+'%. Cân nhắc giảm tốc độ yêu cầu hoặc chọn thời điểm khác.',
      learning:'Đang thu thập mẫu: cần ít nhất 6 mẫu mới trước khi đánh giá dự báo tải cao.',
      unreliable:'Dự báo chưa vượt đối chứng trên phần đã đo. Bộ dự báo chọn tự hồi quy, Holt hoặc giữ mẫu gần nhất theo sai số quá khứ.',
      disabled:'Dự báo đang tắt; phân bổ dùng băng thông còn lại theo tải nền hiện tại.',
      normal:'Chưa thấy tải nền gần ngưỡng 85%. Lưu lượng dự báo tăng không tự chứng minh nghẽn mạng.'
    };
    $('forecast-advice').textContent=messages[advice.state]||messages.learning;
    $('forecast-advice').setAttribute('data-level',advice.level);
    const flow=data.flow,metric=flow?.metrics?.[$('forecast-horizon').value];
    const strategy=flow?.strategies?.[Number($('forecast-horizon').value)-1]||flow?.strategy;const mode={holt:'Holt giảm xu hướng',ar:'tự hồi quy từ 6 mẫu gần nhất',persistence:'giữ nguyên mẫu gần nhất'}[strategy]||'chưa đủ dữ liệu';
    const values=(flow?.history||[]).map(r=>r.actual_mbps);
    const flat=values.length>1&&Math.max(...values)-Math.min(...values)<1e-9;
    $('forecast-status').textContent=flow?('Lưu lượng đến nền · '+values.length+' mẫu gần nhất · dự báo dùng '+mode+'. '+(metric?.samples?'Đối chiếu '+metric.samples+' dự báo phát trước '+$('forecast-horizon').value+' giây: MAE '+fmt(metric.mae_mbps,3)+' Mbps; đối chứng '+fmt(metric.persistence_mae_mbps,3)+' Mbps.':'Chưa đủ mẫu tương lai để chấm sai số ở mốc này.')+(flat?' Chuỗi đang không đổi; sai số bằng 0 không chứng minh khả năng dự báo biến động.':'')+(data.enabled?' Dự báo bật.':' Dự báo tắt: chỉ quan sát.')):'Máy chủ chưa có dữ liệu lưu lượng Mbps; cần khởi động lại.';

  } catch(e) {
    $('forecast-status').textContent = 'Không tải được dữ liệu dự báo.';
  }
}

$('observe-traffic').addEventListener('click',()=>task(async()=>{invalidate();state=await api('advance',{seconds:1});render();notice('Đã quan sát thêm 1 giây và trừ điện nền. Tìm lại phương án trước khi truyền.');}));
$('simulate-traffic').addEventListener('click',()=>task(async()=>{invalidate();state=await api('advance',{seconds:30});render();notice('Đã quan sát 30 giây lưu lượng mới và cập nhật pin điện nền. Các dự báo cũ được đối chiếu với mẫu mới.');}));
$('forecast-horizon').addEventListener('change',()=>{if(forecastNode)loadForecast(forecastNode);});
$('forecast-node-select').addEventListener('change', e => { if(e.target.value) loadForecast(e.target.value); });
window.addEventListener('resize',()=>{if(state){chart();if(forecastNode)loadForecast(forecastNode);}});
await reconnect();
