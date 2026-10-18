"""模型层：整个系统只依赖这里的 chat() / chat_json()。

- 配置了 LLM_API_KEY 时走真实模型（任何 OpenAI 兼容接口，如 DeepSeek）。
- 没配置时自动降级为 MockLLM，返回空结果，由各 Agent 的"规则/模板兜底"接管，
  保证【没有 Key 也能跑通全链路】做演示。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any


class LLMError(RuntimeError):
    pass


class BaseLLM:
    available: bool = False
    model_name: str = "offline-rules"

    def chat(self, system: str, user: str, temperature: float = 0.4) -> str:
        raise NotImplementedError

    def chat_json(self, system: str, user: str, temperature: float = 0.2) -> Any:
        return _extract_json(self.chat(system, user, temperature))


class MockLLM(BaseLLM):
    """离线模式：不产生内容，Agent 会走各自的规则兜底。"""

    available = False
    model_name = "offline-rules"

    def chat(self, system: str, user: str, temperature: float = 0.4) -> str:
        return ""


class OpenAICompatLLM(BaseLLM):
    available = True

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self.model_name = model

    def chat(self, system: str, user: str, temperature: float = 0.4) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # 网络/鉴权/额度问题都收敛成一种错误
            raise LLMError(str(exc)) from exc


def _extract_json(text: str) -> Any:
    """尽量从模型回复里抠出 JSON，兼容 ```json 围栏和前后废话。"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def get_llm() -> BaseLLM:
    """按环境变量创建模型。建议用 load_dotenv() 先读 .env。"""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        return MockLLM()
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").strip()
    model = os.getenv("LLM_MODEL", "deepseek-chat").strip()
    try:
        return OpenAICompatLLM(api_key, base_url, model)
    except Exception:
        return MockLLM()
