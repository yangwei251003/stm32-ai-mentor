# 智能风扇调速系统：V2 全流程项目模式

稳定项目 ID：`smart_fan_pid`。目标为 STM32F103C8Tx LQFP48；下列引脚是条件性建议，实施前确认板版、封装、复用和保留 SWD。**未实机**。

## 需求基线

使用安全小风扇按温度或设定转速调速 默认量化验收：构建成功且无警告性错误；按课堂检查点出现可观察现象；记录串口/测量/照片等证据。可覆写条件：传感器量程、阈值、负载或板版变化时重新验证。

## 方案与 ADR

方案 A 使用 ADC1 TIM3 PWM 驱动 的最小轮询诊断；方案 B 将关键输入转 IRQ 或 DMA；方案 C 在模拟夹具中先验证。ADR-smart_fan_pid：仅在满足本项目响应/采样目标后启用 B，避免为“智能风扇调速系统”引入不必要的 DMA、IRQ 与 RAM 风险。

## BOM 与替代

默认器件：STM32F103C8Tx开发板、面包板与杜邦线、USB 3.3V/5V受控供电、按项目BOM补充器件。替代件须保持 3.3V 逻辑、接口时序与负载域隔离；先断电接线、确认3.3V逻辑与限流；不接市电/高压/无保护锂电池；外设电机类另有专门安全门

## 可覆写接线表

逐信号端点类型、电气约束、合法 AF 候选、组件与电源域的唯一可执行表，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份引脚表。

## CubeMX

为 智能风扇调速系统 启用 ADC1 TIM3 PWM 驱动，RCC 先 HSI 8MHz；仅在确认 HSE 后使用 PLL 72MHz。将本项目使用的 DMA、IRQ 和协议参数（地址/波特率/校验/帧格式）保存进 `.ioc`；IRQ 不打印、不阻塞。

## 资源预算

MCU 信号数、Flash/RAM 区间、MCU/负载分域电流及估算依据，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份数值预算。

## 可构建增量契约

M0 保存 `.ioc`；M1 构建接口自检；M2 用模拟输入验证量化验收；M3 保存 map、DMA/IRQ/协议日志；M4 仅在安全门和一次刷写确认后实机。

## 测试与故障树

接口无响应先查电平、共地与复用；数据异常先查时钟、协议、DMA 缓冲；负载异常立即断开使能并回退 M1。每一分支记录证据。

## 回滚

引脚、时钟、DMA、IRQ、BOM、供电域或协议变化均使本项目后续证据失效；恢复 M0/M1 的 `.ioc`、map 与哈希再逐项重放。

## 安全门

先断电接线、确认3.3V逻辑与限流；不接市电/高压/无保护锂电池；外设电机类另有专门安全门 所有实机动作需可见停机；构建和刷写不等于功能验收。

## C0–C4 创意卡

C0 场景；C1 可测需求；C2 方案 ADR；C3 构建证据；C4 迁移后重新安全复核。

## 发布清单

- [ ] 智能风扇调速系统 的接口、供电域、信号数、Flash/RAM/MCU电流/负载电流预算已复核
- [ ] 接线、CubeMX、DMA、IRQ、协议、测试和回滚证据可追溯
- [ ] 未实机不得声称硬件运行；刷写须一次明确确认

功耗：MCU 与负载分域预算，未实测。

<!-- V2_PATTERN_GENERATED:START sha256=6be593b94a5e607943a0a1f5933c48d35d1e8cdb5f86b2bcafb322cf9e7f7e1e -->
## Manifest 生成的可覆写工程区块

单一来源：`patterns.json`。目标为 `STM32F103C8Tx LQFP48`，板卡版本未知；下表只列 MCU 合法候选能力，实施前必须根据板卡走线、复用冲突和组件数据手册覆写。`PA13/PA14` 始终保留给 SWD。**未实机（not_tested_on_hardware）**。

### 组件规格边界

| component_ref | 组件 | supply_v | logic_v | current_ma | supply_rails |
|---|---|---|---|---|---|
| temp_sensor | 0-3.3 V temperature sensor or divider | 0-3.3 V; module datasheet and board variant must be confirmed | 0.0-3.3 V; module datasheet and board variant must be confirmed | 0-5 mA; module datasheet and board variant must be confirmed | main: 0-3.3 V; module datasheet and board variant must be confirmed / 0-5 mA; module datasheet and board variant must be confirmed / signal_load |
| fan_driver | logic-level fan driver with flyback protection | 3.0-5.25 V; module datasheet and board variant must be confirmed | 0.0-3.3 V; module datasheet and board variant must be confirmed | 0-20 mA; module datasheet and board variant must be confirmed | main: 3.0-5.25 V; module datasheet and board variant must be confirmed / 0-20 mA; module datasheet and board variant must be confirmed / signal_load |
| fan | protected low-voltage fan with tach output | 4.75-12.6 V; module datasheet and board variant must be confirmed | 0-3.3 V; module datasheet and board variant must be confirmed | 80-600 mA; module datasheet and board variant must be confirmed | main: 4.75-12.6 V; module datasheet and board variant must be confirmed / 80-600 mA; module datasheet and board variant must be confirmed / consumer |

### 电源域

| power_domain_ref | 电源域 | 电压 | intrinsic_current | concurrent consumer peak | 电流预算 | source_capacity | concurrency | 状态 |
|---|---|---|---|---|---|---|---|---|
| mcu_3v3 | MCU regulated 3.3 V signal domain | 3.0-3.6 V; Sensor, PWM control, and divided tach stay in the MCU signal domain | 18-55 mA; MCU, clock tree, board regulator losses, and core activity only; external powered ports are excluded | 0 mA | 18-55 mA; Intrinsic maximum plus all connected consumer-port peaks at diversity 1.0; required concurrent maximum is 55 mA | 55-69 mA; Estimated selectable source capability must meet at least the full rail budget before hardware use | diversity=1.0; All connected consumer-port peak currents are assumed simultaneous; no diversity discount is claimed | estimated |
| fan_load | independent protected fan supply | 4.75-12.6 V; Fan running and startup current are supplied outside the MCU regulator and verified at the selected voltage | 0-0 mA; No hidden load is assumed; connected component ports define this rail | 600 mA | 80-700 mA; Intrinsic maximum plus all connected consumer-port peaks at diversity 1.0; required concurrent maximum is 600 mA | 700-875 mA; Estimated selectable source capability must meet at least the full rail budget before hardware use | diversity=1.0; All connected consumer-port peak currents are assumed simultaneous; no diversity discount is claimed | estimated |

### 逐信号契约

| function | endpoint_type | direction | electrical | peripheral | candidate_pins / confirmation | component_ref | component_port_ref | required_rail_voltage | power_domain_ref |
|---|---|---|---|---|---|---|---|---|---|
| TEMP_ADC | mcu_signal | in | 0-3.3 V analog input; source impedance and settling time must be checked | ADC1 | PA0 / ADC1_IN0 / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PA1 / ADC1_IN1 / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PB0 / ADC1_IN8 / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment | temp_sensor | - | - | mcu_3v3 |
| FAN_PWM | mcu_signal | out | 3.3 V timer alternate-function push-pull; drives logic input only | TIM3_CH1 | PA6 / TIM3_CH1 / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PB4 / TIM3_CH1 / AFIO_MAPR_TIM3_REMAP=partial; JTAG disabled, SWD kept / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment | fan_driver | - | - | mcu_3v3 |
| FAN_ENABLE | mcu_signal | out | 3.3 V GPIO push-pull; external driver required for loads | GPIO | PA2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA3 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA4 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA5 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA8 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB0 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB1 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB10 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB11 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB12 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB13 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB14 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB15 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment | fan_driver | - | - | mcu_3v3 |
| FAN_TACH | mcu_signal | in | 3.3 V timer capture input; edge rate and pull state must be confirmed | TIM2_CH1 | PA0 / TIM2_CH1 / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PA15 / TIM2_CH1 / AFIO_MAPR_TIM2_REMAP=partial1/full; JTAG disabled, SWD kept / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment | fan | - | - | mcu_3v3 |
| FAN_VIN | power_terminal | power_in | protected fan-rated low-voltage input | power | unknown; confirm: Confirm module datasheet, connector polarity, measured no-load voltage, current limit, and common-return plan before energizing | fan | main | 4.75-12.6 V; FAN_VIN is accepted only on the named fan_load rail | fan_load |
| FAN_GND | power_terminal | return | planned common return for driver and tach reference | power | unknown; confirm: Confirm module datasheet, connector polarity, measured no-load voltage, current limit, and common-return plan before energizing | fan | main | 4.75-12.6 V; FAN_GND is accepted only on the named fan_load rail | fan_load |

### 资源预算（全部为 estimated）

| 资源 | 估算范围 | rationale | verification_status |
|---|---|---|---|
| MCU 信号数 | 4 | 从 endpoint_type=mcu_signal 的逐信号行派生，不把 A/B、VCC/GND 或模块端子计入 | derived |
| Flash | 13312-24576 B | temperature PID fan controller: HAL drivers, state logic, diagnostics, and protocol code; verify with linker map | estimated |
| RAM | 1536-4096 B | temperature PID fan controller: static state plus PID history, 32-sample temperature filter, tach periods, and console-free diagnostics; verify map and worst-case stack watermark | estimated |
| MCU 电流 | 20-43 mA | temperature PID fan controller: MCU and board-regulator planning range at documented clocks; excludes every load domain | estimated |
| 负载电流 | 80-700 mA | temperature PID fan controller: external modules and actuators only; size from selected datasheets and stall/startup measurement; upper bound covers the sum of split external-rail budgets at diversity 1.0 | estimated |

<!-- V2_PATTERN_GENERATED:END -->
