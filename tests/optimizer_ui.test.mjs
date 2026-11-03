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
const load=file=>import(`data:text/javascript;base64,${Buffer.from(read(file)).toString('base64')}`);
const { verifyOptimizerUI }=await load('./optimizer_ui_harness.js');
test('optimizer controller uses actual Python fixtures; DOM mock does not test rendering',async()=>{
  const script=`import json
from optimizer.service import OptimizerSession
from optimizer.models import Demand, Budget
s=OptimizerSession(deployment='regional',constellation='legacy')
initial=s.snapshot()
p=s.search(Demand(),'aco_pso',42,Budget(ants=6,aco_iterations=8,particles=8,pso_iterations=8))
t=s.transmit(p['plan_id'])
print(json.dumps({'initial':initial,'plan':p,'transmitted':t}))`;
  const fixtures=JSON.parse(execFileSync('python',['-c',script],{encoding:'utf8',cwd:new URL('../',import.meta.url),maxBuffer:2e6}));
  await verifyOptimizerUI(read('../web/js/optimizer/app.js'),read('../web/network.html'),fixtures);
});
