# Mô phỏng SAGIN 3 lớp (Space – Air – Ground)

Bản mô phỏng có mobility thật cho vệ tinh (quỹ đạo Kepler tròn, có tính vòng
quay trái đất), UAV (bay tuần tra vòng tròn), và node mặt đất (lưới cố định).
Topology mạng được dựng lại **mỗi bước thời gian** dựa trên tầm nhìn
(elevation angle) và tầm phủ sóng thực tế — khác với cách gán tọa độ tĩnh của
repo tham khảo trước đó.

## Cấu trúc file

| File | Nội dung |
|---|---|
| `orbital.py` | Cơ học quỹ đạo: vị trí vệ tinh (ECI), chuyển đổi ECEF↔ECI, tính góc nâng |
| `nodes.py` | Class `GroundNode`, `UAVNode`, `SatelliteNode` — mỗi class có `position_eci(t)` |
| `channel.py` | Mô hình kênh truyền: free-space path loss + SINR + Shannon rate cho từng loại liên kết |
| `topology.py` | Dựng graph NetworkX tại một thời điểm t, dựa trên tầm nhìn/tầm phủ sóng |
| `simulation.py` | Vòng lặp mô phỏng chính: lặp qua thời gian, tính routing (Dijkstra động), ghi log |
| `run_demo.py` | Script chạy demo: 3 vệ tinh, 4 UAV, lưới ground 2×2, xuất CSV + biểu đồ |

## Chạy demo

```bash
python3 run_demo.py
```

Kết quả xuất ra: `sim_log.csv` (log từng timestep) và 3 file PNG biểu đồ.

## Cấu hình mặc định

- 3 vệ tinh LEO, cao độ 550 km, nghiêng 53°, lệch pha RAAN đều nhau
- 4 UAV bay tuần tra vòng tròn bán kính 3 km, cao độ 2 km
- Lưới ground 2×2 (4 node), cách nhau 2 km, quanh tọa độ Đà Nẵng
- Mô phỏng ~197 phút (≈ 2 chu kỳ quỹ đạo) để thấy rõ tính gián đoạn của kết nối

## Kết quả mẫu (đã chạy thử)

Với cấu hình mặc định, hệ thống chỉ có kết nối tới lớp vệ tinh trong khoảng
**6% thời gian** — 2 "cửa sổ" ngắn khi vệ tinh bay ngang qua khu vực. Đây là
hiện tượng thật của hệ LEO quy mô nhỏ: cần nhiều vệ tinh hơn (hoặc quỹ đạo
Walker constellation) để có phủ sóng liên tục — một kết quả tốt để đưa vào
phần "Đánh giá" của luận văn khi so sánh baseline (3 vệ tinh) với các cấu
hình khác.

## Hướng mở rộng tiếp theo

1. **Tăng số vệ tinh / dùng Walker constellation** để so sánh độ phủ sóng —
   chỉ cần đổi tham số `n_sat` và cách chia RAAN/mean anomaly trong
   `simulation.py`.
2. **Thêm lớp Sea**: tạo `SeaNode` trong `nodes.py` (di chuyển kiểu random
   walk/drift, xem gợi ý ở các lần trao đổi trước), thêm liên kết
   `sea-ground` hoặc `sea-uav` trong `channel.py` và `topology.py`.
3. **Thay quỹ đạo tròn bằng TLE thật**: khi có mạng để tải dữ liệu từ
   Celestrak, dùng thư viện `sgp4`/`skyfield` thay cho `SatellitePropagator`
   — interface `position_eci(t)` đã được thiết kế để dễ thay thế mà không
   phải sửa `topology.py` hay `simulation.py`.
4. **Liên kết liên vệ tinh (ISL)**: thêm cạnh vệ tinh-vệ tinh trong
   `topology.py` nếu khoảng cách trong ngưỡng, để cho phép định tuyến
   relay giữa các vệ tinh không nhìn thấy trực tiếp UAV.
5. **Thêm nhiễu/giao thoa đồng kênh**: `channel.py` hiện chỉ tính SINR với
   nhiễu nền (chưa có interference giữa các UAV) — có thể bổ sung theo mẫu
   `estimate_co_channel_interference` đã thấy ở repo tham khảo.
6. **Thêm ràng buộc tài nguyên** (năng lượng UAV, nhiên liệu tàu) và chỉ số
   PDR/throughput thực tế bằng cách mô phỏng luồng gói tin qua `simulation.py`.
