"""01 场景解析 Agent：把"产品 + 目标人群 + 场景 + 渠道"的任务输入，解析成【场景判断】结构化结果。

对应统一输出格式第一段：
  一、场景判断
  - 目标人群 / 使用场景
  - 用户问题 / 内容目标 / 平台

判断必须能回溯到用户输入或场景卡，不凭空推断。信息不足时给出【需要补充的问题】。
"""
from __future__ import annotations

from typing import Any

from src.agents import common
from src.config_loader import get_platform, load_scenes
from src.llm import BaseLLM, LLMError
from src.prompt_loader import load_prompt

# 业务场景关键词（来自赛题手册v4 第三节）
SCENE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("开学季", ["开学", "新生", "大一", "大二", "大三", "入学", "报到", "家长买", "给孩子买电脑", "校园"]),
    ("职场办公", ["办公", "职场", "出差", "会议", "上班", "商务", "通勤", "移动办公", "报表", "周报", "公司"]),
    ("内容创作", ["创作", "剪辑", "设计", "修图", "摄影", "视频", "渲染", "画图", "插画", "调色", "自媒体"]),
    ("家庭换新", ["换新", "旧机", "换电脑", "家人", "全家", "父母", "老人", "给孩子", "家用", "退休"]),
    ("企业采购", ["采购", "公司买", "团队", "企业", "批量", "部署", "行政", "统一配"]),
    ("门店到访", ["到店", "门店", "附近", "路过", "进来看看", "逛逛", "体验一下"]),
    ("新品首发", ["新品", "首发", "新款", "刚出", "最新款", "新发布"]),
    ("节日营销", ["节日", "送礼", "礼物", "过年", "春节", "情人节", "双十一", "618", "促销", "开学礼"]),
]

CONTENT_GOAL: dict[str, str] = {
    "公众号": "让读者读完能判断这款机适合谁，并愿意预约到店体验",
    "小红书": "引发同人群共鸣，在评论区或私信产生咨询",
    "门店朋友圈": "让附近熟人产生到店或私信咨询",
    "门店海报": "让路过的人一眼看懂一个核心卖点，愿意进店咨询",
}

_DEFAULT_SYSTEM_PROMPT = """你是华为 PC 营销软文智能体的【场景理解】模块。
请从任务输入中提取结构化场景判断，只输出 JSON：
{
  "业务场景": "开学季 / 职场办公 / 内容创作 / 家庭换新 / 企业采购 / 门店到访 / 新品首发 / 节日营销",
  "目标人群": "大学新生 / 家长 / 商务人士 / 移动办公者 / 创作者 / 家庭用户 / 中小企业采购 等",
  "使用场景": ["客户实际会用它做什么"],
  "用户问题": "客户最想解决的具体问题",
  "购买阶段": "了解 / 对比 / 决策",
  "依据": ["逐条列出判断所依据的原始输入摘录"]
}
硬性要求：不得编造用户没提到的信息；每一项判断都要能在依据里找到出处。"""

SYSTEM_PROMPT = load_prompt("scene", _DEFAULT_SYSTEM_PROMPT)


def match_business_scene(text: str, hint: str = "") -> tuple[str, list[str]]:
    if hint:
        for s in load_scenes():
            if s["key"] == hint:
                return hint, [f"用户/场景卡指定：{hint}"]
    for key, kws in SCENE_KEYWORDS:
        ev = common.match_evidence(text, kws)
        if ev:
            return key, ev
    return "", []


def _fallback_scene(audience: str) -> str:
    if audience == "学生":
        return "开学季"
    if audience == "创作者":
        return "内容创作"
    if audience == "家庭用户":
        return "家庭换新"
    if audience == "商务人士":
        return "职场办公"
    return "职场办公"


def _purchase_stage(text: str) -> str:
    if common.match_evidence(text, common.URGENCY_HIGH):
        return "决策"
    if common.match_evidence(text, ["对比", "看看", "了解一下", "哪个好", "推荐"]):
        return "对比"
    return "了解"


def run_scene(state, llm: BaseLLM) -> dict[str, Any]:
    text = state.raw_task
    platform = state.platform
    plat = get_platform(platform)

    audience, audience_ev = common.best_identity(text)
    scene_key, scene_ev = match_business_scene(text, state.scene_hint)
    usages = common.all_matches(text, common.SCENARIO_RULES)
    problem, problem_ev = common.best_objection(text)

    scene_cfg = None
    if scene_key:
        for s in load_scenes():
            if s["key"] == scene_key:
                scene_cfg = s
                break

    result: dict[str, Any] = {
        "业务场景": scene_key,
        "目标人群": audience,
        "使用场景": usages,
        "用户问题": "",
        "购买阶段": _purchase_stage(text),
        "内容目标": CONTENT_GOAL.get(platform, "让目标人群产生咨询"),
        "平台": platform,
        "平台定位": plat.get("定位", ""),
        "依据": [],
        "_来源": "规则解析（未配置模型 Key）",
        "_scene_cfg": scene_cfg,
    }

    evidence: list[str] = list(audience_ev) + list(scene_ev) + list(problem_ev)
    seen, dedup = set(), []
    for e in evidence:
        if e not in seen:
            seen.add(e)
            dedup.append(e)
    result["依据"] = dedup or ["任务输入信息较少，已按场景卡默认值补充"]

    if scene_cfg:
        if not result["使用场景"]:
            result["使用场景"] = [scene_cfg["内容重点"].split("；")[0]]
        result["用户问题"] = problem if problem != "未明确" else scene_cfg["内容重点"].split("；")[0]
        result["切入角度"] = scene_cfg["切入角度"]
        result["内容重点"] = scene_cfg["内容重点"]
        result["卖点优先级"] = scene_cfg.get("卖点优先级", [])
        if not result["目标人群"] or result["目标人群"] == "未明确":
            result["目标人群"] = scene_cfg["人群"].split("、")[0]
    else:
        result["用户问题"] = result["用户问题"] or "想让一台电脑更好满足日常使用"
        result["切入角度"] = "先讲清使用场景，再对应到具体型号事实"

    # 可选：真实模型细化（无 Key 时跳过；调用失败时自动回落规则结果，不中断流程）
    if llm.available:
        try:
            user = f"发布平台：{platform}\n任务输入：\n{text}"
            data = llm.chat_json(SYSTEM_PROMPT, user)
            if isinstance(data, dict) and data.get("业务场景"):
                for k in ("业务场景", "目标人群", "使用场景", "用户问题", "购买阶段"):
                    if data.get(k):
                        result[k] = data[k]
                result["_来源"] = "模型解析"
        except LLMError:
            result["_来源"] = "规则解析（模型调用失败，已自动降级）"

    return result


def missing_inputs(state, scene: dict) -> list[str]:
    """信息不足时提示补充（赛题手册v4：Task input 功能板块）。"""
    qs: list[str] = []
    if scene.get("业务场景"):
        pass
    else:
        qs.append("业务场景不明确，请补充：这条内容属于开学季 / 职场办公 / 内容创作 / 家庭换新 / 企业采购 / 门店到访 / 新品首发 / 节日营销 中的哪一类？")
    if not scene.get("目标人群") or scene.get("目标人群") == "未明确":
        qs.append("目标人群不明确，请补充：这条内容主要给谁看（学生 / 职场人士 / 创作者 / 家庭用户 / 企业采购 等）？")
    if not state.product_id:
        qs.append("未指定产品，已按场景自动推荐；如需指定型号，请补充具体机型。")
    return qs
