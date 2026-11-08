"""Tạo ingredient_matches_review_v2.xlsx từ bản v1 người dùng đã duyệt.

Chạy từ thư mục grocery-store-ai:  .venv\\Scripts\\python scripts\\recipe_rag\\build_review_v2.py [--force]

v1 KHÔNG bị sửa. v2 = v1 + các thay đổi:
  1. AI_FIXES: sửa các quyết định có vấn đề (đối chiếu ứng viên với dòng gốc trong công thức).
     Quyết định cũ của người dùng được giữ ở cột quyet_dinh_goc, lý do ở cột ai_chinh_sua.
  2. alias:<số hàng> đổi thành alias:<tên nguyên liệu> (số hàng vỡ khi lọc/sắp xếp).
  3. Các ô "1,2" bị Excel đổi thành số 1.2 được ghi lại thành chữ "1,2".
  4. Sheet pantry_san_pham: mỗi nguyên liệu pantry -> ứng viên sản phẩm (hàng thùng/lốc xuống cuối)
     kèm gợi ý của AI (goi_y) để người dùng duyệt tiếp.
"""
import re
import shutil
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from build_recipe_shortlist import PANTRY, find_matches, load_full_catalog

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "data" / "recipe_rag" / "review"
V1 = REVIEW / "ingredient_matches_review_v1.xlsx"
V2 = REVIEW / "ingredient_matches_review_v2.xlsx"

# ingredient -> (quyết định mới, lý do). "none" kèm "Tự thêm vào catalog" = sẽ có trong catalog_additions_v1.json.
AI_FIXES = {
    "đậu hũ": ("3,2", "Công thức cần đậu hũ TRẮNG; ứng viên 1 là đậu hũ chiên, 4 là đậu hũ cá phô mai"),
    "phô mai": ("3", "Công thức cần phô mai LÁT; ứng viên 3 là phô mai lát, 1 là phô mai bào"),
    "cua": ("none", "Cua đồng xay khác cua nguyên con (công thức: cua 1kg). Tự thêm vào catalog"),
    "chanh": ("1", "Bỏ chanh dây (ứng viên 2), không phải chanh"),
    "cá thu": ("none", "Ứng viên là cá thu sốt cà đóng hộp và cá thu đao (khác loài); công thức cần cá thu tươi. Tự thêm vào catalog"),
    "bơ": ("4,5", "Dòng 'Tiêu, dầu ăn, bơ' là bơ làm bếp, không phải trái bơ"),
    "nấm": ("1", "Công thức là nấm bào ngư, chỉ ứng viên 1 là bào ngư"),
    "bánh mì": ("none", "Cả 5 ứng viên là bánh ngọt/đóng gói, công thức cần ổ bánh mì. Tự thêm vào catalog"),
    "hạt sen": ("none", "Công thức cần hạt sen TƯƠI, catalog chỉ có hạt sen khô (hàng khác theo quy tắc dạng khó làm). Tự thêm vào catalog"),
    "nghệ": ("none", "Công thức là nghệ băm (nghệ tươi), ứng viên là nghệ bột. Tự thêm vào catalog"),
    "mực": ("4,3,2", "Đưa 'Mực ống' tươi lên đầu; bỏ 'Mực trứng' (loại riêng); hàng đông lạnh làm lựa chọn phụ"),
    "bắp cải": ("1", "Bỏ bắp cải thảo (loại khác)"),
    "trứng gà ta": ("alias:trứng gà", "alias 140 trỏ về chính nó; ghi chú của bạn nói giống 'trứng gà'"),
    "nấm kim châm": ("2,3,1", "Ứng viên 1 là gói 3 hộp (450g), đưa Thái Lan 150g và Hàn Quốc 150g lên đầu"),
}

# Gợi ý của AI cho sheet pantry_san_pham: số thứ tự ứng viên (người duyệt có thể đổi), hoặc sp:<tên>.
PANTRY_SUGGEST = {
    "bột canh": ("1", ""),
    "bột chiên giòn": ("1,2", ""),
    "bột ngọt": ("1,3", "400g và 100g (gói nhỏ cho nhà ít dùng)"),
    "bột năng": ("1,2", ""),
    "bột tẩm khô chiên giòn": ("none", "Tự thêm vào catalog (bạn đã xác nhận)"),
    "dầu hào": ("1,2", ""),
    "dầu mè": ("1", ""),
    "dầu ăn": ("1,3,2", "Chai 1 lít trước, chai 400ml nhỏ; không chọn hàng thùng"),
    "dầu điều": ("none", "Tự thêm vào catalog"),
    "giấm gạo": ("1", ""),
    "gừng": ("1", ""),
    "hành lá": ("1", ""),
    "hành tím": ("1", ""),
    "hạt nêm": ("8,7,1", "Aji-ngon heo 170g đúng nhãn trong công thức; Knorr 170g; Neptune 850g"),
    "muối": ("5,1", "Muối tinh sấy iot và muối hạt; bỏ muối tôm, muối ớt (là gia vị chấm)"),
    "ngò rí": ("1", ""),
    "nêm sẵn lẩu": ("sp:Xốt gia vị nêm sẵn lẩu Thái Chinsu gói 80g", "Catalog đầy đủ đã có sản phẩm này; không cần thêm mới"),
    "nước mắm": ("1,2,5", ""),
    "nước tương": ("1,4", ""),
    "rượu trắng": ("none", "Tự thêm vào catalog"),
    "sả": ("1", ""),
    "tiêu": ("2,1,3", "Tiêu xay trước (công thức dùng tiêu xay), tiêu hạt làm phụ"),
    "tương cà": ("1,3", ""),
    "tương ớt": ("6,1", ""),
    "tỏi": ("2,1", "Tỏi tím và tỏi cô đơn; bỏ tỏi phi giòn (hàng chế biến)"),
    "xốt mayonnaise": ("1,2", ""),
    "đường": ("2,4", "Đường kính trắng 500g và 1kg; bỏ đường lỏng, đường phèn"),
    "ớt": ("5,7,4", "Ớt hiểm, ớt sừng, ớt xiêm; bỏ ớt xay và ớt bột (hàng khác)"),
}
MAX_CAND = 8
BLUE = PatternFill("solid", fgColor="CCE5FF")
GREY = PatternFill("solid", fgColor="E7E6E6")


def text(x):
    return "" if x is None else str(x).strip()


def decision_text(v):
    """Ô quyết định -> chuỗi. Số thực 1.2 (Excel đổi '1,2' theo dấu thập phân VN) -> '1,2'."""
    if isinstance(v, float):
        return str(v).replace(".", ",")
    return text(v)


def main():
    if V2.exists() and "--force" not in sys.argv:
        sys.exit(f"{V2.name} đã tồn tại (có thể đã duyệt tiếp). Dùng --force để ghi đè.")
    shutil.copyfile(V1, V2)
    wb = load_workbook(V2)
    ws = wb["nguyen_lieu"]
    header = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(header)}
    names_by_row = {r: text(ws.cell(r, col["nguyen_lieu"]).value) for r in range(2, ws.max_row + 1)}
    n_orig, n_fix = len(header) + 1, len(header) + 2
    ws.cell(1, n_orig, "quyet_dinh_goc").font = Font(bold=True)
    ws.cell(1, n_fix, "ai_chinh_sua").font = Font(bold=True)

    changed = {"fix": 0, "alias_name": 0, "float": 0}
    for r in range(2, ws.max_row + 1):
        name = names_by_row[r]
        cell = ws.cell(r, col["quyet_dinh"])
        original = cell.value
        new, why = decision_text(original), ""
        if isinstance(original, float):
            changed["float"] += 1
        m = re.fullmatch(r"alias:\s*(\d+)", new, re.IGNORECASE)
        if m:                                       # alias:<số hàng> -> alias:<tên>
            target = names_by_row.get(int(m.group(1)), "")
            new, why = f"alias:{target}", f"alias số hàng {m.group(1)} đổi thành tên '{target}'"
            changed["alias_name"] += 1
        if name in AI_FIXES:
            new, why = AI_FIXES[name][0], AI_FIXES[name][1]
            changed["fix"] += 1
        if new != text(original) or why:
            ws.cell(r, n_orig, text(original))
            ws.cell(r, n_fix, why)
        cell.value, cell.number_format = new, "@"   # ép kiểu chữ để Excel không đổi '1,2' thành số
        if name in AI_FIXES:
            cell.fill = BLUE
            note = ws.cell(r, col["ghi_chu"])
            if "catalog" in AI_FIXES[name][1] and "catalog" not in text(note.value).lower():
                note.value = (text(note.value) + " " if note.value else "") + "Tự thêm vào catalog"
    for letter, w in (("O", 20), ("P", 60)):
        ws.column_dimensions[letter].width = w

    # Sheet pantry_san_pham -------------------------------------------------------------
    catalog = load_full_catalog()
    ps = wb.create_sheet("pantry_san_pham")
    ps.append(["nguyen_lieu", *[f"ung_vien_{k}" for k in range(1, MAX_CAND + 1)], "goi_y", "quyet_dinh", "ghi_chu"])
    pantry_rows = [text(row[0].value) for row in wb["pantry"].iter_rows(min_row=2)]
    assert set(pantry_rows) == set(PANTRY_SUGGEST), "PANTRY_SUGGEST lệch với danh sách pantry"
    for name in pantry_rows:
        cands = find_matches(name, catalog)[:MAX_CAND]
        shown = [f"{c['product']}  |  {c['category']}  |  "
                 f"{(format(c['pack_size'], 'g') + c['pack_unit']) if c['pack_size'] else 'không rõ quy cách'}"
                 f"{'  |  HÀNG THÙNG/LỐC' if c['multipack'] else ''}" for c in cands]
        suggest, note = PANTRY_SUGGEST[name]
        ps.append([name, *shown, *[""] * (MAX_CAND - len(shown)), suggest, "", note])
        ps.cell(ps.max_row, MAX_CAND + 2).number_format = "@"
        ps.cell(ps.max_row, MAX_CAND + 3).number_format = "@"
    for letter, w in zip("ABCDEFGHIJKLM", [22, *[46] * MAX_CAND, 24, 12, 50]):
        ps.column_dimensions[letter].width = w
    for row in ps.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    for c in ps[1]:
        c.font = Font(bold=True)
    ps.cell(1, MAX_CAND + 3).fill = BLUE
    ps.freeze_panes = "B2"

    guide = wb["huong_dan"]
    for line in [
        "", "=== GHI CHÚ BẢN v2 (AI chỉnh) ===",
        "Dòng tô XANH DƯƠNG ở sheet nguyen_lieu là quyết định AI đã sửa; cột quyet_dinh_goc giữ quyết định cũ của bạn, ai_chinh_sua ghi lý do.",
        "Muốn giữ lựa chọn cũ của bạn: chép lại quyet_dinh_goc vào quyet_dinh.",
        "Sheet pantry_san_pham: pantry cũng phải ghép sản phẩm (khách bấm chọn thêm ở cuối danh sách, không chọn sẵn). Cột goi_y là AI gợi ý,",
        "điền quyet_dinh nếu muốn khác (cú pháp giống sheet nguyen_lieu: số, 1,3, none, sp:TÊN). Để trống = dùng goi_y (đánh dấu 'chưa duyệt').",
        "Hàng thùng/lốc đã bị đẩy xuống cuối danh sách ứng viên (ghi rõ HÀNG THÙNG/LỐC).",
        "Mọi ô quyết định đều là dạng chữ; hãy gõ '1,2' như bình thường, file đã ép kiểu chữ để Excel không đổi thành số 1.2.",
    ]:
        guide.append([line])
    wb.save(V2)
    print(f"đã tạo {V2.relative_to(ROOT)} | sửa {changed['fix']} quyết định, {changed['alias_name']} alias đổi sang tên, "
          f"{changed['float']} ô '1,2' ép lại thành chữ | pantry_san_pham: {len(pantry_rows)} dòng")


if __name__ == "__main__":
    main()
