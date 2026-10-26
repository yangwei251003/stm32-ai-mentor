# V2 项目生成工作流

V2 是按需启用的项目侧车。它把完整项目拆成可验证增量，独立写入
`Projects/<project_id>/` 下的 `generation.*` 事件账本；绝不修改
`Student_Profile/`，也不复制 V1 掌握度。V2 可以引用稳定的 V1 evidence ID，
但不做跨账本双写。

## ProjectIntake

`ProjectIntake` 由 `project-intake.schema.json` 定义，必须包括：明确且量化的目标；
带稳定 ID、非空验收引用的需求和结构化量化验收；MCU、封装、板卡、板卡版本和工具链
构成的规范化 target signature；已有器件、预算和时间；结构化 `resource_plan`；
安全状态与专项门；必需阶段；最多 3 个澄清问题；以及唯一一个 `next_action`。
未知事实写成 unknown，不能伪装成默认事实；unknown 会阻止 baseline、精确接线、
实现和 release。

每项 acceptance criterion 必须显式包含 `metric`、`operator`、数值或范围
`threshold`、`unit`、`window` 和 `observation_method`。量化只由这些结构字段决定，
requirement 文本本身只负责绑定 acceptance，文本中的“智能车 2.0”既不能绕过也不会
误触发量化判断。toolchain 只接受分开的 `ide{name,version}`、
`firmware_package{name,version}`、`compiler{name,version}` 与
`programmer{name,version?}`；不能让一串文本共用一个版本号。

当用户没有任何硬件时，先读取 `procurement-workflow.md`。`exact_target`、`resources` 和
`hardware_identity` 不由用户凭技术名词填写：导师先生成需求说明草案，经用户确认后提供
2–3 个方案卡；用户确认选项后再形成精确目标、选中 BOM 和分批购物清单。采购前记录
`procurement.inventory_status=none_owned`，需求、方案与购物清单分别确认。未确认的候选方案
不能冻结 baseline；已选择/已下单也不等于已收到或已核验。到货照片、标签、数据手册与测量
完成后才创建 `hardware_identity`，并允许依赖实物身份的确定接线与烧录。

一票否决市电/高压、大功率电机、无保护锂电充放电、医疗诊断和安全关键控制。
Blue Pill 只是一类第三方板型，精确引脚与供电结论必须绑定实物版本。

`resources` 使用非占位的 component 对象、正数 `budget{amount,currency}` 和
`time_limit{hours,deadline}`。`resource_plan` 明确 pins 的具体 signal/function、clock、DMA、IRQ、Flash/RAM 预算和各电源 rail 的
电压/最大电流及 load 电压/电流。重复 pin/AF、DMA/IRQ 冲突、USB 非 48 MHz、
STM32F103C8 超过 64 KiB Flash 或 20 KiB RAM、未知负载及供电不足都会阻止
baseline、hardware_plan 和 release。STM32F103C8 LQFP48 的 pin 与 AF/peripheral
signal→pin/AF 组合按能力表检查；DMA channel→function、IRQ→function 也按白名单检查；
PZ99、不可能 AF、非法 DMA/IRQ，以及不满足 SYSCLK≥HCLK≥PCLK1/PCLK2 的时钟直接拒绝。

超声/HC-SR04/Echo/回波一旦进入 MCU 接线范围，必须提供
`safety.echo_interface` 的模块输出电压、≤3.6 V 的 MCU 上限、分压或电平转换方法，
以及电阻值或依据来源；任何直接连接表达都阻断。电机项目必须提供
`safety.motor_driver`，且同型号驱动器必须存在于 components 清单；GPIO 直连电机
无论措辞如何都阻断。

## StageResult、增量与阶段门

`StageResult` 由 `stage-result.schema.json` 定义。不可删除、不可乱序的核心阶段是
requirements → design → resources → hardware_plan → implementation → build →
hardware_acceptance；允许在核心门之后追加项目专用阶段。每个 passed 结果必须绑定当前
`baseline_hash` 和已有证据；前置阶段未通过时不能越级。目标或 baseline 改变会把
旧阶段和旧证据标成 stale，必须重新验证。

固件按 `increment_id` 记录可逆增量。每个增量必须有已核验的 build/compile/link
证据、预期观察、结构化实际观察（expected/observed/result/evidence_id）及当前 baseline
的逻辑、runtime 或测量证据，并提供 `supported=true` 的结构化 rollback：枚举 step
动作、账本已有 baseline/evidence artifact hash 或引用，以及结构化 verification action。
只有 passed 观察派生 `complete=true`；调用方传入的 complete 不受信任。tool 仅能提供
逻辑/runtime 观察，instrument/hardware 来源仅能提供测量或硬件观察；外部文档不能冒充观察。
implementation、build 和 release 要求至少一个当前且完整的增量。

release 阶段门同时检查：需求到验收的引用完整；精确目标无 unknown；资源明确；
安全门通过；所有必需阶段基于当前 baseline 通过；每项验收有当前、已核验、来源
可追踪的证据；`known_not_verified` 为空。硬件验收必须有独立 V5 实物证据。

## 证据

`Evidence` 由 `generation-evidence.schema.json` 定义，采用 V0 文档、V1 配置、V2
编译链接、V3 资源、V4 主机逻辑、V5 实物的分级。编译成功只证明能构建；烧录
成功只证明一次写入结果，二者都不会自动覆盖功能验收或写成 hardware-verified。
`reported_by_user` 永远保留来源并归为 self_reported，不能冒充导师或工具独立观察。
只有 `instrument_capture` 或 `verified_hardware_tool` 可产生 hardware-verified V5；还须
同时绑定 current baseline、target signature、artifact hash、raw evidence hash、operator、
带时区 timestamp 和可复现步骤。`tool`、`imported_reference` 与 self-reported 证据永远
不能覆盖 acceptance。

安全扫描先做 Unicode NFKC 与大小写、连字符、下划线、空格归一化，再按组件、电压、
端点、负载和“接/直连”类别判断。HC-SR04/超声 Echo 的 5V/5伏/五伏直接 GPIO、IO口
或 PAx/PBx，以及 GPIO 直接 motor/电机/马达，均不可由 `safety.status=passed` 覆盖。

每次烧录必须先记录一次明确确认，确认绑定由规范化 exact target 推导的 target
signature、当前 baseline hash 和 artifact SHA-256；target/baseline 变化会使未消费
确认失效，确认消费后不能复用。`project_tool.py` 只记录确认和结果，不调用
烧录器，也不执行自动烧录。

## CLI 用法

```text
python scripts/project_tool.py --store Projects init --project-id desk-sensor --payload-json <ProjectIntake-JSON>
python scripts/project_tool.py --store Projects status --project-id desk-sensor
python scripts/project_tool.py --store Projects validate --project-id desk-sensor
python scripts/project_tool.py --store Projects record --project-id desk-sensor --event-type generation.evidence_recorded --payload-json <JSON> --expected-revision 2 --idempotency-key ev-build-1
python scripts/project_tool.py --store Projects record --project-id desk-sensor --event-type generation.procurement_updated --payload-json <procurement-JSON> --expected-revision 2 --idempotency-key procurement-1
python scripts/project_tool.py --store Projects checkpoint --project-id desk-sensor --payload-json <StageResult-JSON> --expected-revision 3 --idempotency-key stage-build-1
python scripts/project_tool.py --store Projects rebuild --project-id desk-sensor
python scripts/project_tool.py --store Projects release --project-id desk-sensor --payload-json <release-JSON> --expected-revision 9 --idempotency-key release-1
```

`events/events.jsonl` 是权威账本，`state.json` 是可重建快照。写入要求当前
`expected_revision` 和非空规范幂等键；事件先落盘并 fsync，快照再原子替换。快照落后时
恢复，同 revision 分歧、快照超前、坏哈希链或不能证明可安全接管的锁都 fail closed。
