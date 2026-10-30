# 测试预期、实际结果、失败和限制

## 复现

```powershell
python -m unittest discover -s tests -v
python examples/run_examples.py
python examples/verify_evidence.py
```

实际报告：[`../examples/test-results.txt`](../examples/test-results.txt)；逐场景汇总：[`../examples/evaluation-summary.json`](../examples/evaluation-summary.json)。脚本执行真实工具、事务和文件写入，结果非手工编造；模型为确定性 Mock，**只证明离线流程**。

## 验收映射

每个 `*.output.json` 同时包含结果与完整 Trace，`*.input.json` 是实际输入。

| 验收 | 输入 | 实际输出与 Trace | 预期 |
|---|---|---|---|
| 正常 | [normal.input.json](../examples/normal.input.json) | [normal.output.json](../examples/normal.output.json) | completed/saved/未发布 |
| 信息不足 | [missing.input.json](../examples/missing.input.json) | [missing.output.json](../examples/missing.output.json) | 补查后 needs_information，零草稿 |
| 规则风险 | [risk.input.json](../examples/risk.input.json) | [risk.output.json](../examples/risk.output.json) | blocked，零草稿 |
| 时间冲突 | [conflict.input.json](../examples/conflict.input.json) | [conflict.output.json](../examples/conflict.output.json) | 18:00 保留；建议 19:00，pending_confirmation |
| 重复提交 | [repeat.input.json](../examples/repeat.input.json) | [首次](../examples/repeat.first.json)、[重复输出](../examples/repeat.output.json) | 同 ID、existing、仅一份草稿 |
| 保存失败 | [save_failure.input.json](../examples/save_failure.input.json) | [save_failure.output.json](../examples/save_failure.output.json) | failed/failed，零草稿 |
| 补查成功 | [supplement.input.json](../examples/supplement.input.json) | [supplement.output.json](../examples/supplement.output.json) | 补查后重新审核，再保存 |
| 上限 | [limit.input.json](../examples/limit.input.json) | [limit.output.json](../examples/limit.output.json) | 两步后 incomplete |
| 用户已确认 | [approved.input.json](../examples/approved.input.json) | [approved.output.json](../examples/approved.output.json) | 替代时段 completed |
| 更换占用 | [occupancy_changed.input.json](../examples/occupancy_changed.input.json) | [occupancy_changed.output.json](../examples/occupancy_changed.output.json) | 19:00 占用后选择 18:00 |

更换占用场景的实际资料为 [occupancy_changed.data.json](../examples/occupancy_changed.data.json)。默认保存失败使用显式故障注入，另有真实 SQLite 事务与约束测试；没有伪装成生产故障。

## 动态路径证据与未完成项

离线 Trace 的正常路径为读取→检查→查时段→保存→结束；缺失路径为读取→检查→补查→重查→请求补充；冲突路径的 save_draft 参数变为 19:00。它们证明数据影响测试策略，但**不构成真实模型 ReAct 验收证据**。

真实模型入口：`python examples/run_examples.py --model compatible`。2026-10-30 已使用用户指定的 DeepSeek `deepseek-flash`，关闭 thinking、temperature=0，实际完成 10 组场景（重复提交包括首次和第二次执行）。服务通过 GET /models 确认可用。真实模型汇总见 [live/evaluation-summary.json](../examples/live/evaluation-summary.json)，测试报告见 [live/test-results.txt](../examples/live/test-results.txt)。10 组均达到表中预期，22 项自动测试通过。`verify_evidence.py` 还核对真实保存回执、草稿数量、确认状态、原始时间、风险、请求标识与步数上限。

### 真实动态路径与失败纠正

- [正常路径](../examples/live/normal.output.json)：读取 → 审核 → 查询 → 保存 18:00 → 结束。
- [缺失路径](../examples/live/missing.output.json)：读取后模型发现缺少 owner，直接选择补查 → 审核仍报告缺失 → needs_information，未保存。该顺序与离线策略不同。
- [补查成功](../examples/live/supplement.output.json)：读取 → 审核发现缺失 → 补查 → 重新审核 → 查询 → 保存 → 结束。
- [冲突与纠正](../examples/live/conflict.output.json)：查询发现 18:00 占用、19:00 可用；第 4 步模型先尝试 finish，执行器返回 `cannot_finish_success_without_saved_draft`；第 5 步模型根据失败回执选择保存 19:00，第 6 步返回 pending_confirmation。保留了这次错误与纠正，没有删除失败步骤或宣称模型首轮决策完美。
- [风险](../examples/live/risk.output.json)：检查发现禁词后阻断。
- [保存失败](../examples/live/save_failure.output.json)：模型观察 save_failed_injected 后结束 failed，无新增草稿。
- [重复](../examples/live/repeat.first.json)、[再次提交](../examples/live/repeat.output.json)：同一 ID，仅一份草稿，第二次返回 existing。
- [更换占用](../examples/live/occupancy_changed.output.json)：把占用改为 19:00 后，真实模型选择 18:00。

每步保存接口返回的 response id、模型标识和用量；不保存 reasoning_content。真实场景使用实际模型决策和本地业务工具，工具数据与故障均为合成/显式注入，不声称访问了真实内容平台。

## 已发现与修复的问题

1. 初次测试写入系统临时目录失败：改为项目 work/ 下的隔离临时目录，完整重跑通过。
2. 时区表示可能导致同一时刻绕过唯一约束：统一转为 UTC+08:00，增加跨时区冲突测试。
3. 非法 finish 的状态字段可能为对象：增加类型检查，确保被拒绝并计入上限。
4. 导出后独立运行检查发现 Windows 管道输出默认 GBK，无法作为 UTF-8 JSON 解码：CLI 显式设置 UTF-8，增加真实子进程回归测试。

## 限制

- 当前是单次小样本真实模型验证，没有稳定性统计或跨模型比较；模型结果存在不确定性，必须保留失败案例。
- 仅单渠道整点一小时槽位，无跨时段时长、节假日、优先级或批量最优排程。
- 规则仅覆盖合成禁词和版权字段，不能证明真实合规能力。
- 候选时段必须由用户提供；全部占用时返回 blocked，并在 reason 说明需要新时段，未自动扩展硬性范围。
- `approved_slots` 来源依赖可信调用者，无身份认证或审批系统。
- 幂等键绑定不可变请求；修订需新请求号。本版本无更新、取消和迁移旧草稿接口，待确认草稿也占位，真实编辑流程需补齐草稿生命周期。
- 已保存草稿不会因外部排期后续变化而自动撤回；展示的是该次运行的事实。
- Trace 不存密钥，但包含合成素材与工具结果；真实资料使用前需要增加脱敏和访问控制。
- 无生产发布端点、无线上部署、无多 Agent、无任务恢复。
