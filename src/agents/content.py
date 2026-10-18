"""图文软文生成 Agent：按平台与场景生成【标题 / 导语 / 正文 / 行动引导 / 平台标签】。

赛题手册v4 判断标准：换场景后切入点要变，换平台后结构、语气、图片数量和行动引导要变。
所以这里为 4 个平台各写一套结构与语气，绝不只改篇幅。
正文只使用知识库里有依据的产品事实，不写价格、补贴、销量、奖项与用户评价。
"""
from __future__ import annotations

import re
from typing import Any

from src.config_loader import get_platform
from src.llm import BaseLLM, LLMError
from src.prompt_loader import load_prompt
from src.tools import ima_api
from src.tools import retrieval

# 卖点优先级 → 规格事实筛选关键词
_FACT_KEYS: dict[str, list[str]] = {
    "便携": ["kg", "mm", "轻薄", "重量"],
    "续航": ["Wh", "电池", "续航"],
    "多设备协同": ["超级终端", "华为分享", "协同", "碰一碰", "跨设备", "多设备"],
    "护眼屏": ["英寸", "OLED", "IPS", "sRGB", "尼特", "屏幕", "护眼"],
    "屏幕": ["英寸", "OLED", "IPS", "sRGB", "尼特", "屏幕", "Hz", "柔光"],
    "接口": ["USB", "HDMI", "雷电", "DP", "SD", "接口", "网口"],
    "性能": ["酷睿", "Ultra", "i5", "i9", "麒麟", "标压", "处理器", "核"],
    "系统": ["HarmonyOS", "Windows", "鸿蒙", "系统"],
    "存储": ["GB", "TB", "SSD", "内存", "存储"],
    "管理": ["HarmonyOS", "Windows", "系统", "管理"],
    "服务": ["服务", "保修", "售后", "焕新"],
}

# 小红书标题：按场景给不同钩子，避免"职场办公选电脑别只看跑分"这类生硬拼接
_XHS_TITLES: dict[str, str] = {
    "开学季": "开学季选笔记本，别只盯跑分，这台更值得先看",
    "职场办公": "职场办公选笔记本，先看这几点再决定",
    "内容创作": "做内容创作选本，这台值得放进候选清单",
    "家庭换新": "家里换台电脑，这台可能比你想的更合适",
    "企业采购": "团队批量采购笔记本，这篇讲清怎么挑",
    "门店到访": "到店看笔记本，先认清这几个关键点",
    "新品首发": "新品到店，这台华为笔记本先看这几点",
    "节日营销": "节日想换笔记本，这篇帮你一次看清",
}

# 修改要求里的关键词 → 对应处理
_REV_SHRINK = ("精简", "删减", "简短", "压缩", "更短", "短一点", "三句", "缩到", "缩成", "减半")
_REV_COLLOQUIAL = ("口语", "活泼", "接地气", "轻松", "聊天", "随意", "别太正式")

_DEFAULT_SYSTEM_PROMPT = """你是华为 PC 营销软文智能体的【生成】模块。
基于给定的场景判断、平台规则与知识库事实，输出严格 JSON：
{
  "标题": "...", "导语": "...", "正文": "...", "行动引导": "...", "平台标签": ["#..."]
}
硬性要求：
1) 平台不同，结构/语气/篇幅/行动引导必须实质不同；
2) 正文只能使用给定事实，禁止出现价格、补贴、销量、奖项、用户评价与绝对化用语；
3) 不贬损竞品；不虚构个人体验（小红书不得写成"我实测"）。"""

SYSTEM_PROMPT = load_prompt("content", _DEFAULT_SYSTEM_PROMPT)


_SPEC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(\d+(?:\.\d+)?)\s*kg$", re.I), r"约\1kg，单手拎得动的轻薄机身"),
    (re.compile(r"^约?(\d+(?:\.\d+)?)\s*kg"), r"约\1kg 的轻薄机身"),
    (re.compile(r"^(\d+)\s*Wh$", re.I), r"\1Wh 大电池，续航更扛用"),
    (re.compile(r"^(\d+)\s*GB$", re.I), r"\1GB 内存，多开窗口不卡顿"),
    (re.compile(r"^(\d+)\s*(GB|TB)\s*(NVMe\s*)?SSD$", re.I), r"\1\2 固态硬盘，存取快还不卡"),
    (re.compile(r"^(全尺寸)?背光键盘$"), r"\1背光键盘，暗光环境也好打字"),
]


def _humanize_spec(raw: str) -> str:
    """把裸规格片段（如"16GB"、"约1.39kg"、"56Wh"）转成人话表达，
    让列点读起来像在说人话，而不是贴参数表。未命中规则的片段原样返回。"""
    s = (raw or "").strip()
    if not s:
        return s
    for pattern, repl in _SPEC_PATTERNS:
        m = pattern.match(s)
        if m:
            return pattern.sub(repl, s)
    return s


def _facts(product: dict, scene: dict) -> list[str]:
    spec = product.get("spec", "")
    parts = [p.strip() for p in spec.split("/") if p.strip()]
    priority = scene.get("卖点优先级", []) or []
    keys: list[str] = []
    for p in priority:
        keys += _FACT_KEYS.get(p, [])
    ranked = sorted(parts, key=lambda s: -sum(1 for k in keys if k in s))
    out = [p for p in ranked if p][:4]
    out = out or parts[:3]
    return [_humanize_spec(p) for p in out]


def _selling(product: dict) -> list[str]:
    return product.get("selling_points", []) or [product.get("positioning", "华为 PC 产品")]


def _objection_angle(scene: dict) -> str:
    """从客户顾虑库里按场景的"用户问题"检索最相关的一条，取其情感设计角度，
    用于替换写死的过渡句，让不同场景的切入话术真正不一样。"""
    query = scene.get("用户问题", "") or scene.get("业务场景", "")
    if not query:
        return ""
    hit_text = retrieval.search_text(query, k=1, source="objections.md")
    if not hit_text:
        return ""
    m = re.search(r"情感设计[：:]\s*(.+)", hit_text)
    return m.group(1).strip() if m else ""


def _short(name: str) -> str:
    """去掉名称前缀里的"华为 "，避免模板里出现"华为 华为 XX"。"""
    return (name or "").replace("华为 ", "").strip()


# 平台 → 场景关键词 → CTA 模板。场景命中优先，未命中落到平台默认文案，
# 确保"换场景角度要变、换平台结构要变"在行动引导这一环也成立。
_CTA_BY_SCENE: dict[str, dict[str, str]] = {
    "公众号": {
        "企业采购": "想给团队批量选型，可以在文末留言，我们按岗位需求帮你排配置清单。",
        "门店到访": "想先上手体验，文末预约到店时段，我们按你的用途帮你对照配置。",
    },
    "小红书": {
        "开学季": "新生党想要同款，评论区扣「1」或私信我，按你的专业需求帮你看合不合适～",
        "企业采购": "团队采购想了解细节，私信我，我按预算和需求帮你列选型建议～",
    },
    "门店朋友圈": {
        "新品首发": "新品到店，想第一时间上手的直接私信我，我给你留一台先试。",
        "节日营销": "过节想换台电脑的，私信我或直接到店，我给你留一台。",
    },
}

_CTA_DEFAULT: dict[str, str] = {
    "公众号": "想上手感受实际手感，可以在文末预约到店体验，我们会按你的用途帮你对照具体配置。",
    "小红书": "想要同款的姐妹，评论区扣「1」或私信我，我按你的用途帮你看合不合适～",
    "门店朋友圈": "附近的朋友想上手摸一下，私信我或直接到店，我给你留一台。",
    "门店海报": "到店咨询体验，详情以门店当日公示为准。",
}


def _cta(platform: str, short_name: str, scene: dict | None = None) -> str:
    scene = scene or {}
    key = scene.get("业务场景", "")
    by_scene = _CTA_BY_SCENE.get(platform, {})
    if key and key in by_scene:
        return by_scene[key]
    default = _CTA_DEFAULT.get(platform, "到店咨询体验")
    if platform == "公众号":
        return f"想上手感受 {short_name} 的实际手感，可以在文末预约到店体验，我们会按你的用途帮你对照具体配置。"
    return default


def _strategy(scene: dict, product: dict, platform: str) -> str:
    return (
        f"人群={scene.get('目标人群')}，场景={scene.get('业务场景')}，平台={platform}。"
        f"切入角度：{scene.get('切入角度')}。"
        f"主推 {product.get('name')}，优先讲与「{ '、'.join(scene.get('卖点优先级', []) or ['核心卖点']) }」相关的知识库事实，"
        f"不涉及价格与未经证实的信息。"
    )


def _body_gongzhonghao(scene: dict, product: dict, facts: list[str], sp: list[str]) -> tuple[str, str, str]:
    audience = scene.get("目标人群")
    key = scene.get("业务场景")
    problem = scene.get("用户问题")
    title = f"{audience}买笔记本，{key}真正该优先看什么？"
    lead = (
        f"如果你是{audience}，正在为「{key}」挑一台笔记本，先别急着比参数。"
        f"这篇把「{product.get('name')}」的实际配置和适用场景讲清楚，帮你判断它是不是你要的那台。"
    )
    angle = _objection_angle(scene)
    problem_line = f"{problem}。{angle}" if angle else f"{problem}。比起堆参数，更重要的是：这台机在你每天要做的事上，够不够顺手、带不带得动。"
    body = (
        f"### 一、这类人真正要解决的问题\n"
        f"{problem_line}\n\n"
        f"### 二、这台机的关键事实（均来自产品资料，购买前请按具体 SKU 核对）\n"
        + "\n".join(f"- {f}" for f in facts[:4])
        + "\n\n### 三、适合谁、要注意什么\n"
        + f"{product.get('positioning', '').rstrip('。；;')}。"
        + f"\n\n### 四、为什么在这个场景推它\n"
        + f"{('；'.join(sp[:2]))}。"
    )
    return title, lead, body


def _body_xiaohongshu(scene: dict, product: dict, facts: list[str], sp: list[str]) -> tuple[str, str, str, list[str]]:
    audience = scene.get("目标人群")
    key = scene.get("业务场景")
    title = _XHS_TITLES.get(key, f"{key}选笔记本，这篇帮你一次看清" if key else "选笔记本，这篇帮你一次看清")
    lead = f"{key or '选笔记本'}该怎么挑？我把华为 {_short(product.get('name'))} 的产品资料整理了一遍👇"
    angle = _objection_angle(scene)
    intro_line = angle or "理由很实在，一条条说："
    lines = [
        intro_line,
        *[f"✅ {s}" for s in sp[:3]],
        "",
        f"配置也摆给你看（不吹，自己对照需求）：",
        *[f"· {f}" for f in facts[:3]],
        "",
        f"日常{('、'.join(scene.get('使用场景', []) or ['办公学习']))}真的够用，重点是它把{sp[0].split('，')[0]}这件事做好了。",
    ]
    body = "\n".join(lines)
    tags = ["#华为笔记本", f"#{key}", f"#{audience}电脑", "#笔记本推荐", "#轻薄本"]
    return title, lead, body, tags


def _body_pengyouquan(scene: dict, product: dict, facts: list[str], sp: list[str]) -> tuple[str, str, str]:
    key = scene.get("业务场景")
    # 该平台无独立标题，首句即钩子：这里把钩子放进"标题"字段，保证四段输出不出现空标题
    title = f"{key}想换电脑的，我一般先推华为 {_short(product.get('name'))}" if key else f"想换电脑的，我一般先推华为 {_short(product.get('name'))}"
    lead = ""
    body = (
        f"就一个核心点：{sp[0]}。\n"
        f"{scene.get('用户问题')}这一点它正好对上。\n"
        f"配置简单说一句：{facts[0]}。"
    )
    return title, lead, body


def _body_haibao(scene: dict, product: dict, facts: list[str], sp: list[str]) -> tuple[str, str, str]:
    audience = scene.get("目标人群")
    key = scene.get("业务场景")
    title = product.get("name", "华为笔记本")
    lead = f"{audience} · {key}优选"
    body = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sp[:3]))
    return title, lead, body


def _rule_based(platform: str, scene: dict, product: dict) -> dict[str, Any]:
    facts = _facts(product, scene)
    sp = _selling(product)
    tags: list[str] = []
    if platform == "公众号":
        title, lead, body = _body_gongzhonghao(scene, product, facts, sp)
    elif platform == "小红书":
        title, lead, body, tags = _body_xiaohongshu(scene, product, facts, sp)
    elif platform == "门店朋友圈":
        title, lead, body = _body_pengyouquan(scene, product, facts, sp)
    else:  # 门店海报
        title, lead, body = _body_haibao(scene, product, facts, sp)

    return {
        "标题": title,
        "导语": lead,
        "正文": body,
        "行动引导": _cta(platform, _short(product.get("name", "这台机")), scene),
        "平台标签": tags,
        "平台": platform,
        "策略说明": _strategy(scene, product, platform),
        "_来源": "模板生成（未配置模型 Key）",
    }


def _revision_scene(scene: dict, revision: str) -> dict:
    """修改要求里点名某个卖点（如"主打续航"）时，改为只围绕该卖点取事实，保证排序真的变化。"""
    rev = revision or ""
    hit = [k for k in _FACT_KEYS if k in rev]
    if not hit:
        return scene
    s = dict(scene)
    s["卖点优先级"] = hit
    return s


def _apply_revision(result: dict, revision: str, platform: str) -> None:
    """就地按"修改要求"调整文案，保证修改后输出相对上一版有实质变化。"""
    rev = revision or ""
    if not rev:
        return
    if any(k in rev for k in _REV_SHRINK):
        paragraphs = [p for p in (result.get("正文") or "").split("\n\n") if p.strip()]
        if platform == "公众号":
            result["正文"] = "\n\n".join(paragraphs[:2])
        else:
            lines = [ln for ln in (result.get("正文") or "").splitlines() if ln.strip()]
            result["正文"] = "\n".join(lines[:3])
        if result.get("导语"):
            result["导语"] = result["导语"].split("。")[0] + "。"
    if any(k in rev for k in _REV_COLLOQUIAL):
        body = (result.get("正文") or "").replace("### ", "").replace("\n- ", "\n· ")
        if platform == "小红书" and "直接说吧" not in body:
            body = "直接说吧👇\n" + body
        result["正文"] = body
    result["_修改"] = rev


def run_content(state, llm: BaseLLM, product: dict, evidence: list[dict]) -> dict[str, Any]:
    platform = state.platform
    plat = get_platform(platform)
    revision = getattr(state, "revision", "") or ""
    scene = _revision_scene(state.scene_analysis, revision)
    result = _rule_based(platform, scene, product)
    result["结构"] = plat.get("结构", [])
    result["使用素材"] = [e.get("title", "") for e in evidence][:6]

    if llm.available:
        facts = _facts(product, scene)
        evidence_text = "\n\n".join(
            f"【{e.get('title','')}】{e.get('text','')[:1200]}" for e in evidence[:3]
        )
        user = (
            f"平台：{platform}；平台结构：{plat.get('结构')}；语气：{plat.get('语气')}\n"
            f"场景判断：{scene}\n"
            f"主推机型：{product.get('name')}（{product.get('spec')}）\n"
            f"可用产品事实：{facts}\n"
            f"知识库原文摘录：\n{evidence_text}"
        )
        try:
            data = llm.chat_json(SYSTEM_PROMPT, user)
            if isinstance(data, dict) and data.get("正文"):
                for k in ("标题", "导语", "正文", "行动引导"):
                    if data.get(k):
                        result[k] = data[k]
                if data.get("平台标签"):
                    result["平台标签"] = data["平台标签"]
                result["_来源"] = "模型生成（事实来自知识库）"
        except LLMError:
            pass  # 调用失败，保留上面已生成的规则版正文，不中断流程

    _apply_revision(result, revision, platform)
    return result
