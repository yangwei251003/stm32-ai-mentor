# 09：硬件执行与 EDA 基准（2026-08-26）

## 结论

本项目采用“本地、窄权限、可复核”的执行层：STM32 的构建/烧录主干只调用 ST 工具，KiCad 是 PCB 的唯一发布源；Flux 仅为用户授权后的云端方案建议和独立审查。没有任何资料支持将构建、flash、仿真或自动检查直接等同于真实硬件功能、制造可行或用户批准。

## 一手资料与采用边界

| 来源 | 已核实能力/许可证 | 本项目借鉴 | 不采用或限制 |
| --- | --- | --- | --- |
| [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html) | `kicad-cli` 提供 ERC、PCB DRC、parity、Gerber、钻孔、坐标、STEP 与 render 等自动化子命令；文档为 GPL-3.0-or-later 或 CC-BY-3.0-or-later | 固定 argv 的 CLI 导出、检查报告和可复现生产包 | 不把任意 CLI 参数或 shell 暴露给 agent；CLI 退出码非实物功能证明 |
| [KiCad IPC API](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/index.html) | KiCad 9/10 IPC 仅连接运行中的 GUI；9/10 不支持经 IPC plotting/export，文档明确可用 CLI 补足 | 交互编辑应使用官方 IPC；检查/发布应使用 CLI | 不把 IPC 当作无 GUI 的文件篡改接口；首版不承诺双向云同步 |
| [Flux MCP](https://docs.flux.ai/reference/flux-mcp-server) | 官方提供 MCP 接入文档与云端电子设计协作能力；服务条款/账号权限独立于本仓库 | 候选架构、评审提示 | 非权威镜像；不得自动回写 KiCad、不得自动发布或下单；不可用不得阻塞本地流程 |
| [STM32CubeCLT](https://www.st.com/en/development-tools/stm32cubeclt.html)、[CubeProgrammer CLI 2.23](https://dev.st.com/stm32cube-docs/prog/2.23.0/en/docs/markup/CubeProg_Command_Lines.html) | ST 官方命令行工具链/烧录命令参考；CLI 文档明确给出 `-r32 <start_address> <size>` 的只读内存命令；具体许可由 ST 安装包 EULA 管辖 | 固定版本、构建/烧录/verify/reset，以及固定 F103 工厂身份地址的只读容量/UID核验 | 不自动接受许可；不开放调用方指定的读取地址、Option Bytes、OTP、RDP、mass erase 或任意内存写 |
| [agentic-hil](https://github.com/agentic-hil/agentic-hil) | README 明示 Apache-2.0；提供策略门控工具、项目外权威配置和 HIL 收据思路 | 设备身份、审批门、收据、主机与调试器隔离 | 不直接安装、复制或授予其命令面；本项目维持自己的 ST 白名单 |
| [platformio-mcp](https://github.com/jl-codes/platformio-mcp) | README 明示 MIT；提供板级安全审计、构建/烧录/监视、结构化诊断与审批策略 | 结构化诊断、持久运行报告、政策可见性 | 不以 PlatformIO 替代 CubeMX/CubeCLT；不自动选择端口或烧录 |

KiCad CLI 文档明确说明可自动执行原理图、PCB 和生产导出，并列出 `pcb drc --schematic-parity`；这是本地一致性检查的依据，不是对布局、连接器方向或装配的保证。KiCad IPC 文档也明确 9/10 的 headless/export 限制，因此本实现没有将 IPC 伪装成无界文件接口。

## 许可证与再利用记录

- 本仓库没有 vendoring、复制或链接上述第三方实现；仅参考公开接口设计与安全模式，因此不产生其代码的再分发。
- agentic-hil 的 Apache-2.0、platformio-mcp 的 MIT 来自各仓库 `LICENSE`/README；若未来复制代码、模板或测试，必须先记录精确 commit、文件、许可证文本、署名/NOTICE 义务与兼容性复审。
- KiCad 文档的双许可证只适用于文档内容；KiCad 程序及 ST/Flux 服务各自遵循其发行/服务条款，安装或上传前需要用户授权。

## 落地的安全差异

`eda-lab-mcp` 限定 workspace，解析后再次确认未越界；只识别唯一 `.kicad_sch` 和 `.kicad_pcb`。设计替换前做快照和 SHA-256，随后原子写入并回读。ERC、DRC、parity、render 和发布只使用服务内部构造的 `kicad-cli` 参数列表。发布清单含 BOM、Gerber、drill、PnP、STEP、render、哈希、收据与未解决问题；没有 `order_board` 工具。

Flux 故障、未登录或未授权上传均只记录为云端辅助不可用，本地 KiCad/固件路径继续可用。任何自动化结论应表达为“工具收据/检查结果”，不得声称已观察到温度、湿度、发热、气味、机械运动或板厂制造质量。
