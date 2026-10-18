"""四个 Agent 共用的文本小工具：分句、取证、预算解析、字段抽取。"""
from __future__ import annotations

import re

IDENTITY_RULES: list[tuple[str, list[str]]] = [
    ("学生", ["学生", "大学生", "考研", "读研", "研究生", "上课", "宿舍", "论文", "校园", "大一新生", "大二", "大三", "大四", "同学", "学费", "高中生", "中学生", "毕业设计", "毕设"]),
    ("创作者", ["设计", "剪辑", "修图", "摄影", "画图", "绘画", "创作", "渲染", "up主", "UP主", "自媒体", "做视频", "博主", "插画", "后期", "调色"]),
    ("商务人士", ["商务", "老板", "经理", "总监", "出差", "谈客户", "总裁", "高管", "创业", "负责人", "主管", "部门", "见客户", "跑市场"]),
    ("职场新人", ["职场", "上班", "办公", "入职", "工作", "公司", "工位", "开会", "周报", "通勤", "实习", "老师", "教师", "医生", "护士", "会计", "财务", "公务员", "自由职业", "事业单位", "国企", "外企"]),
    ("家庭用户", ["给孩子", "给我妈", "给我爸", "给父母", "给爸妈", "给老人", "老人", "爸妈", "父母", "家里用", "家用", "退休", "孩子用", "全家", "老伴"]),
]

# 显式身份词：客户自己说出的职业/身份，优先级高于泛化关键词，
# 避免"写论文的老师"被判成学生这类误判。
STRONG_IDENTITY: list[tuple[str, list[str]]] = [
    ("职场新人", ["老师", "教师", "医生", "大夫", "护士", "会计", "财务", "公务员", "自由职业", "律师"]),
    ("商务人士", ["老板", "主管", "经理", "总监", "创业者", "负责人", "合伙人"]),
    ("学生", ["大学生", "大一新生", "大二", "大三", "大四", "研究生", "考研", "高中生", "中学生", "应届生"]),
    ("创作者", ["设计师", "剪辑师", "博主", "自媒体", "插画师", "摄影师", "UP主", "up主"]),
]

SCENARIO_RULES: list[tuple[str, list[str]]] = [
    ("论文写作", ["论文", "文献", "查资料", "毕设", "毕业设计"]),
    ("课堂笔记与学习", ["上课", "课堂", "记笔记", "课件", "板书", "复习", "网课"]),
    ("多设备协同", ["手机", "平板", "传文件", "多屏", "协同", "数据线", "互传", "一起用", "华为分享"]),
    ("移动办公", ["办公", "出差", "通勤", "会议", "演示", "ppt", "PPT", "报表", "周报", "投屏", "客户"]),
    ("轻度创作", ["剪辑", "修图", "设计", "创作", "渲染", "视频", "海报", "调色"]),
    ("编程与开发", ["编程", "代码", "开发", "程序", "写代码", "程序员", "跑代码"]),
    ("报表与数据", ["报表", "数据", "做账", "记账", "Excel", "表格", "财务"]),
    ("影音娱乐", ["看剧", "追剧", "游戏", "听歌", "电影"]),
]

OBJECTION_RULES: list[tuple[str, list[str]]] = [
    ("怕买贵", ["便宜", "价格", "贵", "划算", "性价比", "优惠", "省钱", "学生党", "买不起"]),
    ("怕性能不够", ["卡", "性能", "跑不动", "带不动", "剪视频", "处理器", "配置", "能不能跑"]),
    ("怕生态不兼容", ["苹果", "mac", "Mac", "兼容", "传不了", "连不上", "系统", "安卓", "鸿蒙", "文件怎么"]),
    ("怕用不久 / 售后", ["保修", "售后", "几年", "耐用", "坏了", "质量", "返修"]),
    ("怕续航短", ["续航", "电池", "充电", "插座", "没电", "带充电器"]),
    ("怕屏幕色准不够", ["色准", "色域", "屏幕", "OLED", "显示", "色差", "偏色"]),
    ("怕被推销 / 不信任", ["再看看", "考虑一下", "不用了", "再想想", "不需要", "随便看看"]),
]

# 出现这些"强调词"的句子，权重更高（客户自己点名的顾虑最可信）
EMPHASIS_WORDS = ["最在意", "最担心", "最怕", "很怕", "就怕", "最看重", "主要是", "特别怕"]

URGENCY_HIGH = ["今天", "现在", "马上", "立刻", "急", "限时", "这周", "明天", "当场", "就要", "尽快"]
URGENCY_LOW = ["再看看", "考虑", "以后", "不急", "下个月", "再说", "慢慢来"]

CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN = "一两二三四五六七八九"


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?\n；;，,]+", text or "")
    return [p.strip() for p in parts if p.strip()]


def match_evidence(text: str, keywords: list[str]) -> list[str]:
    """找出原话里命中关键词的句子，作为判断依据（能回溯，不凭空编造）。"""
    hits = []
    for s in split_sentences(text):
        if any(k in s for k in keywords):
            if s not in hits:
                hits.append(s)
    return hits


def first_match(text: str, rules: list[tuple[str, list[str]]]) -> str:
    for label, kws in rules:
        if any(k in text for k in kws):
            return label
    return ""


def best_identity(text: str) -> tuple[str, list[str]]:
    """先认显式身份词（老师/老板/研究生…），再退回关键词首次命中。返回 (身份, 依据)。"""
    for label, kws in STRONG_IDENTITY:
        ev = match_evidence(text, kws)
        if ev:
            return label, ev
    label = first_match(text, IDENTITY_RULES) or "未明确"
    kws = dict(IDENTITY_RULES).get(label, [])
    return label, match_evidence(text, kws)


def all_matches(text: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    out = []
    for label, kws in rules:
        if any(k in text for k in kws):
            out.append(label)
    return out


def best_objection(text: str) -> tuple[str, list[str]]:
    """挑出"真正怕什么"：命中句子越多越可疑；含强调词（最在意/最怕…）的句子权重更高。"""
    best_label, best_score, best_ev = "未明确", 0, []
    for label, kws in OBJECTION_RULES:
        ev = match_evidence(text, kws)
        score = len(ev)
        for s in ev:
            if any(w in s for w in EMPHASIS_WORDS):
                score += 2
        if score > best_score:
            best_label, best_score, best_ev = label, score, ev
    return best_label, best_ev


def extract_budget(text: str) -> tuple[float | None, float | None, str]:
    """返回 (预算下限, 预算上限, 依据原话)。"""
    # 预算充足 / 不差钱 / 价格不是问题 → 直接归为高预算
    if re.search(r"(预算|价格)[^\d]{0,4}(充足|不差钱|不是问题|没上限|好说|都好)", text):
        return 10000.0, None, "（客户表示预算充足）"

    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(\d)?", text)
    if m:
        base = float(m.group(1)) * 10000 + (float(m.group(2)) * 1000 if m.group(2) else 0.0)
        if "以上" in text or "起" in text:
            return base, None, m.group(0)
        return base * 0.7, base, m.group(0)

    m = re.search(r"([%s])\s*万\s*([%s])?" % (_CN, _CN), text)
    if m:
        base = CN_NUM.get(m.group(1), 1) * 10000 + (CN_NUM.get(m.group(2), 0) * 1000 if m.group(2) else 0)
        if "以上" in text or "起" in text:
            return float(base), None, m.group(0)
        return base * 0.7, float(base), m.group(0)

    m = re.search(r"(\d{3,5})\s*[-~～到至]\s*(\d{3,5})", text)
    if m:
        return float(m.group(1)), float(m.group(2)), m.group(0)
    m = re.search(r"预算[^\d]{0,6}(\d{3,5})", text)
    if m:
        v = float(m.group(1))
        return v * 0.8, v, m.group(0)
    m = re.search(r"(\d{3,5})\s*(?:元|块|以内|以下|左右|上下)", text)
    if m:
        v = float(m.group(1))
        return v * 0.8, v, m.group(0)
    m = re.search(r"(\d(?:\.\d)?)\s*[kK千]", text)
    if m:
        v = float(m.group(1)) * 1000
        return v * 0.8, v, m.group(0)
    m = re.search(r"([三四五六七八九])\s*千", text)
    if m:
        v = CN_NUM[m.group(1)] * 1000
        if "以上" in text or "起" in text:
            return v, None, m.group(0)  # 只说下限
        return v * 0.8, v, m.group(0)
    return None, None, ""


def budget_label(budget_min: float | None, budget_max: float | None) -> str:
    if budget_max is None and budget_min is None:
        return "未明确"
    if budget_min is not None and budget_max is None:
        return "7000以上" if budget_min >= 7000 else "未明确"
    upper = budget_max if budget_max is not None else 0
    if upper <= 5000:
        return "4000-5000"
    if upper <= 7000:
        return "5000-7000"
    return "7000以上"


def extract_field(text: str, prefix: str) -> str:
    """从知识库段落里抽出 "场景切片：xxx" 这类字段值。"""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line[len(prefix):].strip("：: ").strip()
    return ""
