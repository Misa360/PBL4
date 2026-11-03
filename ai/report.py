"""Enrich completed held-out measurements without repeating searches."""
import argparse
import csv
import json
import statistics
import sys
import platform
from collections import Counter
from html import escape
from pathlib import Path

from .evaluate import interval


def enrich(directory):
    directory = Path(directory)
    report = json.loads((directory/'summary.json').read_text(encoding='utf-8'))
    with (directory/'runs.csv').open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    baseline = {(r['scenario_id'], r['seed']): r for r in rows if r['variant']=='aco_pso'}
    for item in report['summary']:
        group = [r for r in rows if r['variant']==item['variant']]
        valid = [r for r in group if r['feasible']=='True']
        pairs = [(r,baseline[r['scenario_id'],r['seed']]) for r in group]
        joint = [(a,b) for a,b in pairs if a['feasible']==b['feasible']=='True']
        item['feasible_energy_j_mean'] = statistics.mean(float(r['energy_j']) for r in valid) if valid else None
        item['ai_only_feasible'] = sum(a['feasible']=='True' and b['feasible']!='True' for a,b in pairs)
        item['baseline_only_feasible'] = sum(b['feasible']=='True' and a['feasible']!='True' for a,b in pairs)
        item['ai_status_counts'] = dict(Counter(r['ai_status'] for r in group if r['ai_status']))
        item['all_runs_inference_ms_mean'] = statistics.mean(float(r['inference_ms']) for r in group)
        energy = [(a['scenario_id'],100*(float(a['energy_j'])/float(b['energy_j'])-1)) for a,b in joint if float(b['energy_j'])>0]
        item['paired_energy_change_pct'] = statistics.mean(v for _,v in energy) if energy else None
        clusters = [statistics.mean(v for k,v in energy if k==sid) for sid in sorted({k for k,_ in energy})]
        item['scenario_bootstrap_energy_change_pct_95ci'] = interval(clusters)
    report['test_files_sha256'] = {}
    report['environment'] = dict(python=sys.version, system=platform.system(),
        timing_note='Current workstation, no CPU isolation; background activity and OS scheduling can affect wall-clock timings.')
    notes=directory/'measurement-notes.json'
    report['measurement_notes']=json.loads(notes.read_text()) if notes.exists() else {}
    import hashlib
    for source in report['datasets']:
        p = Path(source)/'test.jsonl'
        report['test_files_sha256'][str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    (directory/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    headings = [('variant','Phương pháp'),('feasible','Đạt'),('runs','Tổng lượt'),
        ('all_runs_ms_mean','Tìm kiếm TB (ms)'),('paired_cost_change_pct','Δ Cost (%)'),
        ('paired_delay_change_pct','Δ độ trễ (%)'),('paired_energy_change_pct','Δ năng lượng (%)'),
        ('scenario_bootstrap_delay_change_pct_95ci','CI 95% Δ độ trễ')]
    def fmt(value):
        if value is None:return '—'
        if isinstance(value,float):return f'{value:.4f}'
        if isinstance(value,list):return '['+', '.join(fmt(v) for v in value)+']'
        return str(value)
    header=''.join('<th>'+label+'</th>' for _,label in headings)
    body=''.join('<tr>'+''.join('<td>'+escape(fmt(row.get(key)))+'</td>' for key,_ in headings)+'</tr>' for row in report['summary'])
    html='''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Đánh giá AI · SAGIN</title><style>body{font:16px system-ui;background:#0d1922;color:#e2efef;margin:32px;line-height:1.6}a{color:#9de5d4}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #344852;text-align:left}th{color:#9de5d4}main{max-width:1500px;margin:auto}.scroll{overflow:auto}code{overflow-wrap:anywhere}</style><main><a href="/network.html">← Mô phỏng</a><h1>Đánh giá AI trên kịch bản chưa học</h1>'''
    html+=f'<p>{report["scenarios"]} trạng thái test × {report["seeds"]} seed × {len(report["summary"])} phương pháp. Ngân sách: '+escape(str(report['summary'][0]['budget']))+'.</p>'
    html+='<p>Δ âm: giảm so với ACO+PSO cùng ngân sách chuẩn. Cost, độ trễ và năng lượng chỉ ghép các lượt cả hai có nghiệm hợp lệ; số lượt đạt bao gồm toàn bộ thất bại. CI được bootstrap theo trạng thái, không coi các seed là mẫu độc lập. CI chứa 0: chưa có bằng chứng rõ ràng về chiều thay đổi.</p><div class="scroll"><table><tr>'+header+'</tr>'+body+'</table></div>'
    html+='<p>ai_equal: AI cùng số vòng; ai_half_iterations: AI nửa số vòng; aco_half_iterations: ACO+PSO nửa số vòng; untrained_warm_control: mô hình chưa học. Giảm số vòng không tự chứng minh lợi ích do AI. Đây là cùng ngân sách vòng lặp, không phải cùng thời gian chạy.</p>'
    profile_keys=['size','constellation','variant','feasible','runs','all_runs_ms_mean']
    html+='<details><summary>Kết quả riêng theo sáu cấu hình mạng</summary><div class="scroll"><table><tr>'+''.join('<th>'+k+'</th>' for k in profile_keys)+'</tr>'
    html+=''.join('<tr>'+''.join('<td>'+escape(fmt(row.get(k)))+'</td>' for k in profile_keys)+'</tr>' for row in report['profiles'])
    html+='</table></div></details><p>'+escape(report['timing'])+'</p><p>'+escape(report['environment']['timing_note'])+'</p><p>'+escape(str(report['measurement_notes']))+'</p><p>'+escape(report['limitations'])+'</p><p>Checkpoint SHA-256: <code>'+escape(report['checkpoint_sha256'])+'</code></p><p><a href="/reports/dynamic.html">Thí nghiệm hàng đợi và tải động →</a></p></main></html>'
    (directory/'report.html').write_text(html, encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args=parser.parse_args()
    enrich(args.directory)
