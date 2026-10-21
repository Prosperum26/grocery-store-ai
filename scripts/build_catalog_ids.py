"""Gán catalog_id cho từng sản phẩm của catalog v2 và KHÓA CỨNG.

Chạy từ thư mục grocery-store-ai (sau build_catalog_v2.py):
    .venv\\Scripts\\python scripts\\build_catalog_ids.py

Đầu vào : data/raw/catalogs/products_clean_recipes_v2.json
Đầu ra  : data/review/catalog_ids_v1.json     sổ đăng ký id (KHÓA CỨNG)
          data/review/catalog_ids_v1.sha256   mã băm để phát hiện sửa tay

QUY TẮC KHÓA ID (code thực thi, không chỉ ghi chú):
  1. Khóa nhận diện (key) của sản phẩm: "url:<product_url>" nếu có, không thì "manual:<tên nguyên liệu>"
     (sản phẩm thêm tay). Id gắn với key này, KHÔNG gắn với tên, giá, danh mục hay thứ tự trong file,
     nên đổi tên/giá/quy cách không làm đổi id.
  2. Đã gán id thì không bao giờ đổi, không bao giờ gán lại cho sản phẩm khác, kể cả khi sản phẩm bị bỏ.
  3. Sản phẩm mới chỉ được NỐI THÊM vào cuối (next_number tăng dần, không tái sử dụng số).
  4. Sản phẩm biến mất khỏi catalog -> chuyển sang "retired", id vẫn giữ trong sổ.
  5. Mỗi lần chạy kiểm tra mã băm của sổ; lệch (ai đó sửa tay) thì dừng, không ghi gì.
"""
import hashlib
import json
import os
import stat
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_V2 = ROOT / "data" / "raw" / "catalogs" / "products_clean_recipes_v2.json"
REGISTRY = ROOT / "data" / "review" / "catalog_ids_v1.json"
HASH_FILE = ROOT / "data" / "review" / "catalog_ids_v1.sha256"
ID_FORMAT = "CAT-{:06d}"

README = [
    "SỔ ĐĂNG KÝ catalog_id. ĐÃ KHÓA CỨNG: id không bao giờ được đổi hay gán lại.",
    "Chỉ build_catalog_ids.py được ghi file này, và chỉ để NỐI THÊM sản phẩm mới (id tiếp theo).",
    "Sửa tay file này sẽ bị phát hiện (ids_sha256 và catalog_ids_v1.sha256) và mọi script sẽ dừng.",
    "key = 'url:<product_url>' cho sản phẩm có url, 'manual:<nguyên liệu>' cho sản phẩm thêm tay.",
]


def key_of(p):
    if p.get("product_url"):
        return "url:" + p["product_url"]
    if p.get("needed_for_ingredient"):
        return "manual:" + p["needed_for_ingredient"]
    raise SystemExit(f"sản phẩm '{p['name']}' không có product_url lẫn needed_for_ingredient, không tạo được khóa")


def digest(ids):
    """Mã băm của {key: id}, ổn định theo nội dung, không phụ thuộc thứ tự."""
    canonical = json.dumps({k: v["id"] for k, v in sorted(ids.items())}, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_registry():
    """Đọc sổ và kiểm tra nguyên vẹn. Dừng chương trình nếu có dấu hiệu bị sửa."""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    actual = digest(data["ids"])
    if actual != data["ids_sha256"] or actual != HASH_FILE.read_text(encoding="utf-8").strip():
        raise SystemExit("SỔ ID BỊ SỬA (mã băm không khớp). Khôi phục file gốc; tuyệt đối không tự đánh số lại.")
    numbers = sorted(int(v["id"].split("-")[1]) for v in data["ids"].values())
    if numbers != list(range(1, len(numbers) + 1)) or data["next_number"] != len(numbers) + 1:
        raise SystemExit("SỔ ID không liên tục hoặc next_number sai.")
    return data


def write_registry(data):
    for f in (REGISTRY, HASH_FILE):                 # gỡ chỉ-đọc để ghi, rồi khóa lại
        if f.exists():
            os.chmod(f, stat.S_IWRITE | stat.S_IREAD)
    data["ids_sha256"] = digest(data["ids"])
    REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    HASH_FILE.write_text(data["ids_sha256"] + "\n", encoding="utf-8")
    for f in (REGISTRY, HASH_FILE):
        os.chmod(f, stat.S_IREAD)


def main():
    catalog = json.loads(CATALOG_V2.read_text(encoding="utf-8"))
    keys = [key_of(p) for p in catalog]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise SystemExit(f"khóa trùng, không gán id được: {sorted(dup)[:5]}")

    if REGISTRY.exists():
        data = load_registry()
        status = "đã có sổ"
    else:
        data = {"_readme": README, "locked": True, "locked_on": date.today().isoformat(),
                "id_format": "CAT-NNNNNN (6 chữ số)", "next_number": 1, "ids": {}, "retired": {}}
        status = "tạo sổ mới"

    added = 0
    for p, k in zip(catalog, keys):
        if k not in data["ids"]:                    # chỉ nối thêm cuối sổ
            data["ids"][k] = {"id": ID_FORMAT.format(data["next_number"]), "name_at_assignment": p["name"],
                              "assigned_on": date.today().isoformat()}
            data["next_number"] += 1
            added += 1
    gone = sorted(set(data["ids"]) - set(keys))
    for k in gone:
        data["retired"].setdefault(k, data["ids"][k]["id"])
    if added or not REGISTRY.exists():
        write_registry(data)
    print(f"{status}: {len(data['ids'])} id (CAT-000001..{ID_FORMAT.format(data['next_number'] - 1)}), "
          f"thêm mới lần này: {added}, đã nghỉ (retired): {len(data['retired'])}")
    print(f"ids_sha256 = {data['ids_sha256']}")
    if gone:
        print("CẢNH BÁO: sản phẩm có id nhưng không còn trong catalog (id vẫn giữ, không dùng lại):", gone[:5])


if __name__ == "__main__":
    main()
