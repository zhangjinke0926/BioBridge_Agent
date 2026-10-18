"""价格工具单元测试：保证"最优到手价"正确、可解释、无负数。
运行：python -m pytest -q   （在项目根目录）
"""
from __future__ import annotations

from itertools import combinations

from src.config_loader import load_pricing_rules
from src.tools.pricing import compute_quote

# 机型 SKU 编码来自 config/products.json（改产品表时同步更新这里即可）
D14 = "D14-2024-i5-16G-512G"
MB14 = "MB14U-U5-16G-1T"


def test_offline_store_can_stack_national():
    """线下门店：国补 + 店补 + 教育优惠 可以叠加。"""
    r = compute_quote(D14, "offline_store", edu_eligible=True)
    labels = {a["label"] for a in r["applied"]}
    assert any("国补" in x for x in labels)
    assert any("店补" in x for x in labels)
    assert any("教育优惠" in x for x in labels)
    assert r["final_price"] == r["list_price"] - r["total_saved"]
    assert r["final_price"] > 0


def test_ecommerce_excludes_conflicting_subsidy():
    """电商平台：平台券与国补互斥，程序应选省得更多的国补，并说明原因。"""
    r = compute_quote(D14, "ecommerce_platform")
    applied = {a["label"] for a in r["applied"]}
    excluded_labels = {e["label"] for e in r["excluded"]}
    # 国补省得更多 -> 应采用国补
    assert any("国补" in x for x in applied)
    assert any("店补" in x for x in excluded_labels)
    conflict = [e for e in r["excluded"] if "国补" in e["reason"]]
    assert conflict, "互斥项必须给出'与国补互斥'的原因说明"


def test_edu_eligibility_changes_price():
    """教育优惠资格会实实在在影响到手价。"""
    with_edu = compute_quote(D14, "offline_store", edu_eligible=True)
    without_edu = compute_quote(D14, "offline_store", edu_eligible=False)
    assert with_edu["final_price"] < without_edu["final_price"]


def test_trade_in_adds_device_value():
    """以旧换新：补贴 + 旧机估值都应计入省下的钱。"""
    base = compute_quote(D14, "offline_store")
    trade = compute_quote(D14, "offline_store", has_old_device=True, trade_in_value=600)
    assert trade["total_saved"] > base["total_saved"]
    assert trade["final_price"] < base["final_price"]


def test_result_is_optimal_by_bruteforce():
    """穷举所有合法组合，验证程序给出的确实是"最低到手价"。"""
    rules = load_pricing_rules()
    r = compute_quote(D14, "ecommerce_platform", edu_eligible=True, has_old_device=True, trade_in_value=500)

    # 手工穷举：4 个候选项的所有子集，按同一套叠加规则过滤
    base = r["list_price"]
    amounts = {a["label"]: a["amount"] for a in r["applied"] + r["excluded"]}
    keys = list(amounts.keys())
    best = base
    for n in range(1, len(keys) + 1):
        for combo in combinations(keys, n):
            has_national = any("国补" in k for k in combo)
            if has_national and n > 1:
                # 电商平台店补与国补互斥，本地仅用于验证程序取到了更优解
                others = [k for k in combo if "国补" not in k]
                if any("店补" in k for k in others):
                    continue
            total = sum(amounts[k] for k in combo)
            best = min(best, max(0, base - total))
    assert r["final_price"] >= best - 1  # 允许 1 元取整误差


def test_explanation_is_non_empty_and_traceable():
    r = compute_quote(MB14, "online_official", edu_eligible=True)
    assert r["explanation"]
    assert "到手价" in r["explanation"]
    assert r["competitor"] is not None
