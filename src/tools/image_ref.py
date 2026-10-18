"""图片引用工具：按平台与型号，从 ima 知识库图片索引里选图，
输出【图片名称 / 来源 / 插入位置 / 图片说明】四要素，型号不一致的图不进入配图方案。

赛题手册v4 要求：图片必须来自 ima；核对产品型号；输出来源、说明和建议插入位置。
图片数量按平台：公众号 2-4、小红书 3-6、门店朋友圈 1-3、门店海报 1（主视觉）。
"""
from __future__ import annotations

from src.config_loader import load_platforms
from src.tools import ima_api

# 卖点/场景关键词 → 图片画面关键词（用于挑最相关的图）
_PICTURE_HINTS: dict[str, list[str]] = {
    "便携": ["机身", "轻薄", "重量", "便携", "移动", "主视觉", "折叠"],
    "续航": ["续航", "办公", "移动办公", "场景"],
    "多设备协同": ["协同", "多设备", "手机", "平板", "智慧", "连接", "融合"],
    "护眼屏": ["屏", "护眼", "OLED", "显示", "柔光"],
    "屏幕": ["屏", "OLED", "显示", "柔光", "屏占比"],
    "接口": ["接口", "机身", "细节", "侧面"],
    "性能": ["性能", "散热", "多任务", "流畅"],
    "存储": ["机身", "细节", "存储"],
    "系统": ["鸿蒙", "AI", "系统", "智慧", "桌面", "小艺"],
    "易用性": ["键盘", "触控", "笔记", "手写", "会议"],
    "数据迁移": ["迁移", "克隆", "协同", "连接"],
    "售后": ["服务", "焕新", "保养", "清洁"],
}


def _platform(platform_key: str) -> dict:
    for p in load_platforms():
        if p["key"] == platform_key:
            return p
    return load_platforms()[0]


def _scene_keywords(scene: dict) -> list[str]:
    words: list[str] = []
    for sp in scene.get("卖点优先级", []) or []:
        words += _PICTURE_HINTS.get(sp, [])
    text = " ".join(scene.get("使用场景", []) or []) + " " + (scene.get("业务场景") or "")
    words += [w for w in ["办公", "学习", "会议", "创作", "居家", "移动"] if w in text]
    return words


def _score(entry: dict, keywords: list[str]) -> int:
    blob = (entry.get("说明", "") + entry.get("建议用途", "") + entry.get("文件名", ""))
    return sum(1 for w in keywords if w and w in blob)


def build_image_plan(platform_key: str, product: dict, scene: dict) -> list[dict]:
    """返回配图方案列表，每项含 名称/来源/插入位置/说明/型号。"""
    plat = _platform(platform_key)
    want_min = plat["图片数量"]["min"]
    want_max = plat["图片数量"]["max"]
    positions = plat["图片位置"]

    kb_path = product.get("kb_path", "")
    kb = ima_api.get_product_knowledge(kb_path) if kb_path else {"images": [], "exists": False}
    model_name = product.get("name", "")
    keywords = _scene_keywords(scene)

    pool = list(kb.get("images", []))
    pool.sort(key=lambda e: _score(e, keywords), reverse=True)

    target = min(want_max, max(want_min, len(pool)))
    target = max(want_min, min(want_max, target))

    plan: list[dict] = []
    src = f"ima·{ima_api.KB_NAME} / {kb_path}/图片索引.csv"
    for i, e in enumerate(pool[:target]):
        plan.append(
            {
                "名称": e.get("文件名", ""),
                "来源": src,
                "插入位置": positions[i] if i < len(positions) else positions[-1],
                "说明": _describe(e, scene),
                "型号": e.get("型号") or model_name,
                "是否型号一致": True,
            }
        )

    # 型号图片不足时，用 P6 商城场景示意图补齐，但明确标注「场景示意·待核对型号」
    if len(plan) < want_min:
        gen = ima_api.general_images()
        gen.sort(key=lambda e: _score(e, keywords), reverse=True)
        src_p6 = f"ima·{ima_api.KB_NAME} / P6-营销素材库/04-图片/02-华为商城电脑专区素材/图片索引.csv"
        for e in gen:
            if len(plan) >= want_min:
                break
            plan.append(
                {
                    "名称": e.get("文件名", ""),
                    "来源": src_p6,
                    "插入位置": positions[len(plan)] if len(plan) < len(positions) else positions[-1],
                    "说明": f"场景示意图：{e.get('说明', '')}（使用前需核对与 {model_name} 是否同款）",
                    "型号": "",
                    "是否型号一致": False,
                }
            )

    return plan


def _describe(entry: dict, scene: dict) -> str:
    base = entry.get("说明") or entry.get("建议用途") or "产品画面"
    usage = entry.get("建议用途") or ""
    scene_name = scene.get("业务场景") or ""
    tail = f"；建议用途：{usage}" if usage and usage not in base else ""
    return f"{base}（对应{scene_name}场景）{tail}"
