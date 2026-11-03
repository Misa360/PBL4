"""Real Chromium UI check, using an isolated local server/profile; no npm needed."""
import html
import json
import re
import subprocess
import tempfile
import threading
from functools import partial
from pathlib import Path
from http.server import ThreadingHTTPServer
from app.server import Handler, WEB, SimulationServer

RUNNER = r'''<!doctype html><meta charset="utf-8"><title>UI verification</title>
<iframe id="app" src="/network.html" style="width:1380px;height:1000px"></iframe><pre id="result">RUNNING</pre>
<script>
const output=document.querySelector('#result'), frame=document.querySelector('#app');
const checks=[],errors=[];
const assert=(condition,message)=>{if(!condition)throw Error(message);checks.push(message);output.textContent=JSON.stringify({ok:false,stage:'running',checks,errors});};
const pause=()=>new Promise(r=>setTimeout(r,30));
async function wait(fn,label){for(let i=0;i<1500;i++){if(await fn())return;await pause();}throw Error('Timeout: '+label);}
async function api(path,body){const r=await fetch('/api/optimizer/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error);return data;}
(async()=>{
 await wait(()=>frame.contentDocument?.querySelector('#connection')?.dataset.state==='ready','initial connection');
 const win=frame.contentWindow,doc=frame.contentDocument;
 win.addEventListener('error',event=>errors.push(event.message));
 win.addEventListener('unhandledrejection',event=>errors.push(String(event.reason)));
 const calls=[],original=win.fetch.bind(win);
 win.fetch=async(...args)=>{calls.push(String(args[0]));return original(...args);};
 assert(!doc.querySelector('[href="/reports/catalog.html"]')&&!doc.querySelector('#scenario-list'),'Catalog controls removed from simulation');
 assert(!doc.querySelector('[href^="/reports/"]'),'Experiment links removed from application');
 const {buildNetworkConfig}=await import('/js/optimizer/network-config.js');
 const shared={...await api('state'),traffic_pattern:'periodic',forecast_horizon:12,uav_count:22,forecast_load:false};
 const preserved=buildNetworkConfig(shared,{}),newSize=buildNetworkConfig(shared,{size:'small'});
 assert(preserved.traffic_pattern==='periodic'&&preserved.forecast_horizon===12&&preserved.uav_count===22&&!preserved.forecast_load,'Shared network config preserves traffic, forecast and custom UAV settings');
 assert(!Object.hasOwn(newSize,'uav_count'),'Changing network geometry uses its own default UAV count');
 const applied=await api('reset',preserved);
 assert(applied.traffic_pattern==='periodic'&&applied.forecast_horizon===12&&applied.uav_count===22&&!applied.forecast_load,'Shared configuration accepted by the real backend');
 await api('reset',{size:'small',constellation:'compact',battery_profile:'full',load_profile:'idle',forecast_load:true});
 doc.querySelector('#refresh-state').click();await wait(()=>doc.querySelector('#connection').dataset.state==='ready'&&!doc.querySelector('#optimize').disabled,'refresh');
 const form=doc.querySelector('#request-form');
 function demand(target='G2'){for(const [key,value] of Object.entries({source:'G1',target,data_mb:'.1',required_mbps:'.03',method:'ai_aco_pso',budget:'quick'}))form.elements[key].value=value;form.dispatchEvent(new win.Event('input',{bubbles:true}));}
 async function find(){form.requestSubmit();await wait(()=>!doc.querySelector('#transmit').disabled||doc.querySelector('#connection').dataset.state==='ready'&&doc.querySelector('#notice').classList.contains('error'),'search');if(doc.querySelector('#transmit').disabled)throw Error(doc.querySelector('#notice').textContent);}
 async function send(){const before=await api('state');doc.querySelector('#transmit').click();await wait(async()=>{const s=await api('state');return s.served===before.served+1&&doc.querySelector('#connection').dataset.state==='ready';},'transmit');return {before,after:await api('state')};}
 demand();await find();doc.querySelector('#compare').click();await wait(()=>doc.querySelector('#connection').dataset.state==='ready','core comparison');
 const compared=doc.querySelectorAll('#comparison-body tr');
 assert(compared.length===12&&compared[0].children.length===9,'All twelve methods compared on the same request');
 [...compared].find(row=>row.children[0].textContent==='ACO + PSO').click();
 assert(form.elements.method.value==='aco_pso'&&doc.querySelectorAll('#allocation-body tr').length>0,'Comparison rows select a plan and show per-hop resources');
 assert(doc.querySelector('#convergence-summary').textContent.includes('Cost đầu'),'Convergence reports initial and final cost');
 const axis=doc.querySelector('#chart-zero');axis.checked=true;axis.dispatchEvent(new win.Event('change'));
 assert(doc.querySelector('#convergence-summary').textContent.includes('Trục Y bắt đầu từ 0'),'Convergence zero-baseline toggle is explicit');
 axis.checked=false;axis.dispatchEvent(new win.Event('change'));
 const originalFrame=win.requestAnimationFrame.bind(win);let earlyFrame=false;
 win.requestAnimationFrame=callback=>originalFrame(time=>{if(!earlyFrame){earlyFrame=true;callback(time-10000);}else callback(time);});
 const first=await send();await wait(()=>earlyFrame,'early animation frame');win.requestAnimationFrame=originalFrame;
 assert(errors.length===0,'Replay accepts a frame timestamp earlier than its start');
 assert(first.after.served===1,'First transmission committed');
 assert(!doc.querySelector('#battery-result').hidden&&doc.querySelectorAll('#battery-changes tr').length>0,'Battery before/after table visible');
 assert(doc.querySelector('#route').textContent.includes('G1'),'Committed route remains visible');
 assert(doc.querySelector('#transmit').disabled,'Committed plan cannot transmit twice');
 const txCount=calls.filter(x=>x.endsWith('/transmit')).length;doc.querySelector('#transmit').click();await pause();
 assert(calls.filter(x=>x.endsWith('/transmit')).length===txCount,'Double click sends no duplicate commit');
 const changes=first.after.transfers.at(-1).battery_changes;
 assert(changes.every(c=>Math.abs(c.before_j-c.after_j-c.used_j)<1e-8)&&changes.some(c=>c.used_j>0),'Server battery ledger balances');
 await find();const second=await send();assert(second.after.served===2,'Repeated request commits a fresh plan');
 assert(second.after.nodes.filter(n=>n.battery_j!==null).some(n=>n.battery_j<first.after.nodes.find(p=>p.id===n.id).battery_j),'Repeated transmission reduces battery again');
 doc.querySelector('#observe-traffic').click();await wait(()=>!doc.querySelector('#optimize').disabled,'forecast observation');
 assert(doc.querySelector('#forecast-status').textContent.includes('mẫu gần nhất'),'Forecast shows measured Mbps samples');
 assert(doc.querySelector('#forecast-advice').dataset.level==='info','Few samples do not create a predictive congestion alert');
 const history=[...doc.querySelectorAll('.fc-dot')], future=[...doc.querySelectorAll('.fc-dot-forecast')];
 assert(history.length&&future.length&&+future[0].getAttribute('cx')>+history.at(-1).getAttribute('cx'),'Forecast plotted after last observation');
 const network=doc.querySelector('#network-form');network.elements.forecast_load.value='off';network.requestSubmit();await wait(()=>!doc.querySelector('#optimize').disabled,'reset forecast off');
 demand();await find();const off=await send();assert(off.after.nodes.every(n=>n.predicted_reserved_bandwidth_hz===0),'Forecast off stays off after transmission');
 assert(doc.querySelector('#forecast-status').textContent.includes('Dự báo tắt'),'Forecast disabled state visible');
 const beforeFailure=await api('state');demand('G3');form.elements.required_mbps.value='50';form.dispatchEvent(new win.Event('input',{bubbles:true}));
 form.requestSubmit();await wait(()=>doc.querySelector('#connection').dataset.state==='ready','infeasible request');
 const failed=await api('state');
 assert(doc.querySelector('#transmit').disabled&&failed.served===beforeFailure.served,'Infeasible demand cannot commit');
 assert(doc.querySelector('#plan-status').textContent.includes('Tốc độ đạt'),'Backend constraint diagnostics are visible on the frontend');
 assert(failed.nodes.every(n=>n.battery_j===beforeFailure.nodes.find(p=>p.id===n.id).battery_j),'Failed search does not debit battery');
 demand('G3');await find();const wide=await send();
 assert(wide.after.transfers.at(-1).path.some(id=>/^(LEO|MEO|GEO)/.test(id)),'Distributed intercontinental request uses satellites');
 network.elements.load_profile.value='busy';network.requestSubmit();await wait(()=>!doc.querySelector('#optimize').disabled,'busy background');
 const busyState=await api('state');const loaded=busyState.nodes.find(n=>n.reserved_bandwidth_hz/n.bandwidth_hz>=.85);
 const nodeSelect=doc.querySelector('#forecast-node-select');nodeSelect.value=loaded.id;nodeSelect.dispatchEvent(new win.Event('change'));
 assert(doc.querySelector('#forecast-advice').dataset.level==='caution'&&doc.querySelector('#forecast-advice').textContent.includes('Tải nền hiện tại cao'),'High observed background distinguished from a rising trend');
 network.elements.traffic_pattern.value='periodic';network.elements.load_profile.value='mixed';network.elements.forecast_load.value='on';network.requestSubmit();await wait(()=>!doc.querySelector('#optimize').disabled,'temporal traffic reset');
 const temporal=await api('state'),mostLoaded=temporal.nodes.reduce((a,b)=>a.reserved_bandwidth_hz>b.reserved_bandwidth_hz?a:b);
 nodeSelect.value=mostLoaded.id;nodeSelect.dispatchEvent(new win.Event('change'));
 doc.querySelector('#simulate-traffic').click();await wait(()=>!doc.querySelector('#optimize').disabled,'thirty seconds observation');
 const measured=await api('state'),flow=measured.traffic_forecast[mostLoaded.id].flow;
 assert(new Set(flow.history.map(r=>r.actual_mbps)).size>5,'Packet arrivals create real temporal variation in measured Mbps');
 doc.querySelector('#forecast-horizon').value='6';doc.querySelector('#forecast-horizon').dispatchEvent(new win.Event('change'));
 assert(flow.metrics['6'].samples>0&&flow.metrics['6'].mae_mbps>0,'Six-second forecasts are scored on later observations with nonzero errors');
 assert(doc.querySelector('.fc-verified')&&doc.querySelector('#forecast-status').textContent.includes('Mbps'),'Historical issued forecasts are plotted against actual traffic');
 const fixtures=await (await fetch('/test-support/fixtures')).json();
 const helpers=await Promise.all(['network-config.js','result-messages.js'].map(async name=>(await (await fetch('/js/optimizer/'+name)).text()).replace(/export function/g,'function')));
 const controller=async name=>helpers.join('\n')+'\n'+(await (await fetch('/js/optimizer/'+name)).text()).replace(/^import .*;\r?$/gm,'');
 const {verifyOptimizerUI}=await import('/test-support/optimizer_ui_harness.js');
 await verifyOptimizerUI(await controller('app.js'),await (await fetch('/network.html')).text(),fixtures);
 assert(true,'Workbench controller regression harness passes');
 const {verifyEarthOptimizer}=await import('/test-support/earth_optimizer_harness.js');
 await verifyEarthOptimizer(await controller('earth-optimizer.js'),await (await fetch('/index.html')).text(),fixtures);
 assert(true,'Earth controller preserves API preview, commit and reset semantics');
 assert(errors.length===0,'No uncaught frontend errors');
 frame.style.width='390px';await wait(()=>win.innerWidth<=392,'mobile viewport resize');
 assert(doc.documentElement.scrollWidth<=win.innerWidth+2,'Mobile page fits viewport; wide graphs scroll inside cards');
 win.scrollTo({top:Math.max(0,doc.querySelector('#traffic-forecast-section').getBoundingClientRect().top+win.scrollY-20),behavior:'instant'});
 output.textContent=JSON.stringify({ok:true,checks,errors});
})().catch(error=>{output.textContent=JSON.stringify({ok:false,error:String(error),checks,errors});});
</script>'''


class TestHandler(Handler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/test-support/'):
            name=self.path.removeprefix('/test-support/')
            if name=='fixtures':
                data=json.dumps(self.server.smoke_fixtures).encode()
                content_type='application/json'
            elif name in ('optimizer_ui_harness.js','earth_optimizer_harness.js'):
                data=(Path(__file__).parent/name).read_bytes();content_type='text/javascript'
            else:
                self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
        if self.path=='/ui-check':
            data=RUNNER.encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        else:
            super().do_GET()


def main():
    root=Path(__file__).resolve().parents[1]
    destination=root/'outputs/browser-check';destination.mkdir(parents=True,exist_ok=True)
    browser=next((p for p in [Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),
        Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')] if p.is_file()),None)
    if browser is None:raise RuntimeError('No local Chromium browser available')
    server=SimulationServer(('127.0.0.1',0))
    from optimizer.service import OptimizerSession
    from optimizer.models import Demand,Budget
    session=OptimizerSession(deployment='regional',constellation='legacy')
    initial=session.snapshot()
    plan=session.search(Demand(),'aco_pso',42,Budget(ants=6,aco_iterations=8,particles=8,pso_iterations=8))
    server.smoke_fixtures=dict(initial=initial,plan=plan,transmitted=session.transmit(plan['plan_id']),
        full=OptimizerSession(size='full',deployment='distributed',constellation='legacy').snapshot())
    server.RequestHandlerClass=partial(TestHandler,directory=str(WEB))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='profile-',dir=destination,ignore_cleanup_errors=True) as profile:
            assert Path(profile).resolve().is_relative_to(destination.resolve())
            command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
                '--disable-background-networking','--disable-extensions',f'--user-data-dir={profile}',
                '--dump-dom',f'--screenshot={destination/"screenshot.png"}','--virtual-time-budget=60000','--window-size=1440,1100',
                f'http://127.0.0.1:{server.server_port}/ui-check']
            result=subprocess.run(command,capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
            output=result.stdout.decode('utf-8',errors='replace')
            (destination/'dom.html').write_text(output,encoding='utf-8')
            (destination/'browser.log').write_bytes(result.stderr)
            found=re.search(r'<pre id="result">(.*?)</pre>',output,re.S)
            if not found:raise RuntimeError('No browser result; inspect outputs/browser-check/browser.log')
            value=html.unescape(found.group(1));print(value,flush=True)
            try:report=json.loads(value)
            except json.JSONDecodeError:report=dict(ok=False,error='Browser did not finish',last_state=value)
            (destination/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            if not report.get('ok'):raise AssertionError(report)
    finally:
        server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
