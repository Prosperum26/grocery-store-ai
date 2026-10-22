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
- Kết quả gốc của mỗi lần chạy nằm ở `data/processed/baselines.json` (không commit). Chép số liệu vào đây để lưu lại lâu dài.

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

## Ghi chú theo lần chạy

### 2026-10-22: baseline ban đầu

- `personal_freq` tốt hơn `popularity` khoảng 4 lần ở mọi metric. Hành vi mua lại mang tính cá nhân rất rõ.
- TIFU-KNN với tham số khởi đầu chỉ nhỉnh hơn `personal_freq` một chút.
- Tune TIFU-KNN trên val (8 cấu hình): cho đơn gần đây nặng ký hơn (nhóm nhỏ m=3, r_g nhỏ) giúp tăng điểm rõ nhất. Đổi k và α chỉ tác động nhỏ.
- TIFU-KNN đã tune là baseline mạnh nhất: NDCG@15 trên test 0,4327, so với 0,4143 của `personal_freq`.
- Mốc để model sau này phải vượt: **NDCG@15 ≈ 0,436 và Recall@15 ≈ 0,423 trên val** (TIFU-KNN đã tune).

### Mẫu cho lần sau

- **Mục tiêu**:
- **Thay đổi so với lần trước**:
- **Kết quả chính**:
- **Kết luận và bước tiếp theo**:
