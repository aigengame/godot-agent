<!-- gda-readme-i18n: source=README.md sha256=3a595c5ac14763cd6aa8236c34d543ecaa719371040f852645327be2d78af73f -->

# godot-agent (`gda`): Godot AI Agent CLI, Skill, and MCP Server

![godot-agent title image](https://raw.githubusercontent.com/aigengame/godot-agent/main/assets/godot-agent-title.png)

**其他语言:** [English](../README.md) · **简体中文** · [Español](README.es.md) · [日本語](README.ja.md)

> **`gda` 让你的 AI 编程 agent——或者你的 shell 脚本和 CI——以结构化、机器可读的方式
> 操控 [Godot Engine](https://godotengine.org)。** 以 Headless 方式创建场景、编辑节点和脚本、
> 导出构建产物，然后实时操控*正在运行*的游戏：运行时树、输入、
> 截图、性能——一套命令界面，三种接入方式。

[![pre-1.0](https://img.shields.io/badge/status-pre--1.0-orange)](https://pypi.org/project/gda/)
[![CI](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Godot](https://img.shields.io/badge/godot-4.4%2B%20(live%204.6%2B)-478CBF)](https://godotengine.org)
[![Platform](https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-lightgrey)](#how-it-works)
[![MCP](https://img.shields.io/badge/MCP-server-000)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

AI agent 擅长编写 GDScript，却拙于*看到发生了什么*。`gda` 帮你闭合这个回路：你的 agent
发出一个操作，拿回一个干净的 JSON 结果就能据此行动——而不是一堆它得费劲去扒拉的引擎日志。
它有**两种模式**：

- **Headless（无头）** — 一次性、无状态、零配置。无需编辑器插件、无需 daemon，
  无需往你的项目里安装任何东西。创建和编辑场景、节点、脚本、资源、着色器和主题；
  分析项目；导出构建产物。
- **Live（实时）** — 通过一个后台 daemon 操控*正在运行*的游戏，完成所有只有活引擎才能做的事：
  读取运行时场景树、读写运行时属性、模拟输入、捕获截图、采样性能。

> `gda` 目前处于 **pre-1.0** 阶段：今天每条命令都能端到端跑通，但在 1.0 之前 CLI 界面
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

- **🤖 结构化输出，为 agent 而生。** 每条命令在 stdout 上只输出**恰好一个** JSON
  对象（`--json`）；引擎横幅、警告和 `print()` 都走 stderr。你的 agent 解析的是一个结果，
  而不是一墙日志。
- **📐 带类型、可自描述。** 每条命令的输入和输出都是带类型的模型，它们同时支撑起一份机器可读的
  `--schema`（JSON-Schema 契约），让 agent 可以用程序化的方式发现并校验整个命令界面，而不必靠猜。
- **🔀 CLI、Skill、MCP——交给你的 agent 自选。** 用原生的 `gda` CLI 从终端或 CI 操控 Godot，
  把随包附带的 **Skill**（`gda skill`）交给你的 agent、教它何时以及如何使用 CLI，或者把同一套操作以
  **MCP** 工具的形式暴露出来（`gda-mcp`，由 CLI 自身的 schema 生成）。一套命令界面，三种接入方式——
  你的 agent 支持哪种就挑哪种。
- **🧩 Godot 原生命令。** 按 Godot 对象分组（`gda scene create`、
  `gda node add`、`gda game set`），配上一套精简、一致的动词词汇——只要你已经懂 Godot，
  就几乎没有学习成本。
- **⚡ 默认 Headless，需要时再 Live。** Headless 操作不需要 daemon、也不需要编辑器——
  只要一个 Godot 二进制文件。Live 操作则通过一个基于 Unix 域套接字的 daemon，为正在运行的游戏
  加上实时控制能力，用的还是同一套 CLI 语法。
- **🛡️ 出错就大声报，绝不悄悄吞。** 引擎缺失或卡死会被超时兜住，并映射为一个**稳定的非零退出码**
  外加一个结构化的 `{"error": {…}}` 信封——这样 shell 或 agent 无需解析散文就能按失败类别分支处理。

---

<a id="capabilities-at-a-glance"></a>
## 能力速览

| 你的需求 | 用这个 |
| --- | --- |
| 从 agent 或脚本生成项目文件 | `scene` / `node` / `script` / `resource` / `shader` / `theme`——以 Headless 方式创建和编辑 |
| 解析结果，而不是扒拉引擎日志 | `--json`（一个干净的对象）和 `--schema`（JSON-Schema 契约） |
| 把 Godot 工具交给 agent | 随包附带的 **Skill**（`gda skill`）或 **`gda-mcp`** 服务器 |
| 自动化 CI、导出和项目分析 | Headless 命令——无需编辑器、无需插件，只要一个 Godot 二进制文件 |
| 调试*正在运行*的游戏的运行时行为 | `gda daemon start`，然后用 `game` / `diag` / `logger` / `perf` / `input` / `screen` |

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

**以 Headless 方式构建一个场景。** 让 `gda` 指向一个 Godot 项目（一个含有 `project.godot` 的目录）
一次；之后相对路径都会在它*内部*解析，而节点则通过相对于场景根的路径来寻址：

```bash
export GDA_PROJECT="/path/to/your/godot-project"   # or pass --project to any command
gda scene create scenes/main.tscn --root-type Node2D --json
gda node add  scenes/main.tscn --type Sprite2D --name Hero --json
gda node set  scenes/main.tscn --node Hero --property position --value 10,20 --json
gda scene get scenes/main.tscn --json
# {"path":"scenes/main.tscn","root":{"name":"main","type":"Node2D","children":[{"name":"Hero",…}]}}
```

> 没有项目？`gda` 仍可在普通文件系统路径上以**无项目（projectless）**方式运行（相对于你的当前目录）——
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

`gda` 用三种方式暴露**同一套命令界面**——你的 agent（或你自己）支持哪种就挑哪种：

| 入口 | 适合 | 怎么用 |
| --- | --- | --- |
| **CLI**（`gda`） | 人类、shell 脚本、CI，以及能运行命令的 agent | `gda <group> <command> --json` |
| **Skill**（`gda skill`） | 支持 Agent Skills、偏好省 token 的 CLI 工作流的编程 agent | 打印/安装 `SKILL.md`（见下文） |
| **MCP**（`gda-mcp`） | 通过 Model Context Protocol 调用工具的 agent | 运行 stdio 服务器（见下文） |

### 作为 Skill 使用

`gda` 附带一个 agent **Skill**——一份 `SKILL.md`，教 AI agent *何时*以及*如何*从 CLI 操控
Godot。这是最轻量的接入方式（没有服务器要注册），随包附带，并与你的安装版本锁定。把它打印出来，
或安装到你的 agent 的 skills 目录里：

```bash
gda skill                                              # print SKILL.md (redirect it anywhere)
gda skill --install --provider claude --scope user     # resolve a known agent's skills dir
gda skill --install --dir ~/.claude/skills/gda         # …or give the directory yourself
```

`--install --provider <claude|codex> --scope <project|user>` 会解析出某个已知 agent 的 skills
目录（`--scope` 默认为 `user`）；`--dir` 则是面向任何其他 agent 的中立兜底——没有内置默认值。
[Skill 配方](gda-skill.md) 列出了每个 agent 的目录（Claude Code 的 `~/.claude/skills/`、
Codex 的 `~/.agents/skills/` 等）。或者，如果你不想走 `gda skill`，也可以直接从仓库获取同一个文件——
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

服务器需要解析两项上下文——操控哪个 Godot**项目**，以及运行哪个 Godot**二进制文件**
（MCP 无法逐次调用传递 flag）：

- **项目** — 当你的客户端无法公布工作区 **roots** 时，设置 `GDA_PROJECT`；否则 `gda-mcp`
  会从客户端发来的 roots（你打开的那个文件夹）自动检测项目。*已设置但无效*的 `GDA_PROJECT`
  会被当作一个上报的错误，而不是悄悄兜底。注意 MCP 2026-07-28 规范修订版弃用了 roots 能力：
  现在的客户端行为不变，但固定 `GDA_PROJECT` 才是面向未来的配置（走新无状态协议的客户端没有
  roots 可公布）。完整的 CLI 与 MCP 解析顺序参见[配置](#configuration)。
- **引擎** — 把 `GDA_GODOT` 设为你的 Godot 二进制文件，例如 `"GDA_GODOT": "/path/to/Godot"`。


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
会跟踪当前打开的项目）：

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

> Cursor 是以一个极简 `PATH` 由 GUI 启动的，所以裸的 `uvx` 可能解析不到——这正是上面用绝对路径
> `command` 的原因；用 `which uvx` 的输出来填它。完整的配方——PATH 注入、Claude Desktop、
> 用户级与项目级、各 agent 的项目固定方式——都在[注册配方](gda-mcp-registration.md)里。
</details>

---

<a id="how-it-works"></a>
## 工作原理

`gda` 由三个组件构成，以两种模式服务各类操作：

| 组件             | 职责                                                                  |
| ---------------- | --------------------------------------------------------------------- |
| **`gda`**        | 面向 agent 的 CLI——以结构化的 `--json` 输出暴露 Godot。 |
| **`gda-mcp`**    | 一个 MCP 服务器，从 `--schema` 出发，把同一套操作以工具形式暴露。 |
| **`gda-daemon`** | 一个按项目运行的进程，为 Live 操作监管一个正在运行的游戏。 |

- **Headless 操作**一次性运行——没有 daemon、无需安装任何东西（创建场景、编辑脚本、导出、分析）。
- **Live 操作**需要一个正在运行的游戏——`gda-daemon` 启动它、注入一个惰性的游戏内 harness，
  并通过 Unix 域套接字中转请求（运行时树、输入、截图、性能、诊断）。

`gda-daemon` 注入的游戏内 harness **仅用于开发**：`gda export run` 会把它从产物中彻底剥除；
而即便用其他方式构建（编辑器 GUI、裸的 `godot --export`），它在导出后的游戏里也会自我禁用——
所以一个发行版游戏永远不会*运行*任何与 daemon 相关的东西（而经由 `gda export run`，
它甚至根本不会被携带进去）。

**平台与版本支持：**

| 模式 | Godot | 平台 |
| ---- | ----- | --------- |
| **Headless** | 4.4+ | macOS · Linux · Windows¹ |
| **Live**（经由 `gda-daemon`） | 4.6+ | macOS · Linux² |

¹ Headless 在设计上就是跨平台的（一次性进程，无平台相关依赖）——Windows 保有完整的
  headless 命令界面，尽管 CI 还没有对它做验证。
² Live 操作使用 Unix 域套接字，所以暂不支持 Windows。

---

<a id="command-reference"></a>
## 命令参考

`gda` 命令**按 Godot 领域对象分组**，并使用一套精简、一致的动词词汇，因此同一个动词
在每个分组里含义都一样：

| 动词                | 含义                                                              |
| ------------------- | ----------------------------------------------------------------- |
| `create` / `delete` | 创建 / 删除一个**独立**实体（场景、脚本、资源）。 |
| `add` / `remove`    | 在容器内增加 / 移除一个**子实体**（节点 → 场景）。 |
| `get` / `list`      | 读取单个实体 / 枚举多个。 |
| `set`               | 修改一个属性。 |
| 领域动词        | `play`、`run`、`export`、`import` 等，保留它们的自然含义。 |

每条命令都支持 `--json` 和 `--schema`——只有 `gda schema` 自己例外，它会直接把聚合清单
作为 JSON 输出。读取或修改 `res://` 路径的命令会解析一个[项目上下文](#configuration)。
运行 `gda <group> <command> --help` 查看完整 flag——`gda --help` 是已安装命令的权威清单。

**第一次用？** 一条不错的上手路径：`gda info` → `gda scene create` → `gda node add` →
`gda script validate` → `gda export run`；然后用 `gda daemon start` → `gda game tree` 进入 Live。

**Meta** — 关于 `gda` / 引擎本身

| 命令 | 作用 |
| ------- | ------------ |
| `gda info`   | 报告 Godot 引擎的版本信息。 |
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

**`node`** — 场景文件内的节点

| 命令 | 作用 |
| ------- | ------------ |
| `node add` | 在某个父节点下添加一个节点，可用 `--index` 指定位置：内置类型、带 `class_name` 的脚本，或用 `--instance` 把另一个场景作为实例化子节点组合进来。 |
| `node get` | 按节点路径读取一个节点的属性，输出带类型的 JSON。 |
| `node list` | 列出一个场景的节点树，并给出每个节点相对于根的路径。 |
| `node set` | 设置一个节点属性，并把值强制转换为它声明的 Godot 类型。 |
| `node remove` | 按节点路径移除一个节点（及其子树）。 |
| `node duplicate` | 在父节点下复制一个节点（及其子树）。 |
| `node move` | 把一个节点（及其子树）重新挂到新的父节点下，或用 `--index` 调整同级顺序。 |
| `node connect-signal` | 把源节点的信号接到目标节点的方法上。 |
| `node disconnect-signal` | 断开一个已有的「信号→方法」连接。 |

对于 `Control` 节点，`node set --property position` 会写入底层的
`offset_left` / `offset_top` / `offset_right` / `offset_bottom`，同时保留尺寸。
`Container` 的直接子节点由布局管理，因此应显式设置这些 offset 属性。

**`script`** — GDScript 文件（`.gd`）

| 命令 | 作用 |
| ------- | ------------ |
| `script create` | 从模板或原样的 `--content` 创建一个新的 `.gd` 脚本。 |
| `script get` | 读取一个脚本的源码及其 `class_name` / `extends` 元数据。 |
| `script list` | 枚举已解析项目中的 `.gd` 脚本。 |
| `script set` | 通过搜索替换、行范围或整体覆写来编辑一个脚本。 |
| `script delete` | 删除一个脚本文件并报告删除了什么。 |
| `script attach` | 按节点路径把一个 `.gd` 脚本附加到场景里的某个节点上。 |
| `script validate` | 对一个 `.gd` 脚本做语法 / 编译检查。 |

对 `script validate --json`，要读取结果对象里的 `valid` 字段。脚本无法编译仍然是一个成功操作：
退出码为 `0`，没有顶层 `error`，并以 `valid: false` 携带 `error_string` / `diagnostics`。
缺失文件等操作层问题仍然使用正常的 Error envelope。

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

**`resource`** — 资源文件（`.tres`）

| 命令 | 作用 |
| ------- | ------------ |
| `resource create` | 创建一个给定类型的新 `.tres` 资源。 |
| `resource get` | 读取一个 `.tres` 资源的属性，输出带类型的 JSON。 |
| `resource set` | 设置一个 `.tres` 属性，并把值强制转换为它声明的类型。 |
| `resource delete` | 删除一个 `.tres` 资源文件并报告删除了什么。 |
| `resource uid` | 在资源 UID 与其 `res://` 路径之间双向解析。 |

**`export`** — 导出预设与产物

| 命令 | 作用 |
| ------- | ------------ |
| `export list` | 枚举项目的导出预设（名称、平台等）。 |
| `export get` | 报告某个预设的详情以及导出模板的安装状态。 |
| `export run` | 把一个具名预设（`release` / `debug` / `pack`）导出到目标位置。 |

**`shader`** — 着色器文件（`.gdshader`）

| 命令 | 作用 |
| ------- | ------------ |
| `shader create` | 从模板或原样的 `--content` 创建一个新的 `.gdshader`。 |
| `shader get` | 读取一个着色器的源码及其 `shader_type`。 |
| `shader set` | 通过搜索替换、行范围或整体覆写来编辑一个 `.gdshader`。 |

**`theme`** — 主题资源（`.tres`）

| 命令 | 作用 |
| ------- | ------------ |
| `theme create` | 创建一个可加载的全新 `.tres` Theme 资源（不覆盖已有文件）。 |

### Live 命令 — 经由 `gda-daemon`；Godot 4.6+，macOS/Linux

**`daemon`** — Live 运行时的生命周期

| 命令 | 作用 |
| ------- | ------------ |
| `daemon start` | 启动按项目运行的 daemon 并安装游戏内 harness；引擎会话会在第一个 Live 操作时启动（`screen` 截图需加 `--windowed`）。 |
| `daemon stop` | 停止项目的 daemon 以及任何正在运行的引擎会话。 |
| `daemon status` | 报告 daemon 的状态（是否运行、窗口模式、会话）。 |
| `daemon uninstall` | 从项目中移除游戏内 `gda` harness（autoload 条目 + 文件）——一次显式的开发工具拆除；`gda export run` 在导出产物时已经会自动剥除它。 |

**`game`** — 正在运行的游戏的运行时场景图

| 命令 | 作用 |
| ------- | ------------ |
| `game tree` | 读取正在运行的游戏的运行时场景树（在 `_ready` 之后）。 |
| `game get` | 按节点路径读取一个运行时节点的实时属性；显式命名时可读取附加脚本变量。 |
| `game rect` | 按节点路径读取一个运行时 Control 的渲染后视口矩形。 |
| `game set` | 在正在运行的游戏上设置运行时节点属性，或显式命名的附加脚本变量。 |

Live `game set --property position` 遵循与 `node set` 相同的 `Control` 策略；
`game rect` 仍然是只读的渲染几何查询。`game set` 的成功结果包含
`verified`：当观测到的读回值匹配本次请求的已转换值时为 `true`；当 set
已完成但观测值不同（例如 getter-only/no-op 脚本变量或边沿触发控制）时为
`false`。

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
| `perf monitors` | 对引擎的性能计数器拍一张快照（fps、内存、节点数等）。 |
| `perf monitor` | 在一个帧窗口内对某个节点属性或信号采样（时间线）。 |

**`input`** — 输入模拟

| 命令 | 作用 |
| ------- | ------------ |
| `input key` | 注入一个按键事件（带修饰键）。 |
| `input mouse-click` | 在 `(x, y)` 处注入一次鼠标点击。 |
| `input mouse-move` | 注入一次移动到 `(x, y)` 的鼠标移动。 |
| `input action` | 按下/释放一个已映射的输入动作。 |
| `input sequence` | 注入一条跨多帧的事件时间线。 |

鼠标事件会通过 `event.position` 报告注入的视口坐标。Godot 在 daemon 会话中可能让
`get_mouse_position()` / `get_global_mouse_position()` 保持过期状态，因此游戏代码应从输入事件读取注入的鼠标坐标。

**`screen`** — 视口捕获

| 命令 | 作用 |
| ------- | ------------ |
| `screen capture` | 把一帧视口捕获为一张 PNG。 |
| `screen frames` | 捕获一个 N 帧的 PNG 序列。 |

### 全局 flag

| Flag       | 说明                                                               |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | 在 stdout 上把结果作为单个 JSON 对象输出。不加它时，命令会打印一份简洁的、给人看的渲染结果。 |
| `--schema`  | 输出该命令的输入/输出 JSON Schema 契约（不会启动 Godot）。 |
| `--godot`   | Godot 二进制文件的路径（覆盖 `$GDA_GODOT` 和默认值）。 |
| `--project` | 用于 `res://` 解析的 Godot 项目目录（覆盖 `$GDA_PROJECT`；若当前目录本身是个项目则默认用它）。仅限领域命令。解析一个项目会运行该项目的代码——参见[项目代码执行](#configuration)。 |
| `--help`    | 显示 `gda` 或任意命令的用法。                                |

---

<a id="configuration"></a>
## 配置

`gda` 会从 **`--godot <path>`** flag 找到 Godot 二进制文件，否则就用
**`GDA_GODOT`** 环境变量——设置其中之一，`gda` 才能定位到你的引擎。

领域命令会按以下顺序解析一个 **Godot 项目**（以便 `res://` 路径以及场景的跨资源
引用能够确定性地解析）：

1. **`--project <dir>`** flag。
2. **`GDA_PROJECT`** 环境变量。
3. **当前目录**，当它本身是个 Godot 项目时（含有 `project.godot`）。

显式指定的目录必须是个项目，否则 `gda` 会把它当作错误上报。当没有任何一项解析成功时，
`gda` 会以**无项目（projectless）**方式运行——只有文件系统路径（绝对路径或相对于 cwd 的路径）
能解析，`res://` 不行。**MCP 服务器**没有 flag，所以它解析项目的方式略有不同：

| 上下文 | 项目解析顺序 |
| --- | --- |
| **CLI** | `--project` → `GDA_PROJECT`（两者都严格——无效即上报）→ 含有 `project.godot` 的 cwd，否则无项目 |
| **MCP**（`gda-mcp`） | `GDA_PROJECT`（严格——已设置但无效会被上报，而非跳过）→ 一个*有效的*客户端工作区 `root`（走 2026 前 MCP 协议的客户端；2026-07-28 修订版没有 roots，这类客户端直接跳到下一级）→ 一个*有效的*服务器 cwd，否则无项目 |

<details>
<summary>项目代码执行——当你指向一个项目时会运行什么</summary>

为了让 `res://` 路径生效而解析一个项目，会让 Godot 针对该项目运行，而 Godot 作为其中一环
会运行该项目自己的一部分代码。具体来说：

- **每个 `--project` 操作都会运行 autoload。** 当一个项目被解析时，引擎会在启动阶段——
  在命令本身的工作开始之前——构造该项目的 autoload 单例，因此它们的 `_init`（以及 `_ready`）
  会在**每一个**操作上执行，包括 `scene get`、`node list` 这类只读操作。如果没有解析到项目，
  就不会注册任何 autoload，它们也就不会运行。
- **会实例化场景的命令，会执行该场景所附脚本的构造函数。**
  任何需要一棵活节点树的命令——每一个会改动状态的命令（`node add`、`node set`、
  `node remove` 等），以及 `node get`（它会报告存储数据本身不携带的运行时属性默认值）——
  都会加载并实例化该场景，这会构造每个节点，并运行其中任何附加在节点上的脚本的 `_init`。
  只读取已存储场景数据的命令（`scene get`、`scene list`、`node list`）只是遍历它而不实例化，
  所以不会运行那些脚本。

`gda` 把目标项目视为受信任的，所以这是有意为之——信任模型参见
[ADR-0009](adr/0009-trust-boundary-trusted-project.md)。
</details>

---

<details>
<summary><strong>底层原理</strong> — 结构化输出契约与退出码</summary>

Headless 的 Godot 会把它的横幅、警告和 `print()` 输出交错混进 stdout。`gda`
用一套哨兵（sentinel）契约来解决这个问题
（[ADR-0002](adr/0002-headless-structured-output-contract.md)）：

- GDScript 负载在 stdout 上只输出**恰好一个**结果，用唯一的哨兵包裹起来：

  ```
  <<<GDA:RESULT>>>{ …json… }<<<GDA:END>>>
  ```

- 它把自己**全部**的诊断信息都导向 stderr；stdout 上除了契约什么都不带。
- `gda` 只提取并解析两个哨兵之间的字节，忽略周围的引擎噪声，并把 stderr 暴露出来供检查。

正是这一点让 `gda` 的输出可以安全地被程序化消费，而且它还推广成了 daemon 为 Live 操作
所用的逐消息协议。

**退出码（CLI ABI）。** 一次失败的 `gda` 运行会以一个小而稳定的退出码退出，这样 shell
或 agent 就能**在不解析 JSON 错误的情况下**按失败**类别**分支处理：

| 退出码 | 类别      | 何时                                                                  |
| --------- | ------------- | --------------------------------------------------------------------- |
| `0`       | —             | 成功。                                                              |
| `127`     | `environment` | Godot 二进制文件无法启动（shell 惯例：not found）。 |
| `124`     | `environment` | Godot 启动了，但在 runner 超时之前没有返回（shell 惯例：timed out）。 |
| `3`       | `version`     | 检测到的 Godot 版本低于受支持的最低版本。            |
| `4`       | `operation`   | 引擎运行了，但操作失败了——一个已注册的操作错误、一次引擎崩溃，或一次非结构化的非零退出。 |
| `5`       | `parse`       | 进程声称成功，却违反了结构化输出契约。 |
| `6`       | `live`        | 一个 Live 操作失败了——例如没有正在运行的 daemon/会话，或一次 Live 超时。 |

这些值就是公开 ABI；其权威来源是
[`src/gda/exit_codes.py`](../src/gda/exit_codes.py)。`{"error": {category, code, …}}`
信封在每个类别之内还携带一个**更细的 `code`**（例如 `path_not_found`、
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

`e2e` 这一层在 `uv run pytest` 时默认运行，并且会**大声报错**——指出解析到的路径以及如何修复——
如果在那里找不到 Godot 二进制文件，而不是悄悄跳过。用 `-m "not e2e"` 可以把整层排除掉
（CI 的每个 PR 任务正是这么做的）。

Lint 和格式化由 [ruff](https://docs.astral.sh/ruff/) 强制执行——用一个工具取代
flake8 + black + isort，配置在 `pyproject.toml` 的 `[tool.ruff]` 下，并通过 `uv.lock`
锁定版本，让本地和 CI 保持一致。CI 的 `lint` 任务会在每个 PR 上运行 `ruff check .` 和
`ruff format --check .`；提交前先运行 `uv run ruff format .` 以保持绿色。

类型由 [pyright](https://microsoft.github.io/pyright/) 以 `basic` 模式检查，覆盖
`src/` 和 `tests/`，配置在 `pyproject.toml` 的 `[tool.pyright]` 下（同样通过
`uv.lock` 锁定版本）。CI 的 `type-check` 任务会在每个 PR 上运行 `uv run --frozen pyright`。

```
src/gda/
  cli.py            # CLI entrypoint (Typer): all command groups, --json / --schema
  surface.py        # walks the live Typer tree → the `gda schema` manifest
  headless.py       # the per-command descriptor (one HeadlessCommand per command)
  binary.py         # Godot binary resolution (flag > $GDA_GODOT > default)
  runner.py         # the one-shot headless spawn seam (Protocol + subprocess impl)
  live_runner.py    # the live-operation client that talks to gda-daemon
  models.py         # typed I/O models (Pydantic) backing --json and --schema
  errors.py / error_codes.py / exit_codes.py   # failure classification + the CLI ABI
  render.py         # human-readable (non-JSON) rendering
  ops/operations.gd # the headless GDScript payload, dispatched by operation name
  daemon/           # gda-daemon: server, session supervision, IPC protocol, discovery
  harness/          # the inert in-game `gda` autoload injected into a live session
  mcp/              # gda-mcp: the schema → MCP-tool server
tests/              # unit + e2e tests against a real engine (shared fixtures in conftest.py)
docs/adr/           # architecture decision records
CONTEXT.md          # the project's shared domain language
```

`gda` 有两条外部边界，每条背后都有一个接缝（seam）供快速测试注入：启动一个一次性的
headless 进程（`runner.py`），以及通过 daemon 与正在运行的游戏对话（`live_runner.py`）。
e2e 套件会驱动一个真实引擎跨越这两者。
</details>

---

<a id="contributing"></a>
## 贡献

欢迎贡献。请阅读 [`CONTEXT.md`](../CONTEXT.md) 以对齐项目的共享语言，并查阅你所触及领域的
相关 [ADR](adr/)。Issue 和 PRD 以 [GitHub issues](https://github.com/aigengame/godot-agent/issues)
的形式存在。提交遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范。
Python 代码用 [ruff](https://docs.astral.sh/ruff/) 做 lint 和格式化、用
[pyright](https://microsoft.github.io/pyright/) 做类型检查，二者都在 CI 中强制执行——
提交前先运行 `uv run ruff format .` 和 `uv run pyright`（见上面的**开发**部分）。

> **正在和 AI 编程 agent 协作？** 本项目从设计上就便于 agent 导航——
> [`AGENTS.md`](../AGENTS.md) 是编程 agent 的入口，把项目的规则、领域文档和 skill 都
> 串接了进来。

<a id="license"></a>
## 许可证

基于 [MIT License](../LICENSE) 发布。Copyright (c) 2026 aigengame。
