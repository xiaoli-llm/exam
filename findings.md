# 需求与调查记录

题号 1：素材审核与发布排期 Agent。验收：正常、信息缺失、规则风险、时段冲突、重复提交、保存失败。
交付：逐素材审核状态、风险、建议时段、待确认项和真实保存状态。不可真实发布。
至少两条观察结果不同的模型决策路径；Mock 只能证明流程。

2026-10-30 核对 Ollama 官方 API：https://docs.ollama.com/api/chat 。POST /api/chat 支持 messages、format=json、stream=false，响应 message.content。
选择 Python 3.12 标准库 + SQLite；不引入 Agent 框架。模型通过 JSON 动作协议驱动工具，业务保护与模型分离。

用户指定公开仓库 xiaoli-llm/exam、DeepSeek 服务及 deepseek-flash。GitHub 连接确认有 push 权限，保留初始 LICENSE。密钥只存放于被忽略的 work/。
已核对 https://api-docs.deepseek.com/api/create-chat-completion/ 及 /api/list-models/，支持 JSON 格式和 thinking=disabled。首次本地网络探测 URLError，改为授权网络执行。
