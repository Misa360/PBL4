# PBL4 — Phân bổ tài nguyên SAGIN bằng GenAI + ACO/PSO

Mô phỏng truyền dữ liệu qua vệ tinh, UAV và trạm mặt đất, tối ưu tuyến đi, công suất và băng thông với ràng buộc pin/tốc độ. Giao diện và thuật toán dùng chung trạng thái từ máy chủ Python.

## Chạy ứng dụng

Python 3.10+; ứng dụng chính và mô hình AI dùng thư viện chuẩn, không cần cài NumPy/PyTorch.

```powershell
python server.py
```

- Điều phối mạng: http://127.0.0.1:8000/network.html
- Cảnh Trái Đất: http://127.0.0.1:8000/
- Đổi cổng: `python server.py --port 8001`.

Mở qua máy chủ Python; Live Server chỉ phục vụ HTML, không chạy API. Sau khi sửa Python cần khởi động lại máy chủ. Cảnh 3D tải Three.js từ CDN; sơ đồ 2D vẫn dùng được nếu không tải được thư viện 3D.

## Sử dụng

1. Chọn quy mô, chùm vệ tinh, pin, tải nền và kiểu biến thiên lưu lượng; tạo lại mạng để áp dụng. Tạo lại mạng đặt lại pin, thời gian và lịch sử.
2. Chọn trạm gửi/nhận, dữ liệu MB, tốc độ Mbps và phương pháp. **Tìm phương án** chưa làm giảm pin.
3. **Truyền dữ liệu** kiểm tra lại tài nguyên/vùng phủ rồi cập nhật pin đúng một lần. Bảng pin cho biết trước/sau trên tuyến; tổng năng lượng còn gồm cả điện lưới của trạm/GEO.
4. **So sánh đủ 12 phương pháp** dùng cùng trạng thái, yêu cầu và seed. Chọn một dòng để xem cấp phát từng chặng hoặc thực hiện phương án đó. Kết quả không đạt có thông tin tốc độ, băng thông, pin hoặc tuyến còn thiếu.
5. Để kiểm tra dự báo, chọn tải **Hỗn hợp** và biến thiên **Có chu kỳ/Theo đợt**, rồi **Quan sát 30 giây**. Hành động này tiêu thụ điện nền và làm phương án cũ hết hiệu lực. Mốc 1/6 giây đối chiếu dự báo đã phát trước với số liệu xuất hiện sau đó.

12 phương pháp: Random, Greedy, BFS ít chặng, Dijkstra khoảng cách, Dijkstra độ trễ, Widest, Energy, ACO, Widest+PSO, Energy+PSO, ACO+PSO, AI+ACO+PSO. `pso` là tên API tương thích của Widest+PSO, không phải phương pháp thứ 13.

Mặc định: 69 nút, 10 trạm phân bố rộng, pin yếu/vừa/mạnh, tải hỗn hợp, lưu lượng theo đợt. Các số dưới đây gồm trạm, UAV và vệ tinh; thay đổi số UAV sẽ đổi tổng số nút.

| Chùm vệ tinh | Mạng nhỏ, 4 trạm | Mạng toàn cầu, 10 trạm |
|---|---:|---:|
| Gọn | 20 | 41 |
| Cân bằng | 33 | 69 |
| Tăng phủ | 55 | 109 |

## Đáp ứng đề tài và giới hạn

| Yêu cầu | Hiện trạng |
|---|---|
| Vệ tinh/UAV/trạm, phân bổ công suất và băng thông, tính tiêu hao pin | Có trong mô phỏng, kiểm tra ràng buộc chung cho mọi phương pháp |
| Sinh nhiều phương án theo trạng thái mạng | MLP tự hồi quy sinh tuyến và các mức công suất/băng thông |
| Học tăng cường kết hợp heuristic | Imitation + REINFORCE một bước; gợi ý cho ACO/PSO tinh chỉnh |
| Dùng dự báo lưu lượng | Có lưu lượng đến nền Mbps từ nguồn gói tổng hợp; AR(6), Holt và persistence, chấm dự báo trước khi học mẫu mới |
| Mục tiêu giảm độ trễ | Có trong Cost cùng năng lượng và rủi ro pin |
| Chứng minh AI tốt/nhanh hơn ACO+PSO | Chưa có bằng chứng ổn định trên benchmark của bản hiện tại |

Checkpoint `ai/checkpoints/policy.json` được huấn luyện trong bộ dữ liệu 1.800 trạng thái (1.266 train, 266 validation, 268 test); test không dùng để học hoặc chọn mô hình. Checkpoint được chọn ở epoch 14 thuộc giai đoạn REINFORCE bằng validation. Đây là contextual bandit một bước, chưa phải chính sách điều khiển nhiều bước. Nếu mô hình lỗi hoặc không có gợi ý hợp lệ, thuật toán dùng ACO+PSO và báo trạng thái đó.

Hội tụ ghi cả khởi tạo và các giai đoạn thật; đường phẳng có thể nghĩa là chưa cải thiện sau khởi tạo. Không ép nghiệm AI khác ACO/PSO. Dự báo lưu lượng có đối chứng và sai số; chưa bảo đảm vượt persistence, đặc biệt ở mốc xa hoặc tải đột biến. Kết quả benchmark cũ trong `outputs/` thuộc phiên bản và ngân sách đã ghi trong metadata, không tự chứng minh hiệu quả của bản mới.

Mạng/quỹ đạo/tải là tổng hợp, chưa dùng TLE hoặc lưu lượng đo thực. Mỗi yêu cầu truyền toàn khối nối tiếp qua các chặng theo TDMA; tải nền được giữ trong một lượt truyền, rồi tiến sang trạng thái mới. Chưa mô phỏng nhiều luồng vô tuyến đồng thời, fading, nhiễu đồng kênh, năng lượng bay UAV hay sạc mặt trời. Không có bảo đảm tối ưu toàn cục.

Đơn vị SI: `D = MB × 8e6` bit, Shannon `R = B log2(1 + Pg/(N0B))`, trễ chặng `D/R + d/c`. Điện phát là `(P/η + P_tx_circuit) × D/R`, điện nhận `P_rx × D/R`, mọi nút trả điện nền theo thời gian. Cost phối hợp độ trễ chuẩn hóa, tổng năng lượng và mức tiêu hao pin lớn nhất. Nguồn lưu lượng nền dùng gói 64 KiB và quy chiếu 2 bit/s/Hz để dành băng thông; đây không phải tốc độ Shannon đầu cuối.

## Thư mục

```text
server.py               Lệnh chạy tương thích
app/                    Máy chủ HTTP, API và nạp trạng thái kiểm thử
optimizer/              Mạng, công thức, ACO/PSO, chẩn đoán và dự báo
ai/                     Mô hình sinh, dữ liệu, train và đánh giá
  checkpoints/policy.json       Mô hình đang dùng
  checkpoints/archive/          Mô hình trước và bản ứng viên
web/                    Hai trang HTML, CSS, JS và ảnh dùng thực tế
simulator/              Mô phỏng packet và các mô hình prototype
examples/               Demo cũ tùy chọn, có requirements riêng
experiments/            Công cụ đánh giá ngoại tuyến
tests/                  Test công thức, tài nguyên, API và trình duyệt
outputs/                Dữ liệu, kết quả chạy, log và bản lưu; không đưa vào Git
```

`docs/` đã được dọn theo yêu cầu; bản sao nằm trong `outputs/archive/`. Hướng dẫn hiện tại được giữ tại README này. Ảnh TIFF không dùng đã lưu vào `outputs/archive/unused-textures/`; ảnh JPG/PNG của cảnh 3D vẫn ở `web/assets/textures/`.

## Kiểm tra và tái lập

```powershell
python -m unittest discover -s tests -q
python -m tests.browser_smoke
```

Kiểm tra trình duyệt cần Chrome/Edge trên Windows, dùng profile và máy chủ riêng. Kết quả ở `outputs/browser-check/result.json`, ảnh ở `outputs/browser-check/screenshot.png`. Các bài này không dùng phiên duyệt cá nhân.

Các demo prototype là tùy chọn: `pip install -r examples/requirements.txt`. Không cần cài các gói đó để chạy ứng dụng chính hoặc test Python.

Các công cụ ngoại tuyến có CLI riêng:

```powershell
python -m ai.dataset --help
python -m ai.train --help
python -m ai.evaluate --help
python -m experiments.dynamic --help
```

Tách train/validation/test; giữ lại thất bại, so sánh cùng ngân sách và nhiều seed. Không dùng test để chọn checkpoint. Báo cáo sinh mới nằm trong `outputs/`, không tái tạo thư mục tài liệu trong mã nguồn.
