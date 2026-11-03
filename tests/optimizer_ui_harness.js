// DOM mock for controller logic; this does not replace a rendered-browser test.
export async function verifyOptimizerUI(source, html, fixtures) {
  const assert=(value,message)=>{if(!value)throw Error(message);};
  const ids={};
  class Element {
    constructor(id=''){this.id=id;this.children=[];this.events={};this.style={};this.attrs={};this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.classList={toggle(){},add(){},remove(){}};}
    append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
    replaceChildren(...children){this.children=[];this.append(...children);}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(e=>e!==this);}
    setAttribute(key,value){this.attrs[key]=String(value);}
    addEventListener(event,callback){this.events[event]=callback;}
    querySelector(selector){return this.children.find(e=>selector==='.packet'&&e.attrs.class==='packet')||null;}
    querySelectorAll(selector){return selector==='details'?[]:this.children;}
    checkValidity(){return true;}
    reportValidity(){return true;}
    getBoundingClientRect(){return {width:680,height:270};}
  }
  for(const m of html.matchAll(/id="([^"]+)"/g)){assert(!ids[m[1]],`Duplicate ID ${m[1]}`);ids[m[1]]=new Element(m[1]);}
  for(const m of source.matchAll(/\$\('([^']+)'\)/g))assert(ids[m[1]],`Missing HTML ID ${m[1]}`);
  const request={source:ids.source,target:ids.target};
  for(const [k,v]of Object.entries({data_mb:'0.1',required_mbps:'0.2',energy_weight:'0.5',method:'aco_pso',seed:'42',budget:'quick'})){request[k]=new Element(k);request[k].value=v;}
  const network={};for(const [k,v]of Object.entries({size:'small',deployment:'regional',battery_j:'1000',reserve_percent:'20',uav_count:''})){network[k]=new Element(k);network[k].value=v;}
  ids['request-form'].elements=request;ids['network-form'].elements=network;
  const fields=[...Object.values(request),...Object.values(network)];
  const document={getElementById:id=>{assert(ids[id],`Unknown ID ${id}`);return ids[id];},createElement:()=>new Element(),createElementNS:()=>new Element(),querySelectorAll:()=>fields};
  class FormDataMock {
    constructor(form){this.form=form;}
    *[Symbol.iterator](){for(const [key,value]of Object.entries(this.form.elements))if(!value.disabled)yield[key,String(value.value)];}
  }
  const calls=[],frames=new Map(),intervals=[],storage=new Map();let frameId=0;let current=structuredClone(fixtures.initial);let globeState=null;
  const fetch=async(url,options)=>{
    const path=url.split('/').at(-1),body=options?.body?JSON.parse(options.body):null;calls.push({path,body});
    let result;
    if(path==='state')result=current;
    else if(path==='reset'){current=structuredClone(fixtures.initial);result=current;}
    else if(path==='optimize')result={...structuredClone(fixtures.plan),method:body.method,revision:current.revision};
    else if(path==='transmit'){current=structuredClone(fixtures.transmitted.state);result={state:current,transfer:fixtures.transmitted.transfer};}
    else if(path==='advance'){current={...current,time_s:current.time_s+body.seconds,revision:current.revision+1};result=current;}
    else throw Error('Unexpected API request');
    return{ok:true,status:200,text:async()=>JSON.stringify(result)};
  };
  const code=source.replace(/^import .*;\r?$/gm,'').replace('await reconnect();','const ready=reconnect();');
  const app=new Function('document','fetch','FormData','setInterval','requestAnimationFrame','cancelAnimationFrame','performance','matchMedia','createGlobe','structuredClone','loadThree','sessionStorage','window',
    code+';return {ready,task,get:()=>({state,plan,results,busy,clockRunning}),requestData};')(
    document,fetch,FormDataMock,fn=>intervals.push(fn),fn=>{frames.set(++frameId,fn);return frameId;},id=>frames.delete(id),{now:()=>0},()=>({matches:false}),
    ()=>({update(s){globeState=s;},fit(){},replay(){},clearReplay(){}}),structuredClone,async()=>{},{setItem:(k,v)=>storage.set(k,v)},{addEventListener(){}});
  const settle=async()=>{for(let i=0;i<100;i++)await Promise.resolve();assert(!app.get().busy,'Task should finish');};
  await app.ready;assert(app.get().state.nodes.length===10,'Read initial network');
  assert(ids.source.value==='G1'&&ids.target.value==='G3','Opposite-cluster defaults');
  ids['request-form'].events.submit({preventDefault(){}});await settle();
  assert(app.get().plan.feasible,'Search should produce a feasible plan');
  assert(calls.find(c=>c.path==='optimize').body.request.data_mb===.1,'Form data captured before fields are disabled');
  assert(!ids.transmit.disabled,'Transmit enabled after search');
  ids.transmit.events.click();await settle();
  assert(app.get().state.served===1,'Commit updates served count');assert(ids.transmit.disabled,'Cannot commit same plan twice');assert(frames.size>0,'Replay scheduled only after commit');
  ids['request-form'].events.input();assert(app.get().plan===null,'Editing invalidates old plan');assert(frames.size===0,'Editing clears playback');
  ids.compare.events.click();await settle();assert(app.get().results.length===12,'Compare twelve methods');
  const compared=calls.filter(c=>c.path==='optimize').slice(-12);assert(new Set(compared.map(c=>c.body.seed)).size===1,'Paired seed in comparison');
  ids['view-on-earth'].events.click({preventDefault(){throw Error('Valid Earth navigation should not be blocked');}});
  const transferred=JSON.parse(storage.get('sagin-earth-request'));
  assert(transferred.method===request.method.value&&transferred.request.source===request.source.value,'Selected method and source cross into original Earth scene');
  assert(transferred.budget.particles===8,'Quick budget is preserved between pages');
  await ids['view-globe'].events.click();assert(globeState.revision===app.get().state.revision,'3D consumes the same authoritative state');
  ids['clock-toggle'].events.click();assert(app.get().plan===null,'Orbit motion invalidates plan');
  await intervals[1]();assert(app.get().state.revision>fixtures.initial.revision,'Orbit clock advances backend');
  network.size.events.change();assert(network.uav_count.value==='','Size change restores default constellation UAV count');
  network.size.value='small';network.deployment.value='distributed';ids['network-form'].events.submit({preventDefault(){},currentTarget:ids['network-form']});await settle();
  assert(calls.filter(c=>c.path==='reset').at(-1).body.deployment==='distributed','Workbench sends geographic deployment to backend');
  assert(app.get().state.served===0,'Reset clears served history');assert(ids.target.value==='G3','Reset selects opposite cluster');
  return 'Controller checks passed: initial connection, forms, optimize, commit, replay, invalidation, 12-method comparison, shared 3D state, clock and reset.';
}
