# EDA 执行工作流：KiCad 为唯一发布源

`eda-lab-mcp` 只服务允许的 workspace 白名单，且仅公开：`design_inspect`、`design_snapshot`、`schematic_apply_transaction`、`pcb_apply_transaction`、`erc_run`、`drc_run`、`parity_run`、`render_run`、`release_export`。它不是通用终端，也不写项目账本。

本机安装官方 `kicad-python` 绑定用于探测和连接 KiCad 10 的运行中 GUI IPC。KiCad 10 没有 headless IPC/export，原理图覆盖也不等同于 PCB API；因此当前整文件事务只允许在没有活动 GUI IPC 会话时离线执行并明确标记 `offline_atomic_file_replace`。检测到 GUI 时必须停止，后续 PCB 细粒度编辑只能实现成结构化 IPC 操作，不能偷偷改磁盘文件。

## 受控操作

- `inspect` 识别且只接受一个 `.kicad_sch` 与一个 `.kicad_pcb`；路径解析后必须仍在 whitelist 中。设计文件、元数据、快照和运行目录都拒绝符号链接、junction 或其他重解析点。
- 每次设计事务先写快照和 SHA-256，然后只可替换发现的唯一原理图或 PCB 文件。请求须给出完整、受控格式内容；写后从磁盘回读并比较哈希。失败时自动恢复事务前快照，不得指定任意目标路径。
- KiCad 不可执行时，ERC/DRC/一致性、渲染和发布均结构化 fail-closed，不伪造“通过”。所有 KiCad 调用均为执行层固定拼装的 argv 白名单，无 shell/raw arguments。
- ERC、DRC、原理图—PCB parity、顶层渲染和生产导出产生独立收据；CLI 退出失败不标为设计通过。渲染与自动检查也不替代人工审核安装孔、连接器方向、丝印和机械干涉。

## 发布门

先以同一 pin manifest 和 MPN/数据手册台账生成原理图/PCB；人工锁定板框、连接器、安装孔和关键器件。低压温湿度载板先支持外接 Nucleo-F103RB 或已核实的 F103C8，而不是首板直接做裸 MCU。

`release_export` 先冻结原理图/PCB 源哈希并保存快照，再重跑 ERC、DRC、parity，固定导出 BOM、Gerber、钻孔、PnP、STEP、层图/渲染和 SHA-256 清单。导出期间源文件发生变化时整包作废。发布账本必须同时引用 ERC、DRC、parity、渲染和 CAM 哈希及未解决问题。用户明确批准后才可向板厂交付；系统没有自动下单能力。

Flux MCP 仅在 `cloud_policy` 明确允许上传时作为候选架构和独立审查镜像。它不是权威设计源、没有双向同步权限，任何采纳项必须在本地 KiCad 回写并重跑全部检查。Flux 不可用不得阻塞本地 KiCad/固件流程。
