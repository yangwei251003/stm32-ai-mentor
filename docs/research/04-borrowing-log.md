# 借鉴落实日志

| 来源模式 | 采用的抽象成果 | 落地位置 | 复制第三方代码？ |
|---|---|---|---:|
| STM32Cube 板卡/外设/示例分层 | S0–S7、项目类别、芯片/验证元数据 | `references/curriculum/`、`references/projects/` | 否 |
| Microsoft 短理论—实践—验收—扩展 | 固定预习、课堂四段、课后四级 | `classroom-contract.md`、15 个精讲项目 | 否 |
| Open edX 内容与学习记录分离 | Skill 内容只读，学习事件独立持久 | `.agents/skills/` 与 `Student_Profile/` | 否 |
| Aider 证据—最小修改—验证 | 提示阶梯、固件诊断、构建/日志证据 | `firmware-engineer.md`、精讲调试树 | 否 |
| Codex Skill 渐进加载 | 精简入口按意图读 reference | `SKILL.md` | 否 |
| Codex 多模型子 agent | Sol 固件、Terra 硬件、Luna 评估；只读专家 | `.codex/config.toml`、`.codex/agents/` | 否 |
| 事件溯源/乐观并发通用模式 | 账本、revision、幂等、写锁、原子替换 | `state_tool.py` | 否 |

## 明确排除

- 不复制 ST 混合许可工程或中间件。
- 不嵌入 Open edX AGPL 源码。
- 不复制未统一授权的课程文字、图示、题库或模型。
- 不引入完整 LMS、自动烧录、自动 Git 提交、网页端或云厂商强依赖。
- 不把第三方 Blue Pill 常见引脚写成 ST 官方事实。

