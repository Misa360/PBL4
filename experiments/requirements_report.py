"""Write the current requirement audit from completed, fingerprinted experiments."""
import json
from pathlib import Path


def write(root=Path('.')):
    root=Path(root)
    evaluation=json.loads((root/'outputs/global-scenarios/evaluation/summary.json').read_text())
    dynamic=json.loads((root/'outputs/global-scenarios/dynamic/summary.json').read_text())
    if evaluation['checkpoint_sha256'] != dynamic['checkpoint_sha256']:
        raise ValueError('Static and dynamic experiments used different checkpoints')
    def fmt(value):
        return '—' if value is None else f'{value:.4f}'
    lines=['# Đánh giá bổ sung: GenAI, tài nguyên và độ trễ', '',
        'Đã bổ sung đánh giá trên tập test và thí nghiệm tải động có hàng đợi. '
        'Các con số bên dưới được đọc từ kết quả chạy, không phải mục tiêu kỳ vọng.', '',
        '## Tập test chưa dùng để học', '',
        f"{evaluation['scenarios']} trạng thái × {evaluation['seeds']} seed × 5 nhánh = "
        f"{sum(r['runs'] for r in evaluation['summary'])} lượt tìm kiếm. "
        'Sáu nhóm mạng: small/full × compact/balanced/dense; tất cả phân bố rộng. '
        'Chặn trùng ID giữa test và train/validation trước khi chạy.', '',
        'Ngân sách tham chiếu: `'+str(evaluation['summary'][0]['budget'])+'`. '
        'Nhánh giảm vòng dùng một nửa số vòng ACO/PSO (làm tròn xuống) và giữ nguyên số kiến/hạt. '
        'AI có thêm chi phí sinh gợi ý, được tính vào thời gian tìm kiếm. '
        'Cùng số vòng không đồng nghĩa cùng thời gian hoặc cùng số lần đánh giá.', '',
        '| Nhánh | Đạt/tổng | Tìm kiếm TB (ms) | Δ Cost (%) | Δ độ trễ truyền (%) | Δ năng lượng (%) | CI 95% Δ độ trễ |',
        '|---|---:|---:|---:|---:|---:|---|']
    for r in evaluation['summary']:
        ci=r['scenario_bootstrap_delay_change_pct_95ci']
        lines.append(f"| {r['variant']} | {r['feasible']}/{r['runs']} | {fmt(r['all_runs_ms_mean'])} | "
            f"{fmt(r['paired_cost_change_pct'])} | {fmt(r['paired_delay_change_pct'])} | "
            f"{fmt(r['paired_energy_change_pct'])} | "+('—' if ci is None else f'[{fmt(ci[0])}; {fmt(ci[1])}]')+' |')
    ai=next(r for r in evaluation['summary'] if r['variant']=='ai_equal')
    ci=ai['scenario_bootstrap_delay_change_pct_95ci']
    if ci is None:
        verdict='Không đủ cặp cùng hợp lệ để đánh giá thay đổi độ trễ.'
    elif ci[0] <= 0 <= ci[1]:
        verdict='Khoảng bootstrap của AI cùng ngân sách chứa 0: chưa chứng minh giảm độ trễ truyền rõ ràng.'
    elif ci[1] < 0:
        verdict='AI cùng ngân sách giảm độ trễ trên các cặp hợp lệ trong bộ test tổng hợp này; chưa suy rộng sang mạng thật.'
    else:
        verdict='AI cùng ngân sách làm tăng độ trễ trên các cặp hợp lệ trong bộ test tổng hợp này.'
    lines += ['', verdict, '',
        'Trạng thái gợi ý của nhánh AI cùng ngân sách: `'+str(ai.get('ai_status_counts',{}))+'`. '
        'Ready nghĩa là có gợi ý hợp lệ; fallback nghĩa là chạy tiếp bằng ACO+PSO thông thường.', '',
        'Δ âm là giảm so với ACO+PSO chuẩn. Chỉ ghép chất lượng khi cả hai tìm được nghiệm; '
        'tỷ lệ đạt và thời gian tìm kiếm tính mọi lượt, kể cả thất bại. '
        'Bootstrap 1.000 lần theo trạng thái để không coi các seed của cùng trạng thái là độc lập. '
        'Đây là khoảng thăm dò, không điều chỉnh đa so sánh. '
        'Không dùng test để chọn lại checkpoint, ngân sách hoặc trọng số.', '',
        '## Yêu cầu đến đồng thời và hàng đợi', '',
        f"{dynamic['seeds']} seed × ba kiểu lưu lượng × {dynamic['requests_per_stream']} yêu cầu × ba nhánh = "
        f"{sum(r['attempted'] for r in dynamic['summary'])} lượt yêu cầu. "
        'Mạng full/balanced, pin hỗn hợp, tải ngoài biến thiên theo thời gian. '
        'Các nhánh có cùng lịch đến, tải ngoài và trạng thái ban đầu.', '',
        '| Lưu lượng | Nhánh | Dự báo | Đạt/tổng | Chờ TB mọi yêu cầu (s) | Trễ TB lượt đạt (s) | Năng lượng TB lượt đạt (J) |',
        '|---|---|---|---:|---:|---:|---:|']
    for r in dynamic['summary']:
        lines.append(f"| {r['profile']} | {r['method']} | {'Bật' if r['forecast'] else 'Tắt'} | "
            f"{r['delivered']}/{r['attempted']} | {fmt(r['all_requests_wait_s_mean'])} | "
            f"{fmt(r['delivered_latency_s_mean'])} | {fmt(r['delivered_energy_j_mean'])} |")
    lines += ['',
        'Light: khoảng đến trung bình 0,8 s; busy: 0,04 s; bursty: tám yêu cầu đến cùng lúc, '
        'các đợt cách 0,8–1,5 s. FCFS phục vụ nguyên thông điệp theo TDMA, '
        'một yêu cầu tại một thời điểm; chưa có truyền vô tuyến song song hay tái sử dụng không gian. '
        'Hàng đợi không giới hạn; yêu cầu không khả thi bị loại tại lúc phục vụ. '
        'Thời gian nhàn rỗi được cập nhật với bước tối thiểu 1 ms.', '',
        'Trễ đầu cuối = chờ + truyền toàn khối + truyền lan. Thời gian tìm kiếm trên máy '
        'được đo riêng, chưa cộng vào thời gian mô phỏng. Pin và quỹ đạo cập nhật sau mỗi lượt; '
        'liên kết được kiểm tra trong lúc truyền. Tải nền và dự báo cập nhật khi bắt đầu phục vụ '
        'rồi giữ nguyên trong lượt. Dự báo Holt chỉ đọc quan sát hiện tại/quá khứ. '
        'Các nhánh dần có pin và hàng đợi khác nhau; phương pháp loại nhiều yêu cầu có thể '
        'có độ trễ trung bình thấp hơn, vì vậy phải đọc cùng tỷ lệ thành công.', '',
        '## Phạm vi đã hoàn thành và giới hạn', '',
        '- Có sinh nhiều phương án tuyến/công suất/băng thông bằng MLP và tinh chỉnh ACO/PSO.',
        '- Có imitation + REINFORCE; checkpoint mới được chọn ở epoch 14 thuộc giai đoạn REINFORCE bằng validation.',
        '- Có dự báo tải nền, đối chứng tắt dự báo và thí nghiệm hàng đợi.',
        '- RL vẫn là contextual bandit một bước, chưa học chính sách điều khiển nhiều bước.',
        '- Dữ liệu/quỹ đạo/tải là tổng hợp; chưa có TLE và lưu lượng đo thực, fading/nhiễu, năng lượng bay UAV hoặc sạc mặt trời.',
        '- Không có bảo đảm tối ưu toàn cục hoặc AI luôn nhanh hơn/tốt hơn.', '',
        '## Tái lập', '',
        'Checkpoint SHA-256: `'+evaluation['checkpoint_sha256']+'`.', '',
        'Tệp chi tiết: `outputs/global-scenarios/evaluation/{summary.json,runs.csv,report.html}` '
        'và `outputs/global-scenarios/dynamic/{summary.json,runs.csv,streams.json,report.html}`. '
        'Summary của test lưu SHA-256 từng file test. Giữ nguyên checkpoint khi tái lập; '
        'chọn thư mục output mới vì lệnh không ghi đè kết quả cũ.', '',
        '```powershell',
        '$datasets = Get-ChildItem outputs/global-scenarios -Directory | Where-Object { Test-Path (Join-Path $_.FullName "test.jsonl") } | ForEach-Object FullName',
        'python -m ai.evaluate --dataset $datasets --output outputs/global-evaluation-repeat --seeds 3 --budget dataset',
        'python -m ai.report outputs/global-evaluation-repeat',
        f"python -m experiments.dynamic --output outputs/global-dynamic-repeat --seeds {dynamic['seeds']} --requests {dynamic['requests_per_stream']} --budget dataset",
        '```', '']
    target=root/'outputs/reports/requirements-audit.md'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('\n'.join(lines), encoding='utf-8')
    return target


if __name__=='__main__':
    print(write())
