"""知识库检索：从 knowledge/ 下的 Markdown 里按关键词找最相关的段落。

先用"字词重合度"做检索，简单、可靠、零依赖；
复赛要升级成向量检索时，只替换本文件即可，调用方不用改。
"""
from __future__ import annotations

import os
import re

from src.config_loader import KNOWLEDGE_DIR


def _bigrams(text: str) -> set[str]:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return {text[i : i + 2] for i in range(len(text) - 1)} if len(text) >= 2 else set()


def _split_chunks(file_path: str) -> list[dict]:
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    chunks = []
    name = os.path.basename(file_path)
    # 按二级标题切块；没有标题的按空行切
    blocks = re.split(r"\n(?=##\s)", raw)
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("# ") and len(block) < 40:
            continue
        m = re.search(r"##\s*(.+)", block)
        title = m.group(1).strip() if m else name
        chunks.append({"source": name, "title": title, "text": block})
    return chunks


def load_all_chunks() -> list[dict]:
    chunks: list[dict] = []
    if not os.path.isdir(KNOWLEDGE_DIR):
        return chunks
    for name in sorted(os.listdir(KNOWLEDGE_DIR)):
        if name.lower().endswith(".md"):
            chunks.extend(_split_chunks(os.path.join(KNOWLEDGE_DIR, name)))
    return chunks


def search(query: str, k: int = 3, source: str | None = None) -> list[dict]:
    """返回最相关的 k 个段落。source 可限定只查某个文件（如 selling_points.md）。"""
    q = _bigrams(query)
    scored = []
    for ch in load_all_chunks():
        if source and ch["source"] != source:
            continue
        score = len(q & _bigrams(ch["title"] + ch["text"]))
        if ch["title"] and ch["title"] in query:
            score += 5  # 标题直接被提到，加权
        if score > 0:
            scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


def search_text(query: str, k: int = 3, source: str | None = None) -> str:
    hits = search(query, k=k, source=source)
    if not hits:
        return ""
    return "\n\n".join(f"【{h['title']}】\n{h['text']}" for h in hits)


def load_banned_words() -> list[str]:
    path = os.path.join(KNOWLEDGE_DIR, "banned_words.txt")
    words: list[str] = []
    if not os.path.isfile(path):
        return words
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
    return words


def scan_banned(text: str) -> list[str]:
    """扫描文案里是否命中禁用词，返回命中列表。"""
    return [w for w in load_banned_words() if w in text]
