# 空气质量与通风：V2 全流程项目模式

稳定项目 ID：`environment-017`。目标为 STM32F103C8Tx LQFP48；下列引脚是条件性建议，实施前确认板版、封装、复用和保留 SWD。**未实机**。

## 需求基线

读取空气质量模块的低压模拟/数字输出并提示人工通风 默认量化验收：连续3次超过可覆写等级时显示通风提示；按键确认后静音；保存一次可追溯构建或实机证据；未实机不得声称功能验收。可覆写条件：传感器量程、阈值、负载或板版变化时重新验证。

## 方案与 ADR

方案 A 使用 空气质量 I2C1 OLED 的最小轮询诊断；方案 B 将关键输入转 IRQ 或 DMA；方案 C 在模拟夹具中先验证。ADR-environment-017：仅在满足本项目响应/采样目标后启用 B，避免为“空气质量与通风”引入不必要的 DMA、IRQ 与 RAM 风险。

## BOM 与替代

默认器件：空气质量传感模块、OLED、3.3V蜂鸣器、按键。替代件须保持 3.3V 逻辑、接口时序与负载域隔离；只用于教学趋势，不能作为健康或燃气安全判断；禁止自动控制市电风机

## 可覆写接线表

逐信号端点类型、电气约束、合法 AF 候选、组件与电源域的唯一可执行表，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份引脚表。

## CubeMX

为 空气质量与通风 启用 空气质量 I2C1 OLED，RCC 先 HSI 8MHz；仅在确认 HSE 后使用 PLL 72MHz。将本项目使用的 DMA、IRQ 和协议参数（地址/波特率/校验/帧格式）保存进 `.ioc`；IRQ 不打印、不阻塞。

## 资源预算

MCU 信号数、Flash/RAM 区间、MCU/负载分域电流及估算依据，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份数值预算。

## 可构建增量契约

M0 保存 `.ioc`；M1 构建接口自检；M2 用模拟输入验证量化验收；M3 保存 map、DMA/IRQ/协议日志；M4 仅在安全门和一次刷写确认后实机。

## 测试与故障树

接口无响应先查电平、共地与复用；数据异常先查时钟、协议、DMA 缓冲；负载异常立即断开使能并回退 M1。每一分支记录证据。

## 回滚

引脚、时钟、DMA、IRQ、BOM、供电域或协议变化均使本项目后续证据失效；恢复 M0/M1 的 `.ioc`、map 与哈希再逐项重放。

## 安全门

只用于教学趋势，不能作为健康或燃气安全判断；禁止自动控制市电风机 所有实机动作需可见停机；构建和刷写不等于功能验收。

## C0–C4 创意卡

C0 场景；C1 可测需求；C2 方案 ADR；C3 构建证据；C4 迁移后重新安全复核。

## 发布清单

- [ ] 空气质量与通风 的接口、供电域、信号数、Flash/RAM/MCU电流/负载电流预算已复核
- [ ] 接线、CubeMX、DMA、IRQ、协议、测试和回滚证据可追溯
- [ ] 未实机不得声称硬件运行；刷写须一次明确确认

功耗：MCU 与负载分域预算，未实测。

<!-- V2_PATTERN_GENERATED:START sha256=de1dba2c6da73ee1a9b49672780728ccf9f7c355bd699d66789c6ab8c38037cf -->
## Manifest 生成的可覆写工程区块

单一来源：`patterns.json`。目标为 `STM32F103C8Tx LQFP48`，板卡版本未知；下表只列 MCU 合法候选能力，实施前必须根据板卡走线、复用冲突和组件数据手册覆写。`PA13/PA14` 始终保留给 SWD。**未实机（not_tested_on_hardware）**。

### 组件规格边界

| component_ref | 组件 | supply_v | logic_v | current_ma | supply_rails |
|---|---|---|---|---|---|
| air_sensor | 3.3 V I2C air-quality sensor | 3.0-3.6 V; module datasheet and board variant must be confirmed | 0.0-3.3 V; module datasheet and board variant must be confirmed | 1-60 mA; module datasheet and board variant must be confirmed | main: 3.0-3.6 V; module datasheet and board variant must be confirmed / 1-60 mA; module datasheet and board variant must be confirmed / consumer |
| oled | 3.3 V I2C OLED display | 3.0-3.6 V; module datasheet and board variant must be confirmed | 0.0-3.3 V; module datasheet and board variant must be confirmed | 10-35 mA; module datasheet and board variant must be confirmed | main: 3.0-3.6 V; module datasheet and board variant must be confirmed / 10-35 mA; module datasheet and board variant must be confirmed / consumer |
| fan_driver | logic-level ventilation fan driver | 3.0-5.25 V; module datasheet and board variant must be confirmed | 0.0-3.3 V; module datasheet and board variant must be confirmed | 0-20 mA; module datasheet and board variant must be confirmed | main: 3.0-5.25 V; module datasheet and board variant must be confirmed / 0-20 mA; module datasheet and board variant must be confirmed / signal_load |
| fan | protected low-voltage ventilation fan | 4.75-12.6 V; module datasheet and board variant must be confirmed | 0-3.3 V; module datasheet and board variant must be confirmed | 80-600 mA; module datasheet and board variant must be confirmed | main: 4.75-12.6 V; module datasheet and board variant must be confirmed / 80-600 mA; module datasheet and board variant must be confirmed / consumer |

### 电源域

| power_domain_ref | 电源域 | 电压 | intrinsic_current | concurrent consumer peak | 电流预算 | source_capacity | concurrency | 状态 |
|---|---|---|---|---|---|---|---|---|
| mcu_3v3 | MCU regulated 3.3 V signal domain | 3.0-3.6 V; I2C and fan-enable logic remain at 3.3 V | 18-55 mA; MCU, clock tree, board regulator losses, and core activity only; external powered ports are excluded | 0 mA | 18-55 mA; Intrinsic maximum plus all connected consumer-port peaks at diversity 1.0; required concurrent maximum is 55 mA | 55-69 mA; Estimated selectable source capability must meet at least the full rail budget before hardware use | diversity=1.0; All connected consumer-port peak currents are assumed simultaneous; no diversity discount is claimed | estimated |
| fan_load | independent protected ventilation-fan supply | 4.75-12.6 V; Fan startup current is separated from the sensor rail and verified with a current limit | 0-0 mA; No hidden load is assumed; connected component ports define this rail | 600 mA | 80-700 mA; Intrinsic maximum plus all connected consumer-port peaks at diversity 1.0; required concurrent maximum is 600 mA | 700-875 mA; Estimated selectable source capability must meet at least the full rail budget before hardware use | diversity=1.0; All connected consumer-port peak currents are assumed simultaneous; no diversity discount is claimed | estimated |
| sensor_3v3 | external module 3.3 V rail | 3.0-3.6 V; External sensor or display current is separated from MCU core current and constrained to 3.3 V logic | 0-0 mA; No hidden load is assumed; connected component ports define this rail | 95 mA | 11-100 mA; Intrinsic maximum plus all connected consumer-port peaks at diversity 1.0; required concurrent maximum is 95 mA | 100-125 mA; Estimated selectable source capability must meet at least the full rail budget before hardware use | diversity=1.0; All connected consumer-port peak currents are assumed simultaneous; no diversity discount is claimed | estimated |

### 逐信号契约

| function | endpoint_type | direction | electrical | peripheral | candidate_pins / confirmation | component_ref | component_port_ref | required_rail_voltage | power_domain_ref |
|---|---|---|---|---|---|---|---|---|---|
| AIR_SCL | mcu_signal | bidirectional | 3.3 V open-drain; external pull-up required and total pull-up value must be confirmed | I2C1_SCL | PB6 / I2C1_SCL / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PB8 / I2C1_SCL / AFIO_MAPR_I2C1_REMAP=1 / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment | air_sensor | - | - | mcu_3v3 |
| AIR_SDA | mcu_signal | bidirectional | 3.3 V open-drain; external pull-up required and total pull-up value must be confirmed | I2C1_SDA | PB7 / I2C1_SDA / none / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment<br>PB9 / I2C1_SDA / AFIO_MAPR_I2C1_REMAP=1 / Confirm STM32F103C8Tx LQFP48 package, board routing, remap, and pin conflicts before assignment | air_sensor | - | - | mcu_3v3 |
| OLED_SCL | module_signal | bidirectional | shared 3.3 V open-drain SCL net; one external pull-up set is required | I2C1_SCL | unknown; confirm: Trace the named module pin/net on its schematic and confirm voltage, pull-ups, and connector orientation before wiring | oled | - | - | mcu_3v3 |
| OLED_SDA | module_signal | bidirectional | shared 3.3 V open-drain SDA net; one external pull-up set is required | I2C1_SDA | unknown; confirm: Trace the named module pin/net on its schematic and confirm voltage, pull-ups, and connector orientation before wiring | oled | - | - | mcu_3v3 |
| VENT_FAN_ENABLE | mcu_signal | out | 3.3 V GPIO push-pull; external driver required for loads | GPIO | PA2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA3 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA4 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA5 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PA8 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB0 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB1 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB2 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB10 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB11 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB12 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB13 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB14 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment<br>PB15 / GPIO_output / none / Confirm STM32F103C8Tx LQFP48 package, board routing, GPIO availability, and all peripheral conflicts before assignment | fan_driver | - | - | mcu_3v3 |
| FAN_VIN | power_terminal | power_in | protected fan-rated low-voltage input | power | unknown; confirm: Confirm module datasheet, connector polarity, measured no-load voltage, current limit, and common-return plan before energizing | fan | main | 4.75-12.6 V; FAN_VIN is accepted only on the named fan_load rail | fan_load |
| FAN_GND | power_terminal | return | planned common return at the driver | power | unknown; confirm: Confirm module datasheet, connector polarity, measured no-load voltage, current limit, and common-return plan before energizing | fan | main | 4.75-12.6 V; FAN_GND is accepted only on the named fan_load rail | fan_load |
| AIR_SENSOR_VCC | power_terminal | power_in | 3.0-3.6 V air-sensor supply | power | unknown; confirm: Confirm component datasheet, named supply port, connector polarity, measured no-load voltage, source current limit, and return path before energizing | air_sensor | main | 3.0-3.6 V; AIR_SENSOR_VCC is accepted only on the named sensor_3v3 rail | sensor_3v3 |
| AIR_SENSOR_GND | power_terminal | return | air-sensor return | power | unknown; confirm: Confirm component datasheet, named supply port, connector polarity, measured no-load voltage, source current limit, and return path before energizing | air_sensor | main | 3.0-3.6 V; AIR_SENSOR_GND is accepted only on the named sensor_3v3 rail | sensor_3v3 |
| OLED_VCC | power_terminal | power_in | 3.0-3.6 V OLED supply | power | unknown; confirm: Confirm component datasheet, named supply port, connector polarity, measured no-load voltage, source current limit, and return path before energizing | oled | main | 3.0-3.6 V; OLED_VCC is accepted only on the named sensor_3v3 rail | sensor_3v3 |
| OLED_GND | power_terminal | return | OLED return | power | unknown; confirm: Confirm component datasheet, named supply port, connector polarity, measured no-load voltage, source current limit, and return path before energizing | oled | main | 3.0-3.6 V; OLED_GND is accepted only on the named sensor_3v3 rail | sensor_3v3 |

### 资源预算（全部为 estimated）

| 资源 | 估算范围 | rationale | verification_status |
|---|---|---|---|
| MCU 信号数 | 3 | 从 endpoint_type=mcu_signal 的逐信号行派生，不把 A/B、VCC/GND 或模块端子计入 | derived |
| Flash | 13312-24576 B | air-quality display and ventilation: HAL drivers, state logic, diagnostics, and protocol code; verify with linker map | estimated |
| RAM | 1792-4608 B | air-quality display and ventilation: static state plus sensor baseline state, filtered trend window, OLED lines, and fan hysteresis; verify map and worst-case stack watermark | estimated |
| MCU 电流 | 21-46 mA | air-quality display and ventilation: MCU and board-regulator planning range at documented clocks; excludes every load domain | estimated |
| 负载电流 | 91-800 mA | air-quality display and ventilation: external modules and actuators only; size from selected datasheets and stall/startup measurement; upper bound covers the sum of split external-rail budgets at diversity 1.0 | estimated |

<!-- V2_PATTERN_GENERATED:END -->
