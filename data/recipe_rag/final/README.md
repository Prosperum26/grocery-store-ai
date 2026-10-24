# Bộ file bàn giao cho bên web (v1)

Sinh bởi `scripts/build_final_handoff.py`. Giá không nằm trong catalog: bên web tự đặt giá.

| File | Nội dung |
| :-- | :-- |
| `catalog_v1.json` / `catalog_v1.csv` | Toàn bộ catalog để hiển thị (**1.775 sản phẩm**: 1.756 sản phẩm crawl + 19 thêm tay), mỗi sản phẩm có `catalog_id`. Đã loại 10 món không phải đồ ăn (dao thớt, bàn chải, dầu gội), danh sách ở `data/review/catalog_excluded_v1.json` |
| `ingredient_to_catalog_v1.json` | Nguyên liệu → danh sách `catalog_id` (phần tử đầu là mặc định) |
| `recipes_v1.json` | 100 công thức: nguyên liệu gốc, các bước làm và `basket` (giỏ hàng) |
| `validation_report.txt` | Kết quả kiểm tra tự động |

## `catalog_id` (KHÓA CỨNG)
- Dạng `CAT-000001` … `CAT-001775`. **Không bao giờ đổi, không bao giờ gán lại**, kể cả khi sản phẩm bị bỏ.
- Sản phẩm mới sau này chỉ được nối thêm (`CAT-001776`…). Sổ đăng ký: `data/review/catalog_ids_v1.json` (chỉ-đọc, có mã băm).
- Khi nhập vào Medusa: đặt **`sku = catalog_id`** cho variant. Tên, giá, ảnh đổi thoải mái, matching vẫn đúng vì khớp theo SKU.
- 14 tên sản phẩm bị trùng nhưng khác url/quy cách: phân biệt bằng `catalog_id` (xem cột `note`).

## `recipes_v1.json` → `basket`
Mỗi dòng giỏ: `ingredient`, `kind`, `catalog_ids` (danh sách, đã sắp ưu tiên), `default_catalog_id`, `packs`.
- `kind = core`: nguyên liệu chính, **chọn sẵn** trong giỏ.
- `kind = addon`: gia vị/đồ nhà có sẵn, hiện ở **cuối danh sách, KHÔNG chọn sẵn**; khách tự bấm thêm.
- `packs`: số đơn vị catalog cần mua, mặc định 1 (mua nguyên gói/lốc theo đơn vị catalog). Chỉ >1 khi công thức ghi
  g/kg/ml/lít và nhiều hơn quy cách của sản phẩm mặc định (làm tròn lên). Không quy đổi đơn vị khác.
- Nguyên liệu `side` (ăn kèm/rau nêm) chỉ nằm ở `ingredients`, không có sản phẩm.
- `depends_on_new_products`: các `catalog_id` thêm tay (`needs_review = true`) mà công thức cần.

## Chưa hoàn tất
- Chỉ **222** sản phẩm (id ≤ `CAT-001150`) được công thức dùng; 625 sản phẩm còn lại (`CAT-001151`–`CAT-001775`) chỉ để hiển thị.
- **19 sản phẩm thêm tay** (`source = manual_added`, `needs_review = true`): tên/đơn vị/danh mục là giá trị tạm. Chỉ **48/100 công thức** dùng được khi chưa có các sản phẩm này.
- **28 nguyên liệu addon** do AI gợi ý sản phẩm, chưa được người duyệt (`reviewed = false`).


---

## Bản v2 (mở rộng cho tất cả món phổ biến)

File v2 nằm cạnh v1, v1 giữ nguyên để so sánh. Id của 1.775 sản phẩm cũ KHÔNG đổi; 354 sản phẩm mới nhận id CAT-001776..CAT-002129.

| File | Nội dung |
| :--- | :--- |
| `catalog_v2.json` / `.csv` | 2.129 sản phẩm. 373 sản phẩm là thêm tay (`needs_review: true`): chưa có giá, ảnh; tên/đơn vị/danh mục là giá trị tạm. |
| `ingredient_to_catalog_v2.json` | Tên nguyên liệu (kể cả tên viết khác) -> `catalog_ids`, phần tử đầu là mặc định. `via` cho biết ghép theo cách nào. |
| `recipe_ingredients_v2.csv` | **Bảng phẳng dễ đọc**: mỗi dòng nguyên liệu của mỗi món (15.340 dòng) kèm sản phẩm catalog đã ghép (`catalog_id`, `product_name`, `packs`, `match_via`, `status`). Mở bằng Excel để lọc/kiểm. |
| `recipes_matched_v2.json` | Cùng nội dung với CSV nhưng **JSON lồng nhau** (mở trong IDE thu gọn/mở rộng được): món → `ingredients[]` → `match` (sản phẩm đã ghép + `alternatives`). Là một mảng JSON thường, không phải JSONL. |
| `recipes_v2.json` | 1.061 công thức (100 món mục tiêu + món phổ biến), mỗi món có `basket`, `family`, `family_rank`, `in_target_set`, `complete`. |
| `validation_report_v2.txt` | Kết quả kiểm tra tự động và danh sách ghép chọn tay. |

Giỏ hàng chọn sản phẩm mặc định theo thứ tự luật ghép (xem docstring `scripts/build_final_handoff_v2.py`). Sản phẩm mặc định là sản phẩm khớp đầu tiên, chưa phải lựa chọn tốt nhất; nên cho khách đổi sang các `catalog_ids` còn lại.
