# AI+华为PC营销软文智能体

面向**华为 PC 营销软文**的一体化自研 Agent：从一句任务输入出发，自动完成
**场景解析 → 平台策略 → 知识库检索 → 事实点提取 → 图文编排 → 软文生成 → 事实核验 → 合规检查 → 导出**，
并按赛题要求输出**统一四段格式**。

> 产品事实与图片素材来自华为官方 PC 知识库（ima 共享知识库「任德耀新建华为PC知识库」）。
> **未配置任何 Key 也能离线跑通全链路**：无 LLM Key 时走规则/模板兜底，无 ima 凭证时回退到本地已解压的官方知识库。

---

## 一、对齐赛题的关键点

| 赛题要求 | 本项目实现 |
|---|---|
| 标准流程 9 步 | [`src/orchestrator.py`](src/orchestrator.py) 主线编排，每步写入 `state.trace`，中断可恢复 |
| 统一四段输出（场景判断 / 知识库依据 / 图文软文 / 核验结果） | [`render_report()`](src/orchestrator.py) 与界面「③ 图文软文」页籤 |
| 4 个发布平台（公众号 / 小红书 / 门店朋友圈 / 门店海报） | [`config/platforms.json`](config/platforms.json)：结构、语气、图片数量、行动引导逐项不同 |
| 8 类业务场景 | [`config/scenes.json`](config/scenes.json)：切入点与卖点优先级随场景改变 |
| ima 接入 4 接口 | [`src/tools/ima_api.py`](src/tools/ima_api.py)：`search_knowledge_base` → `get_knowledge_list` → `search_knowledge` → `get_media_info` |
| 图片必须来自知识库且型号一致 | [`src/tools/image_ref.py`](src/tools/image_ref.py) + 事实核验的「图片型号」结论 |
| 系统提示词 8 模块 | [`prompts/system_prompt.md`](prompts/system_prompt.md) |
| 信息不足要追问 | [`src/agents/scene.py`](src/agents/scene.py) 的 `missing_inputs()` |
| 修改与导出 | 界面「修改与导出」：输入修改要求重新生成，并可导出四段 `.txt` |

---

## 二、快速开始（无需改代码）

### 方式 A：双击运行（推荐给评委）

双击 **`run.bat`**：自动创建虚拟环境、安装依赖、启动本地网页并打开浏览器。

### 方式 B：命令行

```bash
python -m src.cli --scenario 01_开学季_小红书                 # 用预置场景卡
python -m src.cli "给大一新生写一篇小红书，主打轻薄和续航" --platform 小红书 --scene 开学季
python -m src.cli --scenario 11_换平台对比_开学季_门店海报 --json   # 输出完整状态快照
```

### 方式 C：手动起 Streamlit

```bash
pip install -r requirements.txt
streamlit run src/ui/app.py
```

---

## 三、目录结构

```
config/        platforms.json（4 平台规则）、scenes.json（8 场景）、products.json（型号+kb_path）、pricing_rules.json
prompts/       system_prompt.md（提交用 8 模块系统提示词）、scene.md、content.md
scenarios/     13 张预置场景卡（含换平台对比与干扰测试）
src/
  orchestrator.py   9 步主线 + 统一四段输出
  state.py          会话状态定义（可持久化 / 中断恢复）
  config_loader.py  读 config/ 下所有 json
  llm.py            大模型接入（无 Key 时 MockLLM 兜底）
  agents/           scene.py（场景解析）、content.py（软文生成）、factcheck.py（事实核验+合规）、common.py
  tools/            ima_api.py（ima 四接口+本地兜底）、image_ref.py（配图方案）、pricing.py（确定性价格工具，非软文主线）
  ui/app.py         演示界面
tests/          端到端与单元测试（pytest）
_official_kb/   本地已解压的华为官方 PC 知识库（离线兜底用）
```

---

## 四、配置（可选，不配也能跑）

复制 `.env.example` 为 `.env` 后按需填写：

```ini
# 1) 大模型（任何 OpenAI 兼容接口）
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# 2) ima 知识库
IMA_OPENAPI_CLIENTID=
IMA_OPENAPI_APIKEY=
```

- **不填 `LLM_API_KEY`** → 走规则/模板生成，全链路照常跑通。
- **不填 ima 凭证** → 回退到本地官方知识库 `_official_kb/`，图片同样取自知识库内的「图片索引.csv」。
- 若要启用真实 ima 接口：把官方脚本 `ima_api.cjs`（来自 `ima-skills-1.1.10.zip`）解压到项目根目录的 `ima-skill/` 下，再填凭证即可。

---

## 五、测试

```bash
python -m pytest -q     # 全部用例
```

覆盖：四段输出、换场景切入点变化、换平台实质变化、图片型号一致、事实点核验、虚构事实拦截、
合规命中、软文不含价格/补贴、信息不足追问、易混淆型号确认、修改要求重新生成等。

赛题「统一测试任务」4 项的操作与预期，见提交材料中的**测试清单**：
① 基础生成 ② 换场景 ③ 换平台 ④ 干扰与修改。

---

## 六、合规与安全

- 软文**不写价格、补贴、销量、奖项、用户评价**（由合规检查模块统一拦截）。
- 所有事实点均可回溯到知识库原文，虚构或无法确认的内容会标记为「待确认」。
- 图片均标注**名称 / 来源 / 插入位置 / 说明**，并核验与产品型号一致。
- **API Key 与 ima 凭证只放 `.env`（已在 `.gitignore` 中排除），源码、界面、导出结果、README 与演示视频中均不出现。**

---

## 七、技术栈

Python 3.10+ ｜ Streamlit（演示界面）｜ pytest（测试）｜ openai SDK（兼容多厂商）｜ 官方 ima 脚本 / 本地官方知识库（事实与图片来源）
