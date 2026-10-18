"""读取 config/ 下的可编辑业务数据（产品、价格规则）。改文件即可，不用改代码。"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_products() -> list[dict]:
    return _load_json(os.path.join(CONFIG_DIR, "products.json"))["products"]


@lru_cache(maxsize=1)
def load_pricing_rules() -> dict:
    return _load_json(os.path.join(CONFIG_DIR, "pricing_rules.json"))


@lru_cache(maxsize=1)
def load_platforms() -> list[dict]:
    """平台规则：公众号 / 小红书 / 门店朋友圈 / 门店海报。"""
    return _load_json(os.path.join(CONFIG_DIR, "platforms.json"))["platforms"]


@lru_cache(maxsize=1)
def load_scenes() -> list[dict]:
    """业务场景：开学季 / 职场办公 / 内容创作 / 家庭换新 / 企业采购 / 门店到访 / 新品首发 / 节日营销。"""
    return _load_json(os.path.join(CONFIG_DIR, "scenes.json"))["scenes"]


def platform_keys() -> list[str]:
    return [p["key"] for p in load_platforms()]


def get_platform(key: str) -> dict:
    for p in load_platforms():
        if p["key"] == key:
            return p
    return load_platforms()[0]


def get_scene(key: str) -> dict | None:
    for s in load_scenes():
        if s["key"] == key:
            return s
    return None


def get_product(product_id: str) -> dict | None:
    """按产品 id 取整机（含 kb_path 与全部 SKU）。"""
    for p in load_products():
        if p["id"] == product_id:
            return p
    return None


def find_product(query: str) -> dict | None:
    """按产品 id 或产品名（模糊）找整机，供"评委会指定产品"。"""
    if not query:
        return None
    q = query.strip()
    for p in load_products():
        if q == p["id"] or q == p.get("name"):
            return p
    for p in load_products():
        if q in p.get("name", "") or q in p["id"]:
            return p
    return None


def pick_product_for_scene(scene: dict, audience: str = "") -> dict:
    """未指定产品时，按业务场景的推荐优先级 + 目标人群挑一款。"""
    products = load_products()
    if not products:
        raise ValueError("config/products.json 里没有任何机型，请先补充数据。")
    pref = scene.get("preferred_products", []) if scene else []
    # 优先：推荐机型里能匹配目标人群的
    if audience:
        for pid in pref:
            p = get_product(pid)
            if p and audience in p.get("target_users", []):
                return p
    if pref:
        for pid in pref:
            p = get_product(pid)
            if p:
                return p
    if audience:
        matched = [p for p in products if audience in p.get("target_users", [])]
        if matched:
            return matched[0]
    return products[0]


def product_brief(p: dict) -> dict:
    """整机 → 精简（含首个 SKU 的规格与指导价）。"""
    sku = (p.get("skus") or [{}])[0]
    return {
        "id": p["id"],
        "name": p["name"],
        "kb_path": p.get("kb_path", ""),
        "spec": sku.get("spec", ""),
        "sku": sku.get("sku", ""),
        "selling_points": sku.get("selling_points", []),
        "positioning": p.get("positioning", ""),
        "target_users": p.get("target_users", []),
    }


def list_skus() -> list[dict]:
    """把 products.json 摊平成一行一个 SKU，方便检索与计算。"""
    rows: list[dict] = []
    for p in load_products():
        for sku in p.get("skus", []):
            rows.append(
                {
                    "product_id": p["id"],
                    "product_name": p["name"],
                    "series": p.get("series", ""),
                    "positioning": p.get("positioning", ""),
                    "target_users": p.get("target_users", []),
                    "competitor_name": p.get("competitor_name"),
                    "competitor_price": p.get("competitor_price"),
                    "sku": sku["sku"],
                    "spec": sku.get("spec", ""),
                    "list_price": sku["list_price"],
                    "selling_points": sku.get("selling_points", []),
                }
            )
    return rows


def get_sku(sku_id: str) -> dict | None:
    for row in list_skus():
        if row["sku"] == sku_id:
            return row
    return None


def list_products_brief() -> list[dict]:
    """给下拉框用的精简机型清单：[{"id","name","price"}]。"""
    out: list[dict] = []
    for p in load_products():
        first = (p.get("skus") or [{}])[0]
        out.append({"id": p["id"], "name": p["name"], "price": first.get("list_price")})
    return out


def find_sku(query: str) -> dict | None:
    """按 SKU 编码或产品 id 或产品名（模糊）找机型，供"评委会指定产品"使用。

    支持：精确 sku、精确 product_id、产品名包含关键词。
    """
    if not query:
        return None
    q = query.strip()
    rows = list_skus()
    for r in rows:
        if q == r["sku"] or q == r["product_id"]:
            return r
    for r in rows:
        if q in r["product_name"] or q in r["sku"]:
            return r
    return None


def pick_sku_for_budget(
    budget_min: float | None,
    budget_max: float | None,
    target_user: str = "",
) -> dict:
    """按预算区间 + 客户身份挑一个推荐机型；给不出预算时返回最便宜的一款。"""
    rows = list_skus()
    if not rows:
        raise ValueError("config/products.json 里没有任何机型，请先补充数据。")

    candidates = rows
    if budget_max:
        candidates = [r for r in candidates if r["list_price"] <= budget_max * 1.15]
    if budget_min:
        # 预算下限只用来排除"太便宜"的，避免过度降级推荐
        lower = [r for r in candidates if r["list_price"] >= budget_min * 0.75]
        if lower:
            candidates = lower
    if not candidates:
        candidates = rows

    if target_user:
        matched = [r for r in candidates if target_user in r.get("target_users", [])]
        if matched:
            candidates = matched

    return min(candidates, key=lambda r: r["list_price"])
