"""Create a standalone, searchable catalog of generated network scenarios."""
import argparse
import json
from pathlib import Path


def catalog(datasets, output):
    output = Path(output)
    index_rows = []
    rows = []
    for directory in map(Path,datasets):
        for split in ('train','validation','test'):
            offset = 0
            for raw in (directory/f'{split}.jsonl').open('rb'):
                line = raw.decode('utf-8')
                row = json.loads(line)
                config, request, label = row['config'], row['request'], row['label']
                successful = [a['method'] for a in row.get('alternatives',[]) if a['feasible']]
                if label is not None:
                    successful.append('aco_pso')
                item = dict(scenario_id=row['scenario_id'],id=row['scenario_id'][:12],split=split,
                    network=config['size']+'/'+config['deployment']+'/'+config.get('constellation','legacy'),battery=config['battery_profile'],
                    load=config['load_profile'],nodes=len(row['state']['nodes']),
                    pair=request['source']+' → '+request['target'],mb=round(request['data_mb'],4),
                    mbps=round(request['required_mbps'],4),latency_weight=round(request['latency_weight'],3),
                    feasible=label is not None,cost=round(label['cost'],7) if label else None,
                    time_s=round(row['state']['time_s'],2),
                    weak=sum(n.get('battery_level')=='weak' for n in row['state']['nodes']),
                    medium=sum(n.get('battery_level')=='medium' for n in row['state']['nodes']),
                    strong=sum(n.get('battery_level')=='strong' for n in row['state']['nodes']),
                    methods=successful,seed=row['teacher_runs'][0]['seed'])
                rows.append(item)
                source=(directory/f'{split}.jsonl').resolve()
                if source.is_relative_to(output.parent.resolve()):
                    index_rows.append({**item,'file':str(source.relative_to(output.parent.resolve())).replace('\\','/'),'offset':offset})
                offset += len(raw)
    data = json.dumps(rows,ensure_ascii=False).replace('<','\\u003c')
    html = '''<!doctype html><html lang="vi"><meta charset="utf-8"><title>Danh mục kịch bản SAGIN</title>
<style>body{font:15px system-ui;margin:32px;background:#f5f7fa;color:#182b37}h1{margin-bottom:8px}p{max-width:1000px;line-height:1.6}form{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}input,select{font:inherit;padding:10px;border:1px solid #acbac5;border-radius:6px}.wrap{overflow:auto;background:white;border:1px solid #dbe2e8}table{border-collapse:collapse;white-space:nowrap;width:100%}th,td{text-align:left;padding:10px;border-bottom:1px solid #e7edf1}th{background:#173f50;color:white;position:sticky;top:0}td.ok{color:#087546}td.fail{color:#a43d3d}small{display:block;color:#526675}</style>
<h1>Danh mục __COUNT__ kịch bản mạng</h1><p>Pin, tải, quỹ đạo, yêu cầu và ưu tiên thay đổi theo kịch bản. “Chưa tìm được” là kết quả teacher ACO+PSO trong ngân sách chạy, không chứng minh mạng không có tuyến. Nhãn là nghiệm tốt nhất tìm được, không bảo đảm tối ưu tuyệt đối.</p>
<form id="filters"><input id="query" placeholder="Tìm ID, cặp trạm hoặc cấu hình…"><select id="network"><option value="">Mọi mạng</option></select><select id="battery"><option value="">Mọi nhóm pin</option></select><select id="load"><option value="">Mọi mức tải</option></select><select id="status"><option value="">Mọi kết quả</option><option value="yes">Có nghiệm teacher</option><option value="no">Chưa tìm được</option></select></form><p id="count"></p><p><small>Nhấn Nạp kịch bản để đưa đúng trạng thái và yêu cầu vào ứng dụng. Không thay đổi ràng buộc để ép kết quả đạt.</small></p>
<div class="wrap"><table><thead><tr><th>ID / tập</th><th>Mạng / nút</th><th>Nhóm pin</th><th>Yếu / vừa / mạnh</th><th>Tải</th><th>Cặp trạm</th><th>MB</th><th>Mbps</th><th>Ưu tiên trễ</th><th>Thời điểm (s)</th><th>Teacher</th><th>Cost</th><th>Mở mô phỏng</th></tr></thead><tbody id="body"></tbody></table></div>
<script type="application/json" id="data">__DATA__</script><script>
const rows=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
for(const key of ['network','battery','load'])for(const value of [...new Set(rows.map(r=>r[key]))].sort()){const o=document.createElement('option');o.value=o.textContent=value;$(key).append(o);}
function render(){const query=$('query').value.toLowerCase(),chosen=rows.filter(r=>['network','battery','load'].every(k=>!$(k).value||$(k).value===r[k])&&(!$('status').value||r.feasible===($('status').value==='yes'))&&(!query||JSON.stringify(r).toLowerCase().includes(query)));$('body').replaceChildren();for(const r of chosen){const tr=document.createElement('tr');for(const value of [r.id+' / '+r.split,r.network+' / '+r.nodes,r.battery,r.weak+' / '+r.medium+' / '+r.strong,r.load,r.pair,r.mb,r.mbps,r.latency_weight,r.time_s,r.feasible?'Có nghiệm':'Chưa tìm được',r.cost??'—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}tr.children[10].className=r.feasible?'ok':'fail';const action=document.createElement('td'),link=document.createElement('a');const origin=location.protocol==='file:'?'http://127.0.0.1:8000':location.origin;link.href=origin+'/network.html?scenario='+encodeURIComponent(r.scenario_id)+'&method='+encodeURIComponent(r.methods[0]||'aco_pso');link.textContent='Nạp kịch bản ↗';link.target='_blank';link.rel='noopener';action.append(link);tr.append(action);$('body').append(tr);}$('count').textContent='Hiển thị '+chosen.length+' / '+rows.length+' kịch bản';}
$('filters').addEventListener('input',render);$('filters').addEventListener('submit',e=>e.preventDefault());render();
</script></html>'''.replace('__COUNT__',str(len(rows))).replace('__DATA__',data)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(html,encoding='utf-8')
    if len(index_rows)==len(rows):
        (output.parent/'index.json').write_text(json.dumps(dict(version=1,scenarios=index_rows),ensure_ascii=False),encoding='utf-8')
    return len(rows)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',nargs='+',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print('Catalog scenarios:',catalog(args.dataset,args.output))
