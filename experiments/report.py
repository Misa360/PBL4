"""Dependency-free, standalone SVG figures plus an HTML results report."""
from html import escape
from pathlib import Path


def chart(path, title, series, labels=None):
    colors = ['#007f78','#a65b00','#7751b8','#c54051','#2776b6','#737c15','#000000']
    values = [v for _, ys in series for v in ys if v is not None]
    maximum = max(values, default=1) or 1
    width, height = 1000, 400
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img"><title>{escape(title)}</title><rect width="100%" height="100%" fill="white"/><text x="50" y="30" font-family="sans-serif" font-size="20">{escape(title)}</text>']
    for j in range(5):
        y=65+j*60
        svg.append(f'<path d="M80 {y}H750" stroke="#ddd"/><text x="5" y="{y+4}" font-family="sans-serif" font-size="12">{maximum*(1-j/4):.4g}</text>')
    for i,(name,ys) in enumerate(series):
        pts=' '.join(f'{80+670*j/max(1,len(ys)-1):.2f},{305-240*v/maximum:.2f}' for j,v in enumerate(ys) if v is not None)
        color=colors[i%len(colors)]
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/><text x="770" y="{70+i*24}" fill="{color}" font-family="sans-serif" font-size="13">{escape(name)}</text>')
    if labels:
        for i,label in enumerate(labels):
            x=80+670*i/max(1,len(labels)-1)
            svg.append(f'<text x="{x}" y="330" text-anchor="middle" font-family="sans-serif" font-size="11">{escape(label)}</text>')
    svg.append(f'<text x="80" y="365" font-family="sans-serif" font-size="12">{"Condition" if labels else "Iteration"} → · Y: Cost (dimensionless)</text></svg>')
    Path(path).write_text(''.join(svg),encoding='utf-8')


def make_report(output, metadata, summary, histories, lifetime):
    chart(output/'cost-comparison.svg','Mean feasible Cost across conditions (failures excluded)',
          [(m,[r['cost_mean'] for r in summary if r['method']==m]) for m in metadata['methods']], metadata['conditions'])
    figures=[]
    for condition in metadata['conditions']:
        series=[]
        for item in histories:
            if item['condition']!=condition: continue
            if item['aco']: series.append((item['method']+' ACO',[h['cost'] for h in item['aco']]))
        filename=f'convergence-{condition}.svg'
        chart(output/filename, f'ACO best feasible Cost - {condition} - seed 0', series)
        figures.append(filename)
        pso_series=[]
        for item in histories:
            if item['condition']==condition:
                for i,p in enumerate(item['pso']):
                    pso_series.append((item['method']+f' route {i+1}',[h['cost'] for h in p['history']]))
        name=f'pso-{condition}.svg';chart(output/name,f'PSO best feasible Cost - {condition} - seed 0',pso_series);figures.append(name)
    rows=[]
    for r in summary:
        def value(key):
            a,b=r[key+'_mean'],r[key+'_std']
            return '—' if a is None else f'{a:.5g} ± {b:.3g}'
        rows.append('<tr>'+''.join(f'<td>{escape(str(v))}</td>' for v in [r['condition'],r['method'],f"{r['success_rate']:.0%}",value('cost'),value('rate_mbps'),value('energy_j'),value('hops'),value('compute_ms')])+'</tr>')
    lifetime_rows=[]
    import statistics
    for method in metadata['methods']:
        group=[r for r in lifetime if r['method']==method]
        served=[r['served'] for r in group]
        touched=[r['first_reserve_s'] for r in group if r['first_reserve_s'] is not None]
        lifetime_rows.append(f'<tr><td>{escape(method)}</td><td>{statistics.mean(served):.3g} ± {statistics.stdev(served):.3g}</td><td>{len(touched)}/{len(group)}</td></tr>')
    html=f'''<!doctype html><html lang="vi"><meta charset="utf-8"><title>SAGIN experiment report</title>
    <style>body{{font:15px/1.6 system-ui;margin:40px;color:#183142}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;border:1px solid #ccd7df;text-align:left}}img{{width:100%;max-width:1100px}}code{{background:#eee}}</style>
    <h1>SAGIN / Kết quả thực nghiệm</h1><p>{metadata['repeats']} seed cho mỗi cấu hình; mạng {metadata['size']}. Cùng trạng thái và yêu cầu giữa các phương pháp. Mean ± sample standard deviation.</p>
    <p>Chỉ lấy Cost, tốc độ, năng lượng và hop của nghiệm hợp lệ; thời gian tính lấy tất cả lượt. Tỷ lệ thành công được báo riêng. Không có nghiệm hợp lệ hiển thị —. Các biểu đồ hội tụ dùng seed 0, không phải trung bình nhiều seed.</p>
    <p>Ngân sách tìm kiếm: <code>{escape(str(metadata['budget']))}</code>. Mô hình tổng hợp; kết quả chưa chứng minh tối ưu toàn cục hoặc tính đúng với thiết bị thực.</p>
    <table><tr><th>Điều kiện</th><th>Phương pháp</th><th>Thành công</th><th>Cost</th><th>Mbps</th><th>J</th><th>Hop</th><th>ms tính</th></tr>{''.join(rows)}</table>
    <h2>Chuỗi yêu cầu và pin</h2><p>{metadata['lifetime_requests']} yêu cầu/seed. Giới hạn quan sát hữu hạn: chưa chạm ngưỡng là dữ liệu chưa quan sát đủ, không phải tuổi thọ vô hạn.</p><table><tr><th>Phương pháp</th><th>Yêu cầu phục vụ: mean ± std</th><th>Số lượt có nút chạm ngưỡng dự trữ</th></tr>{''.join(lifetime_rows)}</table>
    <h2>Hình xuất độc lập</h2><p>Trục ngang biểu đồ so sánh lần lượt: {escape(', '.join(metadata['conditions']))}.</p><img src="cost-comparison.svg">{''.join(f'<img src="{name}">' for name in figures)}
    <p>Dữ liệu gốc: runs.csv, summary.csv, lifetime.csv, results.json.</p></html>'''
    (output/'report.html').write_text(html,encoding='utf-8')
