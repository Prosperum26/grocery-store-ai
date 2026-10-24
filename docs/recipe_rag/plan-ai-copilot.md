# Kế hoạch: API tìm món và giỏ hàng nguyên liệu trên ai-service

Trạng thái: bản nháp để nhóm thống nhất (2026-10-24). Tiếp nối issue #8. Mục có đánh dấu **[cần xác nhận]** là giả định chưa kiểm chứng.

## 1. Quyết định đã chốt

| # | Quyết định | Lý do ngắn |
| :-- | :-- | :-- |
| 1 | **ai-service lo trọn phần AI**: tìm món, lớp lời (Gemini/Claude), kiểm tra schema, bản dự phòng | Khóa API, cấu hình bật/tắt model, schema, số đo nằm một chỗ; khớp mô tả Chef Copilot của đồ án |
| 2 | Đường đi cố định: **Frontend → Medusa backend → ai-service**. Frontend không gọi thẳng ai-service | Giá, ảnh, tồn kho, giỏ hàng chỉ có ở Medusa; ai-service chỉ biết `catalog_id`. Thêm một chặng chỉ tốn vài chục ms so với vài giây của mô hình |
| 3 | Hai endpoint: `/v1/search` (nhanh, không mô hình) và `/v1/copilot` (thêm lời AI) | Backend/web chọn cấp độ; có thể hiện món ngay rồi bổ sung lời giải thích |
| 4 | Giỏ hàng luôn do **code** dựng. Mô hình không ghi `catalog_id` hay số lượng | Mô hình hỏng thì giỏ vẫn đúng |
| 5 | Danh sách có hai phần: `buy` (số lượng mặc định 1) và `maybe_have` (mặc định 0). Khách tăng số lượng; AI chỉ gợi ý | Đơn giản; khớp `core`/`addon` trong dữ liệu |
| 6 | Gemini là nhà cung cấp chính; Claude (Haiku 5.5) tắt mặc định, bật khi demo. Chuỗi dự phòng: Gemini → Claude (nếu bật) → bản code cứng | Rẻ, có lớp dự phòng |
| 7 | Trang admin bật/tắt nhà cung cấp; cấu hình lưu ở `ai_db`, ai-service tự đọc | Không phụ thuộc backend; đổi là có hiệu lực trong vài giây |
| 8 | Để sau: dị ứng, ngân sách, nhóm sản phẩm thay thế tốt hơn, cải thiện chọn sản phẩm mặc định | Chờ giá từ web và matching tốt hơn |

## 2. Kiến trúc

```text
Web (Next.js) ──► Medusa backend ──► ai-service (FastAPI)
                  │  gắn giá/ảnh/tồn kho     ├─ lớp dữ liệu: hybrid search + giỏ dựng sẵn (luôn có)
                  │  đổi catalog_id→variant  └─ lớp lời AI: provider theo cấu hình → kiểm tra schema
                  ▼                              lỗi / hết giờ / tắt → chỉ trả lớp dữ liệu
            thêm vào giỏ Medusa
Trang admin Medusa ──► route backend (đã xác thực admin) ──► ai-service /admin/*
```

Trong lúc backend chưa có route: web tạm gọi ai-service từ phía server của Next.js (route handler), khóa không lộ ra trình duyệt; về sau đổi địa chỉ sang backend.

## 3. Hợp đồng API (v1, có thể đổi khi làm)

Mọi endpoint (trừ `/health`) cần header `X-Internal-Key` (khóa dùng chung backend ↔ ai-service). Phản hồi có `request_id`.

### `GET /health`
`{ "status": "ok", "db": true, "model_loaded": true }`

### `POST /v1/search`
Yêu cầu:
```json
{ "query": "canh chua cá lóc cho 4 người", "servings": 4, "top_k": 5,
  "have": ["cà chua", "CAT-000939"] }
```
`servings` bỏ trống thì lấy từ câu hỏi ("cho 4 người"). `have`: tên nguyên liệu hoặc `catalog_id` khách đã có.

Phản hồi:
```json
{ "request_id": "...", "query": "canh chua cá lóc", "servings": 4,
  "accepted": true, "threshold": 0.64,
  "results": [{
    "recipe": { "id": "canh-chua-ca-loc", "name": "Canh chua cá lóc", "family": "canh chua",
                "servings": 4, "time_minutes": 40, "difficulty": "dễ",
                "description": "...", "image_url": "...", "source_url": "..." },
    "score": 0.71, "matched_by": "both",
    "complete": true,
    "basket": {
      "buy":        [ Item, ... ],
      "maybe_have": [ Item, ... ] } }] }
```
`accepted=false`: điểm dưới ngưỡng, `results` vẫn là món gần nhất, web nên hiển thị kèm cảnh báo "chưa có món đúng ý".

`Item`:
```json
{ "ingredient": "cá lóc", "kind": "core", "raw_text": "Cá lóc 500g",
  "need": { "quantity": 500, "unit": "g", "scaled_for": 4 },
  "product": { "catalog_id": "CAT-001138", "name": "Cá lóc làm sạch vỉ 300g", "category": "Cá, hải sản",
               "pack_size": 300, "pack_unit": "g" },
  "default_qty": 1, "pack_hint": 2,
  "alternatives": [ { "catalog_id": "...", "name": "..." } ] }
```
`default_qty` là 1 ở `buy`, 0 ở `maybe_have`. `pack_hint` chỉ có khi lượng cần và quy cách cùng loại đơn vị (g, kg, ml, lít), ngược lại `null`.

### `POST /v1/copilot`
Cùng yêu cầu như `/v1/search`. Phản hồi:
```json
{ "data": { /* y hệt phản hồi /v1/search */ },
  "ai": { "provider": "gemini", "model": "...", "recipe_id": "canh-chua-ca-loc",
          "explanation": "...",
          "item_notes": [ { "ingredient": "cá lóc", "note": "Nên mua khoảng 2 vỉ cho 4 người" } ],
          "prep_notes": [ { "name": "nước me", "from_ingredient": "me", "steps": ["..."] } ],
          "follow_up_question": null },
  "ai_status": "ok",
  "latency_ms": 2300 }
```
`ai` là `null` nếu lớp lời lỗi. `ai_status`: `ok` | `fallback_invalid` | `fallback_timeout` | `fallback_error` | `fallback_disabled`. Web luôn hiển thị được `data`.

### Admin (chỉ backend gọi)
- `GET /admin/ai-settings`: danh sách nhà cung cấp (`enabled`, `priority`, `model`, `timeout_s`, `key_configured`), cờ `backup_only`.
- `PUT /admin/ai-settings/providers/{name}`: đổi `enabled`, `priority`, `model`, `timeout_s`.
- `PUT /admin/ai-settings/backup-only`: `{ "backup_only": true }` (tắt hẳn lớp AI).
- `GET /admin/ai-stats?window=24h`: số lần gọi, tỉ lệ hợp lệ, tỉ lệ dự phòng, độ trễ, token theo nhà cung cấp.

Khóa API không bao giờ nằm trong DB hay phản hồi; chỉ có biến môi trường của ai-service.

## 4. Dữ liệu

Đã có trong `ai_db`: `recipe`, `recipe_ingredient`, `recipe_embedding` (thẻ món + vector nguyên liệu).

Cần thêm:
- `recipe_basket`: giỏ dựng sẵn của từng món (từ `recipes_matched_v2.json`), cập nhật được mà không phải triển khai lại.
- `catalog_product`: catalog v2 (tên, danh mục, quy cách) để trả `product`.
- `ai_provider_setting`: `provider`, `enabled`, `priority`, `model`, `timeout_s`, `updated_by`, `updated_at`; thêm hàng cho công tắc tổng `backup_only`.
- `ai_call_log`: `request_id`, `provider`, `status`, `latency_ms`, `tokens_in`, `tokens_out`, `created_at` (không lưu nội dung câu hỏi nhạy cảm).

Nguồn: `data/recipe_rag/final/` (nay là bản v2). Catalog id đã khóa cứng; bản cập nhật sau chỉ nối thêm.

## 5. Các giai đoạn

| GĐ | Việc | Làm xong khi | Cỡ |
| :-- | :-- | :-- | :-: |
| 1 | Khung service trong `src/`: cấu hình, nối `ai_db`, nạp bge-m3 khi khởi động, `/health`, nạp `recipe_basket` và `catalog_product` | `/health` OK; nạp đủ 1.061 món | M |
| 2 | `/v1/search`: hybrid (từ khóa bỏ dấu + bge-m3), ngưỡng, giỏ hai phần, tách "cho N người", `have` | Chạy lại bộ 108 câu qua API: Recall@5 khớp script đo (hybrid ≈ 0.99); p95 < 1 giây | M |
| 3 | Dữ kiện cho prompt: lượng cần đã nhân theo khẩu phần, quy cách, `pack_hint` | Có test đơn vị cho phép tính | S |
| 4 | Lớp lời AI: provider Gemini, schema Pydantic, kiểm tra (món nằm trong top-K, nguyên liệu có trong giỏ), thử lại 1 lần, dự phòng, `/v1/copilot` | Khi lỗi cố ý (JSON hỏng, hết giờ), `data` vẫn trả đủ | L |
| 5 | Provider Claude Haiku 5.5 dùng chung schema; chuỗi dự phòng theo cấu hình | Bật/tắt qua DB có tác dụng ≤ vài giây | M |
| 6 | Admin API + `ai_call_log` + `/admin/ai-stats` | Đổi cấu hình qua API, log ghi đúng | M |
| 7 | Đo lường: bộ 108 câu qua cả hai provider; thêm 50 câu hỏi thật do người khác gán nhãn | Có bảng: tỉ lệ JSON hợp lệ, tỉ lệ dự phòng, độ trễ, chi phí, Recall@5 | M |
| 8 | README `ai-service`, `.env.example`, Dockerfile nếu kịp | Người mới chạy được theo README | S |

Thứ tự: 1 → 2 (bàn giao sớm cho web) → 3 → 4 → 5 và 6 song song → 7 → 8.

**Mốc bàn giao sớm cho web:** sau GĐ 2 web đã có `/v1/search` đủ để dựng giao diện món + giỏ. Lớp lời AI thêm sau mà không làm đổi cấu trúc `data`.

## 6. Việc của backend/web (ngoài repo AI) **[cần xác nhận]**

1. **Ánh xạ `catalog_id` → sản phẩm Medusa.** Giả định đã thống nhất ở #8: SKU của variant = `catalog_id`. Cần web xác nhận khi nạp catalog v2.
2. **Route chuyển tiếp** `/store/ai/search` và `/store/ai/copilot` trong backend: xác thực người dùng, gọi ai-service bằng `X-Internal-Key`, gắn giá/ảnh/tồn kho, trả cho frontend.
3. **Sản phẩm chưa mua được:** 373 sản phẩm thêm tay chưa có giá, ảnh. Giỏ có thể chứa sản phẩm web chưa mở bán; backend cần đánh dấu `purchasable=false` để giao diện xử lý (ẩn hoặc báo hết hàng). Ở bản đầu ai-service không biết tồn kho.
4. **Thêm vào giỏ:** gom các dòng `qty > 0` và gọi API giỏ hàng Medusa.
5. **Trang admin** trong Medusa Admin: công tắc từng nhà cung cấp, thứ tự ưu tiên, model, công tắc tổng, bảng số liệu. Gọi qua route backend đã xác thực admin.
6. **Cập nhật catalog:** khi nhóm AI phát hành bản mới, web nạp theo `catalog_id` (chỉ nối thêm, id cũ không đổi).

## 7. Rủi ro và cách giảm

| Rủi ro | Giảm bằng |
| :-- | :-- |
| JSON của mô hình sai | Schema nhỏ, kiểm tra, thử lại 1 lần, lớp dữ liệu luôn trả; đo tỉ lệ ở GĐ 7 |
| Sản phẩm mặc định chưa tốt (vd. thịt heo xay thay vì thịt heo) | Khách đổi bằng `alternatives`; cải thiện chọn mặc định ở việc riêng sau |
| Hết giờ / nhà cung cấp chết giữa buổi demo | Giới hạn thời gian từng provider; chuỗi dự phòng; công tắc tổng |
| Lộ khóa API | Khóa chỉ ở biến môi trường ai-service; không ghi vào DB/giao diện/log |
| Nhãn đo do AI soạn nên lạc quan | Thêm 50 câu hỏi thật với người gán nhãn độc lập (GĐ 7) |
| Ngưỡng "không tìm thấy" dao động | Xem là khoảng 0.60–0.66; đo lại trên câu hỏi thật |
| Mô hình bịa nơi mua / hướng dẫn | Chỉ dùng công thức và món phụ đã duyệt; hướng dẫn món phụ sinh sẵn rồi người duyệt |

## 8. Câu hỏi còn mở

- Gemini dùng model nào, cách khai báo schema trả JSON (tra tài liệu trước khi làm GĐ 4).
- Hướng dẫn món phụ (`che_bien_tu`): sinh sẵn hay sinh khi hỏi? Mình nghiêng về sinh sẵn rồi duyệt.
- Có cần lưu lịch sử hội thoại nhiều lượt không? Bản đầu: mỗi lượt độc lập, không có phiên.
- Giới hạn tần suất gọi (rate limit) đặt ở backend hay ai-service?
