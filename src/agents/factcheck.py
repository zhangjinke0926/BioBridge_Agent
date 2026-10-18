"""事实核验 + 合规检查 Agent：交付前逐项检查产品事实、图片型号、合规风险。

赛题手册v4 要求：
- 逐项检查产品事实；无依据内容必须删除或标记（资料冲突时停止输出并提示人工确认）。
- 合规：识别绝对化用语、虚假承诺、价格误导、无依据对比和竞品贬低。
- 图片：核对产品型号，型号不符的图不进入交付。
"""
from __future__ import annotations

import re
from typing import Any

from src.config_loader import load_products
from src.tools import ima_api, retrieval

# 价格误导 / 虚假承诺 / 无依据对比 / 竞品贬低 的检测规则
_PRICE_PATTERNS = [
    (r"¥\s*\d", "价格误导", "出现具体价格数字"),
    (r"\d[\d,\.]*\s*元", "价格误导", "出现具体金额"),
    (r"(到手价|最低价|起售价|售价|价格)", "价格误导", "出现价格表述"),
    (r"(补贴|国补|店补|立减|折扣|打折|优惠券|秒杀|降价|促销价)", "价格误导", "出现补贴/促销表述"),
    (r"(库存|现货|仅剩|限量\s*\d+)", "价格误导", "出现库存承诺"),
    (r"(销量|排名|第一\s*名|获奖|获奖项|好评率|用户评价|回购率)", "无依据对比", "出现销量/排名/奖项/评价"),
]

_ABSOLUTE_EXTRA = ["全网最低", "史上最强", "绝对", "百分百", "永久", "终身", "包治", "无理由退"]

# 允许在词中间插入少量字符/标点的变体匹配，例如"全网最低"也能命中"全网-最低"
# "全网 最低"等写法。超过2字的词才做变体匹配，避免"第一"之类短词产生过多误匹配噪音。
_VARIANT_GAP = r"[\s\-_·,，。！!]{0,2}"


def _variant_pattern(word: str) -> re.Pattern:
    if len(word) <= 2:
        return re.compile(re.escape(word))
    chars = [re.escape(c) for c in word]
    return re.compile(_VARIANT_GAP.join(chars))


_PROMISE_PATTERNS = [
    (r"(保证|承诺)\S{0,6}(升值|不掉价|赚钱)", "虚假承诺", "出现收益类承诺"),
    (r"(绝对不|永远不|保证不)\S{0,4}(坏|卡|出问题)", "虚假承诺", "出现绝对化质量承诺"),
]


def _norm(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", text or "").lower()


def _signature_tokens(fact: str) -> list[str]:
    """抽出可核验的"签名片段"：型号串、带单位数字、关键数字组合。"""
    tokens = re.findall(r"[A-Za-z]*\d[\w\-\.]*", fact)  # i5-13420H / 2880 / X90
    tokens += re.findall(r"\d+(?:\.\d+)?\s*×\s*\d+", fact)  # 2880×1920
    tokens += re.findall(r"\d+(?:\.\d+)?\s*(?:英寸|mm|kg|g|Wh|GB|TB|Hz|尼特|nits|sRGB|NTSC|%)", fact)
    seen, out = set(), []
    for t in tokens:
        n = _norm(t)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def known_model_strings() -> list[str]:
    """所有已知型号的关键串，用于识别"易混淆型号"。"""
    models: list[str] = []
    for p in load_products():
        models.append(p["name"].replace("华为 ", "").strip())
    models += [
        "MateBook D 14", "MateBook D 16", "MateBook D 16 SE", "MateBook 14",
        "MateBook X Pro", "MateBook GT 14", "MateBook Fold", "MateBook Pro S",
        "MateBook Pro",
    ]
    return sorted(set(models), key=len, reverse=True)


# 型号家族别名 → 产品 id（用于干扰测试：任务里点名型号时纠正推荐）
_MODEL_ALIASES: list[tuple[str, list[str], str]] = [
    ("MateBook D 16 SE", ["d16se", "d16 se", "d 16 se"], "matebook_d16_se_2024"),
    ("MateBook D 16", ["d16", "d 16"], "matebook_d16_2024"),
    ("MateBook D 14", ["d14", "d 14"], "matebook_d14_2024"),
    ("MateBook X Pro", ["xpro", "x pro"], "matebook_xpro_ultra_weirong"),
    ("MateBook GT 14", ["gt14", "gt 14"], "matebook_gt_14"),
    ("MateBook Fold", ["fold"], "matebook_fold_ultimate"),
    ("MateBook Pro S", ["matebookpros", "pro s"], "matebook_pro_s"),
    ("MateBook Pro", ["matebookpro", "matebook pro"], "matebook_pro_harmony"),
]


def detect_model_mentions(text: str) -> list[str]:
    """识别任务输入里被点名的型号家族（长名优先，避免 Pro 抢 Pro S）。返回按出现位置排序。"""
    n = _norm(text)
    found: list[tuple[int, str, str]] = []
    for label, aliases, pid in _MODEL_ALIASES:
        idx = min((n.find(_norm(a)) for a in aliases if _norm(a) in n), default=-1)
        if idx >= 0:
            found.append((idx, label, pid))
    found.sort()
    labels = [f[1] for f in found]
    if "MateBook D 16 SE" in labels and "MateBook D 16" in labels:
        labels.remove("MateBook D 16")
    if "MateBook Pro S" in labels and "MateBook Pro" in labels:
        labels.remove("MateBook Pro")
    return labels


def model_family_product(text: str) -> str:
    """任务里最先点到的型号家族 → 对应产品 id（找不到返回空）。"""
    n = _norm(text)
    best: tuple[int, str] | None = None
    for _label, aliases, pid in _MODEL_ALIASES:
        idx = min((n.find(_norm(a)) for a in aliases if _norm(a) in n), default=-1)
        if idx >= 0 and (best is None or idx < best[0]):
            best = (idx, pid)
    return best[1] if best else ""


def own_model_label(product: dict) -> str:
    n = _norm(product.get("name", ""))
    for label, aliases, _ in _MODEL_ALIASES:
        if any(_norm(a) in n for a in aliases):
            return label
    return ""


def _mentioned_other_models(text: str, product: dict) -> list[str]:
    own = {product.get("name", ""), (product.get("kb_path", "") or "").split("/")[-1], product.get("series", "")}
    own_blob = " ".join(own)
    hits: list[str] = []
    for m in known_model_strings():
        core = _norm(m)
        if core and core in _norm(text) and core not in _norm(own_blob):
            # 允许"MateBook 14"作为通用系列词出现在自身名称里
            if any(core in _norm(o) for o in own):
                continue
            hits.append(m)
    return hits


def _locate_token(token: str, sources: list[tuple[str, str]]) -> dict | None:
    """在原文（未归一化）里找到含有该签名 token 的那一行，返回命中片段+来源文件，供人工核对。"""
    for label, text in sources:
        if not text:
            continue
        for line in text.splitlines():
            if token in _norm(line):
                snippet = line.strip().strip("|").strip()
                if snippet:
                    return {"来源": label, "原文": snippet[:120]}
    return None


def check_product_facts(product: dict, facts: list[str]) -> dict:
    kb = ima_api.get_product_knowledge(product.get("kb_path", ""))
    facts_text = kb.get("facts_text", "")
    selling_text = kb.get("selling_text", "")
    haystack = _norm(facts_text + "\n" + selling_text)
    sources = [
        (kb.get("facts_title") or "产品事实.md", facts_text),
        (kb.get("selling_title") or "卖点与限制.md", selling_text),
    ]
    items = []
    ok = True
    for fact in facts:
        tokens = _signature_tokens(fact)
        if not tokens:
            items.append({"事实": fact, "结论": "通过", "说明": "无可核验的数值/型号签名，按常规表述处理", "原文定位": []})
            continue
        found = [t for t in tokens if t in haystack]
        missing = [t for t in tokens if t not in haystack]
        ratio = len(found) / len(tokens)
        locations = [loc for t in found if (loc := _locate_token(t, sources))]
        if ratio >= 0.5:
            items.append(
                {
                    "事实": fact,
                    "结论": "通过",
                    "说明": f"命中 {len(found)}/{len(tokens)} 项签名",
                    "原文定位": locations,
                }
            )
        else:
            ok = False
            items.append(
                {
                    "事实": fact,
                    "结论": "待确认",
                    "说明": f"资料中未找到：{'、'.join(missing[:4])}；请人工核对后方可发布",
                    "原文定位": locations,
                }
            )
    return {"结论": "全部通过" if ok else "存在待确认项", "逐项": items}


def check_images(image_plan: list[dict]) -> dict:
    items = []
    ok = True
    for img in image_plan:
        consistent = img.get("是否型号一致", False)
        if not consistent:
            ok = False
        items.append(
            {
                "图片": img.get("名称", ""),
                "型号": img.get("型号") or "未标注（场景示意图，需核对型号）",
                "结论": "型号一致" if consistent else "待确认（非本型号素材）",
            }
        )
    return {"结论": "全部型号一致" if ok else "存在待核对图片", "逐项": items}


def check_compliance(text: str) -> dict:
    hits: list[dict] = []
    for w in retrieval.load_banned_words():
        m = _variant_pattern(w).search(text)
        if m:
            hits.append({"类别": "绝对化/违规用语", "词": w, "命中文本": m.group(0)})
    for pat, cat, note in _PRICE_PATTERNS:
        for m in re.finditer(pat, text):
            hits.append({"类别": cat, "词": m.group(0), "说明": note})
            break
    for pat, cat, note in _PROMISE_PATTERNS:
        if re.search(pat, text):
            hits.append({"类别": cat, "词": re.search(pat, text).group(0), "说明": note})
    for w in _ABSOLUTE_EXTRA:
        m = _variant_pattern(w).search(text)
        if m:
            hits.append({"类别": "绝对化/违规用语", "词": w, "命中文本": m.group(0)})
    return {"结论": "通过" if not hits else "需改写", "命中": hits}


def run_factcheck(state, product: dict, facts: list[str], copy: dict, image_plan: list[dict]) -> dict:
    text = " ".join(
        [copy.get("标题", ""), copy.get("导语", ""), copy.get("正文", ""), copy.get("行动引导", "")]
    )
    product_check = check_product_facts(product, facts)
    image_check = check_images(image_plan)
    compliance = check_compliance(text)

    pending: list[str] = []
    other_models = _mentioned_other_models(text, product)
    if other_models:
        compliance = {
            "结论": "需改写",
            "命中": compliance["命中"] + [{"类别": "型号混淆", "词": m, "说明": "文案出现非主推型号，需核对"} for m in other_models],
        }
        pending.append(f"文案中疑似出现非主推型号：{'、'.join(other_models)}，请核对是否应替换为 {product.get('name')}")
    for it in product_check["逐项"]:
        if it["结论"] == "待确认":
            pending.append(f"事实待确认：{it['事实']}（{it['说明']}）")
    for it in image_check["逐项"]:
        if it["结论"].startswith("待确认"):
            pending.append(f"图片来源待核对：{it['图片']}（{it['型号']}）")

    return {
        "产品事实": product_check,
        "图片型号": image_check,
        "合规": compliance,
        "待确认信息": pending,
        "_来源": "规则核验（对照官方知识库原文）",
    }
