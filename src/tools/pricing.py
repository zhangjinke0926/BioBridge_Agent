"""确定性价格计算工具（四级价格规则）。

为什么不交给大模型算：
- 大模型心算价格几乎不可能稳定达到 95% 准确率；
- 这里全部由规则表 + 代码计算，可解释、可测试，准确率接近 100%。

最优解逻辑：把"国补 / 店补 / 教育优惠 / 以旧换新"的所有合法组合枚举一遍，
取"到手价最低"的那一组，并说明每一项省了多少、哪些被排除、为什么。
规则全部来自 config/pricing_rules.json，改数值不用改代码。
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

from src.config_loader import get_sku, load_pricing_rules


def _amount_of(rule: dict, base: float) -> float:
    if rule.get("type") == "fixed":
        return float(rule.get("amount", 0))
    return round(base * float(rule.get("rate", 0)))


def _store_amount(channel: dict, base: float) -> float:
    ss = channel.get("store_subsidy", {})
    if ss.get("type") == "fixed":
        return float(ss.get("amount", 0))
    return round(base * float(ss.get("rate", 0)))


def _is_valid_combo(combo: tuple[dict, ...]) -> bool:
    """国补是基础层；与国补同用时，其他优惠必须标记"可与国补叠加"。"""
    keys = {it["key"] for it in combo}
    if "national" in keys:
        for it in combo:
            if it["key"] != "national" and not it["stack_national"]:
                return False
    return True


def compute_quote(
    sku_id: str,
    channel_key: str = "offline_store",
    *,
    edu_eligible: bool = False,
    has_old_device: bool = False,
    trade_in_value: float = 0.0,
    rules: dict | None = None,
) -> dict[str, Any]:
    """计算某机型在某渠道、给定条件下的【最优到手价】，并给出完整解释。"""
    rules = rules or load_pricing_rules()
    sku = get_sku(sku_id)
    if sku is None:
        raise ValueError(f"找不到机型 SKU：{sku_id}，请检查 config/products.json")

    channels = rules.get("channels", {})
    if channel_key not in channels:
        raise ValueError(f"未知渠道：{channel_key}")
    channel = channels[channel_key]

    base = float(sku["list_price"])
    national = rules["national_subsidy"]
    edu = rules["education_discount"]
    trade = rules["trade_in"]

    items: list[dict] = []

    if national.get("enabled"):
        amt = min(_amount_of(national, base), float(national.get("cap", 10**9)))
        items.append(
            {
                "key": "national",
                "label": national["name"],
                "amount": round(amt),
                "stack_national": True,
                "eligible": True,
            }
        )

    items.append(
        {
            "key": "store",
            "label": f"{channel['name']}店补",
            "amount": round(_store_amount(channel, base)),
            "stack_national": bool(channel.get("can_stack_with_national")),
            "eligible": True,
        }
    )

    items.append(
        {
            "key": "edu",
            "label": edu["name"],
            "amount": round(_amount_of(edu, base)),
            "stack_national": bool(edu.get("can_stack_with_national")),
            "eligible": bool(edu_eligible),
        }
    )

    trade_amount = _amount_of(trade, base) + float(trade_in_value or 0)
    items.append(
        {
            "key": "tradein",
            "label": trade["name"],
            "amount": round(trade_amount),
            "stack_national": bool(trade.get("can_stack_with_national")),
            "eligible": bool(has_old_device),
        }
    )

    eligible_items = [it for it in items if it["eligible"]]
    best_total = -1.0
    best_combo: tuple[dict, ...] = ()
    for r in range(len(eligible_items) + 1):
        for combo in combinations(eligible_items, r):
            if not _is_valid_combo(combo):
                continue
            total = sum(it["amount"] for it in combo)
            if total > best_total:
                best_total = total
                best_combo = combo

    if best_total < 0:
        best_total, best_combo = 0.0, ()

    total_saved = round(best_total)
    final_price = round(max(0.0, base - total_saved))
    applied_keys = {it["key"] for it in best_combo}

    excluded = []
    for it in items:
        if it["key"] in applied_keys:
            continue
        if not it["eligible"]:
            reason = "不满足享受条件（教育优惠需身份验证 / 以旧换新需有旧机）"
        elif "national" in applied_keys and not it["stack_national"]:
            reason = "与国补互斥，不能同时享受"
        else:
            reason = "单独或换一种组合使用，省下的钱更少，不是当前最优解"
        excluded.append({"label": it["label"], "amount": it["amount"], "reason": reason})

    applied = [
        {"label": it["label"], "amount": it["amount"]} for it in best_combo
    ]

    competitor = None
    if sku.get("competitor_name") and sku.get("competitor_price"):
        competitor = {
            "name": sku["competitor_name"],
            "price": sku["competitor_price"],
            "diff": round(float(sku["competitor_price"]) - final_price),
        }

    parts = "、".join(f"{a['label']} ¥{a['amount']}" for a in applied) or "无可用优惠"
    explanation = (
        f"{sku['product_name']}（{sku['spec']}）指导价 ¥{round(base)}，"
        f"在「{channel['name']}」当前条件下的最优到手价是 ¥{final_price}，"
        f"共省 ¥{total_saved}（{parts}）。"
    )
    if excluded:
        explanation += "未采用：" + "；".join(f"{e['label']}——{e['reason']}" for e in excluded) + "。"
    if competitor:
        direction = "低" if competitor["diff"] >= 0 else "高"
        explanation += (
            f"对比 {competitor['name']}（¥{competitor['price']}），"
            f"本机到手价{direction} ¥{abs(competitor['diff'])}。"
        )

    return {
        "sku_id": sku_id,
        "product_name": sku["product_name"],
        "spec": sku["spec"],
        "list_price": round(base),
        "channel": channel_key,
        "channel_name": channel["name"],
        "final_price": final_price,
        "total_saved": total_saved,
        "applied": applied,
        "excluded": excluded,
        "competitor": competitor,
        "inputs": {
            "edu_eligible": bool(edu_eligible),
            "has_old_device": bool(has_old_device),
            "trade_in_value": float(trade_in_value or 0),
        },
        "explanation": explanation,
    }


def format_quote(result: dict[str, Any]) -> str:
    """把计算结果排版成给店员/客户看的文字。"""
    lines = [
        f"机型：{result['product_name']}（{result['spec']}）",
        f"渠道：{result['channel_name']}",
        f"指导价：¥{result['list_price']}",
    ]
    for a in result["applied"]:
        lines.append(f"  - 省 {a['label']}：¥{a['amount']}")
    if result["excluded"]:
        for e in result["excluded"]:
            lines.append(f"  - 未用 {e['label']}（¥{e['amount']}）：{e['reason']}")
    lines.append(f"最优到手价：¥{result['final_price']}（共省 ¥{result['total_saved']}）")
    if result.get("competitor"):
        c = result["competitor"]
        lines.append(f"竞品对照：{c['name']} ¥{c['price']}，价差 ¥{abs(c['diff'])}")
    return "\n".join(lines)
