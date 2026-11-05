"""Demo Streamlit cho recipe_rag: gõ tên món -> danh sách món -> nguyên liệu theo công thức -> giỏ hàng -> lời AI (tùy chọn).

Dùng để thuyết trình và test tay. Không có giá (giá do bên web quản lý). Chạy từ thư mục grocery-store-ai:
    .venv\\Scripts\\streamlit run demo\\recipe_rag\\app.py

Cần ai_db đang chạy (docker compose up -d). Khóa Gemini / Claude đọc từ .env; không có khóa thì phần AI tự tắt,
phần tìm món và giỏ hàng vẫn chạy bình thường vì do code dựng, không do mô hình.
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings                        # noqa: E402
from src.ml.embedder import Embedder                                 # noqa: E402
from src.schemas.recipe_dto import SearchRequest                     # noqa: E402
from src.services.claude_service import ClaudeProvider               # noqa: E402
from src.services.copilot_service import CopilotService, ProviderConfig  # noqa: E402
from src.services.gemini_service import GeminiProvider               # noqa: E402
from src.services.openrouter_service import OpenRouterProvider       # noqa: E402
from src.services.recipe_service import RecipeService, build_basket  # noqa: E402

SUGGEST_COUNT = 8
AI_STATUS_TEXT = {
    "ok": "AI trả lời hợp lệ",
    "skipped_no_match": "Không có món đủ gần nên không nhờ AI",
    "fallback_disabled": "Chưa bật nhà cung cấp AI nào, đang dùng dữ liệu code dựng",
    "fallback_invalid": "AI trả lời sai quy tắc sau khi thử lại, đang dùng dữ liệu code dựng",
    "fallback_timeout": "AI quá thời gian chờ, đang dùng dữ liệu code dựng",
    "fallback_error": "Gọi AI bị lỗi, đang dùng dữ liệu code dựng",
}

st.set_page_config(page_title="Com4Fud - Chef Copilot demo", page_icon="🍲", layout="wide")


@st.cache_resource(show_spinner="Đang nạp bge-m3 và dữ liệu món (khoảng 10 giây lần đầu)...")
def load_services():
    """Nạp một lần cho cả phiên chạy: model embedding, danh sách món, catalog, các nhà cung cấp AI có khóa."""
    settings = get_settings()
    recipes = RecipeService(settings, Embedder(settings.embedding_model))
    providers = {}
    if settings.gemini_api_key.get_secret_value():
        providers["gemini"] = GeminiProvider(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
    if settings.anthropic_api_key.get_secret_value():
        providers["claude"] = ClaudeProvider(settings.anthropic_api_key.get_secret_value(), settings.claude_model)
    if settings.openrouter_api_key.get_secret_value():
        providers["openrouter"] = OpenRouterProvider(settings.openrouter_api_key.get_secret_value(), settings.openrouter_model)
    return settings, recipes, providers


def fmt_qty(quantity: float | None, unit: str | None) -> str:
    if quantity is None:
        return "không ghi lượng"
    return f"{quantity:g} {unit or ''}".strip()


try:
    settings, recipes, providers = load_services()
except Exception as e:                                               # DB chưa bật là lỗi hay gặp nhất
    st.error(f"Không khởi động được service: {e}")
    st.info("Kiểm tra `docker compose up -d` (ai_db, cổng 5434) rồi tải lại trang.")
    st.stop()

# ---------- Thanh bên: trạng thái và cấu hình ----------
with st.sidebar:
    st.header("Trạng thái")
    st.write(f"Món trong kho: **{len(recipes.recipes)}**, sản phẩm catalog: **{len(recipes.catalog)}**")
    st.write(f"Ngưỡng nhận kết quả: **{settings.search_threshold}**")
    st.subheader("AI")
    enabled = {}
    default_on = "openrouter" if "openrouter" in providers else next(iter(providers), None)   # mặc định bật một nhà cung cấp có khóa
    for name, label in (("gemini", "Gemini"), ("claude", "Claude"), ("openrouter", "OpenRouter")):
        has_key = name in providers
        enabled[name] = st.toggle(f"{label} " + ("(có khóa)" if has_key else "(chưa có khóa trong .env)"),
                                  value=name == default_on, disabled=not has_key, key=f"toggle_{name}")
    if not providers:
        st.caption("Không có khóa nào: demo chạy ở chế độ code dựng, vẫn đủ món và giỏ hàng.")
    servings_override = st.number_input("Số người (0 = theo công thức)", min_value=0, max_value=50, value=0)

st.title("🍲 Chef Copilot: món ăn thành giỏ nguyên liệu")

# ---------- Ô tìm kiếm ----------
with st.form("search"):
    cols = st.columns([5, 1])
    query = cols[0].text_input("Gõ tên món hoặc nhu cầu", placeholder="vd: canh chua, gà nướng mật ong, món ăn sáng với trứng",
                               label_visibility="collapsed")
    submitted = cols[1].form_submit_button("Tìm", width="stretch")

if submitted and query.strip():
    st.session_state["query"] = query.strip()
    st.session_state.pop("selected", None)
    st.session_state.pop("ai", None)
    st.session_state["response"] = recipes.search(SearchRequest(query=query.strip(), top_k=SUGGEST_COUNT,
                                                                 servings=servings_override or None))

response = st.session_state.get("response")
if response is None:
    st.info("Gõ một tên món vào ô trên rồi bấm Tìm.")
    st.stop()

# ---------- Danh sách món gợi ý ----------
st.subheader(f"Gợi ý cho: “{st.session_state['query']}”")
if not response.accepted:
    st.warning(f"Không có món nào đủ gần (điểm cao nhất dưới ngưỡng {response.threshold}). Dưới đây là các món gần nhất, độ tin cậy thấp.")
MATCH_LABEL = {"both": "khớp tên + ngữ nghĩa", "keyword": "khớp tên", "semantic": "khớp ngữ nghĩa"}
for result in response.results:
    r = result.recipe
    detail = " · ".join(x for x in [r.family, f"{r.time_minutes} phút" if r.time_minutes else None, r.difficulty,
                                    f"điểm {result.score:.2f}", MATCH_LABEL[result.matched_by]] if x)
    if st.button(f"{r.name}  —  {detail}", key=f"pick_{r.id}", width="stretch"):
        st.session_state["selected"] = r.id
        st.session_state.pop("ai", None)

selected_id = st.session_state.get("selected")
if selected_id is None:
    st.stop()

# ---------- Chi tiết món ----------
recipe = recipes.recipes[selected_id]
recipe_servings = recipe["servings"] or settings.search_default_servings
servings = servings_override or response.servings
st.divider()
st.header(recipe["name"])
st.caption(" · ".join(x for x in [recipe["family"], f"{recipe['time_minutes']} phút" if recipe["time_minutes"] else None,
                                  recipe["difficulty"], f"công thức gốc cho {recipe_servings} người"] if x))
if recipe["description"]:
    st.write(recipe["description"])
if recipe["source_url"]:
    st.markdown(f"[Công thức gốc]({recipe['source_url']})")
if not recipe["complete"]:
    st.warning("Món này còn nguyên liệu chưa ghép được với catalog, giỏ hàng có thể thiếu.")

left, right = st.columns(2)

with left:
    st.subheader("Nguyên liệu theo công thức")
    st.caption("Đúng như công thức ghi (lượng gốc cho khẩu phần của công thức), kèm sản phẩm catalog đã ghép.")
    rows = []
    for line in recipe["ingredients"]:
        match = line["match"] if line["status"] == "da_ghep" else None
        rows.append({"Nguyên liệu (công thức ghi)": line["raw_text"],
                     "Loại": {"core": "chính", "addon": "gia vị / phụ", "side": "ăn kèm"}.get(line["kind"], line["kind"]),
                     "Sản phẩm catalog": match["product_name"] if match else "— chưa ghép / không bán",
                     "Tự làm": "có" if match and match.get("match_via") == "quyet_dinh_che_bien_tu" else ""})
    st.dataframe(rows, hide_index=True, width="stretch")
    with st.expander("Các bước nấu"):
        for step in [*(recipe["prep_steps"] or []), *(recipe["cooking_steps"] or [])]:
            st.markdown(f"- {step}")

with right:
    st.subheader(f"Giỏ hàng cho {servings} người")
    all_names = sorted({l["ingredient"] for l in recipe["ingredients"] if l["status"] == "da_ghep" and l["kind"] != "side"})
    have = st.multiselect("Nhà mình đã có sẵn:", all_names, key=f"have_{selected_id}",
                          help="Chọn nguyên liệu đã có, giỏ hàng sẽ chuyển chúng sang mục “có thể đã có” với số lượng 0.")
    basket = build_basket(recipe["ingredients"], recipes.catalog, recipe_servings, servings, have)

    def render(items, title):
        st.markdown(f"**{title}**")
        if not items:
            st.caption("(trống)")
        for item in items:
            c1, c2 = st.columns([4, 1])
            pack = f"{item.product.pack_size:g} {item.product.pack_unit}" if item.product.pack_size and item.product.pack_unit else "không rõ quy cách"
            hint = f" · gợi ý ~{item.pack_hint} gói" if item.pack_hint else ""
            tag = " · tự làm từ sản phẩm này" if item.derived else ""
            c1.markdown(f"{item.product.name} ({pack})  \n<small>{item.ingredient}: cần {fmt_qty(item.need.quantity, item.need.unit) if item.need else 'không ghi lượng'}{hint}{tag}</small>",
                        unsafe_allow_html=True)
            c2.number_input("SL", min_value=0, max_value=99, value=item.default_qty, key=f"qty_{selected_id}_{item.product.catalog_id}_{item.ingredient}_{item.default_qty}",
                            label_visibility="collapsed")
            if item.alternatives:
                c1.caption("Thay thế: " + ", ".join(a.name for a in item.alternatives[:3]))

    render(basket.buy, "Cần mua (mặc định 1)")
    render(basket.maybe_have, "Có thể đã có trong nhà (mặc định 0)")

# ---------- Lời AI ----------
st.divider()
st.subheader("Gợi ý của AI")
active = [n for n in providers if enabled.get(n)]
if not active:
    st.caption("Chưa bật nhà cung cấp AI nào ở thanh bên (hoặc chưa có khóa trong .env). Phần trên là dữ liệu code dựng, luôn dùng được.")
elif st.button(f"Hỏi AI ({', '.join(active)}) — tốn hạn mức / tiền thật", key="ask_ai"):
    configs = [ProviderConfig(n, True, i) for i, n in enumerate(active, 1)]
    service = CopilotService(recipes, {n: providers[n] for n in active}, settings, config_source=lambda: configs)
    with st.spinner("Đang hỏi AI..."):
        st.session_state["ai"] = service.answer(SearchRequest(query=st.session_state["query"], top_k=SUGGEST_COUNT,
                                                              servings=servings_override or None, have=have))

copilot = st.session_state.get("ai")
if copilot is not None:
    st.caption(f"Trạng thái: {AI_STATUS_TEXT.get(copilot.ai_status, copilot.ai_status)} ({copilot.latency_ms} ms)")
    if copilot.ai:
        ai = copilot.ai
        chosen = recipes.recipes[ai.recipe_id]["name"]
        st.markdown(f"**AI chọn món:** {chosen}  \n<small>{ai.provider} · {ai.model}</small>", unsafe_allow_html=True)
        st.write(ai.explanation)
        for n in ai.item_notes:
            st.markdown(f"- **{n.ingredient}**: {n.note}")
        for p in ai.prep_notes:
            st.markdown(f"**Tự làm {p.ingredient}:**")
            for s in p.steps:
                st.markdown(f"  1. {s}")
        if ai.follow_up_question:
            st.info(ai.follow_up_question)
