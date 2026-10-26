# 权威来源与版本登记

核验日期：2026-08-21。版本是调研基线，不得替代用户本机检查。

| 主题 | 来源 | 记录事实 | 使用位置 | 可信边界 |
|---|---|---|---|---|
| STM32F103C8 | [ST 产品页](https://www.st.com/en/microcontrollers-microprocessors/stm32f103c8.html) | Cortex-M3、72 MHz、64 KB Flash、USB、CAN 等 | 安全事实、课程适配 | MCU 能力，不是 Blue Pill 板级事实 |
| F103 medium-density | [ST 文档页](https://www.st.com/en/microcontrollers-microprocessors/stm32f103/documentation.html) | DS5319 数据手册入口 | 引脚、电气、封装核对 | 精确接线仍需封装/板卡资料 |
| 外设行为 | [RM0008](https://www.st.com/resource/en/reference_manual/cd00171190-stm32f101xx-stm32f102xx-stm32f103xx-stm32f105xx-and-stm32f107xx-advanced-arm-based-32-bit-mcus-stmicroelectronics.pdf) | GPIO、ADC、DMA、定时器、CAN、USB 等寄存器/时钟 | 理论和故障解释 | 不能替代具体器件数据手册电气限制 |
| STM32CubeF1 | [官方仓库](https://github.com/STMicroelectronics/STM32CubeF1) | 调研时 V1.8.7（2026-02-12） | 构建基线和项目示例索引 | 仓库含组合许可，版本须与本机一致 |
| HAL | [F1 HAL driver](https://github.com/STMicroelectronics/stm32f1xx-hal-driver) | 调研时 HAL V1.1.10，CMSIS Device V4.3.5 | HAL API 适用性记录 | HAL/CMSIS 必须使用匹配组合 |
| CubeIDE | [ST 1.19.0 发布公告](https://community.st.com/t5/stm32cubeide-mcus/stm32cubeide-1-19-0-released/td-p/824473) | IDE 1.19.0 发布与工具环境 | Kevin 默认工具链 | IDE 版本不锁定 HAL 包版本 |
| Blue Pill | [STM32-base 板卡页](https://stm32-base.org/boards/STM32F103C8T6-Blue-Pill.html) | 常见 PC13 LED、SWD、USB 和供电风险 | 条件性 board profile | 第三方资料，克隆差异必须确认 |
| Codex Skills | [官方 Skills 文档](https://developers.openai.com/codex/skills) | `.agents/skills`、渐进加载、repo scope | Skill 架构 | 以本机当前规范和 validator 复核 |
| Codex subagents | [官方配置文档](https://developers.openai.com/codex/subagents) | 项目 agents、模型/推理和并行分工 | `.codex` agent 配置 | 专家保持只读、主导师单写 |

## 本机核查

- 已发现 `C:\ST\STM32CubeIDE_1.19.0\STM32CubeIDE\stm32cubeide.exe`、命令行入口和 bundled GCC 13.3。
- 调研时未发现用户目录下已安装的 STM32CubeF1 Repository，因此不能宣称本机已用 HAL V1.1.10 完整编译。
- 编译级验证若需要官方包，应下载到临时固定版本目录并在测试后保留许可证说明；不提交包源码。
- USB/CAN/低功耗/电机等仍必须 V5 实板验证。

