# Modbus RTU：V2 全流程项目模式

稳定项目 ID：`industrial-054`。目标为 STM32F103C8Tx LQFP48；下列引脚是条件性建议，实施前确认板版、封装、复用和保留 SWD。**未实机**。

## 需求基线

在低压桌面网络中作为Modbus RTU从站响应寄存器读取 默认量化验收：9600 8N1下正确响应至少3个保持寄存器；CRC错误帧不得改写状态；保存一次可追溯构建或实机证据；未实机不得声称功能验收。可覆写条件：传感器量程、阈值、负载或板版变化时重新验证。

## 方案与 ADR

方案 A 使用 USART TX/RX DE/RE 120Ω 的最小轮询诊断；方案 B 将关键输入转 IRQ 或 DMA；方案 C 在模拟夹具中先验证。ADR-industrial-054：仅在满足本项目响应/采样目标后启用 B，避免为“Modbus RTU”引入不必要的 DMA、IRQ 与 RAM 风险。

## BOM 与替代

默认器件：RS485收发器、120Ω终端、USB-RS485适配器。替代件须保持 3.3V 逻辑、接口时序与负载域隔离；只限隔离低压桌面总线；禁止接生产线或未知带电RS485网络

## 可覆写接线表

逐信号端点类型、电气约束、合法 AF 候选、组件与电源域的唯一可执行表，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份引脚表。

## CubeMX

为 Modbus RTU 启用 USART TX/RX DE/RE 120Ω，RCC 先 HSI 8MHz；仅在确认 HSE 后使用 PLL 72MHz。将本项目使用的 DMA、IRQ 和协议参数（地址/波特率/校验/帧格式）保存进 `.ioc`；IRQ 不打印、不阻塞。

## 资源预算

MCU 信号数、Flash/RAM 区间、MCU/负载分域电流及估算依据，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份数值预算。

## 可构建增量契约

M0 保存 `.ioc`；M1 构建接口自检；M2 用模拟输入验证量化验收；M3 保存 map、DMA/IRQ/协议日志；M4 仅在安全门和一次刷写确认后实机。

## 测试与故障树

接口无响应先查电平、共地与复用；数据异常先查时钟、协议、DMA 缓冲；负载异常立即断开使能并回退 M1。每一分支记录证据。

## 回滚

引脚、时钟、DMA、IRQ、BOM、供电域或协议变化均使本项目后续证据失效；恢复 M0/M1 的 `.ioc`、map 与哈希再逐项重放。

## 安全门

只限隔离低压桌面总线；禁止接生产线或未知带电RS485网络 所有实机动作需可见停机；构建和刷写不等于功能验收。

## C0–C4 创意卡

C0 场景；C1 可测需求；C2 方案 ADR；C3 构建证据；C4 迁移后重新安全复核。

## 发布清单

- [ ] Modbus RTU 的接口、供电域、信号数、Flash/RAM/MCU电流/负载电流预算已复核
- [ ] 接线、CubeMX、DMA、IRQ、协议、测试和回滚证据可追溯
- [ ] 未实机不得声称硬件运行；刷写须一次明确确认

功耗：MCU 与负载分域预算，未实测。

<!-- V2_PATTERN_GENERATED:START sha256=a8ea7e7a312428b79293304347853f81c48cb9606acabd51d8167efc5356757c -->
## Manifest 生成的可覆写工程区块

单一来源：`patterns.json`。目标为 `STM32F103C8Tx LQFP48`，板卡版本未知；下表只列 MCU 合法候选能力，实施前必须根据板卡走线、复用冲突和组件数据手册覆写。`PA13/PA14` 始终保留给 SWD。**未实机（not_tested_on_hardware）**。

### 组件规格边界

| component_ref | 组件 | supply_v | logic_v | current_ma | supply_rails |
|---|---|---|---|---|---|
| rs485_transceiver | 3.3 V half-duplex RS485 transceiver | 3.0-3.6 V; module datasheet and board variant must be confirmed | 0.0-3.3 V; module datasheet and board variant must be confirmed | 1-70 mA; module datasheet and board variant must be confirmed | main: 3.0-3.6 V; module datasheet and board variant must be confirmed / 1-70 mA; module datasheet and board variant must be confirmed / consumer |
| rs485_connector | isolated bench RS485 A/B connector | 0-5.0 V; module datasheet and board variant must be confirmed | 0-5.0 V; module datasheet and board variant must be confirmed | 0-5 mA; module datasheet and board variant must be confirmed | main: 0-5.0 V; module datasheet and board variant must be confirmed / 0-5 mA; module datasheet and board variant must be confirmed / signal_load |
| termination | selectable 120 ohm termination | 0-5.0 V; module datasheet and board variant must be confirmed | 0-5.0 V; module datasheet and board variant must be confirmed | 0-25 mA; module datasheet and board variant must be confirmed | main: 0-5.0 V; module datasheet and board variant must be confirmed / 0-25 mA; module datasheet and board variant must be confirmed / signal_load |

### 电源域

| power_domain_ref | 电源域 | 电压 | intrinsic_current | concurrent consumer peak | 电流预算 | source_capacity | concurrency | 状态 |
|---|---|---|---|---|---|---|---|---|
| mcu_3v3 | MCU regulated 3.3 V signal domain | 3.0-3.6 V; USART1, DE, RE, and transceiver logic supply remain in the 3.3 V domain | 18-55 mA; MCU, clock tree, board regulator losses, and core activity only; external powered ports are excluded | 0 mA | 18-55 mA; Intrinsic maximum plus all connected consumer-port peaks at diversity 1.0; required concurrent maximum is 55 mA | 55-69 mA; Estimated selectable source capability must meet at least the full rail budget before hardware use | diversity=1.0; All connected consumer-port peak currents are assumed simultaneous; no diversity discount is claimed | estimated |
| bus_logic_3v3 | external bus-transceiver 3.3 V rail | 3.0-3.6 V; External bus-transceiver current is outside the MCU core-current estimate | 0-0 mA; No hidden load is assumed; connected component ports define this rail | 70 mA | 1-100 mA; Intrinsic maximum plus all connected consumer-port peaks at diversity 1.0; required concurrent maximum is 70 mA | 100-125 mA; Estimated selectable source capability must meet at least the full rail budget before hardware use | diversity=1.0; All connected consumer-port peak currents are assumed simultaneous; no diversity discount is claimed | estimated |

### 逐信号契约

| function | endpoint_type | direction | electrical | peripheral | candidate_pins / confirmation | component_ref | component_port_ref | required_rail_voltage | power_domain_ref |
|---|---|---|---|---|---|---|---|---|---|
| RS485_TX | mcu_signal | out | 3.3 V alternate-function push-pull | USART1_TX | PA9 / USART1_TX / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PB6 / USART1_TX / AFIO_MAPR_USART1_REMAP=1 / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment | rs485_transceiver | - | - | mcu_3v3 |
| RS485_RX | mcu_signal | in | 3.3 V input; confirm the adapter never drives 5 V | USART1_RX | PA10 / USART1_RX / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PB7 / USART1_RX / AFIO_MAPR_USART1_REMAP=1 / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment | rs485_transceiver | - | - | mcu_3v3 |
| RS485_DE | mcu_signal | out | 3.3 V GPIO push-pull, active-high driver enable | GPIO | PA2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA3 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA4 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA5 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA8 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB0 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB1 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB10 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB11 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB12 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB13 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB14 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB15 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment | rs485_transceiver | - | - | mcu_3v3 |
| RS485_RE | mcu_signal | out | 3.3 V GPIO push-pull, active-low receiver enable | GPIO | PA2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA3 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA4 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA5 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA8 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB0 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB1 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB10 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB11 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB12 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB13 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB14 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB15 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment | rs485_transceiver | - | - | mcu_3v3 |
| RS485_A | bus_terminal | bidirectional | differential RS485 A terminal; never an MCU GPIO | RS485_bus | unknown; confirm: Confirm terminal label, polarity, termination, and protected low-voltage source with the module schematic and continuity test | rs485_connector | - | - | bus_logic_3v3 |
| RS485_B | bus_terminal | bidirectional | differential RS485 B terminal; never an MCU GPIO | RS485_bus | unknown; confirm: Confirm terminal label, polarity, termination, and protected low-voltage source with the module schematic and continuity test | rs485_connector | - | - | bus_logic_3v3 |
| RS485_VCC | power_terminal | power_in | 3.0-3.6 V transceiver supply | power | unknown; confirm: Confirm module datasheet, connector polarity, measured no-load voltage, current limit, and common-return plan before energizing | rs485_transceiver | main | 3.0-3.6 V; RS485_VCC is accepted only on the named bus_logic_3v3 rail | bus_logic_3v3 |
| RS485_GND | power_terminal | return | bench transceiver logic return | power | unknown; confirm: Confirm module datasheet, connector polarity, measured no-load voltage, current limit, and common-return plan before energizing | rs485_transceiver | main | 3.0-3.6 V; RS485_GND is accepted only on the named bus_logic_3v3 rail | bus_logic_3v3 |
| RS485_TERM_120R | bus_terminal | passive | 120 ohm termination enabled only at a physical bus end | RS485_termination | unknown; confirm: Confirm terminal label, polarity, termination, and protected low-voltage source with the module schematic and continuity test | termination | - | - | bus_logic_3v3 |

### 资源预算（全部为 estimated）

| 资源 | 估算范围 | rationale | verification_status |
|---|---|---|---|
| MCU 信号数 | 4 | 从 endpoint_type=mcu_signal 的逐信号行派生，不把 A/B、VCC/GND 或模块端子计入 | derived |
| Flash | 14336-27648 B | Modbus RTU half-duplex slave: HAL drivers, state logic, diagnostics, and protocol code; verify with linker map | estimated |
| RAM | 2048-5376 B | Modbus RTU half-duplex slave: static state plus 256-byte RX/TX rings, frame timer, CRC workspace, register map, and exception log; verify map and worst-case stack watermark | estimated |
| MCU 电流 | 22-48 mA | Modbus RTU half-duplex slave: MCU and board-regulator planning range at documented clocks; excludes every load domain | estimated |
| 负载电流 | 1-100 mA | Modbus RTU half-duplex slave: external modules and actuators only; size from selected datasheets and stall/startup measurement; upper bound covers the sum of split external-rail budgets at diversity 1.0 | estimated |

<!-- V2_PATTERN_GENERATED:END -->
