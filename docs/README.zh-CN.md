<!-- gda-readme-i18n: source=README.md sha256=2e633d09b48794d0d129d4ec85bd48d23cec200fab96ad0803f0c5727e8ec6a5 -->

# gda — 面向 AI Agent 的 Godot 自动化

[![gda — 面向 AI Agent 的 Godot 自动化](https://raw.githubusercontent.com/aigengame/godot-agent/main/assets/godot-agent-title.png)](https://aigengame.xyz/zh/)

**其他语言:** [English](../README.md) · **简体中文** · [Español](README.es.md) · [日本語](README.ja.md)

[产品概览](https://aigengame.xyz/zh/) ·
[CLI、Agent Skill 还是 MCP？](https://aigengame.xyz/zh/godot-mcp/) ·
[PyPI](https://pypi.org/project/gda/)

> **让 Coding Agent、Shell 脚本与 CI 构建并验证 Godot 项目。**
> `gda` 通过 CLI、随包附带的 Agent Skill 和 MCP server 提供同一套遵循 Godot
> 语义的操作，并返回 Agent 可直接处理的结构化结果。

[![pre-1.0](https://img.shields.io/badge/status-pre--1.0-orange)](https://pypi.org/project/gda/)
[![CI](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Godot](https://img.shields.io/badge/godot-4.4%2B%20(live%204.6%2B)-478CBF)](https://godotengine.org)
[![Platform](https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-lightgrey)](#how-it-works)
[![MCP](https://img.shields.io/badge/MCP-server-000)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

文件修改完成，不代表游戏改动已经通过验证。`gda` 用两种互补模式补上验证环节：

- **Headless** — 无需编辑器插件或 daemon，即可创建和编辑项目内容、编译脚本、
  校验并启动场景、检查项目以及导出构建产物。
- **Live** — 通过项目级 daemon 检查并操控运行中的游戏：读取运行时场景树与状态、
  模拟输入、捕获画面、收集日志和错误以及测量性能。

> `gda` 处于 **pre-1.0** 阶段：目前每条命令都能端到端跑通，但在 1.0 之前命令界面
> 仍可能变化。

---

## 目录

- [为什么选择 `gda`？](#why-gda)
- [能力速览](#capabilities-at-a-glance)
- [安装](#installation)
- [快速上手](#quick-start)
- [选择你的集成方式](#choose-your-integration)
- [工作原理](#how-it-works)
- [命令参考](#command-reference)
- [配置](#configuration)
- [贡献](#contributing)
- [许可证](#license)

---

<a id="why-gda"></a>
## 为什么选择 `gda`？

- **验证不止于文件修改。** Headless 校验确认项目已具备运行条件；Live 操作则以运行时
  证据验证实际行为。
- **结构化结果与可发现的 Schema。** 使用 `--json` 时，每条命令只在 stdout 输出一个
  结果对象。带类型的输入和输出模型同时支撑 `--schema` 与自动生成的 MCP 工具界面。
- **遵循 Godot 语义的操作。** 命令沿用 Godot 的对象和术语，例如
  `gda scene create`、`gda node add` 和 `gda game get`。
- **三种互补接入方式。** Agent、Shell 或 CI 可直接运行 CLI；需要可复用的操作指导时安装
  随包附带的 Agent Skill；需要工具发现与调用时，将同一套操作暴露为 MCP 工具。
  接入方式的对比与取舍详见 [CLI、Agent Skill 还是 MCP？](https://aigengame.xyz/zh/godot-mcp/)。
- **边界明确，失败后可恢复。** 超时、输出上限、类型化失败、诊断信息和变更报告，能帮助
  Agent 判断发生了什么以及如何恢复。

这些能力经过[真实游戏制作中的公开 dogfooding](https://github.com/aigengame/godot-agent/milestone/10)
持续验证与打磨。

---

<a id="capabilities-at-a-glance"></a>
## 能力速览

| 目标 | `gda` 提供 | 从这里开始 |
| --- | --- | --- |
| 构建 Godot 项目内容（Headless） | 创建和编辑场景、节点、脚本、资源、项目设置、着色器与主题 | `scene` / `node` / `script` / `resource` / `project` / `shader` / `theme` |
| 验证项目就绪状态（Headless） | 编译脚本、校验依赖、在限定时间内启动场景、检查项目以及导出构建产物 | `script validate` / `scene validate` / `scene preflight` / `project` / `export` |
| 验证运行时行为（Live） | 读取运行时状态、调用已声明的方法、模拟输入、捕获画面、收集日志和错误以及测量性能 | `gda daemon start`，然后使用 `game` / `input` / `screen` / `diag` / `logger` / `perf` |
| 接入 Coding Agent | 使用 CLI 直接执行、Agent Skill 可复用指导，或 MCP 工具发现与调用 | `gda` / `gda skill` / `gda-mcp` |
| 在自动化环境中可靠运行 | 获得结构化结果、带类型的 Schema 与失败信息、明确的执行边界、隔离日志和可直接处理的诊断信息 | `--json` / `--schema` / `--user-data-root` / 超时设置 |

---

<a id="installation"></a>
## 安装

**环境要求：** Python 3.13+，以及一个 [Godot](https://godotengine.org) 二进制文件——
Headless 命令需要 4.4+，macOS/Linux 上的 Live（daemon）命令需要 4.6+。

把 CLI 从 PyPI 安装到你的 `PATH` 上：

```bash
uv tool install gda      # or: pipx install gda
gda --help
```

<details>
<summary>其他安装方式（pip、从源码）</summary>

安装到已有环境中：

```bash
pip install gda
```

从源码安装（用于开发或获取尚未发布的改动）：

```bash
git clone https://github.com/aigengame/godot-agent.git
cd godot-agent
uv sync                  # create the environment + install dependencies
uv run gda --help
```
</details>

---

<a id="quick-start"></a>
## 快速上手

**让 `gda` 指向你的 Godot 二进制文件**，然后问引擎要它的版本——不需要项目：

```bash
export GDA_GODOT="/path/to/Godot"   # or pass --godot to any command
gda info --json
# {"major":4,"minor":6,"patch":3,"status":"stable","string":"4.6.3-stable (official)",…}
```

stdout 永远是干净、可管道传递的 JSON；所有引擎和脚本的诊断信息都走 stderr：

```bash
gda info --json | jq .major   # → 4
```

**以 Headless 方式构建一个场景。** 让 `gda` 一次性指向一个 Godot 项目（一个含有 `project.godot` 的目录）；
之后相对路径都会在项目*内部*解析，而节点则通过相对于场景根的路径来寻址：

```bash
export GDA_PROJECT="/path/to/your/godot-project"   # or pass --project to any command
gda scene create scenes/main.tscn --root-type Node2D --json
gda node add  scenes/main.tscn --type Sprite2D --name Hero --json
gda node set  scenes/main.tscn --node Hero --property position --value 10,20 --json
gda scene get scenes/main.tscn --json
# {"path":"scenes/main.tscn","root":{"name":"main","type":"Node2D","children":[{"name":"Hero",…}]}}
```

> 没有项目？`gda` 仍可在普通文件系统路径上以**无项目（projectless）**方式运行（路径相对于你的当前目录）——
> 只有 `res://` 解析才需要项目。参见[配置](#configuration)。

**实时操控*正在运行*的游戏。** Live 操作会运行项目的**主场景**，所以先通过 Godot 的
`application/run/main_scene` 项目设置（也就是编辑器里的 *Application → Run → Main Scene*）
把它指向你刚构建好的那个场景，然后启动 daemon（macOS/Linux，Godot 4.6+）：

```bash
gda project set application/run/main_scene --value res://scenes/main.tscn --json  # a Godot project setting key
gda daemon start             # start the daemon for $GDA_PROJECT (installs the in-game harness)
gda game tree --json         # the runtime scene tree, after _ready
gda perf monitors --json     # live engine counters: fps, memory, node count
gda daemon stop
```

（`gda screen capture` 也能实时工作，但需要一个带窗口的会话——用
`gda daemon start --windowed` 启动 daemon。）

---

<a id="choose-your-integration"></a>
## 选择你的集成方式

`gda` 用三种方式暴露**同一套命令界面**——你的 agent（或你自己）支持哪种就用哪种：

| 入口 | 适合 | 怎么用 |
| --- | --- | --- |
| **CLI**（`gda`） | 人类、shell 脚本、CI，以及能运行命令的 agent | `gda <group> <command> --json` |
| **Skill**（`gda skill`） | 支持 Agent Skills、偏好省 token 的 CLI 工作流的编程 agent | 打印/安装 `SKILL.md`（见下文） |
| **MCP**（`gda-mcp`） | 通过 Model Context Protocol 调用工具的 agent | 运行 stdio 服务器（见下文） |

### 作为 Skill 使用

`gda` 附带一个 agent **Skill**——一份 `SKILL.md`，教 AI agent *何时*以及*如何*使用 CLI 操控
Godot。这是最轻量的接入方式（没有服务器要注册），随包附带，并与你的安装版本锁定。把它打印出来，
或安装到你的 agent 的 skills 目录里：

```bash
gda skill                                              # print SKILL.md (redirect it anywhere)
gda skill --install --provider claude --scope user     # resolve a known agent's skills dir
gda skill --install --dir ~/.claude/skills/gda         # …or give the directory yourself
```

[Skill 配方](gda-skill.md) 列出了每个 agent 的 skills 目录。或者直接从仓库获取同一个文件——
你仍然需要安装 `gda`，因为 Skill 靠它来驱动：

```bash
curl --create-dirs -o ~/.claude/skills/gda/SKILL.md \
  https://raw.githubusercontent.com/aigengame/godot-agent/main/src/gda/skill/SKILL.md
```

### 作为 MCP 服务器使用

`gda` 在 `[mcp]` 这个 extra 之下附带了一个 stdio [MCP](https://modelcontextprotocol.io) 服务器，
因此任何 MCP agent（Claude Code、Codex、Cursor 等）都能操控 Godot。无需安装即可一试：

```bash
uvx --from "gda[mcp]" gda-mcp
```

服务器需要确定两件事——操控哪个 Godot**项目**，以及运行哪个 Godot**二进制文件**
（MCP 无法在每次调用时传入 flag）：

- **项目** — 设置 `GDA_PROJECT`。不设时 `gda-mcp` 会用客户端发来的工作区 **roots**（你打开的那个文件夹）。
  但 MCP 2026-07-28 修订版弃用了 roots，因此最好固定 `GDA_PROJECT`，避免客户端升级后无法定位项目。参见[配置](#configuration)。
- **引擎** — 把 `GDA_GODOT` 设为你的 Godot 二进制文件，例如 `"GDA_GODOT": "/path/to/Godot"`。

`gda-mcp` 同时接受两代协议——2026 年以前的 MCP 协议与 **2026-07-28 修订版**——但两者解析项目的方式不同：
2026 前的客户端仍会发送 roots，新修订版的客户端不再发送，`gda-mcp` 会从 `GDA_PROJECT` 或服务器的 cwd 确定项目。
请在客户端切换到新协议之前固定 `GDA_PROJECT`。对新修订版，`gda-mcp` 还会把 `tools/list` 标记为可缓存（1 小时 TTL）。

#### 在编程 agent 中注册

<details>
<summary>Claude Code</summary>

项目级，仓库根目录下的 `.mcp.json`（通过 `roots` 自动检测项目）：

```json
{
  "mcpServers": {
    "gda-mcp": {
      "command": "uvx",
      "args": ["--from", "gda[mcp]", "gda-mcp"]
    }
  }
}
```

用户级（适用于每个项目）——使用 CLI，它会写入 `~/.claude.json`：

```bash
claude mcp add --scope user gda-mcp -- uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Codex</summary>

项目级，仓库根目录下的 `.codex/config.toml`（项目必须是受信任的）：

```toml
[mcp_servers.gda-mcp]
command = "uvx"
args = ["--from", "gda[mcp]", "gda-mcp"]

[mcp_servers.gda-mcp.env]
GDA_PROJECT = "/absolute/path/to/your/godot/project"
```

用户级（处处可用，但固定指向单一项目）——把同一段配置表放进 `~/.codex/config.toml`，
或用 CLI 添加。Codex 没有工作区变量，所以 `GDA_PROJECT` 是一个绝对路径；如果你要跨多个项目工作，
请用项目级：

```bash
codex mcp add gda-mcp --env GDA_PROJECT=/absolute/path/to/your/godot/project -- \
  uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Cursor</summary>

项目级，仓库根目录下的 `.cursor/mcp.json`（`${workspaceFolder}`
会指向当前打开的项目）：

```json
{
  "mcpServers": {
    "gda-mcp": {
      "type": "stdio",
      "command": "/path/to/uvx",
      "args": ["--from", "gda[mcp]", "gda-mcp"],
      "env": {
        "GDA_PROJECT": "${workspaceFolder}"
      }
    }
  }
}
```

用户级（处处可用，但固定指向单一项目）——把同样的配置放进 `~/.cursor/mcp.json`，并把
`GDA_PROJECT` 设为一个绝对路径（`${workspaceFolder}` 只在项目级有效；多项目请用项目级）。
Cursor 没有 `mcp add` 命令——请通过上面的 JSON 或 Settings → MCP 界面来注册。

> Cursor 由 GUI 启动，`PATH` 极简，所以直接调用 `uvx` 可能解析不到——这正是上面用绝对路径
> `command` 的原因；用 `which uvx` 的输出来填它。完整的配方——PATH 注入、Claude Desktop、
> 用户级与项目级、各 agent 的项目固定方式——都在[注册配方](gda-mcp-registration.md)里。
</details>

---

<a id="how-it-works"></a>
## 工作原理

`gda` 由三个组件构成，以两种模式覆盖各类操作：

| 组件             | 职责                                                                  |
| ---------------- | --------------------------------------------------------------------- |
| **`gda`**        | 面向 agent 的 CLI——以结构化的 `--json` 输出暴露 Godot。 |
| **`gda-mcp`**    | 一个 MCP 服务器，从 `--schema` 出发，把同一套操作以工具形式暴露。 |
| **`gda-daemon`** | 一个按项目运行的进程，为 Live 操作守护一个正在运行的游戏。 |

- **Headless 操作**一次性运行——没有 daemon、无需安装任何东西（创建场景、编辑脚本、导出、分析）。
- **Live 操作**需要一个正在运行的游戏——`gda-daemon` 启动它、注入一个默认处于休眠状态的游戏内 harness，
  并通过 Unix 域套接字中转请求（运行时树、输入、截图、性能、诊断）。

`gda-daemon` 注入的游戏内 harness **仅用于开发**：`gda export run` 会把它从产物中彻底剥离；
而即便用其他方式构建（编辑器 GUI、直接执行 `godot --export`），它在导出后的游戏里也会自动禁用——
所以正式发布的游戏永远不会*运行*任何与 daemon 相关的东西（而经由 `gda export run`，
它甚至根本不会被打包进去）。

**平台与版本支持：**

| 模式 | Godot | 平台 |
| ---- | ----- | --------- |
| **Headless** | 4.4+ | macOS · Linux · Windows¹ |
| **Live**（经由 `gda-daemon`） | 4.6+ | macOS · Linux² |

¹ Headless 在设计上就是跨平台的（一次性进程，无平台相关依赖）——Windows 保留完整的
  headless 命令界面，尽管 CI 还没有对它做过验证。
² Live 操作使用 Unix 域套接字，所以暂不支持 Windows。

---

<a id="command-reference"></a>
## 命令参考

`gda` 命令**按 Godot 领域对象分组**，并使用一套精简、统一的动词，因此同一个动词
在每个分组里含义都一样：

| 动词                | 含义                                                              |
| ------------------- | ----------------------------------------------------------------- |
| `create` / `delete` | 创建 / 删除一个**独立**实体（场景、脚本、资源）。 |
| `add` / `remove`    | 在容器内增加 / 移除一个**子实体**（节点 → 场景）。 |
| `get` / `list`      | 读取单个实体 / 枚举多个。 |
| `set`               | 修改一个属性。 |
| 领域动词        | `play`、`run`、`export`、`import` 等，保留它们的自然含义。 |

每条命令都支持 `--json` 和 `--schema`。读取或修改 `res://` 路径的命令会解析一个[项目上下文](#configuration)。
运行 `gda <group> <command> --help` 查看完整 flag——`gda --help` 是已安装命令的权威清单。

**第一次用？** 一条不错的上手路径：`gda info` → `gda scene create` → `gda node add` →
`gda script validate` → `gda export run`；然后用 `gda daemon start` → `gda game tree` 进入 Live。

**Meta** — 关于 `gda` / 引擎本身

| 命令 | 作用 |
| ------- | ------------ |
| `gda info`   | 报告 Godot 引擎的版本。 |
| `gda version` | 报告当前安装的是哪个 `gda`、来自何处（加 `--json` 时附带安装溯源信息）。 |
| `gda help`   | 显示某条命令的帮助（`gda help scene get`）或整个 CLI 的帮助。 |
| `gda schema` | 把整个命令界面作为一份机器可读的 JSON 清单输出。 |
| `gda skill`  | 输出或安装随包附带的 Agent Skill（`SKILL.md`），它教 agent 如何操控 `gda`。 |

### Headless 命令 — Godot 4.4+，全平台

**`scene`** — 场景文件（`.tscn`）

| 命令 | 作用 |
| ------- | ------------ |
| `scene create` | 用指定的根节点类型创建一个新的 `.tscn`。 |
| `scene get` | 读取一个场景并报告其结构化的节点树。 |
| `scene list` | 枚举已解析项目中的 `.tscn` 场景。 |
| `scene get-exports` | 列出场景里各节点脚本声明的 `@export` 属性。 |
| `scene delete` | 删除一个场景文件并报告删除了什么。 |
| `scene validate` | **静态**检查场景——依赖能否解析、绑定的脚本能否编译，子场景一并检查——不实例化场景（项目的 autoload 仍会启动，和所有 `--project` 命令一样）；有问题的场景作为检查结果返回（`valid: false`，退出码 `0`），不会报错。 |
| `scene preflight` | **动态**检查场景——以 headless 方式启动它，运行 `_ready`，报告 `started` 以及启动过程中出现的脚本错误；启动失败同样作为结果返回，不会报错。 |

两者都要跑——`scene get` 会把脚本已丢失的场景当作正常场景读出来，只有 `validate` 能指出那个文件，
也只有 `preflight` 能抓到第一帧的失败。

**`node`** — 场景文件内的节点

| 命令 | 作用 |
| ------- | ------------ |
| `node add` | 在某个父节点下添加一个节点，可用 `--index` 指定位置：内置类型、带 `class_name` 的脚本，或用 `--instance` 将另一个场景实例化为子节点。 |
| `node get` | 按节点路径读取一个节点的属性，输出带类型的 JSON。 |
| `node list` | 列出一个场景的节点树，并给出每个节点相对于根的路径。 |
| `node set` | 设置一个节点属性，并把值强制转换为它声明的 Godot 类型。对 `Control`，`position` 会写入四个 offset；`Container` 的子节点由布局管理，请直接设置它们的 offset。 |
| `node remove` | 按节点路径移除一个节点（及其子树）。 |
| `node duplicate` | 在父节点下复制一个节点（及其子树）。 |
| `node move` | 把一个节点（及其子树）重新挂到新的父节点下，或用 `--index` 调整同级顺序。 |
| `node connect-signal` | 把源节点的信号接到目标节点的方法上。 |
| `node disconnect-signal` | 断开一个已有的「信号→方法」连接。 |

**`script`** — GDScript 文件（`.gd`）

| 命令 | 作用 |
| ------- | ------------ |
| `script create` | 从模板或直接传入的 `--content` 创建一个新的 `.gd` 脚本。 |
| `script get` | 读取一个脚本的源码及其 `class_name` / `extends` 元数据。 |
| `script list` | 枚举已解析项目中的 `.gd` 脚本。 |
| `script set` | 通过搜索替换、行范围或整体覆写来编辑一个脚本。 |
| `script delete` | 删除一个脚本文件并报告删除了什么。 |
| `script attach` | 按节点路径把一个 `.gd` 脚本附加到场景里的某个节点上。 |
| `script validate` | 编译检查 `.gd` 脚本——多个 PATH 在一次引擎启动中完成，或用 `--all` 检查整个项目——报告一个汇总的 `valid` 加上 `scripts` 里每个脚本各自的条目；编译失败的脚本作为检查结果返回（`valid: false`，退出码 `0`），不会报错。 |
| `script run` | 以一次性入口的方式 headless 运行一个项目脚本，受 `--timeout` 约束。脚本的 `exit_status` 与 `stderr` 原样透传；`stdout` 内联返回最多 64 KiB，超出时完整的 stdout 会写入结果中指明的文件；脚本以非零状态 `quit()` 不算失败，只是结果里的数据，加 `--strict` 才按失败处理。 |

**`project`** — 作为整体的项目（设置、autoload、静态分析）

| 命令 | 作用 |
| ------- | ------------ |
| `project info` | 报告项目元数据（名称、主场景、视口、引擎版本）。 |
| `project get` | 按 section/key 读取单个项目设置，输出带类型的 JSON。 |
| `project list` | 列出项目的设置键（默认只列已自定义的；`--all` 加上引擎默认值，`--section` 按前缀过滤）。 |
| `project set` | 设置一个项目设置，并把值强制转换为它声明的类型。 |
| `project add-autoload` | 注册一个 autoload 单例（名称 → 脚本/场景）。 |
| `project remove-autoload` | 按名称注销一个 autoload 单例。 |
| `project add-input-action` | 注册一个绑定按键的 InputMap 动作（`--key` 键名或键码、`--deadzone`、`--physical`）。 |
| `project remove-input-action` | 按名称注销一个 InputMap 动作。 |
| `project find-references` | 找出引用了给定资源的每一个项目文件。 |
| `project dependencies` | 把每个场景/资源映射到它所依赖的资源。 |
| `project find-unused-resources` | 找出没有任何东西引用的资源文件。 |
| `project statistics` | 报告项目的文件/行数统计、autoload 等信息。 |

**`resource`** — 资源文件（`.tres`）与项目的已导入资产

| 命令 | 作用 |
| ------- | ------------ |
| `resource create` | 创建一个给定类型的新 `.tres` 资源。 |
| `resource get` | 读取一个 `.tres` 资源的属性，输出带类型的 JSON。 |
| `resource set` | 设置一个 `.tres` 属性，并把值强制转换为它声明的类型。 |
| `resource delete` | 删除一个 `.tres` 资源文件并报告删除了什么。 |
| `resource uid` | 在资源 UID 与其 `res://` 路径之间双向解析。 |
| `resource import` | 确保资产已导入项目缓存（干净工作树加载）。 |

**`export`** — 导出预设与产物

| 命令 | 作用 |
| ------- | ------------ |
| `export list` | 枚举项目的导出预设（名称、平台等）。 |
| `export get` | 报告某个预设的详情以及导出模板的安装状态。 |
| `export run` | 把一个具名预设（`release` / `debug` / `pack`）导出到目标位置。 |

**`shader`** — 着色器文件（`.gdshader`）

| 命令 | 作用 |
| ------- | ------------ |
| `shader create` | 从模板或直接传入的 `--content` 创建一个新的 `.gdshader`。 |
| `shader get` | 读取一个着色器的源码及其 `shader_type`。 |
| `shader set` | 通过搜索替换、行范围或整体覆写来编辑一个 `.gdshader`。 |

**`theme`** — 主题资源（`.tres`）

| 命令 | 作用 |
| ------- | ------------ |
| `theme create` | 创建一个全新的、可加载的 `.tres` Theme 资源（不覆盖已有文件）。 |

### Live 命令 — 经由 `gda-daemon`；Godot 4.6+，macOS/Linux

**`daemon`** — Live 运行时的生命周期

| 命令 | 作用 |
| ------- | ------------ |
| `daemon start` | 启动按项目运行的 daemon 并安装游戏内 harness；引擎会话按需启动，只有操作需要时才会拉起（`screen` 截图需加 `--windowed`）。 |
| `daemon wait-ready` | 立即启动引擎会话并等待它就绪；`--timeout` 是 daemon 为这次启动分配的预算，不是这次调用的硬性上限。只读的 `diag` / `logger` 读取从不启动会话，所以当这类读取是你的第一个 Live 命令时，先跑这一步。 |
| `daemon stop` | 停止项目的 daemon 以及任何正在运行的引擎会话。 |
| `daemon status` | 报告 daemon 的状态（是否运行、窗口模式、会话）。 |
| `daemon install` | 在不启动 daemon 的情况下安装游戏内 harness，并报告写入了什么。幂等；`daemon start` 自己就会做这一步，因此只在想单独审阅或提交那次 `project.godot` 改动时使用。 |
| `daemon uninstall` | 移除游戏内 harness——autoload 条目、harness 文件、`.uid` 附属文件——还原 `project.godot`，并报告移除了什么。仅用于开发工具卸载：`gda export run` 已经会自动从导出产物中剥离 harness。 |

**`game`** — 正在运行的游戏的运行时场景图

| 命令 | 作用 |
| ------- | ------------ |
| `game tree` | 读取正在运行的游戏的运行时场景树（在 `_ready` 之后）。 |
| `game get` | 按节点路径读取一个运行时节点的实时属性；显式命名时可读取附加脚本变量。 |
| `game rect` | 按节点路径读取一个运行时 Control 渲染后的视口矩形。 |
| `game set` | 在正在运行的游戏上设置运行时节点属性，或显式命名的附加脚本变量；`verified` 报告读回值是否匹配。 |
| `game call` | 调用节点脚本在 `GDA_CALLABLE` 中声明的一个方法，并以结构化数据形式返回结果。项目自己承诺该方法是只读的，gda 无法验证；未声明的方法绝不会被调用。 |

`game call` 读取 `game get` 读不到的东西：项目以方法形式暴露的状态。
`game set --property position` 遵循与 `node set` 相同的 `Control` 规则。

**`diag`** — 运行时诊断

| 命令 | 作用 |
| ------- | ------------ |
| `diag errors` | 跟踪（tail）正在运行的游戏的运行时错误（已分类）。 |

**`logger`** — 结构化运行时日志

| 命令 | 作用 |
| ------- | ------------ |
| `logger tail` | 以结构化记录的形式跟踪正在运行的游戏的整个运行时日志（`--level`、`--limit`、`--raw`）。 |

**`perf`** — 性能监控

| 命令 | 作用 |
| ------- | ------------ |
| `perf monitors` | 对引擎计数器拍快照——或配合 `--frames` 在一个帧窗口内采样，输出聚合统计与预算判定。 |
| `perf monitor` | 在一个帧窗口内对某个节点属性或信号采样（时间线）。 |

**`input`** — 输入模拟

| 命令 | 作用 |
| ------- | ------------ |
| `input key` | 注入一个按键事件（带修饰键）。 |
| `input mouse-click` | 在 `(x, y)` 处注入完整的点击手势(移动、按下、释放)。 |
| `input mouse-move` | 将鼠标移动到 `(x, y)`。 |
| `input action` | 按下/释放一个已映射的输入动作。 |
| `input tap` | 轻按一个按键或动作：跨帧完成按下、保持、释放。 |
| `input sequence` | 注入一条跨多帧的事件时间线。 |

注入的鼠标坐标请从 `event.position` 读取——daemon 会话中 `get_mouse_position()` /
`get_global_mouse_position()` 可能一直是过期值。

**`screen`** — 视口捕获

| 命令 | 作用 |
| ------- | ------------ |
| `screen capture` | 捕获一帧视口并保存为一张 PNG。 |
| `screen frames` | 捕获一个 N 帧的 PNG 序列（`--summary` 返回紧凑的聚合结果）。 |

### 全局 flag

| Flag       | 说明                                                               |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | 在 stdout 上把结果作为单个 JSON 对象输出——成功时是结果，失败时是 `{"error": {…}}` 信封。不加它时，两者都会改为打印一份简洁的、供人阅读的渲染结果。写在命令之前同样有效。 |
| `--schema`  | 输出该命令的输入/输出 JSON Schema 契约（不会启动 Godot）。 |
| `--godot`   | Godot 二进制文件的路径（覆盖 `$GDA_GODOT` 和默认值）。 |
| `--project` | 用于 `res://` 解析的 Godot 项目目录（覆盖 `$GDA_PROJECT`；若当前目录本身是个项目则默认用它）。仅限领域命令。解析一个项目会运行该项目的代码——参见[项目代码执行](#configuration)。 |
| `--version` | 打印已安装的 `gda` 版本。加上 `--json` 时，同时给出它的来源——安装类型（`wheel`、`editable` 或 `unknown`），以及 editable 安装对应源码检出的 Git 版本号。 |
| `--help`    | 显示 `gda` 或任意命令的用法。                                |

---

<a id="configuration"></a>
## 配置

`gda` 会从 **`--godot <path>`** flag 找到 Godot 二进制文件，否则就用
**`GDA_GODOT`** 环境变量——设置其中之一，`gda` 才能定位到你的引擎。

领域命令会解析一个 **Godot 项目**，以便 `res://` 路径能够解析。显式指定的目录必须是个项目，
否则 `gda` 会报错；当没有任何一项解析成功时，`gda` 会以**无项目（projectless）**方式运行——
普通文件系统路径可用，`res://` 不行。

| 上下文 | 项目解析顺序 |
| --- | --- |
| **CLI** | `--project` → `GDA_PROJECT`（两者都严格：无效即报错）→ 当前目录（若含有 `project.godot`）→ 无项目 |
| **MCP**（`gda-mcp`） | `GDA_PROJECT`（严格）→ 客户端的工作区 `root`（若发来的是有效项目；仅 2026 前的客户端）→ 服务器的 cwd（若它是项目）→ 无项目 |

<details>
<summary>项目代码执行——当你指向一个项目时会运行什么</summary>

把 `gda` 指向一个项目，就会运行该项目自身的一部分代码——这是有意为之，因为项目被视为可信
（[ADR-0009](adr/0009-trust-boundary-trusted-project.md)）：

- **autoload** 在每个会启动引擎的 `--project` 操作中运行，只读操作也不例外（缓存完好的
  `resource import` 不启动任何东西）。
- **场景脚本的 `_init`** 在场景被实例化的地方运行：每个改动状态的 `node` 命令以及 `node get`；
  `scene get` / `scene list` / `node list` 只读取、不实例化。
- **`script run`** 会执行指定脚本的全部内容；**`scene preflight`** 启动场景并运行其 `_ready`。
- **`resource import`** 在缓存缺失时运行引擎的导入器（以及项目的导入插件），不运行 autoload。
- **`game call`** 只运行节点 `GDA_CALLABLE` 声明中列出的那一个方法；未声明的绝不会被调用。

</details>

---

<details>
<summary><strong>底层原理</strong> — 结构化输出契约与退出码</summary>

Headless 的 Godot 会把它的横幅、警告和 `print()` 输出混在 stdout 中。`gda`
用一套哨兵（sentinel）契约来解决这个问题
（[ADR-0002](adr/0002-headless-structured-output-contract.md)）：

- GDScript 负载在 stdout 上只输出**恰好一个**结果，用唯一的哨兵包裹起来：

  ```
  <<<GDA:RESULT>>>{ …json… }<<<GDA:END>>>
  ```

- 它会将**全部**诊断信息写入 stderr；stdout 上除了契约什么都不带。
- `gda` 只提取并解析两个哨兵之间的字节，忽略周围的引擎噪声，并把 stderr 暴露出来供检查。

正是这一点让程序可以安全解析并使用 `gda` 的输出，而且这一契约还延续成了 daemon 为 Live 操作
所用的逐消息协议。

**退出码（CLI ABI）。** 一次失败的 `gda` 运行会返回一个稳定的退出码，这样 shell
或 agent 就能**在不解析 JSON 错误的情况下**按失败**类别**分支处理：

| 退出码 | 类别      | 何时                                                                  |
| --------- | ------------- | --------------------------------------------------------------------- |
| `0`       | —             | 成功。                                                              |
| `2`       | `usage`       | `gda` 无法解析你的请求——命令或选项无法识别。若属于已知的近似写法，信封的 `hint` 会给出应当改用的调用方式。 |
| `127`     | `environment` | Godot 二进制文件无法启动（shell 惯例：not found）。 |
| `124`     | `environment` | Godot 启动了，但在超时之前没有返回（shell 惯例：timed out）；信封携带截至当时捕获的部分输出。 |
| `3`       | `version`     | 检测到的 Godot 版本低于受支持的最低版本。            |
| `4`       | `operation`   | 引擎运行了，但操作失败了——已注册的操作错误、引擎崩溃，或进程以非零退出码退出且没有结构化输出。 |
| `5`       | `parse`       | 进程返回成功，但输出不符合结构化契约。 |
| `6`       | `live`        | 一个 Live 操作失败了——例如没有正在运行的 daemon/会话，或一次 Live 超时。 |

这些值就是公开 ABI；其权威来源是
[`src/gda/exit_codes.py`](../src/gda/exit_codes.py)。`{"error": {category, code, …}}`
信封在每个类别之内还携带一个**更细粒度的 `code`**（例如 `path_not_found`、
`already_exists`、`node_not_found` 都归在 `operation` / 退出码 `4` 之下）。完整的
注册表见
[ADR-0002 的 `GdaError.code` 表](adr/0002-headless-structured-output-contract.md#gdaerrorcode-registry)。
</details>

<details>
<summary><strong>开发</strong></summary>

```bash
uv sync                       # set up the environment

uv run pytest                 # run the full suite (includes e2e tests against a real Godot)
uv run pytest -m "not e2e"    # unit tests only (no Godot binary required)
uv run pytest -m e2e          # only the end-to-end tests (needs Godot 4.4+ on this machine)

uv run ruff check .           # lint
uv run ruff format .          # auto-format (append --check to verify without writing)
uv run pyright                # type-check (src/ + tests/, basic mode)
```

`e2e` 这一层在 `uv run pytest` 时默认运行；如果在默认位置找不到 Godot 二进制文件，它会**明确报错**——
指出解析到的路径以及如何修复——而不是静默跳过。用 `-m "not e2e"` 可以把整层排除掉
（CI 的每个 PR 任务正是这么做的）。

Lint 和格式化由 [ruff](https://docs.astral.sh/ruff/) 强制执行——用一个工具取代
flake8 + black + isort，配置在 `pyproject.toml` 的 `[tool.ruff]` 下，并通过 `uv.lock`
锁定版本，让本地和 CI 保持一致。CI 的 `lint` 任务会在每个 PR 上运行 `ruff check .` 和
`ruff format --check .`；提交前先运行 `uv run ruff format .`，保持 CI 绿色。

类型由 [pyright](https://microsoft.github.io/pyright/) 以 `basic` 模式检查，覆盖
`src/` 和 `tests/`，配置在 `pyproject.toml` 的 `[tool.pyright]` 下（同样通过
`uv.lock` 锁定版本）。CI 的 `type-check` 任务会在每个 PR 上运行 `uv run --frozen pyright`。

```
src/gda/
  cli.py            # composition root (Typer): mounts every command group
  commands/         # one module per command group: its models, renderers, commands
  dispatch.py       # the CLI dispatch tails + the runner seams the groups call
  surface.py        # walks the live Typer tree → the `gda schema` manifest
  headless.py       # the per-command descriptor (one HeadlessCommand per command)
  binary.py         # Godot binary resolution (flag > $GDA_GODOT > default)
  runner.py         # the one-shot headless spawn seam (Protocol + subprocess impl)
  live_runner.py    # the live-operation client that talks to gda-daemon
  models.py         # the shared typed I/O core (Pydantic) backing --json and --schema
  errors.py / error_codes.py / exit_codes.py   # failure classification + the CLI ABI
  render.py         # the shared human-readable (non-JSON) render helpers
  ops/operations.gd # the headless GDScript payload, dispatched by operation name
  daemon/           # gda-daemon: server, session supervision, IPC protocol, discovery
  harness/          # the inert in-game `gda` autoload injected into a live session
  mcp/              # gda-mcp: the schema → MCP-tool server
tests/              # unit + e2e tests against a real engine (shared fixtures in conftest.py)
docs/adr/           # architecture decision records
CONTEXT.md          # the project's shared domain language
```

`gda` 有两条外部边界，每条边界背后都有一个便于快速注入测试替身的接缝（seam）：启动一次性的
headless 进程（`runner.py`），以及通过 daemon 与正在运行的游戏对话（`live_runner.py`）。
e2e 套件会驱动真实引擎覆盖这两条边界。
</details>

---

<a id="contributing"></a>
## 贡献

欢迎贡献。请阅读 [`CONTEXT.md`](../CONTEXT.md) 以对齐项目的共享语言，并查阅你改动所涉及的领域的
相关 [ADR](adr/)。Issue 和 PRD 以 [GitHub issues](https://github.com/aigengame/godot-agent/issues)
的形式存在。提交遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范。
Python 代码用 [ruff](https://docs.astral.sh/ruff/) 做 lint 和格式化、用
[pyright](https://microsoft.github.io/pyright/) 做类型检查，二者都在 CI 中强制执行——
提交前先运行 `uv run ruff format .` 和 `uv run pyright`（见上面的**开发**部分）。

> **正在和 AI 编程 agent 协作？** 本项目从设计上就便于 agent 导航——
> [`AGENTS.md`](../AGENTS.md) 是编程 agent 的入口，把项目的规则、领域文档和 skill 都
> 串联起来。

<a id="license"></a>
## 许可证

基于 [MIT License](../LICENSE) 发布。Copyright (c) 2026 aigengame。
