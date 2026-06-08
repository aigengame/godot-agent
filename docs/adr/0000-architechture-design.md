# Godot-Agent 架构方案设计

## 背景

为了便于 agent 操作 Godot 引擎并制作游戏，需要提供能够作为 Godot 操作接口的的、带结构化输出的、面向 agent 的 cli 工具 与 mcp 服务.

Godot 自身提供有 Godot --headless 命令行操作工具， 但并非面向 agent 提供，不支持结构化输出 . 

其他 godot mcp 仓库(见 `参考仓库` 一节内容)，虽然提供了 godot mcp 的实现，但是没有提供 cli 实现，其完备性、性能、状态一致性等，都有所欠缺.

## 目标

godot-agent(以下简称 `gda`) 将实现面向 agent 的 Godot cli 与 mcp ，它们具有功能完备、高性能、状态一致等优势.

目标按自底向上、由简单到复杂，依次为：

- `gda` : godot-agent 的 cli 实现，覆盖完整的 Godot 操作功能，支持结构化输出 `--json`, `--schema` 等. 独立运行，不依赖任何服务. 提供底层能力，作为自动化的入口.

- `gda-mcp`   : godot-agent 的 mcp 实现. 对 gda 的薄层封装，作为协议适配，提供 mcp 服务.

- `gda-daemon` : 由于 gda, gda-mcp 都是无状态的调用，从性能与功能方面考虑，gda-daemon 能够提供长久且状态一致的 gda 服务.

## 开发规范

- 基于垂直切片的、TTD驱动的增量式开发
    - 垂直切片是贯穿所有层的、最小的可展示和可运行单元
    - TTD 使用 Red, Green, Refactor 迭代驱动开发

- 所有的issue(需求、特性、bug等)，都要经过 issue tracker 闭环

## 技术约束

- 采用 Python(3.13) 技术栈


