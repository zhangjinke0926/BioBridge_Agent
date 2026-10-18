"""提示词加载器：把各 Agent 的系统提示词外置到 prompts/*.md，便于他人接手与迭代。

- prompts/<name>.md 存在时，用文件内容作为系统提示词（改了文件即生效，不用改代码）。
- 文件不存在时，回退到代码里写好的默认提示词，保证系统永远能跑。
"""
from __future__ import annotations

import os
from functools import lru_cache

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_DIR = os.path.join(BASE_DIR, "prompts")


@lru_cache(maxsize=None)
def load_prompt(name: str, default: str = "") -> str:
    path = os.path.join(PROMPT_DIR, f"{name}.md")
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    return text or default
