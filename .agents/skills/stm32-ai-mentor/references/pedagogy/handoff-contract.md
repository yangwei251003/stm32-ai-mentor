# 多 Agent 委派合同

主导师只在任务独立、复杂或用户明确要求时委派。硬件和固件核对互不依赖时可并行；简单问答、实时课堂追问、状态写入不委派。

每次 handoff 至少包含：

```yaml
task_id:
role:
goal:
workspace_scope:
state_revision:
hardware_context:
toolchain_context:
input_artifacts:
allowed_actions: [read, analyze, test-read-only]
forbidden_actions: [write-learning-state, flash-hardware, expand-scope]
required_output_schema:
```

子 agent 不向用户追问，不嵌套扩散，不编辑 `Student_Profile/`。缺少关键输入时返回 `blocked_by_missing_input`。输出区分 facts、assumptions、unknowns、risks、evidence_candidates 和 limitations。主导师核验、去重、整合后只做一次状态事务提交。

默认路由：固件给 `firmware_engineer`，电源/接线给 `hardware_engineer`，测验/评价给 `learning_assessor`。所有 agent 读取同一 revision；合并时若 revision 已变化，丢弃过期提案并重读。

