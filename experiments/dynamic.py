"""FCFS whole-message TDMA with queued arrivals and causal background-load forecasts.

Multiple requests may arrive together. One message is served at a time; this is
not a spatial-reuse or simultaneous-radio scheduler. Search wall time is reported
separately and is not added to simulated service time.
"""
import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict
from html import escape
from pathlib import Path

from ai.policy import MODEL_PATH
from optimizer.models import Budget, Demand
from optimizer.service import OptimizerSession
from optimizer.traffic import forecast_utilization

PROFILES = ('light', 'busy', 'bursty')


def arrivals(seed, count=40, profile='light'):
    if profile not in PROFILES or type(count) is not int or not 1 <= count <= 500:
        raise ValueError('Invalid arrival profile or request count')
    rng, time_s, rows = random.Random(seed), 0., []
    mean_gap = {'light': .8, 'busy': .04, 'bursty': .1}[profile]
    for index in range(count):
        if profile == 'bursty':
            time_s += rng.uniform(.8, 1.5) if index % 8 == 0 else 0.
        else:
            time_s += rng.expovariate(1/mean_gap)
        source, target = rng.sample(range(1, 11), 2)
        rows.append(dict(id=index, arrival_s=time_s, request=asdict(Demand(
            source=f'G{source}', target=f'G{target}', data_mb=rng.uniform(.03, .3),
            required_mbps=rng.uniform(.15, 1.5), energy_weight=.5, latency_weight=.7))))
    return rows


def load_at(seed, key, tick, profile):
    """Exogenous bounded load, independent of method and previous RNG consumption."""
    digest = hashlib.sha256(f'{seed}:{key}:{tick}'.encode()).digest()
    jitter = int.from_bytes(digest[:8], 'big')/2**64
    base = {'light': .12, 'busy': .55, 'bursty': .2}[profile]
    burst = .45 if profile == 'bursty' and tick % 12 in (3, 4, 5) else 0.
    return min(.94, max(0., base+burst+.12*math.sin(tick/3)+.12*(jitter-.5)))


def update_load(network, seed, profile, forecast=True):
    tick = int(network.time_s)
    for key, node in network.nodes.items():
        # Only observations at or before the current time enter the forecast.
        history = [load_at(seed, key, t, profile) for t in range(max(0, tick-7), tick+1)]
        network.load_history[key] = history
        node.reserved_bandwidth_hz = history[-1]*node.bandwidth_hz
        node.predicted_reserved_bandwidth_hz = (
            forecast_utilization(history)*node.bandwidth_hz if forecast else 0.)
    network.revision += 1


def serve(stream, method, seed, profile, budget, forecast=True):
    session = OptimizerSession(size='full', constellation='balanced', battery_j=1000,
        battery_profile='mixed', load_profile='idle', state_seed=seed,
        forecast_load=forecast)
    rows = []
    for event in stream:
        arrival = event['arrival_s']
        while session.network.time_s < arrival:
            session.advance(min(600., max(.001, arrival-session.network.time_s)))
        started = session.network.time_s
        update_load(session.network, seed, profile, forecast)
        plan = session.search(Demand(**event['request']), method, seed*1000+event['id'], budget)
        delivered, reason, transfer = False, plan.get('reason'), None
        if plan['feasible']:
            try:
                transfer = session.transmit(plan['plan_id'])['transfer']
                delivered = True
            except ValueError as error:
                reason = str(error)
        rows.append(dict(seed=seed, profile=profile, method=method, forecast=forecast,
            request_id=event['id'], source=event['request']['source'], target=event['request']['target'],
            arrival_s=arrival, started_s=started, wait_s=started-arrival,
            delivered=delivered, reason=reason, search_ms=plan['elapsed_ms'],
            service_s=transfer['duration_s'] if transfer else None,
            end_to_end_s=session.network.time_s-arrival if delivered else None,
            energy_j=transfer['energy_j'] if transfer else None,
            cost=plan['cost'] if delivered else None))
    return rows


def run(output, seeds=3, requests=40, budget=None, resume=False):
    if type(seeds) is not int or not 1 <= seeds <= 30:
        raise ValueError('seeds must be in [1,30]')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=resume)
    budget = budget or Budget()
    rows, streams = [], []
    metadata=dict(seeds=seeds,requests=requests,budget=asdict(budget),
        checkpoint_sha256=hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest())
    manifest=output/'progress-metadata.json'
    if manifest.exists():
        if json.loads(manifest.read_text()) != metadata:
            raise ValueError('Cannot resume changed dynamic experiment')
    else:
        if any(output.iterdir()):
            raise ValueError('Cannot resume unrecognized dynamic directory')
        manifest.write_text(json.dumps(metadata,indent=2))
    trace=output/'progress.jsonl'
    if trace.exists():
        rows=[json.loads(line) for line in trace.read_text().splitlines()]
    completed={}
    for row in rows:
        completed.setdefault((row['seed'],row['profile'],row['method'],row['forecast']),set()).add(row['request_id'])
    if any(ids != set(range(requests)) for ids in completed.values()) or len(rows)!=len(completed)*requests:
        raise ValueError('Incomplete or duplicate dynamic progress block')
    allowed={(seed,profile,method,forecast) for seed in range(seeds) for profile in PROFILES
             for method,forecast in [('aco_pso',True),('ai_aco_pso',True),('ai_aco_pso',False)]}
    if not set(completed)<=allowed:
        raise ValueError('Unknown dynamic progress block')
    for seed in range(seeds):
        for profile in PROFILES:
            stream = arrivals(seed, requests, profile)
            streams.append(dict(seed=seed, profile=profile, arrivals=stream))
            # Rotate arm order; same exogenous arrivals/load and initial batteries.
            arms = [('aco_pso', True), ('ai_aco_pso', True), ('ai_aco_pso', False)]
            arms = arms[seed % 3:]+arms[:seed % 3]
            for method, forecast in arms:
                if (seed,profile,method,forecast) in completed:
                    continue
                block = serve(stream, method, seed, profile, budget, forecast)
                rows.extend(block)
                with (output/'progress.jsonl').open('a', encoding='utf-8') as handle:
                    for row in block:
                        handle.write(json.dumps(row)+'\n')
            print(f'Dynamic: seed {seed+1}/{seeds}, {profile}', flush=True)
    summary = []
    for profile in PROFILES:
        for method, forecast in [('aco_pso', True), ('ai_aco_pso', True), ('ai_aco_pso', False)]:
            group = [r for r in rows if r['profile']==profile and r['method']==method and r['forecast']==forecast]
            valid = [r for r in group if r['delivered']]
            summary.append(dict(profile=profile, method=method, forecast=forecast,
                attempted=len(group), delivered=len(valid), success_rate=len(valid)/len(group),
                all_requests_wait_s_mean=statistics.mean(r['wait_s'] for r in group),
                delivered_latency_s_mean=statistics.mean(r['end_to_end_s'] for r in valid) if valid else None,
                delivered_energy_j_mean=statistics.mean(r['energy_j'] for r in valid) if valid else None,
                all_search_ms_mean=statistics.mean(r['search_ms'] for r in group)))
    if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()!=metadata['checkpoint_sha256']:
        raise ValueError('Checkpoint changed during dynamic experiment')
    report = dict(seeds=seeds, requests_per_stream=requests, budget=asdict(budget),
        checkpoint_sha256=hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(), summary=summary,
        limitations='Synthetic FCFS, one whole message at a time. Arrivals may overlap; radios do not transmit concurrently. Background load and forecast updated at dispatch and held during service. No multi-step RL. Search wall time excluded from simulated latency. Separate arms develop different queues and battery states; compare delivery rates alongside latency.')
    with (output/'runs.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    (output/'streams.json').write_text(json.dumps(streams, indent=2), encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    headings = [('profile','Lưu lượng'), ('method','Phương pháp'), ('forecast','Dự báo'),
        ('delivered','Truyền thành công'), ('attempted','Yêu cầu'),
        ('all_requests_wait_s_mean','Chờ TB (s)'), ('delivered_latency_s_mean','Trễ thành công TB (s)'),
        ('delivered_energy_j_mean','Năng lượng TB (J)'), ('all_search_ms_mean','Tìm kiếm TB (ms)')]
    def cell(value):
        if value is None:return '—'
        if isinstance(value,bool):return 'Bật' if value else 'Tắt'
        return f'{value:.4f}' if isinstance(value,float) else str(value)
    table='<tr>'+''.join('<th>'+label+'</th>' for _,label in headings)+'</tr>'
    table+=''.join('<tr>'+''.join('<td>'+escape(cell(r[k]))+'</td>' for k,_ in headings)+'</tr>' for r in summary)
    html='''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tải động · SAGIN</title><style>body{font:16px system-ui;background:#0d1922;color:#e2efef;margin:32px;line-height:1.6}a{color:#9de5d4}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #344852;text-align:left}th{color:#9de5d4}.scroll{overflow:auto}main{max-width:1500px;margin:auto}</style><main><a href="/network.html">← Mô phỏng</a><h1>Lưu lượng động và hàng đợi FCFS</h1>'''
    html+=f'<p>{seeds} seed × 3 kiểu lưu lượng × {requests} yêu cầu × 3 nhánh so sánh.</p>'
    html+='<p>light: đến thưa; busy: đến dày; bursty: đến đồng thời theo đợt. Một yêu cầu được phục vụ tại một thời điểm, các yêu cầu còn lại chờ. Trễ = chờ + truyền + truyền lan; thời gian tính thuật toán được đo riêng. Các nhánh dùng cùng lịch đến, tải ngoài và pin ban đầu, nhưng hàng đợi và pin sau truyền có thể khác nhau.</p><div class="scroll"><table>'+table+'</table></div><p>Phải đọc tỷ lệ thành công cùng độ trễ: phương pháp bỏ nhiều yêu cầu có thể làm hàng đợi ngắn hơn. Mỗi nhánh AI tắt dự báo là đối chứng cho dự báo tải, không phải mô hình chưa học.</p><p>'+escape(report['limitations'])+'</p><p><a href="/reports/evaluation.html">Đánh giá trên 268 trạng thái test →</a></p></main></html>'
    (output/'report.html').write_text(html, encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seeds', type=int, default=3)
    parser.add_argument('--requests', type=int, default=40)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--budget', choices=['standard','dataset'], default='standard')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    budget = Budget(ants=6, aco_iterations=8, particles=8, pso_iterations=8) if args.quick else Budget()
    if args.budget=='dataset':
        if args.quick:parser.error('--quick and --budget dataset cannot be combined')
        budget=Budget(ants=10,aco_iterations=20,particles=12,pso_iterations=25,candidates=2)
    run(args.output, args.seeds, args.requests, budget, args.resume)
