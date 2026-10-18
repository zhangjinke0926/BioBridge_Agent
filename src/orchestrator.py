"""协调器（Orchestrator）：AI+华为PC营销软文智能体 的主线编排。

标准流程（赛题手册v4 第四节）：
  场景解析 → 平台策略 → ima资料与图片检索 → 事实点提取 → 图文编排
  → 软文生成 → 事实核验 → 合规检查 → 导出

输出统一为四段：一、场景判断 / 二、知识库依据 / 三、图文软文 / 四、核验结果。
每一步都写入 state.trace，中断后能看轨迹知道卡在哪、从哪继续。
"""
from __future__ import annotations

from src.agents import content
from src.agents.content import run_content
from src.agents.factcheck import run_factcheck
from src.agents import factcheck as factcheck_mod
from src.agents.scene import match_business_scene, missing_inputs, run_scene
from src.config_loader import get_platform, get_product, pick_product_for_scene, platform_keys, product_brief
from src.llm import BaseLLM
from src.state import SessionState
from src.tools import ima_api, image_ref

STEP_AGENT = {
    "start": "场景解析Agent",
    "scene": "平台策略模块",
    "strategy": "知识检索Agent",
    "retrieve": "软文生成Agent",
    "draft": "事实核验Agent",
    "verify": "导出模块",
    "done": "流程结束",
}


def new_state(
    raw_task: str,
    platform: str = "公众号",
    scene_hint: str = "",
    product_id: str = "",
    session_id: str = "demo",
) -> SessionState:
    return SessionState(
        session_id=session_id,
        raw_task=raw_task,
        platform=platform,
        scene_hint=scene_hint,
        product_id=product_id,
    )


def next_agent(state: SessionState) -> str:
    return STEP_AGENT.get(state.stage, "场景解析Agent")


def _detect_platform(text: str) -> str:
    """修改要求里点名平台（如"换成小红书""改成朋友圈"）时返回该平台，否则空串。"""
    t = text or ""
    for k in platform_keys():
        if k in t or (k.startswith("门店") and k[2:] in t):
            return k
    return ""


def _apply_revision(state: SessionState, revision: str) -> None:
    """把"修改要求"落到 state：可换平台、换场景，并记录要求本身。"""
    state.revision = revision
    pf = _detect_platform(revision)
    if pf:
        state.platform = pf
    sc = match_business_scene(revision, "")[0]
    if sc:
        state.scene_hint = sc
    state.raw_task = (state.raw_task + f"\n【临时修改要求】{revision}").strip()


def _build_platform_strategy(platform: str) -> dict:
    plat = get_platform(platform)
    return {
        "平台": platform,
        "定位": plat.get("定位"),
        "结构": plat.get("结构"),
        "语气": plat.get("语气"),
        "图片数量": plat.get("图片数量"),
        "行动引导": plat.get("行动引导"),
        "话题标签": plat.get("话题标签"),
        "策略说明": (
            f"{platform}：结构按「{' / '.join(plat.get('结构', []))}」组织，"
            f"语气为{plat.get('语气')}，配图 {plat['图片数量']['min']}-{plat['图片数量']['max']} 张，"
            f"行动引导为「{plat.get('行动引导')}」。"
        ),
    }


def _build_evidence(state: SessionState) -> list[dict]:
    kb = state.product_knowledge
    kb_path = state.product.get("kb_path", "")
    ev: list[dict] = []
    if kb.get("facts_text"):
        ev.append(
            {
                "title": kb.get("facts_title", ""),
                "path": f"{kb_path}/产品事实.md",
                "kb_name": ima_api.KB_NAME,
                "text": kb.get("facts_text", ""),
            }
        )
    if kb.get("selling_text"):
        ev.append(
            {
                "title": kb.get("selling_title", ""),
                "path": f"{kb_path}/卖点与限制.md",
                "kb_name": ima_api.KB_NAME,
                "text": kb.get("selling_text", ""),
            }
        )
    sa = state.scene_analysis or {}
    query = " ".join(
        [state.product.get("name", "")] + [sa.get("业务场景", "")] + list(sa.get("使用场景", []) or [])
    ).strip()
    ev.extend(ima_api.search_evidence(query or state.product.get("name", ""), k=3, prefix=kb_path))
    return ev


def _source_titles(state: SessionState) -> list[str]:
    titles: list[str] = []
    for s in state.product_knowledge.get("sources", []):
        if s.get("标题"):
            titles.append(s["标题"])
    for e in state.evidence:
        t = e.get("title")
        if t and t not in titles:
            titles.append(t)
    return titles[:8]


def _build_output(state: SessionState) -> dict:
    sa = state.scene_analysis or {}
    copy = state.copy or {}
    ver = state.verification or {}
    return {
        "一、场景判断": {
            "业务场景": sa.get("业务场景") or "未明确",
            "目标人群": sa.get("目标人群"),
            "使用场景": sa.get("使用场景"),
            "用户问题": sa.get("用户问题"),
            "内容目标": sa.get("内容目标"),
            "购买阶段": sa.get("购买阶段"),
            "平台": state.platform,
            "依据": sa.get("依据", []),
        },
        "二、知识库依据": {
            "产品型号": f"{state.product.get('name')}（SKU：{state.product.get('sku')}）",
            "事实点": state.facts,
            "资料标题": _source_titles(state),
            "检索来源": ima_api.connection_status()["mode"],
        },
        "三、图文软文": {
            "标题": copy.get("标题", ""),
            "导语": copy.get("导语", ""),
            "正文": copy.get("正文", ""),
            "行动引导": copy.get("行动引导", ""),
            "平台标签": copy.get("平台标签", []),
            "图片方案": state.image_plan,
        },
        "四、核验结果": {
            "产品事实": (ver.get("产品事实") or {}).get("结论", "未核验"),
            "图片型号": (ver.get("图片型号") or {}).get("结论", "未核验"),
            "合规": (ver.get("合规") or {}).get("结论", "未核验"),
            "待确认信息": ver.get("待确认信息", []),
        },
    }


def run_pipeline(
    state: SessionState,
    llm: BaseLLM,
    *,
    product_id: str | None = None,
    scene_hint: str | None = None,
    platform: str | None = None,
    revision: str | None = None,
) -> SessionState:
    if platform:
        state.platform = platform
    if scene_hint is not None:
        state.scene_hint = scene_hint
    if product_id is not None:
        state.product_id = product_id
    if revision:
        _apply_revision(state, revision)

    state.log("协调器", "意图识别", f"发布平台={state.platform}；判断为「华为PC营销软文生成任务」→ 进入标准流程")
    if revision:
        state.log(
            "协调器",
            "应用修改要求",
            f"「{revision}」→ 平台={state.platform}，场景={state.scene_hint or '沿用原场景'}，按新要求重新生成",
        )

    try:
        _run_main_steps(state, llm)
    except Exception as exc:  # 任一环节意外出错也不让整条流水线崩掉，先保住已有进度
        state.log(
            "协调器",
            "异常兜底",
            f"流程在「{next_agent(state)}」阶段出错（{type(exc).__name__}: {exc}），"
            f"已保留已完成步骤的结果，可根据 trace 定位后重试。",
        )
        if not state.output:
            state.output = _build_output(state)
    return state


def _run_main_steps(state: SessionState, llm: BaseLLM) -> None:
    # ---------- 1. 场景解析 ----------
    state.scene_analysis = run_scene(state, llm)
    state.stage = "scene"
    state.log(
        "场景解析Agent",
        "解析人群/场景/目标",
        f"业务场景={state.scene_analysis.get('业务场景')}，人群={state.scene_analysis.get('目标人群')}，"
        f"购买阶段={state.scene_analysis.get('购买阶段')}，依据 {len(state.scene_analysis.get('依据', []))} 条"
        f"（来源：{state.scene_analysis.get('_来源')}）",
    )

    state.pending_questions = missing_inputs(state, state.scene_analysis)
    if state.pending_questions:
        state.log("协调器", "信息不足追问", "；".join(state.pending_questions))

    # ---------- 2. 平台策略 ----------
    state.platform_strategy = _build_platform_strategy(state.platform)
    state.stage = "strategy"
    state.log("平台策略模块", "确定结构/语气/配图", state.platform_strategy["策略说明"])

    # ---------- 3. ima 资料检索（选定产品 + 取产品事实/卖点/图片） ----------
    scene_cfg = state.scene_analysis.get("_scene_cfg") or {}
    if state.product_id:
        prod = get_product(state.product_id)
        if prod is None:
            state.log("知识检索Agent", "指定产品失败", f"未找到「{state.product_id}」，已按场景自动推荐")
            prod = pick_product_for_scene(scene_cfg, state.scene_analysis.get("目标人群", ""))
        else:
            state.log("知识检索Agent", "指定产品", f"评委指定 → {prod['name']}（{prod.get('kb_path')}）")
    else:
        stated_pid = factcheck_mod.model_family_product(state.raw_task)
        if stated_pid and get_product(stated_pid):
            prod = get_product(stated_pid)
            state.log("知识检索Agent", "任务点名型号", f"任务中提到型号 → {prod['name']}（{prod.get('kb_path')}）")
        else:
            prod = pick_product_for_scene(scene_cfg, state.scene_analysis.get("目标人群", ""))
    state.product = product_brief(prod)
    state.product_knowledge = ima_api.get_product_knowledge(state.product.get("kb_path", ""))

    # 干扰处理：任务点名了多个相近型号时，提示人工确认，避免参数与图片错配
    mentions = factcheck_mod.detect_model_mentions(state.raw_task)
    if mentions and not state.product_id:
        own = factcheck_mod.own_model_label(state.product)
        if len(mentions) > 1 or own not in mentions:
            state.pending_questions.append(
                f"任务中提到型号「{'、'.join(mentions)}」，当前主推「{state.product.get('name')}」；"
                f"如需改推其他型号请指定，避免参数与图片错配。"
            )

    state.stage = "retrieve"
    state.log(
        "知识检索Agent",
        "检索 ima 知识库",
        f"命中型号目录 {state.product.get('kb_path')}；"
        f"产品事实 {len(state.product_knowledge.get('facts_text', ''))} 字，"
        f"卖点 {len(state.product_knowledge.get('capabilities', []))} 条，"
        f"图片索引 {len(state.product_knowledge.get('images', []))} 张",
    )

    # ---------- 4. 事实点提取 ----------
    state.facts = content._facts(state.product, state.scene_analysis)
    state.log("事实提取", "提取可用事实点", f"{len(state.facts)} 条事实点，均来自 P1-产品参数库")

    state.evidence = _build_evidence(state)

    # ---------- 5. 图文编排（图片方案） ----------
    state.image_plan = image_ref.build_image_plan(state.platform, state.product, state.scene_analysis)
    state.log(
        "图文编排",
        "生成图片引用方案",
        f"{len(state.image_plan)} 张图，均标注来源与插入位置；型号一致="
        f"{all(i.get('是否型号一致') for i in state.image_plan) if state.image_plan else False}",
    )

    # ---------- 6. 软文生成 ----------
    state.copy = run_content(state, llm, state.product, state.evidence)
    state.stage = "draft"
    state.log(
        "软文生成Agent",
        "生成图文软文",
        f"平台={state.copy.get('平台')}，含标题/导语/正文/行动引导（来源：{state.copy.get('_来源')}）",
    )

    # ---------- 7 + 8. 事实核验 + 合规检查 ----------
    state.verification = run_factcheck(state, state.product, state.facts, state.copy, state.image_plan)
    state.stage = "verify"
    ver = state.verification
    state.log(
        "事实核验Agent",
        "逐项核验",
        f"产品事实={ver['产品事实']['结论']}；图片型号={ver['图片型号']['结论']}；合规={ver['合规']['结论']}",
    )
    if ver["合规"]["命中"]:
        state.log("合规检查", "命中风险项", "；".join(f"{h['类别']}：{h['词']}" for h in ver["合规"]["命中"]))

    # ---------- 9. 导出（统一四段输出） ----------
    state.output = _build_output(state)
    state.stage = "done"
    state.log("协调器", "整合输出", "四段格式已生成，可复制或导出。")


def render_report(state: SessionState) -> str:
    """把四段输出渲染成可直接复制的文本。"""
    o = state.output or _build_output(state)
    a = o["一、场景判断"]
    b = o["二、知识库依据"]
    c = o["三、图文软文"]
    d = o["四、核验结果"]
    lines: list[str] = []
    lines.append("一、场景判断")
    lines.append(f"- 业务场景：{a.get('业务场景')}")
    lines.append(f"- 目标人群：{a.get('目标人群')}；使用场景：{'、'.join(a.get('使用场景') or []) or '未明确'}")
    lines.append(f"- 用户问题：{a.get('用户问题')}")
    lines.append(f"- 内容目标 / 购买阶段 / 平台：{a.get('内容目标')} / {a.get('购买阶段')} / {a.get('平台')}")
    lines.append(f"- 判断依据：{'；'.join(a.get('依据') or []) or '无'}")
    lines.append("")
    lines.append("二、知识库依据")
    lines.append(f"- 产品型号：{b.get('产品型号')}")
    lines.append(f"- 事实点：")
    for f in b.get("事实点") or []:
        lines.append(f"  · {f}")
    lines.append(f"- 资料标题：{'；'.join(b.get('资料标题') or [])}")
    lines.append("")
    lines.append("三、图文软文")
    lines.append(f"【标题】{c.get('标题')}")
    if c.get("导语"):
        lines.append(f"【导语】{c.get('导语')}")
    lines.append("【正文】")
    lines.append(c.get("正文", ""))
    lines.append(f"【行动引导】{c.get('行动引导')}")
    if c.get("平台标签"):
        lines.append(f"【平台标签】{' '.join(c['平台标签'])}")
    lines.append("【图片方案】")
    for i, img in enumerate(c.get("图片方案") or [], 1):
        lines.append(
            f"  {i}. 图片名称：{img.get('名称')}｜来源：{img.get('来源')}｜插入位置：{img.get('插入位置')}｜图片说明：{img.get('说明')}"
        )
    lines.append("")
    lines.append("四、核验结果")
    lines.append(f"- 产品事实：{d.get('产品事实')}")
    lines.append(f"- 图片型号：{d.get('图片型号')}")
    lines.append(f"- 合规：{d.get('合规')}")
    pending = d.get("待确认信息") or []
    lines.append(f"- 待确认信息：{('；'.join(pending)) if pending else '无'}")
    return "\n".join(lines)
