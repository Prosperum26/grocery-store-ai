# Nhật ký thí nghiệm: predictive reorder

File này ghi lại kết quả của từng lần chạy baseline và model, để so sánh trên cùng một thước đo. Mỗi lần chạy thêm **một dòng** vào bảng kết quả và, nếu cần, một mục ghi chú bên dưới.

## Thiết lập chung

| Mục | Giá trị |
| --- | --- |
| Dữ liệu | Instacart, gộp prior và train, bỏ đơn `eval_set = test` |
| Lọc user | Ít nhất 5 đơn có sản phẩm |
| Split | Đơn cuối là test, đơn kế cuối là val, các đơn còn lại là train ([scripts/data_prep.py](../scripts/data_prep.py)) |
| Seed lấy mẫu user | 42 |
| Đánh giá | So với giỏ hàng thật đầy đủ của đơn nhãn, kể cả món chưa từng mua. Lấy trung bình theo đơn; đơn không có dự đoán được tính 0 |
| Metric | Recall@15, NDCG@15, F1@15, Precision@20. Precision@K chia cho K |

Quy tắc:
- Chỉ chọn tham số trên **val**. Chạy **test** cho cấu hình đã chốt, không tune lại theo kết quả test.
- Kết quả gốc của baseline trên val nằm ở `data/processed/baselines.json`, trên test ở `data/processed/final_test.json` (không commit). Chép số liệu vào đây để lưu lại lâu dài.

Lệnh chạy:

```bash
python -m scripts.baselines --users 20000
python -m scripts.baselines --users 20000 --group-size 7 --r-b 0.9 --r-g 0.7 --k-neighbors 300 --alpha 0.9
```

## Bảng kết quả

| Ngày | Người chạy | Commit | Số user | Phương pháp | Tham số | Split | Recall@15 | NDCG@15 | F1@15 | Precision@20 | Ghi chú |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-22 | | | 20.000 | popularity | top-20 toàn cục, chỉ đếm đơn không làm nhãn | val | 0,0862 | 0,0972 | 0,0638 | 0,0518 | |
| 2026-10-22 | | | 20.000 | popularity | như trên | test | 0,0870 | 0,0987 | 0,0647 | 0,0521 | |
| 2026-10-22 | | | 20.000 | personal_freq | mua nhiều nhất; hòa thì ưu tiên mua gần đây | val | 0,4078 | 0,4166 | 0,2631 | 0,2041 | |
| 2026-10-22 | | | 20.000 | personal_freq | như trên | test | 0,4024 | 0,4143 | 0,2625 | 0,2055 | |
| 2026-10-22 | | | 20.000 | TIFU-KNN | m=7, r_b=0,9, r_g=0,7, k=300, α=0,9 | val | 0,4114 | 0,4197 | 0,2652 | 0,2065 | Tham số khởi đầu, chưa tune |
| 2026-10-22 | | | 20.000 | TIFU-KNN | như trên | test | 0,4043 | 0,4148 | 0,2636 | 0,2066 | |
| 2026-10-22 | | | 20.000 | TIFU-KNN (đã tune) | m=3, r_b=0,9, r_g=0,6, k=900, α=0,7 | val | 0,4234 | 0,4362 | 0,2749 | 0,2137 | Chọn trên val |
| 2026-10-22 | | | 20.000 | TIFU-KNN (đã tune) | như trên | test | 0,4172 | 0,4327 | 0,2740 | 0,2143 | Chạy test một lần |
| | | | | | | | | | | | |

## Tune tham số (chỉ trên val)

| Ngày | Phương pháp | Tham số | Recall@15 | NDCG@15 | F1@15 | Precision@20 | Chọn? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-22 | TIFU-KNN | m=7, r_g=0,7, k=300, α=0,9 (khởi đầu) (r_b=0,9) | 0,4114 | 0,4197 | 0,2652 | 0,2065 |  |
| 2026-10-22 | TIFU-KNN | m=3, r_g=0,7, k=300, α=0,9 (r_b=0,9) | 0,4206 | 0,4311 | 0,2724 | 0,2119 |  |
| 2026-10-22 | TIFU-KNN | m=7, r_g=0,7, k=300, α=0,7 (r_b=0,9) | 0,4117 | 0,4201 | 0,2654 | 0,2066 |  |
| 2026-10-22 | TIFU-KNN | m=7, r_g=0,7, k=900, α=0,9 (r_b=0,9) | 0,4111 | 0,4194 | 0,2651 | 0,2064 |  |
| 2026-10-22 | TIFU-KNN | m=7, r_g=0,9, k=300, α=0,9 (r_b=0,9) | 0,3993 | 0,4056 | 0,2562 | 0,1998 |  |
| 2026-10-22 | TIFU-KNN | m=7, r_g=0,5, k=300, α=0,9 (r_b=0,9) | 0,4195 | 0,4294 | 0,2714 | 0,2111 |  |
| 2026-10-22 | TIFU-KNN | m=3, r_g=0,6, k=900, α=0,7 (r_b=0,9) | 0,4234 | 0,4362 | 0,2749 | 0,2137 | ✅ |
| 2026-10-22 | TIFU-KNN | m=7, r_g=0,7, k=900, α=0,7 (r_b=0,9) | 0,4112 | 0,4198 | 0,2651 | 0,2065 |  |
| | | | | | | | |

## LightGBM

Thiết lập: `objective = binary`, early stopping theo logloss trên val (dừng sau 50 vòng không cải thiện), không dùng `scale_pos_weight`. Tham số mặc định: `learning_rate = 0,05`, `num_leaves = 63`, `min_data_in_leaf = 100`, `feature_fraction = 0,9`, `bagging_fraction = 0,9`. Xếp hạng theo xác suất dự đoán, lấy top-20 cho mỗi đơn. Dữ liệu: 20.000 user, seed 42. Feature của từng lượt xem trong [features.md](features.md).

```bash
python -m scripts.data_prep --users 20000 --train-targets 1 --out-dir data/processed_tt1   # thư mục tạm, xóa sau khi chạy
python -m scripts.train_lgbm --versions v0,v1,v2,v3,v4 --data-dir data/processed_tt1 --tag ablation
```

Kết quả gốc của mỗi lần chạy nằm trong `data/processed/lgbm_runs.jsonl` (không commit).

### Ablation theo lượt feature (val, train_targets = 1)

| Lượt | Số vòng | Logloss val | Recall@15 | NDCG@15 | F1@15 | Precision@20 |
| --- | --- | --- | --- | --- | --- | --- |
| *TIFU-KNN (mốc)* | | | *0,4234* | *0,4362* | *0,2749* | *0,2137* |
| v0 | 89 | 0,29124 | 0,4212 | 0,4318 | 0,2734 | 0,2124 |
| v1 | 108 | 0,28731 | 0,4245 | 0,4372 | 0,2764 | 0,2144 |
| v2 | 113 | 0,28629 | 0,4256 | 0,4400 | 0,2774 | 0,2149 |
| v3 | 148 | 0,28137 | 0,4336 | 0,4490 | 0,2833 | 0,2194 |
| v4 | 222 | 0,28049 | 0,4336 | 0,4493 | 0,2833 | 0,2196 |

### Chỉnh nhẹ trên v4 (val, mỗi lần chỉ đổi một thứ so với v4 mặc định)

| Thay đổi | Số vòng | Logloss val | Recall@15 | NDCG@15 | F1@15 | Precision@20 | Chọn? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| *(v4 mặc định)* | 222 | 0,28049 | 0,4336 | 0,4493 | 0,2833 | 0,2196 | |
| `num_leaves = 31` | 364 | 0,28046 | 0,4340 | 0,4496 | 0,2835 | 0,2196 | |
| `num_leaves = 127` | 189 | 0,28058 | 0,4338 | 0,4495 | 0,2836 | 0,2195 | |
| `min_data_in_leaf = 20` | 218 | 0,28060 | 0,4341 | 0,4496 | 0,2837 | 0,2196 | |
| `min_data_in_leaf = 500` | 236 | 0,28043 | 0,4344 | 0,4499 | 0,2838 | 0,2198 | |
| Thêm đơn nhãn T−3, T−4 (`train_targets = 3`) | 517 | 0,27971 | 0,4342 | **0,4505** | 0,2839 | 0,2201 | ✅ |
| `train_targets = 3` + `min_data_in_leaf = 500` | 387 | 0,27969 | 0,4343 | 0,4504 | 0,2840 | 0,2201 | |

Model được chọn: **v4, `train_targets = 3`, tham số mặc định**, lưu tại `weights/lgbm_v4_selected.txt` (không commit). Chưa chạy trên test.

```bash
python -m scripts.data_prep --users 20000
python -m scripts.train_lgbm --versions v4 --tag selected --save-model
```

### Feature importance (v4, tỉ lệ gain)

| Feature | Gain | Feature | Gain |
| --- | --- | --- | --- |
| `up_decay` | 0,703 | `a_reorder_ratio` | 0,019 |
| `p_reorder_ratio` | 0,036 | `u_reorder_rate` | 0,019 |
| `up_rate` | 0,034 | `u_n_products` | 0,012 |
| `up_days_since` | 0,030 | `u_basket` | 0,011 |
| `up_orders_since` | 0,025 | `u_mean_dsp` | 0,011 |
| `streak_ratio` | 0,025 | `ua_rate` | 0,009 |
| `u_n_orders` | 0,021 | `up_mean_gap` | 0,006 |
| `t_dsp` | 0,019 | các feature còn lại | < 0,006 mỗi cái |

`t_dsp_capped` có gain bằng 0: thông tin này đã nằm sẵn trong `t_dsp`. `in_last_1/2/3` gần như vô dụng vì `up_decay` và `up_orders_since` đã chứa thông tin đó.

## Ghi chú theo lần chạy

### 2026-10-22: baseline ban đầu

- `personal_freq` tốt hơn `popularity` khoảng 4 lần ở mọi metric. Hành vi mua lại mang tính cá nhân rất rõ.
- TIFU-KNN với tham số khởi đầu chỉ nhỉnh hơn `personal_freq` một chút.
- Tune TIFU-KNN trên val (8 cấu hình): cho đơn gần đây nặng ký hơn (nhóm nhỏ m=3, r_g nhỏ) giúp tăng điểm rõ nhất. Đổi k và α chỉ tác động nhỏ.
- TIFU-KNN đã tune là baseline mạnh nhất: NDCG@15 trên test 0,4327, so với 0,4143 của `personal_freq`.
- Mốc để model sau này phải vượt: **NDCG@15 ≈ 0,436 và Recall@15 ≈ 0,423 trên val** (TIFU-KNN đã tune).

### 2026-10-23: LightGBM

- Thử ONNX trước (`python -m scripts.onnx_probe`): model đồ chơi có và không có cột categorical đều chuyển được. Sai lệch giữa ONNX và LightGBM khoảng 1e-7. Hiện mọi feature đều là số, kể cả `t_dow`, nên không cần categorical.
- Từ v3, LightGBM vượt TIFU-KNN. Bước tăng lớn nhất là v3 (feature khách và món): NDCG@15 tăng 0,009. v1 tăng 0,005, v2 tăng 0,003, còn v4 gần như không thêm gì.
- `up_decay` chiếm 70% gain. Model chủ yếu dựa vào tần suất có trọng số theo độ gần đây.
- Kiểm tra tay 5 khách (`--inspect 5`): top-15 trông hợp lý. Đứng đầu là món mua thường xuyên và vừa mua ở đơn gần nhất. Món đã lâu không mua bị đẩy xuống dù tổng số lần mua cao. Phần lớn món bị bỏ sót là món mới, nằm ngoài tập candidate.
- Chỉnh `num_leaves` và `min_data_in_leaf` chỉ thay đổi NDCG@15 khoảng ±0,0006. Thêm đơn nhãn T−3, T−4 cho mức tăng lớn nhất (+0,0012) và là cấu hình được chọn.
- Kết quả so với TIFU-KNN trên val: NDCG@15 0,4505 so với 0,4362 (+0,014), Recall@15 0,4342 so với 0,4234.

### 2026-10-23: chọn τ, calibration, model gate

- Calibration trên val: ECE = 0,0008 (ngưỡng 0,02), nên không dùng isotonic. Hình: [figures/reliability_val.png](figures/reliability_val.png).
- Quét τ từ 0,02 đến 0,60 trên val: **τ = 0,13**, F1@15 = 0,318 (precision 0,321, recall 0,379, trung bình 10,4 món mỗi đơn). Đã ghi vào `weights/model_metadata.json`.
- **Chạy test một lần** (`python -m scripts.final_eval`):

  | Phương pháp | Recall@15 | NDCG@15 | F1@15 | Precision@20 |
  | --- | --- | --- | --- | --- |
  | popularity | 0,0870 | 0,0987 | 0,0647 | 0,0521 |
  | personal_freq | 0,4024 | 0,4143 | 0,2625 | 0,2055 |
  | TIFU-KNN | 0,4172 | 0,4327 | 0,2740 | 0,2143 |
  | **LightGBM** | **0,4311** | **0,4492** | **0,2848** | **0,2221** |

  LightGBM với τ = 0,13 trên test: F1@15 = 0,316. ECE trên test = 0,0013.
- **Gate: QUA.** Recall@15 của LightGBM là 0,4311, cao hơn TIFU-KNN (0,4172). Báo cáo: [report.md](report.md).

### 2026-10-26: rà soát lại calibration, F1 và mức trần (chỉ val)

- ECE với 10 bin quantile = 0,0010 (bin đều 0,0008). Brier = 0,0815, so với 0,1022 khi luôn dự đoán tỉ lệ nền. Kết luận calibrate tốt vẫn giữ.
- F1@15 cùng định nghĩa (precision chia cho số món gợi ý): không cắt 0,298, với τ = 0,13 là 0,318. Mức tăng thật nhờ τ là +0,020, không phải +0,033 như khi so với 0,285.
- Oracle Recall@15 trên val = 0,601 (tính trực tiếp, thay cho ước lượng từ tỉ lệ 39% món mới). LightGBM đạt 0,434, khoảng 72%.
- Chạy lại `select_threshold`: τ vẫn = 0,13. Không chạy lại test.

### 2026-11-05: gộp dữ liệu, chạy lại toàn bộ, đo @5 (chỉ val)

- Dọn dữ liệu: xóa `data/processed/test.zip` (702 MB, bộ parquet cũ không còn dùng), bỏ bộ `train_targets = 1` khỏi đĩa và chuyển `data/processed_tt3` thành `data/processed`. Bộ `train_targets = 1` chỉ được tạo tạm khi chạy `scripts/run_pipeline.py`.
- Chạy lại `run_pipeline`: mọi dòng ablation và chỉnh tham số trùng số cũ, τ vẫn = 0,13. ONNX probe: sai lệch 1,1e-7 cả có và không có categorical. Không chạy lại test.
- Đo @5, @10, @15 kèm bootstrap: xem [report.md](report.md). Recall@5: LightGBM 0,2627, TIFU-KNN 0,2529, personal_freq 0,2414. τ = 0,13 làm giảm mọi chỉ số ở top-5.

### Kiểm tra bằng mắt: top-15 của 5 khách mẫu (val)

Chạy với `--inspect 5` (5 khách lấy ngẫu nhiên, seed 42). Kết quả đầy đủ ở `data/processed/inspect_v4_selected.md` (không commit) gồm top-15, 15 món mua nhiều nhất và đơn gần nhất của từng khách.

| User | Số món đúng trong top-15 |
| --- | --- |
| 168532 | 7 |
| 66191 | 3 |
| 202814 | 8 |
| 144589 | 3 |
| 163899 | 8 |

Nhận xét: đầu danh sách luôn là các món mua thường xuyên và vừa mua ở đơn trước (ví dụ user 66191: Flaky Biscuits 10/10 đơn, điểm 0,82). Món mua ít lần hay đã lâu không mua thì bị xếp xuống dưới. Phần cuối top-15 (điểm ~0,1) là các món mới mua một lần ở đơn gần nhất, ít khi trúng. Model không đoán được món khách chưa từng mua, đúng như giới hạn của tập candidate. Thứ tự này hợp lý.

### Cấu hình máy

Từ 2026-10-26, mỗi dòng trong `lgbm_runs.jsonl` và `model_metadata.json` có thêm trường `machine` (OS, CPU, số nhân, phiên bản Python và LightGBM). Các lần chạy trước đó không ghi máy. Máy dev hiện tại: Windows 11 (10.0.26300), Intel 64 Family 6 Model 154, LightGBM 4.7.0, seed 42.

### Mẫu cho lần sau

- **Mục tiêu**:
- **Thay đổi so với lần trước**:
- **Kết quả chính**:
- **Kết luận và bước tiếp theo**:
