"""Duyệt sơ bộ danh sách sản phẩm đề xuất, để người chỉ phải xem phần nhỏ thật sự cần quyết định.

Chạy từ thư mục grocery-store-ai (sau suggest_catalog_expansion.py và khi bạn đã duyệt sheet gop_ten_de_xuat):
    .venv\\Scripts\\python scripts\\triage_catalog_expansion.py candidates   # tính lại danh sách theo quyết định của bạn
    .venv\\Scripts\\python scripts\\triage_catalog_expansion.py apply        # ghép quyết định sơ bộ của AI -> Excel gọn

Hai bước:
 1. candidates: đọc file duyệt của bạn (CHỈ ĐỌC, không sửa), dùng các quyết định "gop" ở sheet gop_ten_de_xuat để tính lại
    món nào còn thiếu gì, rồi ghi data/review/catalog_expansion_candidates_v2.json. Danh sách này ngắn hơn nhiều vì bản
    đầu chỉ giả định 79 gợi ý gộp tên được chấp nhận, trong khi bạn đã chấp nhận hàng trăm.
 2. apply: đọc catalog_expansion_ai_decisions_v1.json (quyết định sơ bộ của AI cho từng sản phẩm, có lý do và độ chắc chắn)
    và ghi data/review/catalog_expansion_triage_v1.xlsx với sheet can_ban_quyet (chỉ mục AI không chắc hoặc ảnh hưởng lớn),
    ai_da_quyet (để bạn kiểm ngẫu nhiên) và tom_tat. Quyết định cuối cùng vẫn là của bạn.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from build_recipe_shortlist import EXCLUDED_CATEGORIES, PANTRY, find_matches, load_full_catalog
from suggest_catalog_expansion import classify, not_purchasable, popular_families

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "review"
SRC = REVIEW / "catalog_expansion_review_v1.xlsx"
CANDIDATES = REVIEW / "catalog_expansion_candidates_v2.json"
RECIPES = REVIEW / "catalog_expansion_recipes_v2.json"       # từng món: họ món, hạng, còn thiếu gì (để tính độ phủ)
DECISIONS = REVIEW / "catalog_expansion_ai_decisions_v1.json"
OUT = REVIEW / "catalog_expansion_triage_v1.xlsx"
K_MAX = 999                                           # 999 = tất cả món phổ biến


def read_sheet(wb, name):
    rows = wb[name].iter_rows(values_only=True)
    head = next(rows)
    return [dict(zip(head, r)) for r in rows]


def build_candidates():
    wb = load_workbook(SRC, read_only=True, data_only=True)       # chỉ đọc: file có thể đang mở trong Excel
    alias_rows = read_sheet(wb, "gop_ten_de_xuat")
    user_alias, user_no = {}, set()
    for r in alias_rows:
        d = str(r["quyet_dinh"] or "").strip().lower()
        if d == "gop":
            user_alias[r["nguyen_lieu_thieu"]] = r["gop_vao"]
        elif d.startswith("khong"):
            user_no.add(r["nguyen_lieu_thieu"])
    print(f"quyết định của bạn ở gop_ten_de_xuat: gộp {len(user_alias)}, không gộp {len(user_no)}, chưa điền {len(alias_rows) - len(user_alias) - len(user_no)}")

    recipes = json.loads((ROOT / "data" / "processed" / "recipes_clean.json").read_text(encoding="utf-8"))
    mapping = json.loads((REVIEW / "ingredient_catalog_map_v1.json").read_text(encoding="utf-8"))["ingredients"]
    additions = json.loads((REVIEW / "catalog_additions_v1.json").read_text(encoding="utf-8"))["additions"]
    catalog = load_full_catalog()
    available = {a["ingredient"] for a in additions} | {m["ingredient"] for m in mapping if m["status"] != "not_in_catalog"}
    cache = {}

    def present(name):
        if name not in cache:
            cache[name] = name in available or bool(find_matches(name, catalog))
        return cache[name]

    families, belongs, _ = popular_families(recipes)
    popular = [r for r in recipes if r["id"] in belongs]
    core_of = {r["id"]: sorted({i["name"] for i in r["ingredients"] if i["role"] == "main" and i["name"] not in PANTRY}) for r in popular}
    raw_line = {}
    for r in popular:
        for i in r["ingredients"]:
            raw_line.setdefault(i["name"], (i.get("raw_text") or "").replace("\t", " ").strip())
    missing_of = {rid: [n for n in core if not not_purchasable(n) and not present(n)] for rid, core in core_of.items()}
    after = {rid: [n for n in ms if n not in user_alias] for rid, ms in missing_of.items()}

    by_family = defaultdict(list)
    for r in popular:
        by_family[belongs[r["id"]]].append(r)
    rank = {}
    for fam, rs in by_family.items():
        rs.sort(key=lambda r: (len(after[r["id"]]), len(core_of[r["id"]]), r["name"]))
        for i, r in enumerate(rs, start=1):
            rank[r["id"]] = i
    names = {r["id"]: r["name"] for r in popular}

    print("K món đầu mỗi họ -> (số món, số món đã đủ sẵn, số sản phẩm cần thêm), SAU KHI áp quyết định của bạn:")
    for K in (1, 2, 3, 5, 10, 999):
        recs = [rid for rid, i in rank.items() if i <= K]
        print(f"   K={K}: {len(recs)} món, {sum(1 for rid in recs if not after[rid])} đủ sẵn, {len({n for rid in recs for n in after[rid]})} sản phẩm")

    RECIPES.write_text(json.dumps([{"id": rid, "ten": names[rid], "ho_mon": belongs[rid], "hang": rank[rid], "thieu": after[rid]}
                                   for rid in rank], ensure_ascii=False, indent=1), encoding="utf-8")
    supported = [rid for rid, i in rank.items() if i <= K_MAX]
    users = defaultdict(list)
    for rid in supported:
        for n in after[rid]:
            users[n].append(rid)
    candidates = []
    for n, rids in users.items():
        category, unit, sure = classify(n)
        k_min = min(rank[rid] for rid in rids)
        candidates.append({
            "name": n, "so_mon_can": len(rids), "ho_tro_tu_K": k_min, "danh_muc_may_doan": category, "don_vi_may_doan": unit,
            "may_chac_danh_muc": sure, "dong_goc": raw_line.get(n, ""), "vi_du_mon": [names[r] for r in rids[:3]],
            "user_khong_gop": n in user_no,
        })
    candidates.sort(key=lambda c: (c["ho_tro_tu_K"], -c["so_mon_can"], c["name"]))
    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {CANDIDATES.relative_to(ROOT)}: {len(candidates)} sản phẩm cần xét (K<={K_MAX}) | K=1: {sum(1 for c in candidates if c['ho_tro_tu_K'] == 1)}")


def resolve(name, decisions, seen=()):
    """Theo chuỗi 'gộp vào' tới đích cuối. Trả (loại, tên): 'them' (sản phẩm sẽ thêm), 'hoan' (hoãn, chưa thêm),
    'co_san' (đã có hoặc là nguyên liệu gốc có sẵn), 'bo' (không phải nguyên liệu), 'vong' (lỗi vòng)."""
    if name in seen:
        return "vong", name
    d = decisions.get(name)
    if d is None:
        return "co_san", name                                    # không phải ứng viên: sản phẩm/nguyên liệu đã có
    q = d["quyet_dinh"]
    if q == "bo":
        return "bo", name
    if q == "che_bien_tu":
        return "co_san", d["muc_tieu"]
    if q in ("them", "sua"):
        return "them", name                                      # hàng hiếm (độ chắc thấp) cũng thêm: người dùng đã chấp nhận phủ đủ món
    target = d["muc_tieu"].replace(" (đề xuất)", "").strip()      # gop
    return resolve(target, decisions, seen + (name,))


def apply_decisions():
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    recipes = json.loads(RECIPES.read_text(encoding="utf-8"))
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]
    names = {c["name"] for c in candidates}
    missing = [n for n in names if n not in decisions]
    if missing:
        sys.exit(f"{len(missing)} sản phẩm chưa có quyết định của AI, ví dụ: {missing[:8]}")

    # kiểm tra nhất quán: 'gộp vào' một đề xuất thì đề xuất đó phải được THÊM (không bị hoãn/bỏ), và không vòng
    problems = []
    final = {}
    for n in names:
        kind, target = resolve(n, decisions)
        final[n] = (kind, target)
        if decisions[n]["quyet_dinh"] == "gop" and kind in ("vong", "bo"):
            problems.append(f"'{n}' gộp vào '{decisions[n]['muc_tieu']}' nhưng đích là {kind}")
        if decisions[n]["quyet_dinh"] == "gop" and kind == "hoan" and decisions[n]["chac_chan"] != "thap":
            problems.append(f"'{n}' (độ chắc {decisions[n]['chac_chan']}) gộp vào '{target}' đang bị HOÃN")
    if problems:
        print("CẢNH BÁO nhất quán:")
        for x in problems:
            print("  -", x)

    # quyết định mặc định (nếu bạn không đổi gì): them thap -> hoãn
    def default_action(n):
        d = decisions[n]
        return d["quyet_dinh"]

    rows = []
    for c in candidates:
        d = decisions[c["name"]]
        act = default_action(c["name"])
        conflict = c["user_khong_gop"] and d["quyet_dinh"] in ("gop", "che_bien_tu")
        need = (d["quyet_dinh"] == "bo" and d["chac_chan"] == "thap") or (d["quyet_dinh"] == "gop" and d["chac_chan"] == "thap") or conflict
        tier = "can_ban_quyet" if need else ("de_sau" if act in ("them", "sua") and d["chac_chan"] == "thap" else ("kiem_nhanh" if d["chac_chan"] == "trung_binh" else "ai_da_quyet"))
        rows.append({**c, **d, "mac_dinh": act, "tier": tier, "dich_cuoi": final[c["name"]]})

    # độ phủ nếu áp quyết định MẶC ĐỊNH: món được hỗ trợ khi mọi nguyên liệu thiếu đều giải quyết được
    def coverage(K, accept_deferred=False):
        sup, need_products = 0, set()
        for r in recipes:
            if r["hang"] > K:
                continue
            prods, ok = set(), True
            for n in r["thieu"]:
                kind, tgt = final.get(n, ("co_san", n))
                if kind == "hoan" and not accept_deferred:
                    ok = False
                elif kind in ("them", "hoan"):
                    prods.add(tgt)
                elif kind == "vong":
                    ok = False
            if ok:
                sup += 1
                need_products |= prods
        return sup, len(need_products)

    stat = Counter((r["quyet_dinh"], r["chac_chan"]) for r in rows)
    tiers = Counter(r["tier"] for r in rows)
    wb = Workbook()
    ws = wb.active
    ws.title = "tom_tat"
    ws.append(["DUYỆT SƠ BỘ BẰNG AI (quyết định cuối vẫn là của bạn)"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Sản phẩm cần xét (hỗ trợ tối đa {K_MAX} món đầu mỗi họ, sau khi áp quyết định gộp tên của bạn)", len(rows)])
    ws.append([])
    ws.append(["Bạn cần làm gì", "số dòng", "sheet"])
    ws.append(["Cần BẠN quyết (AI không chắc nghĩa hoặc mâu thuẫn với lựa chọn trước của bạn)", tiers["can_ban_quyet"], "can_ban_quyet"])
    ws.append(["Kiểm nhanh (AI khá chắc, thường là gộp hoặc thêm hàng thông dụng): đọc lướt, sửa nếu thấy sai", tiers["kiem_nhanh"], "kiem_nhanh"])
    ws.append(["Hàng hiếm, AI khuyên ĐỂ SAU (không thêm). Chỉ xem nếu bạn muốn món đó", tiers["de_sau"], "de_sau"])
    ws.append(["AI chắc chắn cao: chỉ kiểm ngẫu nhiên ~20 dòng để biết AI đúng đến đâu", tiers["ai_da_quyet"], "ai_da_quyet"])
    ws.append([])
    ws.append(["QUYẾT ĐỊNH CỦA AI", "độ chắc chắn", "số dòng"])
    for (q, ch), n in sorted(stat.items()):
        ws.append([q, ch, n])
    ws.append([])
    ws.append(["NẾU ÁP QUYẾT ĐỊNH MẶC ĐỊNH CỦA AI", "số món được hỗ trợ", "số sản phẩm cần thêm", "(nếu cũng thêm cả hàng hiếm)"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for K in (1, 2, 3, 5, 10, 999):
        sup, prods = coverage(K)
        sup2, prods2 = coverage(K, accept_deferred=True)
        ws.append([f"hỗ trợ {K} món đầu mỗi họ (tổng {sum(1 for r in recipes if r['hang'] <= K)} món)", sup, prods, f"{sup2} món / {prods2} sản phẩm"])
    ws.append([])
    for line in ("them = nên thêm vào catalog làm sản phẩm.", "bo = không phải hàng mua được hoặc lỗi gõ/tách chữ, bỏ.",
                 "che_bien_tu:<X> = làm ra từ nguyên liệu khác (nước me từ me, mỡ hành từ hành lá), không thêm sản phẩm; chỉ cần có nguyên liệu gốc X.",
                 "gop:<X> = cùng một mặt hàng với X (đã có hoặc cũng đang đề xuất), gộp lại, không thêm sản phẩm riêng.",
                 "Một số đích gộp nằm trong danh mục snack/trà/cà phê nên hệ thống chưa tự ghép được; khi áp dụng sẽ ghép tay."):
        ws.append([line])
    for col, w in zip("ABCD", [110, 18, 24, 34]):
        ws.column_dimensions[col].width = w

    head = ["ho_tro_tu_K", "so_mon_can", "nguyen_lieu", "ai_quyet_dinh", "mac_dinh", "ai_chac_chan", "ai_ly_do", "ten_de_xuat", "danh_muc",
            "don_vi", "dong_goc", "vi_du_mon", "quyet_dinh_cua_ban", "ghi_chu"]
    fills = {"cao": "D4EDDA", "trung_binh": "FFF3CD", "thap": "F8D7DA"}

    def sheet(title, items):
        w = wb.create_sheet(title)
        w.append(head)
        for r in items:
            q = r["quyet_dinh"] + (f": {r['muc_tieu']}" if r.get("muc_tieu") else "")
            w.append([r["ho_tro_tu_K"], r["so_mon_can"], r["name"], q, r["mac_dinh"], r["chac_chan"], r["ly_do"], r.get("ten_de_xuat") or "",
                      r.get("danh_muc") or r["danh_muc_may_doan"], r.get("don_vi") or r["don_vi_may_doan"], r["dong_goc"],
                      " | ".join(r["vi_du_mon"]), "", ""])
            w.cell(w.max_row, 6).fill = PatternFill("solid", fgColor=fills[r["chac_chan"]])
        for col, wd in zip("ABCDEFGHIJKLMN", [8, 8, 26, 34, 10, 11, 52, 32, 24, 12, 44, 60, 18, 24]):
            w.column_dimensions[col].width = wd
        for c in w[1]:
            c.font = Font(bold=True)
        for row in w.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        w.freeze_panes = "D2"

    for tier in ("can_ban_quyet", "kiem_nhanh", "de_sau", "ai_da_quyet"):
        sheet(tier, sorted([r for r in rows if r["tier"] == tier], key=lambda r: (r["ho_tro_tu_K"], -r["so_mon_can"], r["name"])))
    wb.save(OUT)
    print(f"-> {OUT.relative_to(ROOT)}")
    print("tầng duyệt:", dict(tiers))
    for K in (1, 2, 3, 5, 10, 999):
        print(f"   K={K}: mặc định {coverage(K)} (món, sản phẩm) | nếu thêm cả hàng hiếm {coverage(K, True)}")


if __name__ == "__main__":
    {"candidates": build_candidates, "apply": apply_decisions}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
