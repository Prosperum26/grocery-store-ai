"""Sinh file Excel để duyệt tay: mỗi nguyên liệu core của tập công thức mục tiêu -> sản phẩm catalog.

Chạy từ thư mục grocery-store-ai (cần openpyxl; sau build_recipe_shortlist.py):
    .venv\\Scripts\\python scripts\\recipe_rag\\build_ingredient_review.py            # không ghi đè file đã có
    .venv\\Scripts\\python scripts\\recipe_rag\\build_ingredient_review.py --force    # ghi đè (MẤT phần đã duyệt)

Đầu ra : data/recipe_rag/review/ingredient_matches_review_v1.xlsx, gồm 3 sheet:
    huong_dan   cách điền
    nguyen_lieu mỗi dòng 1 nguyên liệu core, tối đa 5 sản phẩm ứng viên, cột `quyet_dinh` để điền
    pantry      danh sách đồ nhà có sẵn, cột `quyet_dinh` (giu / bo)
File nằm ở data/recipe_rag/review/ (KHÔNG phải data/recipe_rag/processed/) để các script khác không ghi đè; nên commit
file này sau khi duyệt vì nó là bảng ghép chính thức.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from build_recipe_shortlist import PANTRY, find_matches, load_full_catalog

ROOT = Path(__file__).resolve().parents[2]
SHORTLIST = ROOT / "data" / "recipe_rag" / "processed" / "recipes_shortlist.json"
PANTRY_CSV = ROOT / "data" / "recipe_rag" / "processed" / "pantry_review.csv"
OUT = ROOT / "data" / "recipe_rag" / "review" / "ingredient_matches_review_v1.xlsx"
MAX_CANDIDATES = 5

GUIDE = [
    "CÁCH DUYỆT (sheet nguyen_lieu)",
    "",
    "Mỗi dòng là 1 nguyên liệu chính (core) dùng trong 100 công thức đã chọn.",
    "Đọc cột vi_du_dong_goc để biết công thức thật sự cần gì, rồi xem các cột ung_vien_1..5.",
    "Điền cột quyet_dinh bằng MỘT trong các cách sau:",
    "",
    "  ok          đồng ý với cột goi_y (gợi ý của máy)",
    "  1           chọn ứng viên số 1 (tương tự 2, 3, 4, 5)",
    "  1,3         chọn nhiều ứng viên: giỏ hàng chọn sẵn cái đầu, khách có thể đổi sang cái sau",
    "  none        catalog KHÔNG có sản phẩm phù hợp (không đoán, sẽ báo 'chưa có trong catalog')",
    "  pantry      đây là đồ nhà thường có sẵn, không cần đưa vào giỏ",
    "  alias:X     nguyên liệu này giống hệt nguyên liệu X (X là tên ở cột nguyen_lieu)",
    "  sp:TÊN      chọn một sản phẩm khác không có trong ứng viên; TÊN chép đúng tên sản phẩm catalog",
    "",
    "Cột ghi_chu: ghi lý do khi chọn none / alias / sp, hoặc khi phân vân.",
    "Dòng màu đỏ (THIẾU): máy không tìm thấy gì, chỉ cần chọn none / pantry / alias / sp.",
    "Dòng màu vàng (CẦN CHỌN): có ứng viên nhưng máy không chắc, hãy đọc kỹ.",
    "Dòng màu xanh (GỢI Ý): khớp đúng tên, thường chỉ cần gõ ok sau khi liếc qua.",
    "",
    "Nguyên tắc: thà chọn none còn hơn chọn sai. Giỏ hàng có 'dầu tỏi' khi món cần tỏi là lỗi nặng.",
    "Dạng: 'tỏi phi' được gộp về 'tỏi' (làm tại nhà được); 'tôm khô', 'cà chua hộp' là hàng riêng.",
    "",
    "SHEET pantry: điền giu (giữ là đồ có sẵn, không vào giỏ) hoặc bo (bỏ khỏi pantry, sẽ phải có trong catalog).",
    "",
    "Xong thì lưu file, báo lại để chạy bước tiếp theo (đọc quyết định thành bảng ghép chính thức).",
]
FILL = {"THIẾU": "F8D7DA", "CẦN CHỌN": "FFF3CD", "GỢI Ý": "D4EDDA"}


def describe(m):
    pack = f"{m['pack_size']:g}{m['pack_unit']}" if m["pack_size"] else "không rõ quy cách"
    return f"{m['product']}  |  {m['category']}  |  {pack}"


def main():
    if OUT.exists() and "--force" not in sys.argv:
        sys.exit(f"{OUT.relative_to(ROOT)} đã tồn tại (có thể đã duyệt). Dùng --force nếu thật sự muốn ghi đè.")
    shortlist = json.loads(SHORTLIST.read_text(encoding="utf-8"))
    catalog = load_full_catalog()

    recipes, raws, forms = defaultdict(list), defaultdict(list), defaultdict(set)
    for r in shortlist:
        for i in r["ingredients"]:
            if i["kind"] != "core":
                continue
            if r["name"] not in recipes[i["name"]]:
                recipes[i["name"]].append(r["name"])
            if i["raw_text"] and len(raws[i["name"]]) < 2 and i["raw_text"] not in raws[i["name"]]:
                raws[i["name"]].append(" ".join(i["raw_text"].split()))
            if i["form"]:
                forms[i["name"]].add(i["form"])

    rows = []
    for name in recipes:
        cands = find_matches(name, catalog)[:MAX_CANDIDATES]
        if not cands:
            status, hint = "THIẾU", "none"
        elif cands[0]["source"] == "exact" and cands[0]["form"] is None:
            status, hint = "GỢI Ý", "1"
        else:
            status, hint = "CẦN CHỌN", ""
        rows.append((status, name, cands, hint))
    order = {"THIẾU": 0, "CẦN CHỌN": 1, "GỢI Ý": 2}
    rows.sort(key=lambda x: (order[x[0]], -len(recipes[x[1]]), x[1]))

    wb = Workbook()
    ws = wb.active
    ws.title = "huong_dan"
    for line in GUIDE:
        ws.append([line])
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 120

    ws = wb.create_sheet("nguyen_lieu")
    header = ["trang_thai", "nguyen_lieu", "so_mon", "vi_du_mon", "vi_du_dong_goc", "dang",
              *[f"ung_vien_{k}" for k in range(1, MAX_CANDIDATES + 1)], "goi_y", "quyet_dinh", "ghi_chu"]
    ws.append(header)
    for status, name, cands, hint in rows:
        ws.append([status, name, len(recipes[name]), "; ".join(recipes[name][:3]), " || ".join(raws[name]),
                   ", ".join(sorted(forms[name])),
                   *[describe(c) for c in cands] + [""] * (MAX_CANDIDATES - len(cands)), hint, "", ""])
        fill = PatternFill("solid", fgColor=FILL[status])
        for cell in ws[ws.max_row][:2]:
            cell.fill = fill
    widths = [11, 22, 7, 40, 40, 8, *[45] * MAX_CANDIDATES, 8, 12, 30]
    for col, w in zip("ABCDEFGHIJKLMN", widths):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws["M1"].fill = PatternFill("solid", fgColor="CCE5FF")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions

    ws = wb.create_sheet("pantry")
    lines = PANTRY_CSV.read_text(encoding="utf-8-sig").splitlines()
    import csv
    reader = list(csv.reader(lines))
    ws.append(["nguyen_lieu", "so_dong_moi_cong_thuc", "so_mon_trong_100", "catalog_co_ban",
               "vi_du_san_pham", "quyet_dinh", "ghi_chu"])
    for name, all_lines, short, has, examples, _ in reader[1:]:
        ws.append([name, int(all_lines), int(short), has, examples, "", ""])
    for col, w in zip("ABCDEFG", [24, 12, 12, 10, 90, 12, 30]):
        ws.column_dimensions[col].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "B2"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    count = {s: sum(1 for r in rows if r[0] == s) for s in order}
    print(f"{len(rows)} nguyên liệu: {count} | pantry: {len(reader) - 1} -> {OUT.relative_to(ROOT)}")
    assert PANTRY == {r[0] for r in reader[1:]}, "pantry_review.csv lệch với PANTRY, chạy lại build_recipe_shortlist.py"


if __name__ == "__main__":
    main()
