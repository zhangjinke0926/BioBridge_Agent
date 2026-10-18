"""图文软文智能体端到端测试：四段输出、换场景、换平台、干扰与修改、核验与合规。

运行：python -m pytest -q （在项目根目录）
无 LLM Key、无 ima 凭证时全部走本地兜底（规则/模板 + 官方知识库），保证离线可测。
"""
from __future__ import annotations

from src.agents.factcheck import check_compliance, check_product_facts
from src.agents.scene import missing_inputs
from src.config_loader import get_platform, get_product
from src.llm import get_llm
from src.orchestrator import new_state, render_report, run_pipeline

D14 = "matebook_d14_2024"
GT14 = "matebook_gt_14"


def _run(task: str, platform: str, scene: str = "", product_id: str = ""):
    state = new_state(task, platform=platform, scene_hint=scene, product_id=product_id)
    return run_pipeline(state, get_llm())


def test_output_has_four_sections():
    state = _run("为大一新生写开学购机内容，看论文、记笔记、带得动", "小红书", "开学季", D14)
    assert set(state.output.keys()) == {"一、场景判断", "二、知识库依据", "三、图文软文", "四、核验结果"}
    copy = state.output["三、图文软文"]
    assert copy["标题"] and copy["正文"] and copy["行动引导"]
    assert state.image_plan, "应产出配图方案"
    assert state.facts, "应提取到事实点"


def test_render_report_contains_sections():
    state = _run("给职场出差同事写办公本推荐", "公众号", "职场办公", D14)
    text = render_report(state)
    for marker in ["一、场景判断", "二、知识库依据", "三、图文软文", "四、核验结果", "图片名称", "插入位置"]:
        assert marker in text


def test_platform_change_is_substantive():
    """换平台：标题、行动引导、配图数量必须实质变化（只改篇幅不算完成）。"""
    task = "为准备开学购机的新生写内容，兼顾学习、携带和续航"
    a = _run(task, "公众号", "开学季", D14)
    b = _run(task, "小红书", "开学季", D14)
    c = _run(task, "门店海报", "开学季", D14)

    assert a.copy["行动引导"] != b.copy["行动引导"] != c.copy["行动引导"]
    assert len({a.copy["标题"], b.copy["标题"], c.copy["标题"]}) >= 2
    counts = {len(a.image_plan), len(b.image_plan), len(c.image_plan)}
    assert len(counts) >= 2, f"配图数量应随平台变化，实际：公众号{len(a.image_plan)} 小红书{len(b.image_plan)} 海报{len(c.image_plan)}"
    # 各平台图片数量应落在平台规定区间内
    for st_, plat in [(a, "公众号"), (b, "小红书"), (c, "门店海报")]:
        rng = get_platform(plat)["图片数量"]
        assert rng["min"] <= len(st_.image_plan) <= rng["max"]


def test_every_platform_has_nonempty_title():
    """四段输出要求「标题」字段不能为空，门店朋友圈 / 门店海报也不例外。"""
    for pf in ["公众号", "小红书", "门店朋友圈", "门店海报"]:
        state = _run("新生开学购机内容，主打轻薄和续航", pf, "开学季", D14)
        assert state.copy["标题"].strip(), f"{pf} 的标题为空"
        assert state.copy["行动引导"].strip(), f"{pf} 的行动引导为空"


def test_scene_change_changes_angle():
    """换场景：业务场景与切入点必须变化。"""
    a = _run("大学生开学买电脑，主要看论文写作业", "公众号", "开学季", D14)
    b = _run("做视频剪辑的创作者要换电脑，主要剪素材", "公众号", "内容创作", GT14)
    assert a.scene_analysis["业务场景"] == "开学季"
    assert b.scene_analysis["业务场景"] == "内容创作"
    assert a.copy["标题"] != b.copy["标题"]
    assert a.copy["正文"] != b.copy["正文"]


def test_images_are_model_consistent():
    state = _run("新生开学购机内容", "小红书", "开学季", D14)
    assert all(img["是否型号一致"] for img in state.image_plan)
    assert state.verification["图片型号"]["结论"] == "全部型号一致"


def test_product_facts_verified_against_kb():
    prod = get_product(D14)
    kb_facts = prod["skus"][0]["selling_points"][:2]
    result = check_product_facts(prod, kb_facts)
    assert result["逐项"], "应有逐项核验结果"
    assert any(it["结论"] == "通过" for it in result["逐项"])


def test_factcheck_flags_fabricated_fact():
    prod = get_product(D14)
    result = check_product_facts(prod, ["搭载 9999mAh 电池、重量 0.5kg"])
    assert result["结论"] == "存在待确认项"
    assert any(it["结论"] == "待确认" for it in result["逐项"])


def test_compliance_detects_absolute_and_price_claims():
    result = check_compliance("这台是全网最低价，续航最强，绝对不卡，到手价只要 3999 元")
    assert result["结论"] == "需改写"
    cats = {h["类别"] for h in result["命中"]}
    assert "绝对化/违规用语" in cats
    assert "价格误导" in cats


def test_copy_never_contains_price_or_subsidy():
    state = _run("新生开学购机内容", "小红书", "开学季", D14)
    text = state.copy["标题"] + state.copy["导语"] + state.copy["正文"] + state.copy["行动引导"]
    for bad in ["¥", "到手价", "补贴", "立减", "国补", "元"]:
        assert bad not in text, f"软文不得出现价格/补贴表述：{bad}"
    assert state.verification["合规"]["结论"] == "通过"


def test_incomplete_input_asks_followup():
    state = _run("想买台轻薄本", "公众号")
    assert state.pending_questions, "信息不足时应提示补充"
    assert any("业务场景" in q or "目标人群" in q or "产品" in q for q in state.pending_questions)


def test_confusable_models_trigger_confirmation():
    state = _run("华为 MateBook D 16 和 MateBook D 16 SE 版有什么区别，哪个适合做表", "公众号", "职场办公")
    assert any("型号" in q for q in state.pending_questions), state.pending_questions


def test_revision_regenerates():
    """临时修改：带上修改要求后重新生成，输出必须相对上一版有实质变化。"""
    base = _run("新生开学购机内容，主打轻薄和续航", "小红书", "开学季", D14)
    state = new_state(base.raw_task, platform="小红书", scene_hint="开学季", product_id=D14)
    state = run_pipeline(state, get_llm(), revision="换成门店朋友圈语气")
    # 修改要求里点名平台 → 平台应真的切换，配图数量随之变化
    assert state.platform == "门店朋友圈"
    assert len(state.image_plan) <= 3
    assert "临时修改要求" in state.raw_task

    # 精简类要求 → 正文变短
    short = new_state(base.raw_task, platform="小红书", scene_hint="开学季", product_id=D14)
    short = run_pipeline(short, get_llm(), revision="正文精简到三句以内")
    assert len(short.copy["正文"]) < len(base.copy["正文"])


def test_missing_inputs_helper_direct():
    state = new_state("想买台轻薄本", platform="公众号")
    qs = missing_inputs(state, {"业务场景": "", "目标人群": "未明确"})
    assert any("业务场景" in q for q in qs)
