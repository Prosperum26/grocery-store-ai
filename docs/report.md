# Báo cáo: dự đoán mua lại (predictive reorder)

*Ngày 2026-10-23 · nhánh `feature/predictive-reorder` · dữ liệu Instacart, 20.000 user*

## Kết luận

**Model gate: QUA.** Trên tập test, chạy đúng một lần, LightGBM đạt **Recall@15 = 0,431**, cao hơn baseline tốt nhất là TIFU-KNN (0,417). LightGBM cũng dẫn đầu ở mọi metric còn lại. Model được calibrate tốt (ECE 0,001 cả khi chia bin theo quantile; Brier 0,082 so với 0,102 của dự đoán hằng bằng tỉ lệ nền), nên xác suất dự đoán dùng được trực tiếp để quyết định có gợi ý một món hay không.

## Bài toán

Với mỗi khách, dự đoán những món **đã từng mua** sẽ có trong đơn tiếp theo, và gợi ý tối đa 15 món. Model chấm điểm từng món trong lịch sử mua của khách (tối đa 100 món mỗi khách), rồi xếp hạng theo xác suất được mua.

## Dữ liệu và cách đánh giá

- **Dữ liệu**: Instacart, gộp prior và train. Giữ khách có ít nhất 5 đơn, lấy ngẫu nhiên 20.000 khách (seed 42).
- **Split theo từng khách**:
  - đơn cuối là **test**;
  - đơn kế cuối là **val**;
  - các đơn còn lại là **train**: dùng các đơn T−2, T−3, T−4 làm nhãn, các đơn trước đó để tính feature.
- **Chống rò rỉ**: feature chỉ dùng các đơn đứng trước đơn cần dự đoán. Điều này được kiểm tra tự động bằng test, trong đó có test tính lại feature từ dữ liệu gốc. Chi tiết trong [scripts/data_prep.py](../scripts/data_prep.py).
- **Metric**: Recall@15, NDCG@15, F1@15, Precision@20. Tính trên **giỏ hàng thật đầy đủ**, kể cả món khách chưa từng mua, rồi lấy trung bình theo đơn.
- **Quy trình**: chọn feature, tham số, τ và kiểm tra calibration đều chỉ trên val. Test được chạy **một lần duy nhất** ở bước cuối; script [scripts/final_eval.py](../scripts/final_eval.py) từ chối chạy lại.

## Kết quả trên test (một lần duy nhất)

| Phương pháp | Recall@15 | NDCG@15 | F1@15 | Precision@20 |
| --- | --- | --- | --- | --- |
| popularity | 0,0870 | 0,0987 | 0,0647 | 0,0521 |
| personal_freq (món mua nhiều nhất) | 0,4024 | 0,4143 | 0,2625 | 0,2055 |
| TIFU-KNN (đã tune trên val) | 0,4172 | 0,4327 | 0,2740 | 0,2143 |
| **LightGBM** | **0,4311** | **0,4492** | **0,2848** | **0,2221** |

- So với TIFU-KNN: Recall@15 **+0,014**, NDCG@15 **+0,017**.
- Kết quả trên test rất gần val (Recall@15: 0,431 trên test, 0,434 trên val), nên không có dấu hiệu overfit vào val.
- **Trần candidate**: top-100 candidate bao phủ 61,1% số món trong đơn thật trên test (60,4% trên val), lấy từ `recall_ceiling` trong `data/processed/meta.json`.
- **Mức trần**: khoảng 39% món trong giỏ thật là món khách chưa từng mua. Các món này nằm ngoài tập candidate của LightGBM và `personal_freq`, nên hai phương pháp này không thể đoán được (popularity và TIFU-KNN thì có thể, vì gợi ý cả món khách chưa mua). Recall@15 của một oracle xếp mọi món đúng trong candidate lên đầu (vẫn giới hạn 15 món) là **0,601 trên val**. LightGBM đạt 0,434 trên val, khoảng 72% mức trần đó. Oracle được tính trên val (`scripts/select_threshold.py`) để không phải xem test lần nữa.

## Model

- **LightGBM**, `objective = binary`, early stopping theo logloss trên val, không dùng `scale_pos_weight`. Tham số mặc định: `num_leaves = 63`, `min_data_in_leaf = 100`, `learning_rate = 0,05`, dừng ở vòng 517.
- **23 feature** (bộ v4), mô tả trong [features.md](features.md). Không dùng `product_id` làm feature, để áp được cho catalog khác.
- **Ablation trên val** (NDCG@15):

  | Lượt | NDCG@15 |
  | --- | --- |
  | v0 | 0,432 |
  | v1 | 0,437 |
  | v2 | 0,440 |
  | v3 (khách và món) | 0,449 |
  | v4 (ngữ cảnh) | 0,449 |

  Feature của khách và món giúp nhiều nhất. Feature ngữ cảnh gần như không thêm gì.
- **Feature quan trọng nhất**: `up_decay` (tần suất mua có trọng số theo độ gần đây) chiếm 70% gain.
- **Chỉnh tham số**: tăng giảm `num_leaves` hay `min_data_in_leaf` chỉ thay đổi khoảng ±0,0006. Thêm đơn T−3, T−4 làm nhãn train cho +0,0012, và là cấu hình được chọn.
- **Kiểm tra tay 5 khách**: top-15 hợp lý. Đứng đầu là món mua thường xuyên và vừa mua gần đây.

## Ngưỡng τ và calibration

![Reliability diagram](figures/reliability_val.png)

- **Calibration**: trên val, ECE = 0,0008 với 10 bin chia đều; trên test, ECE = 0,0013. Vì phần lớn xác suất nằm trong bin 0–0,1, ECE bin đều có thể che sai lệch, nên đã đo thêm trên val: **ECE với 10 bin quantile = 0,0010**, **Brier = 0,0815** (dự đoán hằng bằng tỉ lệ nền: 0,1022). Đường cong gần như trùng với đường chéo. Chỉ có bin cao nhất (dự đoán khoảng 0,92, thực tế 0,86, chỉ 562 dòng) là hơi tự tin quá. Vì ECE (cả hai cách chia bin) thấp hơn nhiều so với ngưỡng 0,02 nên **không cần isotonic**.
- **τ = 0,13**, chọn trên val theo F1@15. Một món được gợi ý nếu nằm trong top-15 **và** có xác suất ≥ τ.

  | | F1@15 | Precision | Recall | Số món gợi ý trung bình | Đơn không có gợi ý nào |
  | --- | --- | --- | --- | --- | --- |
  | val, τ = 0,13 | 0,318 | 0,321 | 0,379 | 10,4 | 0,8% |
  | val, không cắt (τ = 0) | 0,298 | 0,270 | 0,434 | 14,3 | 0% |
  | test, τ = 0,13 | 0,316 | 0,319 | 0,376 | 10,5 | 0,9% |

  Bảng này chia precision cho số món thực sự được gợi ý (không chia cho 15), nên khác F1@15 ở bảng kết quả (0,285). So sánh đúng là hai dòng val cùng định nghĩa: cắt bằng τ tăng F1@15 thêm **+0,020** (0,298 → 0,318), đổi lại recall giảm 0,055 và danh sách ngắn hơn khoảng 4 món.
- τ được ghi trong `weights/model_metadata.json`, cùng danh sách feature, tên file model và cách calibration. Code không viết cứng τ.

![Đường cong τ](figures/tau_curve_val.png)

## So sánh ở danh sách ngắn (val, 2026-11-05)

Backend hiện chỉ gợi ý 5 món, nên đã đo thêm ở @5 bằng [scripts/eval_topk.py](../scripts/eval_topk.py). Khoảng tin cậy 95% lấy từ bootstrap ghép cặp theo đơn (2.000 lần). Phần này chỉ dùng val, nên chưa phải kết quả của gate.

| Phương pháp | Recall@5 | Precision@5 | NDCG@5 | Có ít nhất 1 món đúng |
| --- | --- | --- | --- | --- |
| personal_freq | 0,2414 | 0,3668 | 0,4302 | 80,1% |
| TIFU-KNN | 0,2529 | 0,3870 | 0,4528 | 81,0% |
| LightGBM, không τ | **0,2627** | **0,4012** | **0,4688** | **82,4%** |
| LightGBM, τ = 0,13 | 0,2538 | 0,3945 | 0,4620 | 80,9% |

| Chênh lệch Recall (khoảng tin cậy 95%) | @5 | @15 |
| --- | --- | --- |
| LightGBM − personal_freq | +0,0213 (0,0195 đến 0,0229) | +0,0265 (0,0250 đến 0,0280) |
| LightGBM − TIFU-KNN | +0,0098 (0,0083 đến 0,0113) | +0,0109 (0,0095 đến 0,0122) |
| LightGBM τ − TIFU-KNN | +0,0009 (−0,0007 đến +0,0024) | −0,0440 (−0,0462 đến −0,0418) |

- LightGBM hơn baseline ở cả @5 và @15, nhưng mức hơn nhỏ.
- τ = 0,13 được chọn cho top-15. Áp vào top-5 thì mọi chỉ số đều giảm và lợi thế về Recall so với TIFU-KNN không còn rõ. Nếu chỉ hiện 5 món, không nên dùng τ này.
- Gate so Recall@15 khi chưa cắt theo τ, nên kết quả gate không áp dụng cho cấu hình có τ.

## Đưa model vào phục vụ (val, 2026-11-05)

- **ONNX**: `weights/lgbm_v4_selected.onnx` (opset 15). Trên 1.096.031 dòng val, sai lệch xác suất tối đa 2,6e-7, và top-15 của cả 20.000 đơn không đổi.
- **`POST /api/v1/predict`**: nhận lịch sử đơn của một khách, trả danh sách món. Không dự đoán số lượng. Chưa có xác thực, nên chỉ được mở trong mạng nội bộ. Backend chưa gọi endpoint này.
- **Latency CPU, Train/serve**: số đo nằm trong `latency_cpu` và `train_serve_check` của `weights/model_metadata.json`. Latency đo trong tiến trình, không tính mạng.
- **τ**: chỉ áp dụng khi `top_k` bằng 15, vì τ được chọn cho top-15 và làm giảm chỉ số ở top-5.
- **Ghép danh mục**: 11 danh mục được ghép tay với aisle trong `src/ml/category_map.json`, bao phủ 82,2% lượt mua Instacart. Catalog chưa có lịch sử bán, nên `p_reorder_ratio` và `a_reorder_ratio` dùng chung một tỉ lệ theo danh mục (`weights/category_stats.json`). Mô phỏng trên val cho thấy mức giảm nhỏ: Recall@5 0,2627 → 0,2595, Recall@15 0,4342 → 0,4301. Đây vẫn là dữ liệu Instacart, không nói được gì về hành vi khách Bách Hóa Xanh.
- **Luật hạn sử dụng**: catalog không có hạn dùng, nên hạn theo danh mục là giả định của nhóm.
  - `lot_expiring` (lô còn dưới 2 ngày): luôn bật, nhưng chỉ có tác dụng khi backend gửi hạn của lô.
  - `not_due` (hàng còn dùng được và chưa tới nửa chu kỳ mua): **tắt mặc định**. Trên val, luật này làm Recall@5 giảm từ 0,2627 xuống 0,2423 và Recall@15 từ 0,4342 xuống 0,3952. Món bị loại có tỉ lệ được mua 22,0%, gấp đôi mức trung bình 11,6%. Khách Instacart mua lại sớm hơn luật giả định, nên cần đo lại trên dữ liệu thật trước khi bật.

## Hạn chế

- **Không gợi ý được món mới**: 39% giỏ hàng là món khách chưa từng mua. Muốn vượt mức trần 0,60 thì cần thêm nguồn candidate, ví dụ món phổ biến trong aisle khách hay mua.
- **Val được dùng cho early stopping, chọn τ và đo calibration**, nên các con số trên val có thể hơi lạc quan. Kết quả test (ECE 0,0013, F1@15 với τ 0,316 so với 0,318 trên val) cho thấy ảnh hưởng này không đáng kể.
- **Chỉ chạy trên 20.000 khách.** Chưa chạy trên toàn bộ khoảng 200.000 khách. TIFU-KNN chỉ tìm láng giềng trong mẫu này, nên kết quả so sánh có thể đổi.
- **Test của baseline đã được xem nhiều hơn một lần** khi tune TIFU-KNN (script cũ tính cả test mỗi lần chạy). Điều này chỉ có thể có lợi cho baseline. Từ 2026-11-05, `baselines.py` mặc định chỉ tính val.
- **Instacart không có mùa vụ, khuyến mãi, hạn sử dụng**, nên không thể kết luận model học được các yếu tố này.
- **Instacart không có ngày tuyệt đối**, nên split dựa trên thứ tự đơn của từng khách, không phải mốc thời gian chung.
- **Áp cho Bách Hóa Xanh**: feature không phụ thuộc mã sản phẩm, nhưng phân phối hành vi mua có thể khác Instacart. Cần đo lại trên dữ liệu thật trước khi đưa vào sử dụng.

## Tái lập kết quả

```bash
python -m scripts.run_pipeline   # từ data/raw đến hết; không chạy lại test nếu đã có final_test.json
```

Đã chạy lại ngày 2026-11-05: toàn bộ ablation, chỉnh tham số và model được chọn (517 vòng, NDCG@15 val 0,4505), baseline trên val, τ và calibration đều ra đúng số cũ. Giữa hai lần sinh dữ liệu chỉ có `up_decay` lệch tối đa 1,8e-15 (nhiễu dấu phẩy động). Test không chạy lại. File model của lần chạy test cũ không còn để so từng byte, nên việc model mới trùng model đã test được suy ra từ các số trên val.

Kết quả gốc: `data/processed/final_test.json`, `data/processed/lgbm_runs.jsonl`, `weights/model_metadata.json`. Nhật ký chi tiết của từng lần chạy: [experiments.md](experiments.md).

## Bước tiếp theo

1. Chuyển model sang ONNX (đã kiểm tra converter với model đồ chơi), và viết `/predict` dùng `extract_features`. Chọn lại τ theo đúng số món sẽ hiển thị.
2. Chạy toàn bộ pipeline trên toàn bộ khách.
3. Thử thêm nguồn candidate ngoài lịch sử mua để vượt mức trần 0,60.
