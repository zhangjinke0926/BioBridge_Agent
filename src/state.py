"""会话状态对象：全链路唯一的"真相来源"。

协调器 9 步都基于它判断"当前该由谁处理、还缺什么参数"，
每一步都写入 trace，便于中断后从任意一份快照恢复（赛题：中断一次扣 10 分）。

主线：场景解析 → 平台策略 → ima资料与图片检索 → 事实点提取 → 图文编排
      → 软文生成 → 事实核验 → 合规检查 → 导出。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

STAGES = ["start", "scene", "strategy", "retrieve", "draft", "verify", "done"]

# 会话快照落盘目录：中断后可从这里恢复（赛题：中断一次扣 10 分）。
SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions")


@dataclass
class SessionState:
    session_id: str = "demo"
    stage: str = "start"
    raw_task: str = ""              # 用户原始任务输入（产品/人群/场景/渠道）
    platform: str = "公众号"         # 发布平台：公众号 / 小红书 / 门店朋友圈 / 门店海报
    scene_hint: str = ""            # 用户/场景卡显式指定的业务场景
    product_id: str = ""            # 指定产品 id（评委指定产品时）
    revision: str = ""              # 临时修改要求（重新生成时使用）

    product: dict[str, Any] = field(default_factory=dict)       # 主推机型（brief）
    product_knowledge: dict[str, Any] = field(default_factory=dict)  # 型号产品事实/卖点/图片索引
    scene_analysis: dict[str, Any] = field(default_factory=dict)     # 一、场景判断
    platform_strategy: dict[str, Any] = field(default_factory=dict)  # 二、平台策略
    evidence: list[dict[str, Any]] = field(default_factory=list)     # ima 检索到的资料（含来源）
    facts: list[str] = field(default_factory=list)                   # 事实点提取
    image_plan: list[dict[str, Any]] = field(default_factory=list)   # 图文编排·图片方案
    copy: dict[str, Any] = field(default_factory=dict)               # 三、图文软文
    verification: dict[str, Any] = field(default_factory=dict)       # 四、核验结果（事实/图片/合规）
    output: dict[str, Any] = field(default_factory=dict)             # 统一四段输出
    pending_questions: list[str] = field(default_factory=list)       # 需要补充的信息
    trace: list[dict[str, Any]] = field(default_factory=list)        # 运行轨迹（给评委看）

    def log(self, agent: str, action: str, detail: str = "") -> None:
        self.trace.append({"agent": agent, "action": action, "detail": detail})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        """把当前状态落盘到 sessions/{session_id}.json，供中断后恢复。"""
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        path = os.path.join(SESSIONS_DIR, f"{self.session_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, session_id: str = "demo") -> "SessionState | None":
        """从磁盘恢复指定会话，不存在则返回 None。"""
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
