# 第一题：素材审核与发布排期 Agent

帮助内容团队审核素材、发现冲突、形成可确认的排期草稿。**只保存草稿，永不发布。**

当前交付状态：21 项自动测试通过；10 组离线场景和 10 组 DeepSeek `deepseek-flash` 真实模型场景达到预期。分别见 `examples/evaluation-summary.json` 与 `examples/live/evaluation-summary.json`，不能用 Mock 记录替代真实模型决策证据。最终提交 SHA 以 GitHub 提交记录为准。

## 评审入口

1. `docs/01-requirements.md`：需求与成功标准。
2. `src/agent.py`：有限步模型决策循环；`src/models.py`：模型协议与适配器。
3. `src/core.py`：审核、时段、确认边界、事务防重与保存工具。
4. `examples/evaluation-summary.json` 和 `examples/*.output.json`：实际结果与逐步 Trace。
5. `docs/03-evaluation.md`：逐项验收、失败和限制。

## 环境与安装

Python **3.12+**，仅标准库（含 SQLite），无第三方依赖。已在 Windows / Python 3.12.10 验证。Linux/macOS 可使用 `python3` 替代命令中的 `python`。

```powershell
git clone https://github.com/xiaoli-llm/exam.git
cd exam
python --version
python -m pip install -r requirements.txt
```

## 离线运行

在项目根目录执行，无须配置密钥：

```powershell
python -m src.cli --model mock --input examples/normal.input.json --db work/demo.sqlite --output work/normal.json
python -m src.cli --model mock --input examples/conflict.input.json --db work/conflict.sqlite --output work/conflict.json
python -m unittest discover -s tests -v
python examples/run_examples.py
python examples/verify_evidence.py
```

最后一条命令使用隔离数据库重建全部离线证据与测试报告，不覆盖真实模型证据。再次执行同一 CLI 请求和同一数据库会返回已有草稿；不会新增草稿。失败、阻断、资料不足和步数耗尽返回退出码 2，参数/配置错误返回 1，草稿成功或待确认返回 0。待确认并不等于用户已批准。

保存失败复现：

```powershell
python -m src.cli --model mock --input examples/save_failure.input.json --db work/failure.sqlite --simulate-save-failure --output work/failure.json
```

## 真实模型运行

兼容 Chat Completions 的服务需要支持 `response_format=json_object`；服务地址必须是你信任的地址，素材内容会发送给该服务。没有服务时不会悄悄降级为 Mock。

```powershell
$env:MODEL_BASE_URL = 'https://your-provider.example/v1'
$env:MODEL_NAME = 'your-model-name'
# 在本地环境设置 MODEL_API_KEY，勿写入仓库或聊天。
python -m src.cli --model compatible --input examples/conflict.input.json --db work/live.sqlite --output work/live-conflict.json
python examples/run_examples.py --model compatible
```

完整真实模型评估产生 `examples/live/` 内的输入、实际输出、Trace 和汇总。运行会调用收费服务，最多每场景 12 次模型请求，执行上限场景为 2 次。单次模型请求默认超时 60 秒，可用 `MODEL_TIMEOUT_SECONDS` 调整。

本次使用 DeepSeek：`MODEL_BASE_URL=https://api.deepseek.com`、`MODEL_NAME=deepseek-flash`、`MODEL_THINKING=disabled`，协议依据 [DeepSeek 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。本地可显式使用 `--config work/model-config.json` 读取包含同名 `MODEL_*` 字段的私有 JSON 配置；CLI 和评估脚本均支持该参数。配置文件不能提交。

也支持已安装并启动的 Ollama：设置 `MODEL_BASE_URL=http://localhost:11434` 和实际安装的 `MODEL_NAME`，将 `--model` 改为 `ollama`。[Ollama 官方协议](https://docs.ollama.com/api/chat) 是该适配器的参考来源。

`.env.example` 仅说明变量，程序不自动加载 `.env`。PowerShell 使用 `$env:NAME`；bash 使用 `export NAME=...`。

## 输入与结果

一个 CLI 请求处理一项素材；多素材逐项调用并共享数据库，能够检测彼此占用。完整输入见 `examples/normal.input.json`。

字段：`request_id`（幂等请求号）、`material_id`、`channel`、带时区的 `requested_slot`、`candidate_slots`、布尔 `hard_time`，以及可选的 `approved_slots`（由调用方传入的用户明确确认结果）。

结果包括审核状态、风险、缺失信息、原始时间、建议时间、待确认项、确认状态、真实保存状态、草稿 ID 和 `not_published`。Trace 每步记录动作、参数、工具返回、后续动作及简要依据，不要求或记录模型内部思维过程。

硬性时间 18:00 被占用而 19:00 可用时，建议 19:00 并保存待确认草稿，原始要求仍是 18:00。收到用户确认后，以**新 request_id** 和 `approved_slots` 创建修订请求；相同幂等键的输入变更会被拒绝。当前版本不提供旧草稿修改/撤销接口，详情见限制说明。

## 边界

单时区展示（Asia/Shanghai），每个渠道每整点一个一小时时段。固定禁词与版权状态检查用于演示，不能替代生产合规审核。无 UI、线上部署、真实发布或复杂 Runtime。`work/` 和密钥不提交；`examples/` 仅使用合成资料。
