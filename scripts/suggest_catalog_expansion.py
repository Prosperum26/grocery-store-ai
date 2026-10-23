"""Gợi ý mở rộng catalog để phủ các món phổ biến, xuất Excel để duyệt tay.

Chạy từ thư mục grocery-store-ai:
    .venv\\Scripts\\python scripts\\suggest_catalog_expansion.py            # không ghi đè file đã duyệt
    .venv\\Scripts\\python scripts\\suggest_catalog_expansion.py --force    # ghi đè (MẤT phần đã duyệt)

Cách làm (mọi bước đều in số liệu để kiểm tra):
 1. MÓN PHỔ BIẾN: tên công thức được làm sạch rồi đếm các cụm 2 từ kiểu "canh chua", "gà nướng", "cơm chiên".
    Cụm có từ chỉ món (canh, kho, xào, nướng...) lặp lại >= MIN_FAMILY lần là một "họ món phổ biến"; thêm một ít
    họ món nền tảng của bếp Việt (WHITELIST). Mọi công thức thuộc một họ như vậy là "món phổ biến".
 2. THIẾU GÌ: với mỗi món, nguyên liệu chính (role main, không thuộc PANTRY) nào chưa có sản phẩm trong catalog
    (kể cả sản phẩm thêm tay trong catalog_additions_v1.json) là nguyên liệu thiếu.
 3. GỘP TÊN: nhiều nguyên liệu "thiếu" thực ra là tên gọi khác của hàng đã có ("gừng mài" = "gừng", "đầu hành lá"
    = "hành lá"). Gợi ý bằng cách bỏ từ cuối/đầu tên cho tới khi khớp; kèm độ giống bge-m3 làm tham khảo. CẦN DUYỆT.
 4. SẢN PHẨM ĐỀ XUẤT: nguyên liệu còn lại cần sản phẩm mới. Tên, danh mục, đơn vị là ĐỀ XUẤT TẠM theo từ khóa.
 5. BAO NHIÊU LÀ ĐỦ: bảng "nếu chỉ hỗ trợ món thiếu tối đa k nguyên liệu thì cần thêm bao nhiêu sản phẩm".
Chỉ đọc dữ liệu hiện có và ghi file Excel; không sửa catalog hay id.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from build_recipe_shortlist import EXCLUDED_CATEGORIES, PANTRY, find_matches, load_full_catalog

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "review"
OUT = REVIEW / "catalog_expansion_review_v1.xlsx"
MIN_FAMILY = 6          # một cụm tên phải lặp lại ít nhất ngần này công thức mới tính là "họ món phổ biến"

DISH_WORDS = {"canh", "kho", "xào", "nướng", "chiên", "rang", "luộc", "hấp", "lẩu", "gỏi", "súp", "cháo", "cơm",
              "bún", "phở", "miến", "mì", "chả", "nem", "rim", "om", "cuốn", "salad"}
NOT_A_DISH = {"xốt", "sốt", "mayo", "giòn", "và", "với", "kiểu", "cho", "nhật", "thái", "hàn", "chay", "lá", "ngũ", "sắc",
              "thập", "cẩm", "hải", "mặn", "ngọt", "cay", "xù", "áp", "chảo"}
# Họ món nền tảng của bếp Việt có thể không đủ lặp trong dữ liệu; chỉ tính nếu có công thức khớp.
WHITELIST = {"bánh mì", "bánh xèo", "bánh cuốn", "chả giò", "hoành thánh", "cà ri", "khổ qua", "bí đao", "bí đỏ",
             "đậu hũ", "rau muống", "thịt kho", "cá kho", "trứng chiên", "trứng cuộn", "bún chả", "bún riêu", "phở bò"}
NOISE = re.compile(r"^(cách (làm|nấu|chế biến)|bí quyết|công thức|hướng dẫn|làm|nấu|tổng hợp|top \d+|\d+ cách)\s+", re.I)
# Từ chỉ là mô tả, bỏ đi thì vẫn là cùng mặt hàng -> gợi ý gộp tên có độ tin cậy cao.
MODIFIERS = {"tươi", "mài", "củ", "mọng", "chín", "non", "già", "sống", "loại", "baby", "ta", "úc", "mỹ", "đỏ", "xanh",
             "vàng", "trắng", "nhỏ", "lớn", "tách", "vỏ", "nguyên", "con", "đầu", "cọng", "lát", "sợi", "băm", "nhuyễn"}
# Tên quá chung: không gợi ý gộp vào đây (sẽ gộp bừa "thịt ba chỉ bò" thành "thịt").
# Không phải hàng mua được (động từ sơ chế, món tự nấu, tên chung chung...): bỏ khỏi danh sách "thiếu" nhưng liệt kê ở sheet bo_qua để bạn kiểm.
SKIP_START = {"cắt", "băm", "thái", "xắt", "giã", "đập", "chẻ", "nguyên", "phần", "loại", "các", "vài", "ít"}
# "nước ..." tự làm (nước me, nước tắc, nước nắm) không phải hàng mua; chỉ giữ các loại nước đóng chai/lon sẵn có.
LIQUID_PRODUCTS = {"nước mắm", "nước tương", "nước cốt dừa", "nước cốt chanh", "nước dừa", "nước màu", "nước hàng", "nước suối", "nước khoáng", "nước soda"}
SKIP_EXACT = {"cơm trắng", "cơm", "rau củ", "nước dùng", "nước vôi trong", "muối đường", "rau sống", "nước lọc", "bột chiên", "xốt"}
SKIP_CONTAINS = ("nước dùng", "nguyên liệu", "salad mỡ", "ăn kèm", "các loại", "tùy ý")
TOO_GENERIC = {"bắp", "bông", "mỡ", "rượu", "đầu", "chả", "baking", "ngò", "cam", "nạm", "ớt", "dưa", "thịt", "cá", "rau", "nấm", "hành", "dầu", "bột", "nước", "trứng", "tôm", "gà", "bò", "heo", "đậu", "củ",
               "lá", "hạt", "xốt", "tương", "sữa", "cải", "bí", "khoai", "mì", "bánh", "cơm", "bún", "gạo", "muối", "đường"}


def clean_name(name):
    """'Cách làm canh chua cá lóc ngon...' -> 'canh chua cá lóc'."""
    n = name.lower().strip()
    for sep in (":", " - ", " – ", ",", "|", "("):
        n = n.split(sep)[0]
    n = NOISE.sub("", n)
    n = re.sub(r"\s+(ngon|đơn giản|dễ làm|tại nhà|chuẩn vị|đậm đà|thơm ngon|hấp dẫn|cực|siêu|nhanh|mềm|giòn).*$", "", n)
    return n.strip()


def popular_families(recipes):
    """Trả {họ món: số công thức} và gắn họ món cho từng công thức."""
    names = {r["id"]: clean_name(r["name"]) for r in recipes}
    bigrams = Counter()
    for n in names.values():
        t = n.split()
        bigrams.update({" ".join(t[i:i + 2]) for i in range(len(t) - 1)})     # mỗi công thức chỉ tính 1 lần cho mỗi cụm

    def dish_like(bg):
        a, b = bg.split()
        return (a in DISH_WORDS and b not in NOT_A_DISH) or (b in DISH_WORDS and a not in NOT_A_DISH)

    families = {bg: c for bg, c in bigrams.items() if (dish_like(bg) and c >= MIN_FAMILY) or (bg in WHITELIST and c >= 2)}
    belongs = {}
    for rid, n in names.items():
        t = n.split()
        mine = [bg for bg in {" ".join(t[i:i + 2]) for i in range(len(t) - 1)} if bg in families]
        if mine:
            belongs[rid] = max(mine, key=lambda b: families[b])
    return families, belongs, names


def shorten_candidates(name):
    """Các cách rút gọn tên: bỏ dần từ cuối (ưu tiên, danh từ chính đứng đầu), rồi bỏ dần từ đầu.
    Chặt hơn bản đầu: phần còn lại phải >= 2 từ, hoặc những từ bị bỏ chỉ là mô tả (MODIFIERS). Tránh
    'thịt bò bắp' -> 'bắp', 'bông bí' -> 'bông'."""
    t = name.split()
    for k in range(len(t) - 1, 0, -1):
        if k >= 2 or all(w in MODIFIERS for w in t[k:]):
            yield " ".join(t[:k]), "bỏ từ cuối", t[k:]
    for k in range(1, len(t)):
        if len(t) - k >= 2 or all(w in MODIFIERS for w in t[:k]):
            yield " ".join(t[k:]), "bỏ từ đầu", t[:k]


def not_purchasable(name):
    t = name.split()
    homemade_liquid = t[0] == "nước" and name not in LIQUID_PRODUCTS and not name.startswith(("nước cốt", "nước dừa"))
    return (not t or len(name) <= 2 or t[0] in SKIP_START or name in SKIP_EXACT or homemade_liquid
            or any(c in name for c in SKIP_CONTAINS) or len(t) > 6)


def classify(name):
    """Đề xuất (danh mục, đơn vị tạm, chắc chắn?). Danh mục lấy từ danh mục có sẵn của catalog."""
    def has(*words):
        return any(re.search(rf"(^|\s){re.escape(w)}(\s|$)", name) for w in words)
    if has("nêm sẵn", "aji", "gia vị"):
        return "Gia vị nêm sẵn", "gói 50g", False
    if has("bánh tráng", "bánh phở", "bánh canh", "bánh"):
        return "Bánh tươi, Sandwich", "gói 200g", False
    if has("rong biển", "tảo", "kombu", "konbu", "wakame", "nori"):
        return "Rong biển", "gói 50g", True
    if has("chả", "nem"):
        return "Hàng mát chế biến", "gói 200g", False
    if has("mì ý", "nui", "mì trứng"):
        return "Mì Ý, mì trứng", "gói 500g", True
    if has("bún"):
        return "Bún các loại", "gói 400g", True
    if has("miến", "phở", "hủ tiếu"):
        return "Hủ tiếu, miến", "gói 200g", True
    if has("dầu"):
        return "Dầu ăn", "chai 250ml", True
    if has("rượu"):
        return "Rượu", "chai 500ml", True
    if has("sữa"):
        return "Sữa tươi", "hộp 1 lít", True
    if has("trứng"):
        return "Trứng gà, vịt, cút", "hộp 10 quả", True
    if has("nấm"):
        return "Nấm các loại", "gói 200g", True
    if has("tôm", "cua", "ghẹ", "mực", "cá", "nghêu", "sò", "ốc", "hến", "ếch", "lươn", "bạch tuộc", "hàu", "ngao", "điệp", "tép", "hải sâm", "hải sản"):
        return "Cá, hải sản", "khay 300g" if has("tôm", "mực", "nghêu", "sò", "ốc", "hến") else "500g", True
    if has("bò"):
        return "Thịt bò", "khay 500g", True
    if has("gà", "vịt"):
        return "Thịt gà, vịt", "khay 500g", True
    if has("heo", "sườn", "ba chỉ", "ba rọi", "giò", "nạc", "móng", "mỡ", "thịt"):
        return "Thịt heo", "khay 500g", True
    if has("cốt dừa"):
        return "Nước cốt dừa lon", "lon 400ml", True
    if has("đậu phộng", "đậu xanh", "đậu đỏ", "đậu đen", "đậu trắng", "mè", "vừng", "hạt é", "hạt", "hạnh nhân", "óc chó", "điều"):
        return "Đậu, nấm, đồ khô", "gói 200g", True
    if has("bột"):
        return "Bột các loại", "gói 400g", True
    if has("salad", "xà lách"):
        return "Rau lá", "300g", True
    if has("ngò", "rau", "húng", "thì là", "tía tô", "kinh giới", "hẹ", "cải", "mồng tơi", "xà lách", "lá", "bạc hà", "diếp", "cần", "ngổ", "răm", "mùi", "rau om", "dọc mùng"):
        return "Rau lá", "300g" if has("cải", "xà lách", "mồng tơi", "rau") else "100g", True
    if has("tiêu", "quế", "hồi", "thảo quả", "nghệ", "riềng", "sả", "ớt bột", "ngũ vị"):
        return "Bột nghệ, tỏi, hồi, quế,...", "gói 50g", False
    if has("tương", "mắm", "xốt", "sốt", "giấm", "dấm", "nước cốt", "caramel", "nước màu"):
        return "Gia vị nêm sẵn", "chai 250ml", False
    if has("dưa", "cà", "bầu", "bí", "mướp", "khoai", "củ", "su", "măng", "đậu que", "đậu cô ve", "đậu hà lan", "bắp", "ớt", "chanh", "gừng", "tỏi", "hành", "nấm", "cần", "su hào", "đu đủ", "chuối", "xoài", "dứa", "thơm", "bưởi", "cam"):
        return "Củ, quả", "500g", True
    return "Củ, quả", "500g", False        # không nhận ra: để mặc định và đánh dấu cần xem lại


def main():
    if OUT.exists() and "--force" not in sys.argv:
        sys.exit(f"{OUT.name} đã tồn tại (có thể đã duyệt). Dùng --force để ghi đè.")
    recipes = json.loads((ROOT / "data" / "processed" / "recipes_clean.json").read_text(encoding="utf-8"))
    mapping = json.loads((REVIEW / "ingredient_catalog_map_v1.json").read_text(encoding="utf-8"))["ingredients"]
    additions = json.loads((REVIEW / "catalog_additions_v1.json").read_text(encoding="utf-8"))["additions"]
    target_ids = {r["id"] for r in json.loads((ROOT / "data" / "final" / "recipes_v1.json").read_text(encoding="utf-8"))}
    catalog = load_full_catalog()
    available = {a["ingredient"] for a in additions} | {m["ingredient"] for m in mapping if m["status"] != "not_in_catalog"}
    cache = {}

    def present(name):
        if name not in cache:
            cache[name] = name in available or bool(find_matches(name, catalog))
        return cache[name]

    # 1. món phổ biến
    families, belongs, cleaned = popular_families(recipes)
    popular = [r for r in recipes if r["id"] in belongs]
    print(f"họ món phổ biến: {len(families)} | công thức thuộc các họ đó: {len(popular)}/{len(recipes)}")
    print("   họ lớn nhất:", sorted(families.items(), key=lambda x: -x[1])[:12])

    # 2. nguyên liệu thiếu của từng món
    core_of = {r["id"]: sorted({i["name"] for i in r["ingredients"] if i["role"] == "main" and i["name"] not in PANTRY}) for r in popular}
    raw_line = {}
    for r in popular:
        for i in r["ingredients"]:
            raw_line.setdefault(i["name"], (i.get("raw_text") or "").replace("\t", " ").strip())
    skipped = Counter(n for core in core_of.values() for n in core if not_purchasable(n))
    missing_of = {rid: [n for n in core if not not_purchasable(n) and not present(n)] for rid, core in core_of.items()}
    need_count = Counter(n for ms in missing_of.values() for n in ms)
    print(f"nguyên liệu thiếu (khác nhau): {len(need_count)} | món đã đủ ngay: {sum(1 for m in missing_of.values() if not m)}/{len(popular)}")

    # 3. gợi ý gộp tên
    alias = {}
    for name in need_count:
        for cand, rule, removed in shorten_candidates(name):
            if cand not in TOO_GENERIC and present(cand):
                conf = "cao" if all(w in MODIFIERS for w in removed) else "thấp"
                alias[name] = (cand, rule, conf)
                break
    similarity = {}
    model = None
    try:
        import os
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-m3", device="cuda" if torch.cuda.is_available() else "cpu")
        if torch.cuda.is_available():
            model.half()
        pairs = sorted(alias.items())
        a = model.encode([n for n, _ in pairs], normalize_embeddings=True, batch_size=64)
        b = model.encode([t for _, (t, _, _) in pairs], normalize_embeddings=True, batch_size=64)
        similarity = {n: float((x * y).sum()) for (n, _), x, y in zip(pairs, a, b)}
    except Exception as e:                                    # chỉ là cột tham khảo, thiếu thì bỏ qua
        print("   (bỏ qua độ giống bge-m3:", type(e).__name__, ")")
    print(f"gợi ý gộp tên: {len(alias)} (tin cậy cao: {sum(1 for v in alias.values() if v[2] == 'cao')})")

    # 4. còn thiếu gì sau khi gộp tên? Kịch bản CHÍNH (bảo thủ): chỉ nhận gợi ý tin cậy cao. Kịch bản lạc quan: nhận hết.
    accepted = {n for n, v in alias.items() if v[2] == "cao"}
    after_alias = {rid: [n for n in ms if n not in accepted] for rid, ms in missing_of.items()}
    after_all = {rid: [n for n in ms if n not in alias] for rid, ms in missing_of.items()}
    print(f"bỏ qua vì không phải hàng mua được: {len(skipped)} tên")

    # 5. KHÔNG cần hỗ trợ mọi công thức của một họ món: khách hỏi "canh chua" chỉ cần thấy vài món canh chua có giỏ hàng.
    #    Mỗi họ món xếp công thức theo ít thiếu nguyên liệu nhất; hạng 1 = dễ phủ nhất. Hỗ trợ "K món đầu mỗi họ".
    by_family = defaultdict(list)
    for r in popular:
        by_family[belongs[r["id"]]].append(r)
    rank_in_family = {}
    for fam, rs in by_family.items():
        rs.sort(key=lambda r: (len(after_alias[r["id"]]), len(core_of[r["id"]]), r["name"]))
        for i, r in enumerate(rs, start=1):
            rank_in_family[r["id"]] = i
    KS = (1, 2, 3, 5, 10, 999)

    def scenario(table):
        out = []
        for K in KS:
            recs = [rid for rid, i in rank_in_family.items() if i <= K]
            out.append((K, len(recs), sum(1 for rid in recs if not table[rid]), len({n for rid in recs for n in table[rid]})))
        return out
    scenarios, scenarios_all = scenario(after_alias), scenario(after_all)
    print("kịch bản CHÍNH (K món/họ, số món, số món đã đủ sẵn, số sản phẩm cần thêm):", scenarios)
    print("kịch bản lạc quan (nhận hết gộp tên):", scenarios_all)

    # Danh sách sản phẩm đề xuất lấy theo K_MAX món đầu mỗi họ (rộng rãi); cột ho_tro_tu_K cho biết lọc theo K nào.
    K_MAX = 5
    supported = {rid for rid, i in rank_in_family.items() if i <= K_MAX}
    need_sets = {rid: set(after_alias[rid]) for rid in supported}
    product_need = Counter(n for ns in need_sets.values() for n in ns)
    k_min = {n: min(rank_in_family[rid] for rid, ns in need_sets.items() if n in ns) for n in product_need}
    print(f"sản phẩm cần thêm cho K={K_MAX} (kịch bản chính): {len(product_need)}")

    # 6. thứ tự thêm (tham lam) trong tập K_MAX: mỗi bước chọn sản phẩm hoàn thành thêm nhiều món nhất
    remaining = {rid: ns for rid, ns in need_sets.items() if ns}
    order, chosen, done = [], set(), sum(1 for ns in need_sets.values() if not ns)
    pool = set(product_need)
    while pool:
        def gain(p):
            return sum(1 for need in remaining.values() if p in need and need <= chosen | {p})
        best = max(pool, key=lambda p: (gain(p), -k_min[p], product_need[p]))
        g = gain(best)
        chosen.add(best)
        pool.discard(best)
        done += g
        order.append((best, g, done))
    rank = {p: i + 1 for i, (p, _, _) in enumerate(order)}
    completes = {p: g for p, g, _ in order}
    cumulative = {p: d for p, _, d in order}

    # sản phẩm đề xuất nào có tên rất giống nhau (nên gộp thành một)?
    dup_hint = {}
    if model is not None:
        listed = sorted(product_need)
        vec = model.encode(listed, normalize_embeddings=True, batch_size=64).astype(np.float32)
        sims = vec @ vec.T
        for i, n in enumerate(listed):
            close = [(listed[j], float(sims[i, j])) for j in np.argsort(-sims[i])[1:4] if sims[i, j] >= 0.88]
            dup_hint[n] = ", ".join(f"{m} ({v:.2f})" for m, v in close)

    # ---------- Excel ----------
    wb = Workbook()
    ws = wb.active
    ws.title = "huong_dan"
    guide = [
        "ĐỀ XUẤT MỞ RỘNG CATALOG ĐỂ PHỦ MÓN PHỔ BIẾN (AI gợi ý, CẦN BẠN DUYỆT)", "",
        f"Món phổ biến = công thức thuộc {len(families)} 'họ món' (cụm tên như canh chua, gà nướng, cơm chiên) lặp lại ít nhất {MIN_FAMILY} lần trong dữ liệu, cộng vài họ nền tảng của bếp Việt: {len(popular)} công thức. Không cần hỗ trợ hết: mỗi họ chọn K món ít thiếu nhất.",
        "Sheet tong_quan: bao nhiêu sản phẩm cần thêm tùy theo mức bạn muốn phủ. Đọc sheet này đầu tiên.",
        "Sheet gop_ten_de_xuat: nguyên liệu 'thiếu' thực ra là tên gọi khác của hàng đã có. Duyệt trước, vì chấp nhận gộp tên thì KHÔNG cần thêm sản phẩm. Điền quyet_dinh: gop (đồng ý) / khong (cần sản phẩm riêng).",
        "   Các gợi ý tin_cay = cao đã được tính là chấp nhận trong kịch bản chính; tin_cay = thap là AI đoán, hay sai (ví dụ 'ngò tây' khác 'ngò').",
        "Sheet san_pham_de_xuat: sản phẩm mới đề xuất thêm vào catalog. Điền cột quyet_dinh: them (đồng ý) / bo (không thêm) / sua (đồng ý nhưng sửa tên-đơn vị-danh mục ở cột ghi_chu).",
        "Sheet bo_qua: tên bị coi là KHÔNG phải hàng mua được (động từ sơ chế, món tự nấu...) nên không tính là thiếu. Xem có cái nào bị bỏ oan không.",
        "Sheet mon_pho_bien: tham khảo, từng món đang thiếu gì.", "",
        "LƯU Ý: tên sản phẩm, danh mục, đơn vị là ĐỀ XUẤT TẠM theo từ khóa (cột chac_chan_danh_muc = khong nghĩa là máy đoán, cần xem lại).",
        "Giá và ảnh do bên web thêm. Id sẽ cấp nối tiếp từ CAT-001776 khi bạn chốt, không đụng id đã khóa.",
        "ho_tro_tu_K: sản phẩm cần cho món xếp hạng K trong họ món (hạng 1 = ít thiếu nhất). Muốn hỗ trợ 3 món đầu mỗi họ thì chỉ lấy dòng ho_tro_tu_K <= 3.",
        "Ưu tiên A = ho_tro_tu_K = 1, B = 2-3, C = 4-5.",
    ]
    for line in guide:
        ws.append([line])
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 150

    ws = wb.create_sheet("tong_quan")
    ws.append(["Số món phổ biến", len(popular)])
    ws.append(["Đã đủ nguyên liệu ngay (không cần thêm gì)", sum(1 for m in missing_of.values() if not m)])
    ws.append(["Đủ nếu chấp nhận gộp tên tin cậy cao (kịch bản chính)", sum(1 for m in after_alias.values() if not m)])
    ws.append(["Đủ nếu chấp nhận HẾT gợi ý gộp tên (lạc quan, nhiều gợi ý sai)", sum(1 for m in after_all.values() if not m)])
    ws.append(["Số nguyên liệu 'thiếu' khác nhau trên toàn bộ món phổ biến (đã bỏ hàng không mua được)", len(need_count)])
    ws.append(["... gợi ý gộp tên: tin cậy cao / thấp", f"{sum(1 for v in alias.values() if v[2] == 'cao')} / {sum(1 for v in alias.values() if v[2] != 'cao')}"])
    ws.append([])
    for title, table in (("KỊCH BẢN CHÍNH (chỉ nhận gộp tên tin cậy cao): hỗ trợ K món đầu mỗi họ", scenarios),
                         ("KỊCH BẢN LẠC QUAN (nhận hết gợi ý gộp tên, nhiều gợi ý sai)", scenarios_all)):
        ws.append([title, "số món được hỗ trợ", "trong đó đã đủ sẵn", "số sản phẩm cần thêm"])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        for K, n_rec, n_ready, n_prod in table:
            ws.append([f"K = {K}" if K < 999 else "tất cả món phổ biến", n_rec, n_ready, n_prod])
        ws.append([])
    ws.append(["Họ món lớn nhất", "số công thức"])
    for bg, c in sorted(families.items(), key=lambda x: -x[1])[:15]:
        ws.append([bg, c])
    for col, w in zip("ABCD", [70, 18, 22, 16]):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("gop_ten_de_xuat")
    ws.append(["nguyen_lieu_thieu", "gop_vao", "cach_suy_ra", "tin_cay", "do_giong_bge_m3", "so_mon_can", "dong_goc_vi_du", "quyet_dinh", "ghi_chu"])
    for name, (cand, rule, conf) in sorted(alias.items(), key=lambda x: (x[1][2] != "cao", -need_count[x[0]])):
        ws.append([name, cand, rule, conf, round(similarity[name], 3) if name in similarity else "", need_count[name], raw_line.get(name, ""), "", ""])
    for col, w in zip("ABCDEFGHI", [26, 22, 12, 9, 12, 9, 50, 12, 30]):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("san_pham_de_xuat")
    ws.append(["thu_tu_them", "nguyen_lieu", "ten_san_pham_de_xuat", "danh_muc", "don_vi_tam", "chac_chan_danh_muc", "uu_tien",
               "so_mon_can", "ho_tro_tu_K", "hoan_thanh_them_mon", "tong_mon_da_phu", "vi_du_mon", "dong_goc_vi_du", "neu_gop_ten_thi_bo", "giong_san_pham_khac", "quyet_dinh", "ghi_chu"])
    fill = {"A": "D4EDDA", "B": "FFF3CD", "C": "F8D7DA"}
    cats = Counter()
    for name in sorted(product_need, key=lambda n: rank[n]):
        users = [rid for rid, ns in need_sets.items() if name in ns]
        pr = "A" if k_min[name] == 1 else "B" if k_min[name] <= 3 else "C"
        category, unit, sure = classify(name)
        assert category in {p["category"] for p in catalog} and category not in EXCLUDED_CATEGORIES, category
        cats[category] += 1
        title = name[:1].upper() + name[1:]
        examples = [next(r["name"] for r in popular if r["id"] == rid) for rid in users[:3]]
        ws.append([rank[name], name, f"{title} {unit}", category, unit, "có" if sure else "khong", pr, product_need[name], k_min[name],
                   completes[name], cumulative[name], " | ".join(examples), raw_line.get(name, ""),
                   f"{alias[name][0]} ({alias[name][2]})" if name in alias else "", dup_hint.get(name, ""), "", ""])
        ws.cell(ws.max_row, 7).fill = PatternFill("solid", fgColor=fill[pr])
    for col, w in zip("ABCDEFGHIJKLMNOPQ", [8, 24, 32, 26, 12, 10, 8, 9, 10, 12, 12, 70, 40, 24, 40, 12, 30]):
        ws.column_dimensions[col].width = w
    print("danh mục đề xuất:", dict(cats))

    ws = wb.create_sheet("bo_qua")
    ws.append(["ten_bi_bo_qua", "so_mon", "dong_goc_vi_du", "quyet_dinh", "ghi_chu"])
    for name, c in skipped.most_common():
        ws.append([name, c, raw_line.get(name, ""), "", ""])
    for col, w in zip("ABCDE", [40, 9, 60, 12, 30]):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("mon_pho_bien")
    ws.append(["ho_mon", "hang_trong_ho", "id", "ten_mon", "so_nguyen_lieu_chinh", "trang_thai", "con_thieu_sau_khi_gop_ten", "se_gop_ten", "co_gio_hang_san"])
    for r in sorted(popular, key=lambda r: (-families[belongs[r["id"]]], belongs[r["id"]], rank_in_family[r["id"]])):
        rid = r["id"]
        status = "đủ ngay" if not missing_of[rid] else ("đủ nếu gộp tên" if not after_alias[rid] else f"thiếu {len(after_alias[rid])}")
        ws.append([belongs[rid], rank_in_family[rid], rid, r["name"], len(core_of[rid]), status, ", ".join(after_alias[rid]),
                   ", ".join(f"{n}→{alias[n][0]}" for n in missing_of[rid] if n in alias), "có" if rid in target_ids else ""])
    for col, w in zip("ABCDEFGHI", [18, 8, 34, 50, 10, 16, 55, 45, 10]):
        ws.column_dimensions[col].width = w

    for sheet in wb.worksheets[1:]:
        for c in sheet[1]:
            c.font = Font(bold=True)
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.freeze_panes = "A2"
    wb.save(OUT)
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
