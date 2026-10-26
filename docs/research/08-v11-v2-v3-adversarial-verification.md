# V1.1 + V2 + V3 对抗验证报告

日期：2026-08-21（Asia/Shanghai）

## 发布结论

- V1.1 课堂路由与学习账本：独立审查 `Spec ✅ / Quality approved`。
- V2 项目侧车：独立审查 `Spec ✅ / Quality approved`。
- V2 30 个深案例与 70 个索引：独立审查 `Spec ✅ / Quality approved`。
- V3 竞赛侧车：独立审查 `Spec ✅ / Quality approved`。
- 跨能力盲测：55/55 个自然语言压力样例通过，无 Critical 或 Important 遗留项。

## 新鲜验证证据

- 全仓确定性测试：`207 passed in 91.41s`。
- V2 工程专项：72 项通过。
- V2 经验库专项：25 项通过；目录、精讲和经验库组合 40 项通过。
- V1.1 与 V3 联合回归：79 项通过。
- 五个核心脚本通过 Python 编译检查。
- 15 份 Draft 2020-12 JSON Schema 通过结构校验。
- `render_v2_patterns.py --check` 无生成漂移。
- Skill 官方结构校验：`Skill is valid!`。
- `Student_Profile` 校验结果：revision 1、event_count 1、无需恢复；六个文件前后 SHA-256 不变。

## 重点攻击面

盲测和定向 mutation 覆盖：V3>V2>V1 路由优先级、最多三问、readiness 4/5、catalog-only 拒绝开课、未知 Blue Pill 版本、HC-SR04 Echo 5 V、GPIO 直驱电机、引脚/AF/DMA/IRQ/时钟冲突、Flash/RAM 预算、构建/烧录/用户口述证据降级、新 baseline 使旧证据失效、规则过期或官网不可达、AI 使用/匿名/前案/原始实测合规，以及三个状态目录互不污染。

最后两项 breaker 修复为：

1. 电源校验从“范围有交集”收紧为 `terminal requirement ⊆ component port` 且 `power domain ⊆ terminal requirement`；4.75–12 V 的超声模块电源域会被拒绝。
2. 安全文本按单个字段识别 `Echo/回波/HC-SR04 ↔ MCU/GPIO/pin` 和 `motor ↔ MCU/GPIO/pin` 的普通中文“接”关系，同时允许明确写出分压、电平转换、驱动器或 TB6612 的安全桥接路径。

## 未宣称的验证

本轮没有实板、烧录、真实电气测量或比赛提交，也没有实时访问所有赛事官网。因此不会把编译成功升级为硬件通过，不会把用户口述升级为独立实测，不会断言未来届次规则，也不会承诺获奖。
