# 第三方许可证与复用边界

| 来源 | 许可证/状态 | 本项目是否复制代码/文字 | 决策 |
|---|---|---:|---|
| OpenAI Codex | Apache-2.0 | 否 | 只借鉴 Skill 渐进加载和验证方式 |
| Aider | Apache-2.0 | 否 | 只借鉴证据—最小修改—验证反馈循环 |
| Microsoft AI Agents for Beginners | MIT | 否 | 只借鉴 lesson contract |
| Open edX | AGPL-3.0 | 否 | 只借鉴内容/学习状态分离，不嵌入代码 |
| Ferrous Embedded Trainings 代码 | MIT 或 Apache-2.0 | 否 | 只借鉴练习组织 |
| Ferrous Embedded Trainings 文字 | CC-BY-SA-4.0 | 否 | 不复制或改写课程段落 |
| STM32CubeF1/F4 | 多许可证：Apache-2.0、BSD-3-Clause、SLA0044 等 | 否 | 不提交官方工程/中间件；仅链接、事实摘要和临时本地编译 |
| STM32AI Model Zoo | 按 use case/SBOM，非单一 SPDX | 否 | V1 不引入模型/数据/代码 |
| Anthropic Skills | 仓库非统一许可，部分 source-available | 否 | 仅借鉴抽象目录思想，逐项许可审查后才能未来复用 |
| STM32-base | 网站第三方资料 | 否 | 只用于条件性 Blue Pill 风险说明，并保留链接 |

本仓库所有教案、HAL 片段、测试和状态脚本均为本项目新写内容。源码片段只表达通用 API 使用，不复制 ST 完整例程。未来若引入外部模板、图片、固件、模型或数据，必须在本表新增精确版本、文件级来源、许可证和再分发条件。

