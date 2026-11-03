// Controller/geometry mocks only: this verifies API semantics, not WebGL pixels.
export async function verifyEarthOptimizer(source, html, fixtures) {
  const assert=(v,message)=>{if(!v)throw Error(message);};
  class V {
    constructor(x=0,y=0,z=0){this.x=x;this.y=y;this.z=z;}
    clone(){return new V(this.x,this.y,this.z);}copy(p){Object.assign(this,{x:p.x,y:p.y,z:p.z});return this;}
    add(p){this.x+=p.x;this.y+=p.y;this.z+=p.z;return this;}
    sub(p){this.x-=p.x;this.y-=p.y;this.z-=p.z;return this;}
    multiplyScalar(s){this.x*=s;this.y*=s;this.z*=s;return this;}
    addScaledVector(p,s){return this.add(p.clone().multiplyScalar(s));}
    lengthSq(){return this.x*this.x+this.y*this.y+this.z*this.z;}length(){return Math.sqrt(this.lengthSq());}
    normalize(){return this.multiplyScalar(1/(this.length()||1));}dot(p){return this.x*p.x+this.y*p.y+this.z*p.z;}
    cross(p){const {x,y,z}=this;this.x=y*p.z-z*p.y;this.y=z*p.x-x*p.z;this.z=x*p.y-y*p.x;return this;}
    distanceTo(p){return this.clone().sub(p).length();}
    lerpVectors(a,b,t){return this.copy(a).addScaledVector(b.clone().sub(a),t);}
    project(){return this;}
  }
  class Obj {constructor(g,m){this.children=[];this.position=new V();this.scale={setScalar(){}};this.quaternion={setFromUnitVectors(){}};this.geometry=g;this.material=m;this.visible=true;}add(...xs){this.children.push(...xs);}remove(x){this.children=this.children.filter(y=>y!==x);}}
  class Geo {dispose(){}setFromPoints(){return this;}}
  class Color {setHSL(){return this;}setHex(){return this;}}
  class Material {constructor(){this.color=new Color();}dispose(){}}
  class Box {constructor(){this.points=[];}expandByPoint(p){this.points.push(p.clone());}getCenter(v){for(const p of this.points)v.add(p);return v.multiplyScalar(1/this.points.length);}getSize(v){v.x=.1;v.y=.1;v.z=.1;return v;}}
  const THREE={Group:Obj,Mesh:Obj,Line:Obj,Vector3:V,Box3:Box,SphereGeometry:Geo,CylinderGeometry:Geo,ConeGeometry:Geo,BufferGeometry:Geo,MeshBasicMaterial:Material,LineBasicMaterial:Material,Color,MathUtils:{degToRad:x=>x*Math.PI/180}};
  const ids={};
  class Element {constructor(){this.children=[];this.events={};this.value='';this.style={};this.attrs={};this.classList={add(){},remove(){},toggle(){}};}setAttribute(k,v){this.attrs[k]=v;}replaceChildren(...xs){this.children=xs;}append(...xs){this.children.push(...xs);}remove(){}addEventListener(k,fn){this.events[k]=fn;}querySelectorAll(){return Object.values(this.elements||{});}}
  for(const m of html.matchAll(/id="([^"]+)"/g))ids[m[1]]=new Element();
  ids['eo-route-only'].checked=true;
  ids['eo-follow-hop'].checked=true;
  const form=ids['eo-form'];form.elements={};
  ids['eo-network-form'].elements={size:new Element(),deployment:new Element()};ids['eo-network-form'].elements.size.value='small';ids['eo-network-form'].elements.deployment.value='regional';
  for(const[k,v]of Object.entries({method:'aco_pso',source:'',target:'',data_mb:'.1',required_mbps:'.2',seed:'42',energy_weight:'.5'})){const e=new Element();e.value=v;form.elements[k]=e;}
  const document={getElementById:id=>{assert(ids[id],`Missing Earth HTML id ${id}`);return ids[id];},createElement:()=>new Element(),createElementNS:()=>new Element(),createTextNode:text=>({textContent:text}),body:new Element()};
  const calls=[],modes=[];let current=structuredClone(fixtures.initial);
  const fetch=async(url,options)=>{const path=url.split('/').at(-1),body=options?.body?JSON.parse(options.body):null;calls.push({path,body});
    let result;if(path==='state')result=current;else if(path==='optimize')result=fixtures.plan;else if(path==='transmit'){result=fixtures.transmitted;current=result.state;}else if(path==='reset'){result=body.size==='full'?fixtures.full:fixtures.initial;current=structuredClone(result);}else throw Error(path);
    return{ok:true,json:async()=>structuredClone(result)};};
  const camera={position:new V(0,0,3),near:.1,far:1000,fov:45,setViewOffset(...values){this.offset=values;},updateProjectionMatrix(){},updateMatrixWorld(){}};
  const controls={target:new V(),update(){}};const scene=new Obj();
  class FormDataMock {constructor(form){this.form=form;}*[Symbol.iterator](){for(const[key,value]of Object.entries(this.form.elements))if(!value.disabled)yield[key,String(value.value)];}}
  const mount=new Function('FormData','THREE','document','fetch','performance','URLSearchParams','location','innerWidth','innerHeight','matchMedia',source.replace(/export function/g,'function')+';return mountEarthOptimizer;')(
    FormDataMock,THREE,document,fetch,{now:()=>0},class{get(){return null;}},{search:''},1200,800,()=>({matches:false}));
  const app=mount({scene,camera,controls,renderer:{},setMode:value=>modes.push(value)});
  const incoming={request:{source:'G1',target:'G3',data_mb:.1,required_mbps:.2,energy_weight:.5},method:'aco_pso',seed:42,budget:{ants:6,particles:8,aco_iterations:8,pso_iterations:8}};
  await app.open(incoming,true);
  assert(app.active,'Opens optimizer on original scene');
  const search=calls.find(c=>c.path==='optimize');assert(search.body.request.source==='G1','Transferred source is kept even while form disabled');
  assert(search.body.budget.particles===8,'Search budget crosses pages');
  assert(!ids['eo-preview'].disabled&&!ids['eo-transmit'].disabled,'Valid plan enables preview and transmission');
  assert(form.elements.source.children.length===4,'Small scene offers four ground stations');
  assert(ids['eo-hop-list'].children.filter(e=>e.type==='button').length===fixtures.plan.path.length,'Every real route node is present in the overview');
  assert(ids['eo-route-title'].textContent.includes('G1')&&ids['eo-route-title'].textContent.includes('G3'),'Overview identifies both endpoints');
  assert(camera.offset[2]>0,'Camera leaves space for the right-hand panel');
  const before=calls.length;ids['eo-preview'].events.click();app.tick(500);
  assert(calls.length===before,'Preview never calls a mutating API');
  ids['eo-transmit'].events.click();for(let i=0;i<30;i++)await Promise.resolve();
  assert(calls.filter(c=>c.path==='transmit').length===1,'Transmission calls commit exactly once');
  assert(ids['eo-transmit'].disabled,'Committed plan cannot transmit again');
  form.events.input();assert(ids['eo-preview'].disabled,'Changing method invalidates preview');
  ids['eo-network-form'].elements.size.value='full';
  ids['eo-network-form'].elements.deployment.value='distributed';
  ids['eo-network-form'].events.submit({preventDefault(){}});for(let i=0;i<40;i++)await Promise.resolve();
  assert(form.elements.source.children.length===10&&form.elements.target.children.length===10,'Full scene offers ten stations in both selectors');
  assert(form.elements.source.value==='G1'&&form.elements.target.value==='G6','Full scene defaults to opposite clusters');
  assert(ids['eo-preview'].disabled&&ids['eo-transmit'].disabled,'Changing network removes old plans');
  assert(calls.filter(c=>c.path==='reset').length===1,'Applying a size resets once, without transmitting');
  assert(calls.find(c=>c.path==='reset').body.deployment==='distributed','Wide deployment is sent to the physics backend');
  ids['eo-network-form'].elements.size.value='small';
  ids['eo-network-form'].events.submit({preventDefault(){}});for(let i=0;i<40;i++)await Promise.resolve();
  assert(form.elements.source.children.length===4&&form.elements.target.value==='G3','Switching back removes obsolete station choices');
  app.close();assert(!app.active&&modes.join(',')==='true,false','Closing restores original scene mode');
  return 'Earth controller passed: shared demand/budget, read-only preview, one commit, 10/39-node switching, station refresh, plan invalidation and scene restoration.';
}
