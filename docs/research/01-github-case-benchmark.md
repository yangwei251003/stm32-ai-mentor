# GitHub 与学习工作台案例对比

检索日期：2026-08-21。以下只借鉴结构和反馈模式，不复制第三方课程文字或工程代码。

| 案例 | 值得借鉴 | V1 的落点 | 不采用 |
|---|---|---|---|
| [STM32CubeF1](https://github.com/STMicroelectronics/STM32CubeF1) / [STM32CubeF4](https://github.com/STMicroelectronics/STM32CubeF4) | 芯片系列→板卡→外设→Examples/Applications/Demonstrations 分层；官方 HAL/CMSIS 版本组合 | S0–S7、项目目录、适用芯片和验证等级 | 不提交 ST 固件源码，不复制混合许可工程 |
| [STM32AI Model Zoo](https://github.com/STMicroelectronics/stm32ai-modelzoo) | 用例、模型、数据、部署板、指标和代码生成形成可追踪清单 | 仅作为未来 V2 模板/manifest 思路 | V1 不引入训练、量化、Docker 或云基准依赖 |
| [Ferrous Embedded Trainings](https://github.com/ferrous-systems/embedded-trainings-2020) | 硬件前提、教材、可运行练习、检查点分离 | 每课 BOM、前置、最小实验和验收证据 | 不复制 CC-BY-SA 课程文字；Rust/nRF 不替代 C/HAL 主线 |
| [Microsoft AI Agents for Beginners](https://github.com/microsoft/ai-agents-for-beginners) | 每课“短理论—代码实践—验收—扩展”的一致契约 | 预习+课堂四段+四级作业 | 不绑定 Azure 或供应商 SDK |
| [Open edX](https://github.com/openedx/openedx-platform) | 内容制作与学习记录分离；历史完成记录不被课程更新覆盖 | Skill references 与 `Student_Profile` 分离，事件账本不可变 | 不引入完整 LMS、前端、MySQL/Mongo/缓存；不复制 AGPL 代码 |
| [OpenAI Codex](https://github.com/openai/codex) / [Skills 文档](https://developers.openai.com/codex/skills) | Skill 目录、渐进加载、仓库作用域、可选 references/scripts | 精简 `SKILL.md` 做意图路由，课程和角色按需加载 | 不用一个超长提示词装下整个课程库 |
| [Anthropic Skills](https://github.com/anthropics/skills) | 技能目录、说明/脚本/资源分层 | 稳定项目 ID、明确输入输出和风险元数据 | 仓库无统一授权，不直接搬运；不混用不兼容字段 |
| [Aider](https://github.com/Aider-AI/aider) | 先读取工程和错误证据，再做最小修改，再 lint/test | 固件专家的“证据→最小改变→验证→学习者解释”循环 | 不自动提交、不默认烧录、不替学习者完成全部工程 |

## 汇总后的产品模式

```text
项目卡（生活任务）
  → 预习手册（必要理论/常考/安全/5题）
  → 最小可运行里程碑
  → 观察与故障证据
  → 解释与迁移
  → 事件账本 + 下次恢复指针
```

这套模式保留 STM32Cube 的工程分层、Microsoft 的统一课契约、Open edX 的内容/状态分离、Aider 的证据反馈循环和 Codex 的渐进加载，同时主动排除 V1 不需要的 LMS、云依赖、自动烧录和一键完整工程。

