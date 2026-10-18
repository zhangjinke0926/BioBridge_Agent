"""ima 知识库接入层（工具）：把赛题要求的 4 个 ima OpenAPI 封装成统一方法。

设计目标：
- 有凭证（IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY）且官方 ima-skill 脚本存在时，走真实接口
  （node ima-skill/ima_api.cjs <interface> <json>）。
- 没有凭证或调用失败时，自动回退到本地已解压的官方知识库 _official_kb，保证【离线也能跑通全链路】。
- 无论线上线下，返回结构一致，并始终保留【资料标题 + 来源路径】，用于事实核验与可追溯。

赛题手册v4 第七节要点已内置：
  search_knowledge_base → get_knowledge_list（搜索为空时用它回退）→ search_knowledge → get_media_info
  搜索无结果不等于无权限：应按目录进入 P1-产品参数库，再读取具体型号的 article/产品事实。
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
from functools import lru_cache

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KB_ROOT = os.path.join(BASE_DIR, "_official_kb", "华为PC全板块深度知识库_v7")
KB_NAME = "任德耀新建华为PC知识库"
IMA_SKILL = os.path.join(BASE_DIR, "ima-skill", "ima_api.cjs")

# 本地兜底时参与全文检索的板块（P1 产品事实 / P2 卖点话术 / P6 营销素材 / P8 客户场景）
_SEARCH_PREFIXES = ("P1-产品参数库", "P2-卖点话术库", "P6-营销素材库", "P8-客户场景库")
_SKIP_DIRS = ("00-建库规范", "90-待审核", "99-历史归档")


# --------------------------------------------------------------------------- #
# 凭证与连通状态
# --------------------------------------------------------------------------- #
def credentials() -> tuple[str, str]:
    return (
        os.getenv("IMA_OPENAPI_CLIENTID", "").strip(),
        os.getenv("IMA_OPENAPI_APIKEY", "").strip(),
    )


def connection_status() -> dict:
    """给界面展示的连接状态；不返回任何密钥内容。"""
    cid, key = credentials()
    live = bool(cid and key and os.path.isfile(IMA_SKILL))
    return {
        "mode": "ima在线接口" if live else "本地官方知识库（离线兜底）",
        "kb_name": KB_NAME,
        "has_credentials": bool(cid and key),
        "skill_script": os.path.relpath(IMA_SKILL, BASE_DIR).replace("\\", "/"),
        "kb_root": os.path.relpath(KB_ROOT, BASE_DIR).replace("\\", "/"),
        "ready": os.path.isdir(KB_ROOT),
    }


def _call_live(interface: str, payload: dict) -> dict | None:
    """调用官方 ima-skill 脚本；任何异常都返回 None，交由本地兜底。"""
    cid, key = credentials()
    if not (cid and key and os.path.isfile(IMA_SKILL)):
        return None
    env = dict(os.environ, IMA_OPENAPI_CLIENTID=cid, IMA_OPENAPI_APIKEY=key)
    try:
        proc = subprocess.run(
            ["node", IMA_SKILL, interface, json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            cwd=BASE_DIR,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 本地知识库索引（全文检索兜底）
# --------------------------------------------------------------------------- #
def _bigrams(text: str) -> set[str]:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "")
    return {text[i : i + 2] for i in range(len(text) - 1)} if len(text) >= 2 else set()


@lru_cache(maxsize=1)
def _local_index() -> list[dict]:
    """扫描本地官方知识库，返回 [{"rel","title","text"}]。"""
    docs: list[dict] = []
    if not os.path.isdir(KB_ROOT):
        return docs
    for root, dirs, files in os.walk(KB_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        rel_root = os.path.relpath(root, KB_ROOT).replace("\\", "/")
        if not rel_root.startswith(_SEARCH_PREFIXES):
            continue
        for name in files:
            if not name.lower().endswith((".md", ".txt")):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > 400_000:
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                continue
            rel = os.path.relpath(path, KB_ROOT).replace("\\", "/")
            m = re.search(r"^#\s*(.+)$", raw, re.M)
            title = m.group(1).strip() if m else name
            docs.append({"rel": rel, "title": title, "text": raw})
    return docs


def _local_search(query: str, k: int, prefix: str | None = None) -> list[dict]:
    q = _bigrams(query)
    scored = []
    for doc in _local_index():
        if prefix and not doc["rel"].startswith(prefix):
            continue
        score = len(q & _bigrams(doc["title"] + doc["text"][:6000]))
        if doc["title"] and doc["title"] in query:
            score += 8
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"title": d["title"], "path": d["rel"], "kb_name": KB_NAME, "text": d["text"]}
        for _, d in scored[:k]
    ]


# --------------------------------------------------------------------------- #
# 4 个 ima 接口（线上优先，离线兜底）
# --------------------------------------------------------------------------- #
def search_knowledge_base(query: str, limit: int = 20) -> dict:
    """A. 按名称查找知识库，返回 kb_id / kb_name。"""
    live = _call_live("openapi/wiki/v1/search_knowledge_base", {"query": query, "cursor": "", "limit": limit})
    if isinstance(live, dict):
        info = (live.get("data") or {}).get("info_list") or []
        if info:
            first = info[0]
            kb_id = first.get("kb_id") or first.get("knowledge_base_id")
            if kb_id:
                return {"kb_id": kb_id, "kb_name": first.get("kb_name", query), "source": "ima在线接口"}
    return {"kb_id": "local-official-kb", "kb_name": KB_NAME, "source": "本地官方知识库（离线兜底）"}


def get_knowledge_list(kb_id: str, path: str = "P1-产品参数库", limit: int = 100) -> list[dict]:
    """B. 浏览目录；搜索为空时回退用。返回 [{name, type, path}]。"""
    live = _call_live("openapi/wiki/v1/get_knowledge_list", {"knowledge_base_id": kb_id, "cursor": "", "limit": limit})
    if isinstance(live, dict):
        items = (live.get("data") or {}).get("list") or []
        if items:
            return [
                {"name": it.get("name") or it.get("title"), "type": it.get("type", "doc"), "path": it.get("path", "")}
                for it in items
            ]
    out: list[dict] = []
    start = os.path.join(KB_ROOT, path)
    if os.path.isdir(start):
        for name in sorted(os.listdir(start)):
            full = os.path.join(start, name)
            out.append(
                {
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "doc",
                    "path": os.path.relpath(full, KB_ROOT).replace("\\", "/"),
                }
            )
    return out


def search_knowledge(query: str, k: int = 5, prefix: str | None = None) -> list[dict]:
    """C. 按关键词/型号搜索资料；返回 [{title, path, kb_name, text}]。

    线上接口 info_list 只给 media_id/title/highlight_content，没有正文全文；
    只有命中了 highlight_content（说明内容本身匹配到了关键词）才采信线上结果，
    否则（纯文件夹标题匹配、无可展示正文）回退本地检索，避免拿空文本当证据。
    """
    kb = search_knowledge_base(KB_NAME)
    kb_id = kb.get("kb_id")
    live = None
    if kb.get("source") == "ima在线接口" and kb_id:
        live = _call_live(
            "openapi/wiki/v1/search_knowledge",
            {"query": query, "knowledge_base_id": kb_id, "cursor": "", "limit": k},
        )
    if isinstance(live, dict):
        items = (live.get("data") or {}).get("info_list") or []
        usable = [it for it in items if it.get("highlight_content")]
        if usable:
            return [
                {
                    "title": it.get("title", ""),
                    "path": it.get("media_id", ""),
                    "kb_name": KB_NAME,
                    "text": it.get("highlight_content", ""),
                }
                for it in usable[:k]
            ]
    return _local_search(query, k, prefix)


def get_media_info(media_id: str) -> dict:
    """D. 按 media_id 获取命中资料的访问链接（URL 类型）或笔记 ID；不是本地路径。"""
    live = _call_live("openapi/wiki/v1/get_media_info", {"media_id": media_id})
    if isinstance(live, dict) and live.get("code") == 0:
        data = live.get("data") or {}
        url = (data.get("url_info") or {}).get("url", "")
        if url:
            return {"title": os.path.basename(media_id), "path": media_id, "text": "", "url": url}
    return {"title": os.path.basename(media_id), "path": media_id, "text": "", "url": ""}


# --------------------------------------------------------------------------- #
# 面向业务的高层方法：按型号取「产品事实 + 卖点与限制 + 图片索引」
# --------------------------------------------------------------------------- #
def kb_dir(kb_path: str) -> str:
    return os.path.join(KB_ROOT, kb_path.replace("/", os.sep))


def _read(rel_or_abs: str) -> str:
    full = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(KB_ROOT, rel_or_abs.replace("/", os.sep))
    if not os.path.isfile(full):
        return ""
    with open(full, "r", encoding="utf-8-sig") as f:
        return f.read()


def parse_capabilities(selling_text: str) -> list[dict]:
    """从《卖点与限制.md》抽取「N个沟通角度」的可用结论 / 支撑事实 / 表达边界。"""
    caps: list[dict] = []
    # 按 ### 编号 切分角度块
    blocks = re.split(r"\n###\s*\d+\.\s*", selling_text)
    for block in blocks[1:]:
        lines = block.split("\n")
        angle = lines[0].strip()
        def _grab(marker: str, next_marker: str) -> str:
            m = re.search(
                r"\*\*" + marker + r"\*\*\s*\n+(.+?)\n+\*\*(?:" + next_marker + r")\*\*",
                block,
                re.S,
            )
            return m.group(1).strip() if m else ""

        def _grab_tail(marker: str) -> str:
            m = re.search(r"\*\*" + marker + r"\*\*\s*\n+(.+)$", block, re.S)
            return m.group(1).strip() if m else ""

        caps.append(
            {
                "角度": angle,
                "可用结论": _grab("可用结论", "支撑事实"),
                "支撑事实": _grab("支撑事实", "表达边界"),
                "表达边界": _grab_tail("表达边界"),
            }
        )
    return caps


def useful_tasks(selling_text: str) -> list[str]:
    m = re.search(r"##\s*适合进入候选清单的任务\s*\n+(.+?)\n\n", selling_text, re.S)
    if not m:
        return []
    return [ln.strip("- ").strip() for ln in m.group(1).splitlines() if ln.strip().startswith("-")]


def must_ask(selling_text: str) -> list[str]:
    m = re.search(r"##\s*发布或销售前必须追问\s*\n+(.+?)\n\n", selling_text, re.S)
    if not m:
        return []
    return [ln.strip("- ").strip() for ln in m.group(1).splitlines() if ln.strip().startswith("-")]


def _parse_image_csv(text: str) -> list[dict]:
    if not text.strip():
        return []
    rows = list(csv.DictReader(text.splitlines()))
    out = []
    for r in rows:
        bad = {"文件名", "画面说明", "产品型号", "来源页面", "页面来源", "官网图片说明", "建议用途", "原始图片URL", "使用提示"}
        norm = {}
        name = r.get("文件名", "").strip()
        if not name:
            continue
        norm = {
            "文件名": name,
            "型号": (r.get("产品型号") or "").strip(),
            "来源页面": (r.get("来源页面") or r.get("页面来源") or "").strip(),
            "图片URL": (r.get("原始图片URL") or "").strip(),
            "说明": (r.get("官网图片说明") or r.get("画面说明") or "").strip(),
            "建议用途": (r.get("建议用途") or r.get("使用提示") or "").strip(),
        }
        _ = bad
        out.append(norm)
    return out


@lru_cache(maxsize=32)
def get_product_knowledge(kb_path: str) -> dict:
    """读取某型号目录下的产品事实、卖点与限制、图片索引。全部保留来源路径。"""
    directory = kb_dir(kb_path)
    facts_rel = f"{kb_path}/产品事实.md"
    selling_rel = f"{kb_path}/卖点与限制.md"
    images_rel = f"{kb_path}/图片索引.csv"
    facts_text = _read(facts_rel)
    selling_text = _read(selling_rel)
    images = _parse_image_csv(_read(images_rel))

    facts_title = ""
    m = re.search(r"^#\s*(.+)$", facts_text, re.M)
    if m:
        facts_title = m.group(1).strip()
    selling_title = ""
    m = re.search(r"^#\s*(.+)$", selling_text, re.M)
    if m:
        selling_title = m.group(1).strip()

    return {
        "kb_path": kb_path,
        "exists": os.path.isdir(directory),
        "facts_text": facts_text,
        "selling_text": selling_text,
        "facts_title": facts_title or os.path.basename(kb_path),
        "selling_title": selling_title or f"{os.path.basename(kb_path)}｜卖点与限制",
        "capabilities": parse_capabilities(selling_text),
        "useful_tasks": useful_tasks(selling_text),
        "must_ask": must_ask(selling_text),
        "images": images,
        "sources": [
            {"标题": facts_title or os.path.basename(kb_path), "路径": facts_rel},
            {"标题": selling_title, "路径": selling_rel},
            {"标题": f"{os.path.basename(kb_path)} 图片索引", "路径": images_rel},
        ],
    }


@lru_cache(maxsize=1)
def general_images() -> list[dict]:
    """P6 营销素材库的通用商城素材，作为型号图片不足时的场景示意图兜底。"""
    base = "P6-营销素材库/04-图片/02-华为商城电脑专区素材/图片索引.csv"
    rows = _parse_image_csv(_read(base))
    for r in rows:
        r.setdefault("型号", "")
        r["来源页面"] = r.get("来源页面") or "P6-营销素材库/04-图片/02-华为商城电脑专区素材"
    return rows


def search_evidence(query: str, k: int = 5, prefix: str | None = None) -> list[dict]:
    """通用检索：先按关键词搜，搜索为空时用目录回退（对应赛题 Step B 回退规则）。"""
    hits = search_knowledge(query, k=k, prefix=prefix)
    if hits:
        return hits
    listing = get_knowledge_list("local-official-kb", path="P1-产品参数库", limit=50)
    names = "、".join(item["name"] for item in listing[:8])
    return [
        {
            "title": "目录回退：P1-产品参数库",
            "path": "P1-产品参数库",
            "kb_name": KB_NAME,
            "text": f"关键词未命中，按目录回退查看 P1-产品参数库：{names}",
        }
    ]
