# 新 OSS Venture 研究与决策

**作者：Manus AI**  
**研究日期：2026-08-15**  
**结论：创建 `mcp-shipcheck`，一个在发布前从已安装分发包启动 MCP server、握手并验证 `tools/list` 合约的零模型 CLI。**

## 研究方法与样本

本研究没有以 Star 作为需求代理。它组合了仓库活跃度、公开的开放 Issue、Discussions、已关闭未合并 PR 与维护者文档。样本涵盖 OpenHands、Cline、Continue、Goose、官方 MCP servers、Semgrep、zizmor、GUAC、GuardDog、mcpserver-audit 及 Cisco 的 MCP 测试实现。`awesome-mcp-servers` 已汇集大量 MCP server，说明“新建一个泛 MCP server”不是空白市场，而是高度拥挤的供给侧市场。[1]

> 这里的“真实痛点”指的是公开、可访问的 Issue、Discussion 或 PR 中由用户/维护者明确描述的问题；它不等同于市场规模估算。

| 代表项目 | 研究材料 | 关键观察 |
|---|---|---|
| `modelcontextprotocol/servers` | 公开 Issue、已关闭 PR、发布流水线变更 | 兼容性、安装、路径、持久化、安全边界和跨平台回归同时存在，且 package/release 与源码行为分离。|
| Cline、Continue、Goose、OpenHands | 高互动 Issue、Discussion、未合并 PR | 代理工具普遍在终端、编辑、provider、长会话、后台任务和取消语义上出现运行时断裂。|
| Semgrep、zizmor、GuardDog、GUAC | 功能请求与 bug | 安全与 CI 工具需要机器可消费的输出、离线可靠性、准确告警、可执行的下一步以及稳定配置。|
| `mcptoolkit-test`、`mcpserver-audit` | 方法论文档与项目结构 | 一边是广义契约测试路线，一边是静态安全审计；二者均没有将“**已发布包能否在干净环境中启动并保留 MCP 工具面**”做成一个 60 秒运行的狭窄发布门。|

## 已验证的真实痛点（23 项）

| # | 真实痛点 | 公开证据 | 可转化的工程含义 |
|---:|---|---|---|
| 1 | npm 发布包没有携带源码中的环境变量行为。 | 官方 memory server 的 `MEMORY_FILE_PATH` 在已发布包中不生效。[2] | 必须测试**安装后的产物**，不能只测试 checkout。|
| 2 | 用户在客户端添加 MCP server 时遇到模块缺失。 | 官方 servers 的 “No Module Error” 安装问题。[3] | 启动冒烟测试应明确报告 executable/模块/工作目录失败。|
| 3 | server 对不同 client/SDK 发生静默兼容性破坏。 | filesystem server 在 OpenAI Agent SDK 中停止工作。[4] | 发布前应记录并比较基础协议能力和工具表面。|
| 4 | memory server 的安全持久化默认值缺少原子写、配额、脱敏和破坏性操作保护。 | 官方 server 的集中改进请求。[5] | 运行时验证需将工具的写入/破坏性标识与结构化基线保留下来。|
| 5 | 官方 tools 普遍缺少 input schema 的长度、模式、枚举限制。 | 跨七个 server 的安全审计发现。[6] | 合约基线需显示 schema 约束缺失，便于保持或改善。|
| 6 | 高影响 browser automation 默认缺少 guardrails。 | Puppeteer server 的专项请求。[7] | 工具表面变化本身应被清晰显示，供 maintainer 决定是否需要额外审查。|
| 7 | filesystem server 在云盘/lazy provider 路径会挂起。 | macOS CloudStorage 递归搜索问题。[8] | 进程启动和协议调用必须有可配置超时，而不是无限等待。|
| 8 | 文件系统工具在不同 Windows、macOS 配置中失败。 | Windows 路径、EPERM 替换与 transport early-exit 报告。[9] [10] | 干净环境/显式 command/timeout 的失败证据比“本机可用”更有价值。|
| 9 | coding agent 的终端集成跨 shell 和平台不可靠。 | Cline 的高互动终端可靠性 Issue。[11] | agent 内建运行轨道不适合代替独立可复现的发布验证。|
| 10 | agent 的文件编辑/替换工具会失败。 | Cline 文件编辑可靠性 Issue。[12] | 不可把 agent 声称“已修改/已验证”作为发布证据。|
| 11 | 大上下文/大文件导致 agent 不可靠。 | Cline context window 与大文件 Issue。[13] | 发布门应保持常数级、无 LLM 的轻量职责。|
| 12 | MCP 子进程在 editor 环境无法找到 `npx`。 | Continue 的 MCP server 启动 Issue。[14] | CLI 应捕获、分类并展示 PATH/executable 启动失败。|
| 13 | agent 会把 API key 以明文保存。 | Continue 的明文 key Issue。[15] | 运行日志和 snapshot 必须默认不记录 tool arguments、环境变量或响应正文。|
| 14 | unattended recipe 在首次 tool call 即失败，配置被静默忽略且任务会永久卡住。 | Goose scheduler Issue。[16] | 无人值守 CI 应只依赖确定性、可退出的 protocol check。|
| 15 | 长会话恢复时无限 replay，无法重新使用。 | Goose ACP session restore Issue。[17] | 需限制检查的超时、最大读取量和退出路径。|
| 16 | security scanner 缺少 SARIF 输出。 | GuardDog 的 SARIF 功能请求。[18] | 安全/CI 工具需提供稳定、机器可消费 JSON/SARIF，而非仅人类文本。|
| 17 | dependency/security graph 用户不知道“下一项最应修的关键依赖”。 | GUAC “next actionable critical dependency” 功能请求。[19] | 输出应强调**可行动的变化**，不要堆积原始元数据。|
| 18 | CI scanner 在离线校验时仍试图拉取 registry。 | Semgrep `--validate` 行为 Issue。[20] | MVP 需零网络、零 registry、可离线运行。|
| 19 | CI policy 用户希望自动修复过度权限。 | zizmor `--fix` 请求。[21] | 工具应产生精确 diff/建议，减少 review 噪声。|
| 20 | tool-call approval 与 hook 执行顺序可能违背用户的审批预期。 | Cline 已关闭未合并 hook 顺序 PR。[22] | 要避免运行未知工具；发布检查只执行 handshake 和 `tools/list`。|
| 21 | UI/CLI E2E 测试依赖 live API 与 key，导致慢、脆弱、不可离线。 | Cline 未合并 VCR fixture PR。[23] | MCP 发布门应没有模型、无网络、可在 CI 做 deterministic replay。|
| 22 | messages 在 agent 忙碌时消失，request queuing 方案长期停滞。 | Cline 的已关闭 request queue PR。[24] | 发布验证不能依赖交互式 agent session，必须单进程、单输出。|
| 23 | MCP 契约测试本身要处理 state、非确定性、复杂 schema、协议演进和非 HTTP 错误。 | Cisco MCP contract-testing 方法论。[25] | 先聚焦最稳定、最高信号的 release surface：启动、initialize、`tools/list` 与 break classification。|

## 候选方向与评分

评分范围为 1–10。**competition** 是“竞争有利度”，即 10 表示直接可替代品少、细分入口清楚，而非“竞争者数量越多越高”。评分同时考虑三项既有仓库边界。

| 候选项目 | real demand | competition | differentiation | technical depth | build feasibility | OSS usefulness | growth potential | ecosystem fit | 总分 /80 | 结论 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **MCP ShipCheck：已安装发布包的启动与工具合约门** | 9 | 8 | 9 | 7 | 10 | 9 | 8 | 8 | **68** | **选中** |
| MCP schema fuzz/security benchmark | 8 | 4 | 5 | 9 | 5 | 8 | 7 | 6 | 52 | 与 mcp-verify、audit 项目重叠高。|
| MCP config doctor（client 配置诊断） | 8 | 5 | 5 | 5 | 9 | 7 | 6 | 6 | 51 | 易沦为安装教程，缺少 release-grade 长期护城河。|
| AI agent session/replay debugger | 8 | 5 | 6 | 9 | 4 | 7 | 7 | 5 | 51 | 平台耦合、范围过大，60 秒价值不清晰。|
| AI code-review finding ratchet | 7 | 3 | 4 | 7 | 7 | 7 | 7 | 3 | 45 | 合理并入 PatchWitness。|
| CI permission auto-remediator | 8 | 3 | 4 | 7 | 6 | 8 | 7 | 4 | 47 | 以 PR/CI policy 为核心，合理并入 PatchWitness。|
| Agent instruction conflict/approval planner | 7 | 5 | 4 | 7 | 7 | 7 | 6 | 2 | 45 | 合理并入 GuardSpec。|
| Issue-to-verified-fix executor | 8 | 2 | 3 | 8 | 4 | 7 | 7 | 1 | 40 | 合理并入 TaskToPR。|

## 最终选择：MCP ShipCheck

**一句话价值主张：**在发布 MCP server 前，对已经安装到干净虚拟环境的分发包执行 JSON-RPC initialize 与 `tools/list`，存下安全的工具合约快照；下一次运行只在 client 可见的能力发生破坏性变化时失败。

其 killer feature 是 `mcp-shipcheck verify`：用户在 CI 中对**真实 install command 与真实 server command**运行一次，即得到启动失败分类、协议错误或成功 snapshot。随后 `mcp-shipcheck compare` 能在不读 tool arguments、环境变量或 tool output 的前提下，指出删除/重命名工具、必填 input 新增、input 类型变化和 server capability 变化。

它不是泛用 MCP 测试框架，不运行 tool call，不 fuzz，不做漏洞判定，也不负责 client 配置。这个故意狭窄的边界使其在短时间内给出强证据，同时不会碰潜在有副作用的工具。

## 创建新仓库前的独立性判断

| 现有项目 | 核心职责 | ShipCheck 是否可合理并入？ | 判断依据 |
|---|---|---|---|
| PatchWitness | 对已经存在的代码变更做 scope、受保护路径、执行检查、secret 与 Change Passport 证据验证。 | **否。** | ShipCheck 以 release artifact 为输入，通过 MCP JSON-RPC 给 server 做黑盒协议生命周期检查；它不读 diff，不做 policy gate，也不签发 Change Passport。可以由 PatchWitness 调用，但不应成为其 feature。|
| GuardSpec | 在 agent 开始前把仓库指令转换为 paths/commands/network/MCP 的允许边界。 | **否。** | ShipCheck 是 server maintainer 的发布兼容性测试，不判断某次 agent 运行是否获准。它只启动用户明确提供的 command 并在握手后停下。|
| TaskToPR | 将单一 Issue 变成隔离分支、真实测试与可选 PR，并保存过程证据。 | **否。** | ShipCheck 不创建/修改代码、不调用模型、不创建分支或 PR；它可以作为 TaskToPR 所产出 server 的检查项，但具有独立的语言、包管理器和 CI 使用者。|

## MVP 规格与非目标

MVP 采用标准库 Python，接受 shell command（参数以 `--` 之后传入），与 stdio MCP server 进行仅两次请求：`initialize`、`tools/list`。它生成 JSON snapshot，比较时按照名称、input schema 的 `required`、type、enum/const、server capabilities 生成 breaking/non-breaking 结果。MVP 包含 CLI、公共 Python API、测试、fixture server、真实 demo、GitHub Actions、MIT LICENSE、安全策略、贡献指南和已知限制。

非目标包括：执行 `tools/call`、存储/记录秘密、替代完整 contract/fuzz 测试框架、判断安全漏洞、托管 MCP server、或替代现有三项目的 agent policy/PR/patch 工作流。MVP 也不模拟所有远程 HTTP/SSE/streamable transport；它首先提供可移植、最小权限、最易纳入发布流程的 stdio 路径。

## 参考资料

[1]: https://github.com/punkpeye/awesome-mcp-servers "awesome-mcp-servers"
[2]: https://github.com/modelcontextprotocol/servers/issues/1018 "Environment variables not respected in memory package"
[3]: https://github.com/modelcontextprotocol/servers/issues/1836 "No Module Error"
[4]: https://github.com/modelcontextprotocol/servers/issues/3051 "Filesystem server stopped working with OpenAI Agent SDK"
[5]: https://github.com/modelcontextprotocol/servers/issues/4117 "Safer memory persistence defaults"
[6]: https://github.com/modelcontextprotocol/servers/issues/3537 "Unconstrained string parameters audit"
[7]: https://github.com/modelcontextprotocol/servers/issues/4118 "Puppeteer guardrails"
[8]: https://github.com/modelcontextprotocol/servers/issues/4162 "Filesystem recursive search hangs"
[9]: https://github.com/modelcontextprotocol/servers/issues/447 "Windows paths"
[10]: https://github.com/modelcontextprotocol/servers/issues/1748 "Transport closed unexpectedly"
[11]: https://github.com/cline/cline/issues/4356 "Terminal integration reliability"
[12]: https://github.com/cline/cline/issues/4384 "File editing tool reliability"
[13]: https://github.com/cline/cline/issues/4389 "Context management and large files"
[14]: https://github.com/continuedev/continue/issues/4791 "npx unavailable for MCP"
[15]: https://github.com/continuedev/continue/issues/1729 "Plain-text API keys"
[16]: https://github.com/aaif-goose/goose/issues/11164 "Unattended recipes fail"
[17]: https://github.com/aaif-goose/goose/issues/10764 "Unresumable long sessions"
[18]: https://github.com/DataDog/guarddog/issues/197 "SARIF output request"
[19]: https://github.com/guacsec/guac/issues/1505 "Next actionable critical dependency"
[20]: https://github.com/semgrep/semgrep/issues/4620 "Offline validation pulls registry"
[21]: https://github.com/zizmorcore/zizmor/issues/1958 "Fix excessive permissions"
[22]: https://github.com/cline/cline/pull/7356 "Approval/hook ordering"
[23]: https://github.com/cline/cline/pull/9797 "Offline VCR E2E fixtures"
[24]: https://github.com/cline/cline/pull/7112 "Request queuing"
[25]: https://github.com/cisco-open/mcptoolkit-test/blob/main/docs/maintainers/mcp-contract-testing-methodology.md "MCP Contract Testing Methodology"
[26]: https://github.com/ModelContextProtocol-Security/mcpserver-audit "mcpserver-audit"

*原始研究材料位于本工作目录的 `raw/`、`issue-evidence.csv`、`discussion-evidence.md` 与 `rejected-pr-evidence.md`。*
