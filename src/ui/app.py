"""演示界面（Streamlit）：AI+华为PC营销软文智能体。

视觉走"苹果官网"风格：深色 Hero + 纯白底 + 大字排版 + 药丸按钮 / 圆角卡片。
功能板块仍对齐赛题手册v4：账号与知识库 / 任务输入（信息不足追问）/ 知识与图片检索
/ 场景与平台策略 / 图文软文生成 / 事实核验 / 合规检查 / 修改与导出。
运行：双击 run.bat，或 streamlit run src/ui/app.py
"""
from __future__ import annotations

import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st  # noqa: E402

from src.config_loader import list_products_brief, load_scenes, platform_keys  # noqa: E402
from src.llm import get_llm  # noqa: E402
from src.orchestrator import new_state, next_agent, render_report, run_pipeline  # noqa: E402
from src.state import SessionState  # noqa: E402
from src.tools.ima_api import connection_status  # noqa: E402

SCENARIO_DIR = os.path.join(ROOT, "scenarios")

st.set_page_config(page_title="AI+华为PC营销软文智能体", layout="wide")

# ----------------------------------------------------------------------------
# 全局样式：模仿苹果官网 —— 系统字体、超大标题、留白、圆角、蓝色强调
# ----------------------------------------------------------------------------
APPLE_CSS = """
<style>
:root{
  --ink:#1d1d1f; --muted:#6e6e73; --line:#d2d2d7; --bg:#ffffff; --soft:#f5f5f7;
  --accent:#0071e3; --accent-hover:#0077ed;
}
html, body, [data-testid="stAppViewContainer"], [class*="st-"]{
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text",
    "PingFang SC","Helvetica Neue","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased;
}
[data-testid="stAppViewContainer"]{ background:var(--bg); }
[data-testid="stHeader"]{ background:transparent; }
.block-container{ max-width:1120px; padding-top:1.2rem; padding-bottom:4rem; }

h1,h2,h3,h4{ color:var(--ink); letter-spacing:-.02em; font-weight:600; }
h1{ font-size:2.5rem; line-height:1.12; }
h2{ font-size:1.55rem; }
h3{ font-size:1.22rem; }
p, li, span, label, .stMarkdown, .stMarkdown p{ color:var(--ink); }
[data-testid="stCaptionContainer"], small{ color:var(--muted); }

/* Hero */
.hero{
  background:linear-gradient(135deg,#000 0%,#1d1d1f 55%,#2b2b30 100%);
  border-radius:24px; padding:46px 48px; margin-bottom:24px;
  box-shadow:0 20px 50px -24px rgba(0,0,0,.45);
}
.hero .eyebrow{ font-size:12px; letter-spacing:.24em; text-transform:uppercase;
  color:#86868b; margin-bottom:14px; }
.hero .title{ font-size:2.7rem; font-weight:700; letter-spacing:-.03em;
  line-height:1.08; color:#fff; }
.hero .sub{ margin-top:16px; font-size:1.02rem; color:#a1a1a6; line-height:1.65; }

/* 状态药丸 */
.pill-row{ display:flex; flex-wrap:wrap; gap:10px; margin:0 0 24px; }
.pill{ display:inline-flex; align-items:center; gap:8px; background:var(--soft);
  color:var(--ink); border-radius:999px; padding:7px 15px; font-size:13px; }
.pill .dot{ width:8px; height:8px; border-radius:50%; background:#30d158; }
.pill.off .dot{ background:#ff9f0a; }

/* 指标卡片 */
.stat-grid{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:24px; }
.stat-card{ background:var(--soft); border-radius:18px; padding:20px 22px; }
.stat-label{ font-size:12px; color:var(--muted); letter-spacing:.05em; margin-bottom:8px; }
.stat-value{ font-size:1.16rem; font-weight:600; color:var(--ink); }

/* 空状态 */
.empty{ background:var(--soft); border-radius:24px; padding:52px 46px; text-align:center; }
.empty .t{ font-size:1.45rem; font-weight:600; color:var(--ink); margin-bottom:10px; }
.empty .d{ color:var(--muted); line-height:1.7; }

/* 按钮：药丸形 */
div[data-testid="stButton"] > button, .stButton > button, [data-testid="stDownloadButton"] > button{
  border-radius:999px; border:1px solid var(--line); background:#fff; color:var(--ink);
  font-weight:500; padding:.55rem 1.35rem; transition:all .2s ease; box-shadow:none;
}
div[data-testid="stButton"] > button:hover, .stButton > button:hover,
[data-testid="stDownloadButton"] > button:hover{
  border-color:#b0b0b5; transform:translateY(-1px);
}
div[data-testid="stButton"] > button[kind="primary"], .stButton > button[kind="primary"],
[data-testid="stBaseButton-primary"]{
  background:var(--accent); color:#fff; border-color:var(--accent);
}
div[data-testid="stButton"] > button[kind="primary"]:hover, .stButton > button[kind="primary"]:hover{
  background:var(--accent-hover); border-color:var(--accent-hover);
}

/* Tabs */
[data-baseweb="tab-list"]{ gap:6px; border-bottom:1px solid var(--line); }
[data-baseweb="tab"]{ padding:11px 6px; color:var(--muted); font-size:15px; }
[data-baseweb="tab"][aria-selected="true"]{ color:var(--ink); font-weight:600; }
[data-baseweb="tab-highlight"]{ background:var(--ink); }

/* 侧栏 */
[data-testid="stSidebar"]{ background:var(--soft); border-right:1px solid var(--line); }
[data-testid="stSidebar"] h2{ font-size:12px; letter-spacing:.1em; color:var(--muted);
  font-weight:600; text-transform:uppercase; margin-bottom:6px; }
[data-testid="stSidebar"] .stTextArea textarea,
[data-testid="stSidebar"] .stTextInput input{ border-radius:12px; }

/* 提示 / 代码块 */
[data-testid="stAlert"]{ border-radius:16px; }
pre, .stCode{ border-radius:16px !important; }
</style>
"""


@st.cache_resource
def _llm():
    return get_llm()


@st.cache_data
def _scenarios() -> dict:
    out = {}
    if os.path.isdir(SCENARIO_DIR):
        for name in sorted(os.listdir(SCENARIO_DIR)):
            if name.endswith(".json"):
                with open(os.path.join(SCENARIO_DIR, name), "r", encoding="utf-8") as f:
                    out[name.replace(".json", "")] = json.load(f)
    return out


def _e(x) -> str:
    """转义后再拼进 HTML，避免内容里的 < > & 破坏布局。"""
    return html.escape(str(x))


def _hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <div class="eyebrow">HUAWEI&nbsp;&nbsp;·&nbsp;&nbsp;AI MARKETING AGENT</div>
          <div class="title">AI+华为PC<br/>营销软文智能体</div>
          <div class="sub">场景解析 · 平台策略 · 知识检索 · 图文编排 · 软文生成 · 事实核验 · 合规检查</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _pills(llm, kb) -> None:
    model_ok = getattr(llm, "available", False)
    cred_ok = kb.get("has_credentials")
    st.markdown(
        f"""
        <div class="pill-row">
          <span class="pill {'on' if model_ok else 'off'}"><span class="dot"></span>模型：
            {'已接入 ' + _e(llm.model_name) if model_ok else '离线模板模式'}</span>
          <span class="pill on"><span class="dot"></span>知识库：{_e(kb['kb_name'])}</span>
          <span class="pill {'on' if cred_ok else 'off'}"><span class="dot"></span>ima 凭证：
            {'已配置' if cred_ok else '未配置（本地官方知识库兜底）'}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _stat_cards(a: dict) -> None:
    items = [
        ("业务场景", a.get("业务场景", "-")),
        ("目标人群", a.get("目标人群", "-")),
        ("发布平台", a.get("平台", "-")),
        ("购买阶段", a.get("购买阶段", "-")),
    ]
    cards = "".join(
        f'<div class="stat-card"><div class="stat-label">{_e(k)}</div>'
        f'<div class="stat-value">{_e(v)}</div></div>'
        for k, v in items
    )
    st.markdown(f'<div class="stat-grid">{cards}</div>', unsafe_allow_html=True)


def main() -> None:
    st.markdown(APPLE_CSS, unsafe_allow_html=True)

    llm = _llm()
    kb = connection_status()
    _hero()
    _pills(llm, kb)

    scenarios = _scenarios()
    keys = list(scenarios.keys())
    platforms = platform_keys()
    scene_names = ["自动识别"] + [s["key"] for s in load_scenes()]
    products = list_products_brief()

    with st.sidebar:
        st.header("① 账号与知识库")
        st.write(f"- 知识库名称：**{kb['kb_name']}**")
        st.write(f"- 连接方式：{kb['mode']}")
        st.write(f"- 凭证状态：{'已配置环境变量（不在界面展示）' if kb['has_credentials'] else '未配置（使用本地官方知识库兜底）'}")
        st.caption(f"调用脚本：{kb['skill_script']}")
        st.caption("凭证明文不会出现在源码、界面与导出结果中。")

        st.header("② 任务输入")
        labels = {k: scenarios[k]["name"] for k in keys}
        picked = st.selectbox("预置场景卡（可改）", ["（不使用）"] + keys, format_func=lambda k: labels.get(k, k))
        sc = scenarios.get(picked, {}) if picked != "（不使用）" else {}

        task = st.text_area("任务输入（产品 / 目标人群 / 场景 / 渠道）", value=sc.get("task", ""), height=140)

        platform = st.selectbox(
            "发布渠道（平台）", platforms,
            index=platforms.index(sc["platform"]) if sc.get("platform") in platforms else 0,
        )
        scene = st.selectbox(
            "业务场景",
            scene_names,
            index=scene_names.index(sc["scene"]) if sc.get("scene") in scene_names else 0,
        )
        prod_labels = ["自动（按场景推荐）"] + [f"{p['name']}" for p in products]
        prod_ids = [""] + [p["id"] for p in products]
        prod_pick = st.selectbox(
            "指定产品（评委指定产品时用）", range(len(prod_labels)),
            format_func=lambda i: prod_labels[i],
            index=prod_ids.index(sc["product_id"]) if sc.get("product_id") in prod_ids else 0,
        )
        product_id = prod_ids[prod_pick]

        st.divider()
        run = st.button("▶ 生成图文软文", type="primary", use_container_width=True)
        st.caption("流程：场景解析 → 平台策略 → 资料与图片检索 → 事实点提取 → 图文编排 → 软文生成 → 核验 → 合规 → 导出")
        clear = st.button("清除当前会话", use_container_width=True)

    if clear:
        st.session_state.pop("state", None)
        st.session_state["_resumed"] = True  # 跳过本轮的自动恢复，视为全新会话
        st.rerun()

    if run and task.strip():
        with st.spinner("智能体正在执行标准流程……"):
            try:
                st_state = new_state(
                    task,
                    platform=platform,
                    scene_hint="" if scene == "自动识别" else scene,
                    product_id=product_id,
                )
                st_state = run_pipeline(st_state, llm)
                st_state.save()
                st.session_state["state"] = st_state
            except Exception as exc:
                st.error(f"生成过程出现异常，已中断本次生成，请重试或更换输入。（详情：{exc}）")

    state = st.session_state.get("state")
    if state is None and not st.session_state.get("_resumed"):
        # 页面刚加载、本次会话还没生成过结果：尝试从磁盘恢复中断前的最后一次快照。
        state = SessionState.load()
        if state is not None:
            st.session_state["state"] = state
            st.info("已自动恢复上次中断前的会话，可直接查看或重新生成。")
    st.session_state["_resumed"] = True

    if state is None:
        st.markdown(
            """
            <div class="empty">
              <div class="t">开始生成你的第一组营销软文</div>
              <div class="d">在左侧选一张预置场景卡，或直接填写任务输入，<br/>
              点击「▶ 生成图文软文」，即可看到赛题规定的四段式输出。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    a = state.output["一、场景判断"]
    _stat_cards(a)

    if state.pending_questions:
        st.warning("信息不足，需向用户补充/确认：\n" + "\n".join(f"- {q}" for q in state.pending_questions))

    tabs = st.tabs(["① 场景判断", "② 知识库依据", "③ 图文软文", "④ 核验结果", "⑤ 运行轨迹"])

    with tabs[0]:
        st.subheader("一、场景判断")
        st.write(f"**使用场景**：{'、'.join(a.get('使用场景') or []) or '未明确'}")
        st.write(f"**用户问题**：{a.get('用户问题')}")
        st.write(f"**内容目标**：{a.get('内容目标')}")
        st.markdown("**判断依据（可回溯到用户输入）**")
        for e in a.get("依据", []):
            st.markdown(f"- 「{e}」")
        st.markdown("**平台策略**")
        st.info(state.platform_strategy.get("策略说明", ""))

    with tabs[1]:
        st.subheader("二、知识库依据（来自 ima 共享知识库）")
        b = state.output["二、知识库依据"]
        st.write(f"**产品型号**：{b.get('产品型号')}")
        st.write(f"**检索来源**：{b.get('检索来源')}")
        st.markdown("**事实点**")
        for f in b.get("事实点") or []:
            st.markdown(f"- {f}")
        st.markdown("**资料标题**")
        for t in b.get("资料标题") or []:
            st.markdown(f"- {t}")
        with st.expander("查看检索命中的知识库原文片段"):
            for e in state.evidence:
                st.markdown(f"**{e.get('title')}**　`{e.get('path')}`")
                st.text((e.get("text") or "")[:1500])

    with tabs[2]:
        st.subheader(f"三、图文软文（{state.copy.get('平台')}）")
        st.markdown(f"**策略说明**：{state.copy.get('策略说明')}")
        st.markdown(f"### {state.copy.get('标题')}")
        if state.copy.get("导语"):
            st.markdown(f"*{state.copy.get('导语')}*")
        st.code(state.copy.get("正文", ""), language=None)
        st.markdown(f"**行动引导**：{state.copy.get('行动引导')}")
        if state.copy.get("平台标签"):
            st.markdown("**平台标签**：" + " ".join(state.copy["平台标签"]))
        st.markdown("**配图方案（名称 / 来源 / 插入位置 / 说明）**")
        for img in state.image_plan:
            tag = "✅" if img.get("是否型号一致") else "⚠️"
            st.markdown(
                f"{tag} **{img.get('名称')}**\n\n"
                f"- 来源：{img.get('来源')}\n"
                f"- 插入位置：{img.get('插入位置')}\n"
                f"- 说明：{img.get('说明')}"
            )

    with tabs[3]:
        st.subheader("四、核验结果")
        ver = state.verification
        st.write(f"**产品事实**：{ver.get('产品事实', {}).get('结论')}")
        for it in ver.get("产品事实", {}).get("逐项", []):
            st.markdown(f"- {it['结论']}｜{it['事实']}　（{it['说明']}）")
        st.write(f"**图片型号**：{ver.get('图片型号', {}).get('结论')}")
        for it in ver.get("图片型号", {}).get("逐项", []):
            st.markdown(f"- {it['结论']}｜{it['图片']}")
        st.write(f"**合规**：{ver.get('合规', {}).get('结论')}")
        for h in ver.get("合规", {}).get("命中", []):
            st.error(f"{h.get('类别')}：{h.get('词')}" + (f"（{h.get('说明')}）" if h.get("说明") else ""))
        st.write(f"**待确认信息**：{'；'.join(ver.get('待确认信息') or []) or '无'}")

    with tabs[4]:
        st.subheader("运行轨迹（中断可从这里恢复）")
        for i, t in enumerate(state.trace, 1):
            st.markdown(f"{i}. **[{t['agent']}]** {t['action']} — {t['detail']}")
        st.caption(f"当前下一步由：{next_agent(state)} 接手")

    st.divider()
    st.subheader("修改与导出")
    col1, col2 = st.columns([3, 1])
    with col1:
        revision = st.text_input("临时修改要求（如：删减篇幅 / 换成小红书 / 替换卖点 / 再口语化一点）", value="")
    with col2:
        st.write("")
        redo = st.button("按修改要求重新生成", use_container_width=True)

    if redo and revision.strip():
        with st.spinner("按临时要求重新生成……"):
            st_state = new_state(
                state.raw_task,
                platform=state.platform,
                scene_hint=state.scene_hint,
                product_id=state.product_id,
            )
            st_state = run_pipeline(st_state, llm, revision=revision)
            st_state.save()
            st.session_state["state"] = st_state
        st.success("已按修改要求重新生成，请查看上方结果。")

    st.download_button(
        "⬇ 导出完整结果（四段格式 .txt）",
        data=render_report(state).encode("utf-8"),
        file_name=f"华为PC软文_{state.platform}_{state.product.get('id', 'auto')}.txt",
        mime="text/plain",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
