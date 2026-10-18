"""命令行版：不依赖界面，用于快速自测与排障。

用法（在项目根目录）：
  python -m src.cli "任务输入……" --platform 公众号 --scene 开学季 --product matebook_d14_2024
  python -m src.cli --scenario 开学季_小红书 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.config_loader import platform_keys  # noqa: E402
from src.llm import get_llm  # noqa: E402
from src.orchestrator import new_state, render_report, run_pipeline  # noqa: E402
from src.tools.ima_api import connection_status  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="AI+华为PC营销软文智能体 · 命令行版")
    ap.add_argument("task", nargs="?", default="", help="任务输入（产品/人群/场景/渠道）")
    ap.add_argument("--scenario", help="直接用预置场景卡，取值：scenarios/ 下的文件名（不含 .json）")
    ap.add_argument("--platform", default="公众号", choices=platform_keys(), help="发布平台")
    ap.add_argument("--scene", default="", help="业务场景：开学季/职场办公/内容创作/家庭换新/企业采购/门店到访/新品首发/节日营销")
    ap.add_argument("--product", default="", help="指定产品 id 或名称关键词（不填则按场景自动推荐）")
    ap.add_argument("--revision", default="", help="临时修改要求，重新生成（如：删减篇幅 / 换成小红书 / 替换卖点）")
    ap.add_argument("--json", action="store_true", help="输出完整状态快照 JSON")
    args = ap.parse_args()

    task, platform, scene, product = args.task, args.platform, args.scene, args.product
    if args.scenario:
        path = os.path.join(ROOT, "scenarios", f"{args.scenario}.json")
        with open(path, "r", encoding="utf-8") as f:
            sc = json.load(f)
        task = sc.get("task", task)
        platform = sc.get("platform", platform)
        scene = sc.get("scene", scene)
        product = sc.get("product_id", product)
    if not task.strip():
        ap.error("请提供任务输入，或用 --scenario 指定预置场景卡。")

    llm = get_llm()
    kb = connection_status()
    print(f"[模型] {'真实模型：' + llm.model_name if llm.available else '离线模式（未配置 LLM_API_KEY，走规则/模板兜底）'}")
    print(f"[知识库] {kb['mode']}｜{kb['kb_name']}\n")

    state = new_state(task, platform=platform, scene_hint=scene, product_id=product)
    state = run_pipeline(state, llm)

    if args.json:
        print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
        return

    print("=" * 64)
    print(render_report(state))
    print("=" * 64)
    if state.pending_questions:
        print("【需要补充的信息】")
        for q in state.pending_questions:
            print(f"  - {q}")
    print("\n协调器运行轨迹：")
    for i, t in enumerate(state.trace, 1):
        print(f"  {i}. [{t['agent']}] {t['action']} — {t['detail']}")


if __name__ == "__main__":
    main()
