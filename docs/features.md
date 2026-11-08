# Feature cho predictive reorder

Mọi feature được tạo bởi một hàm duy nhất, `extract_features(history, at, item_stats, version)` trong [src/ml/feature_extractor.py](../src/ml/feature_extractor.py). Pipeline offline ([scripts/data_prep.py](../scripts/data_prep.py)) và endpoint `/predict` sau này đều gọi đúng hàm này, nên feature lúc train và lúc phục vụ giống hệt nhau.

## Đầu vào

| Tham số | Nội dung |
| --- | --- |
| `history` | Lịch sử mua, mỗi dòng là một cặp (đơn, sản phẩm): `user_id`, `order_number`, `day`, `dsp`, `dsp_capped`, `add_to_cart_order`, `reordered`, `product_id`, `aisle_id` |
| `at` | Thời điểm dự đoán, mỗi dòng là một cặp (user, đơn cần dự đoán): `user_id`, `t_order`, `t_day`, `t_dow`, `t_hour`, `t_dsp`, `t_dsp_capped`. Với user thật, dùng `prediction_point(history, dow, hour, days_since_last)` để tạo |
| `item_stats` | Thống kê theo sản phẩm và aisle, tạo bởi `item_stats(history)`. Chỉ cần từ v3 trở đi. Khi tạo dữ liệu train, chỉ tính trên các đơn không bao giờ làm nhãn |
| `version` | `v0` … `v4`, quyết định trả về những feature nào |

Hàm chỉ dùng các đơn có `order_number < t_order`. Nếu `history` có chứa đơn từ thời điểm dự đoán trở về sau, các đơn đó bị bỏ qua (có test riêng cho điều này).

## Quy ước

- Mỗi dòng là một cặp **(thời điểm dự đoán, sản phẩm candidate)**. Candidate là tối đa 100 sản phẩm user đã mua trước `t_order`, xếp theo `up_decay`. **Mọi version dùng chung một tập candidate**, nên khi so các lượt với nhau chỉ có feature thay đổi.
- Tiền tố: `up_` = user × sản phẩm, `u_` = user, `p_` = sản phẩm, `a_` = aisle, `ua_` = user × aisle, `t_` = thời điểm dự đoán.
- "Đơn trước" là các đơn có `order_number < t_order`. `n` = số đơn trước = `u_n_orders`.
- `day` là số ngày cộng dồn từ đơn đầu tiên. Khi `days_since_prior_order` bị chặn ở 30, mọi feature tính theo ngày chỉ là **cận dưới** của giá trị thật.
- **`product_id` và `aisle_id` chỉ là khóa, không bao giờ là feature.** Feature chỉ gồm số đếm, tỉ lệ và khoảng thời gian, nên model huấn luyện trên Instacart có thể áp dụng cho catalog Bách Hóa Xanh. Có test kiểm tra không feature nào có tên kết thúc bằng `_id`.

## Các cột không phải feature

| Cột | Ý nghĩa |
| --- | --- |
| `user_id`, `t_order`, `product_id` | Khóa của dòng |
| `up_last_order` | `order_number` lần mua gần nhất. Chỉ dùng để kiểm tra rò rỉ (luôn < `t_order`) |
| `label` | Chỉ có trong dữ liệu train/val/test: 1 nếu sản phẩm có trong đơn `t_order` |

## Bảng feature

Mỗi lượt gồm toàn bộ feature của các lượt trước, cộng thêm các feature mới.

### v0: tần suất cơ bản

| Feature | Ý nghĩa | Công thức |
| --- | --- | --- |
| `up_cnt` | Số lần user mua sản phẩm | số đơn trước có sản phẩm |
| `up_orders_since` | Số đơn kể từ lần mua cuối | `t_order − up_last_order` |
| `up_rate` | Tỉ lệ đơn có sản phẩm | `up_cnt / u_n_orders` |

### v1: nhịp mua

| Feature | Ý nghĩa | Công thức |
| --- | --- | --- |
| `up_days_since` | Số ngày từ lần mua cuối | `t_day − day(lần mua cuối)` |
| `up_mean_gap` | Khoảng cách trung bình giữa hai lần mua liên tiếp (ngày) | trung bình `day[i] − day[i−1]` trên các lần mua. Null nếu mới mua một lần |
| `streak_ratio` | Đã tới lúc mua lại chưa (gần 1 là đúng hạn, lớn hơn 1 là quá hạn) | `up_days_since / up_mean_gap`. Null nếu `up_mean_gap` null hoặc bằng 0. Cố ý để null, LightGBM xử lý trực tiếp |

### v2: độ gần đây

| Feature | Ý nghĩa | Công thức |
| --- | --- | --- |
| `up_decay` | Tần suất có trọng số, lần mua càng gần đây càng nặng | `Σ 0,9^(t_order − order_number)` trên các lần mua |
| `in_last_1`, `in_last_2`, `in_last_3` | Có trong 1, 2 hoặc 3 đơn gần nhất không | `up_orders_since ≤ 1`, `≤ 2`, `≤ 3` (0/1) |

### v3: khách và món

| Feature | Ý nghĩa | Công thức |
| --- | --- | --- |
| `u_n_orders` | Số đơn trước của khách | đếm đơn có `order_number < t_order` |
| `u_basket` | Cỡ giỏ trung bình | trung bình số món mỗi đơn |
| `u_reorder_rate` | Tỉ lệ món là hàng mua lại | `Σ reordered / Σ số món` |
| `u_n_products` | Số sản phẩm khác nhau đã mua | đếm `product_id` khác nhau |
| `u_mean_dsp` | Số ngày trung bình giữa các đơn | trung bình `dsp`, không tính đơn đầu |
| `u_pct_capped` | Tỉ lệ khoảng cách giữa các đơn ≥ 30 ngày (bị chặn) | trung bình `dsp_capped`, không tính đơn đầu |
| `p_reorder_ratio` | Tỉ lệ mua lại toàn cục của sản phẩm | trung bình `reordered` trên mọi lần mua sản phẩm (từ `item_stats`) |
| `a_reorder_ratio` | Tỉ lệ mua lại toàn cục của aisle | trung bình `reordered` trên mọi lần mua trong aisle (từ `item_stats`) |
| `ua_rate` | Mức độ khách hay mua trong aisle này | số đơn trước có ít nhất một món thuộc aisle / `u_n_orders` |

Feature của món là tỉ lệ, không phải số đếm, nên không phụ thuộc vào kích thước bộ dữ liệu. Với catalog mới, chỉ cần tính lại `item_stats` từ lịch sử bán hàng của catalog đó.

### v4: ngữ cảnh đơn cần dự đoán

| Feature | Ý nghĩa | Công thức |
| --- | --- | --- |
| `t_dow` | Thứ trong tuần (0–6) | `order_dow` của đơn `t_order` |
| `t_hour` | Giờ đặt (0–23) | `order_hour_of_day` của đơn `t_order` |
| `t_dsp` | Số ngày từ đơn trước tới đơn cần dự đoán | `days_since_prior_order`, chặn ở 30 |
| `t_dsp_capped` | Khoảng cách có bị chặn không | `t_dsp ≥ 30` (0/1) |

## Dùng theo lượt

Các file parquet được lưu với đầy đủ feature của v4. Khi train từng lượt, chỉ lấy các cột của lượt đó:

```python
from src.ml.feature_extractor import FEATURE_SETS

X_train = train.select(FEATURE_SETS["v2"])
```

Kết quả của từng lượt ghi vào [experiments.md](experiments.md).

## Thay đổi so với bộ feature trước

Các cột sau đã bị bỏ: `up_first_order`, `up_avg_cart_pos`, `p_cnt`, `p_avg_cart_pos`, `p_n_users`.
- `p_cnt` và `p_n_users` là số đếm, phụ thuộc kích thước bộ dữ liệu, nên không chuyển được sang catalog khác.
- Các cột còn lại không nằm trong kế hoạch theo lượt.

Nếu cần, có thể thêm lại trong một lượt riêng.
