import test from 'node:test';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
const raw=file=>readFileSync(new URL(file,import.meta.url),'utf8');
const read=file=>{
  const source=raw(file);
  if(file.endsWith('/optimizer/app.js')||file.endsWith('/optimizer/earth-optimizer.js')){
    const shared=['network-config.js','result-messages.js'].map(name=>raw('../web/js/optimizer/'+name).replace(/export function/g,'function')).join('\n');
    return shared+'\n'+source.replace(/^import .*;\r?$/gm,'');
  }
  return source;
};
const { verifyEarthOptimizer }=await import(`data:text/javascript;base64,${Buffer.from(read('./earth_optimizer_harness.js')).toString('base64')}`);
test('route labels separate coincident anchors and avoid panels',()=>{
  const source=read('../web/js/optimizer/earth-optimizer.js').replace(/export function/g,'function');
  const layout=new Function(source+';return layoutEarthLabels;')();
  const items=['G1','U1','LEO1','U5','G10'].map((id,i)=>({id,x:380,y:320,width:115,height:40,priority:i===0||i===4?0:1}));
  const reserved=[{x:640,y:112,width:340,height:480},{x:20,y:116,width:240,height:285},{x:0,y:590,width:1000,height:110}];
  const result=layout(items,1000,700,reserved);
  if(result.length!==5)throw Error('Every route node must be readable');
  const overlap=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
  for(let i=0;i<result.length;i++){
    if(reserved.some(r=>overlap(result[i],r)))throw Error('Label overlaps a HUD panel');
    if(result.slice(i+1).some(r=>overlap(result[i],r)))throw Error('Route labels overlap');
  }
});
test('radio tube stays within 2.3 pixels radius as camera zooms',()=>{
  const source=read('../web/js/optimizer/earth-optimizer.js').replace(/export function/g,'function');
  const radius=new Function(source+';return earthLinkRadius;')();
  for(const d of [.003,.03,.3,3,30]){
    const r=radius(d,45,900,20e6,1),pixels=r*900/(d*2*Math.tan(Math.PI/8));
    if(pixels>2.300001||r>.025)throw Error('Radio link becomes an oversized ribbon');
  }
});
test('original Earth scene controller: preview is read-only and transmission is once-only',async()=>{
  const script=`import json
from optimizer.service import OptimizerSession
from optimizer.models import Demand, Budget
s=OptimizerSession(deployment='regional',constellation='legacy')
initial=s.snapshot()
p=s.search(Demand(),'aco_pso',42,Budget(ants=6,aco_iterations=8,particles=8,pso_iterations=8))
t=s.transmit(p['plan_id'])
print(json.dumps({'initial':initial,'plan':p,'transmitted':t,'full':OptimizerSession(size='full',deployment='distributed',constellation='legacy').snapshot()}))`;
  const fixtures=JSON.parse(execFileSync('python',['-c',script],{encoding:'utf8',cwd:new URL('../',import.meta.url),maxBuffer:2e6}));
  await verifyEarthOptimizer(read('../web/js/optimizer/earth-optimizer.js'),read('../web/index.html'),fixtures);
});
