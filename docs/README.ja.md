<!-- gda-readme-i18n: source=README.md sha256=ff71c57fd774bc54d9bf9af04f9a7e6c4e7939ad4a38e5f9d12b693cc9bb379e -->

# gda — AI エージェント向け Godot オートメーション

[![gda — AI エージェント向け Godot オートメーション](https://raw.githubusercontent.com/aigengame/godot-agent/main/assets/godot-agent-title.png)](https://aigengame.xyz/)

**他の言語:** [English](../README.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · **日本語**

[製品概要](https://aigengame.xyz/) ·
[CLI、Agent Skill、MCP のどれを選ぶ？](https://aigengame.xyz/godot-mcp/) ·
[PyPI](https://pypi.org/project/gda/)

> **AI コーディングエージェント、シェルスクリプト、CI から Godot プロジェクトを構築・検証できます。**
> `gda` は、Headless 検証と Live ランタイムの検査・操作を備えた Godot オートメーションを、
> CLI、同梱の Agent Skill、MCP サーバーのいずれかを通じて提供し、エージェントがそのまま
> 処理できる構造化結果を返します。

[![pre-1.0](https://img.shields.io/badge/status-pre--1.0-orange)](https://pypi.org/project/gda/)
[![CI](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Godot](https://img.shields.io/badge/godot-4.4%2B%20(live%204.6%2B)-478CBF)](https://godotengine.org)
[![Platform](https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-lightgrey)](#how-it-works)
[![MCP](https://img.shields.io/badge/MCP-server-000)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

`gda` は、この構築・検証ワークフローに 2 つの相補的なモードを提供します。

- **Headless** — エディタプラグインやデーモンを使わずに、プロジェクト内容の作成・編集、
  スクリプトのコンパイル、シーンの検証と起動、プロジェクト構造の分析、ビルドのエクスポートを行います。
- **Live** — プロジェクトごとのデーモンを通じて実行中のゲームを検査・操作します。
  ランタイムツリーと状態、入力シミュレーション、フレーム取得、ログ、エラー、パフォーマンスを扱えます。

> `gda` は **pre-1.0** です。現時点ですべてのコマンドがエンドツーエンドで動作しますが、
> コマンド体系は 1.0 までにまだ変わる可能性があります。

---

## 目次

- [なぜ `gda`？](#why-gda)
- [ひと目でわかる機能](#capabilities-at-a-glance)
- [インストール](#installation)
- [クイックスタート](#quick-start)
- [統合方法を選ぶ](#choose-your-integration)
- [仕組み](#how-it-works)
- [コマンドリファレンス](#command-reference)
- [設定](#configuration)
- [コントリビューション](#contributing)
- [ライセンス](#license)

---

<a id="why-gda"></a>
## なぜ `gda`？

- **ゲーム開発ライフサイクルを通じた検証。** Headless 検証はプロジェクトが実行可能な状態かを確認し、
  Live 操作は実際の挙動に関するランタイム証拠を返します。
- **構造化結果と参照可能なスキーマ。** `--json` を使うと、各コマンドは stdout に結果
  オブジェクトを 1 つだけ出力します。型付きの入出力モデルは、`--schema` と生成される
  MCP ツール体系にも使われます。
- **Godot ネイティブな境界づけられたコンテキストとユビキタス言語。** `gda` は Godot に
  沿った単一の操作モデルと語彙を使用し、エージェントがプロジェクト内容とランタイム状態を
  一貫した用語で扱えるようにします。
- **制約された環境でも安定して実行。** ユーザーデータとログを書き込み可能な場所へ移し、
  同時実行を分離し、Godot がクラッシュする前に型付きの環境エラーを返します。これにより、
  エージェントはサンドボックス内でも作業しやすくなります。
- **相補的な 3 つのアクセス方法。** エージェント、シェル、CI から CLI を直接実行する、
  再利用可能なガイダンスとして同梱の Agent Skill をインストールする、または同じ操作を
  MCP ツールとして公開できます。各方式の比較と違いは
  [CLI、Agent Skill、MCP のどれを選ぶ？](https://aigengame.xyz/godot-mcp/)で確認できます。
- **範囲を制御でき、失敗後に対応できる自動化。** タイムアウト、出力上限、型付きの失敗、
  診断情報、変更レポートにより、エージェントは何が起きたかと復旧方法を判断できます。

これらの機能は[実際のゲーム制作](https://aigengame.xyz/#showcase)を通じて磨かれ、その過程は
公開されている[dogfooding の記録](https://github.com/aigengame/godot-agent/milestone/10)にまとめられています。

---

<a id="capabilities-at-a-glance"></a>
## ひと目でわかる機能

| 目的 | `gda` が提供するもの | 最初に使うもの |
| --- | --- | --- |
| Godot プロジェクトの内容を構築する（Headless） | シーン、ノード、スクリプト、リソース、プロジェクト設定、シェーダー、テーマの作成と編集 | `scene` / `node` / `script` / `resource` / `project` / `shader` / `theme` |
| プロジェクトの実行準備を検証する（Headless） | スクリプトのコンパイル、依存関係の検証、時間制限付き preflight でのシーン起動、プロジェクト構造の分析、ビルドのエクスポート | `script validate` / `scene validate` / `scene preflight` / `project` / `export` |
| ランタイム挙動を検証する（Live） | ランタイム状態の読み取り、宣言済みメソッドの呼び出し、入力シミュレーション、フレーム取得、ログとエラーの収集、パフォーマンス計測 | `gda daemon start`、その後 `game` / `input` / `screen` / `diag` / `logger` / `perf` |
| AI コーディングエージェントを接続する | CLI の直接実行、Agent Skill の再利用可能なガイダンス、または MCP ツールの検出と呼び出し | `gda` / `gda skill` / `gda-mcp` |
| 自動化環境で安定して実行する | 構造化結果、型付きのスキーマと失敗、範囲を制御した実行、分離されたログ、復旧に使える診断情報 | `--json` / `--schema` / `--user-data-root` / タイムアウト |

---

<a id="installation"></a>
## インストール

**要件:** Python 3.13 以上、および [Godot](https://godotengine.org) バイナリ — Headless コマンドには
4.4 以上、macOS/Linux での Live(デーモン)コマンドには 4.6 以上。

PyPI から CLI を `PATH` 上にインストールします。

```bash
uv tool install gda      # or: pipx install gda
gda --help
```

<details>
<summary>その他のインストール方法(pip、ソースから)</summary>

既存の環境へインストールする場合:

```bash
pip install gda
```

ソースから(開発用または未リリースの変更):

```bash
git clone https://github.com/aigengame/godot-agent.git
cd godot-agent
uv sync                  # create the environment + install dependencies
uv run gda --help
```
</details>

---

<a id="quick-start"></a>
## クイックスタート

**`gda` に Godot バイナリの場所を教え**、エンジンにバージョンを尋ねます — プロジェクトは不要です。

```bash
export GDA_GODOT="/path/to/Godot"   # or pass --godot to any command
gda info --json
# {"major":4,"minor":6,"patch":3,"status":"stable","string":"4.6.3-stable (official)",…}
```

stdout は常にパイプ可能なクリーンな JSON です。エンジンとスクリプトの診断出力はすべて stderr に
流れます。

```bash
gda info --json | jq .major   # → 4
```

**シーンを Headless で構築します。** 一度 `gda` に Godot プロジェクト(`project.godot` を含む
ディレクトリ)を指定すれば、相対パスはその *内部* で解決され、ノードはシーンルートからの相対パスで
指定されます。

```bash
export GDA_PROJECT="/path/to/your/godot-project"   # or pass --project to any command
gda scene create scenes/main.tscn --root-type Node2D --json
gda node add  scenes/main.tscn --type Sprite2D --name Hero --json
gda node set  scenes/main.tscn --node Hero --property position --value 10,20 --json
gda scene get scenes/main.tscn --json
# {"path":"scenes/main.tscn","root":{"name":"main","type":"Node2D","children":[{"name":"Hero",…}]}}
```

> プロジェクトがない? `gda` はそれでも、プレーンなファイルシステムパス(カレントディレクトリからの
> 相対)に対して **projectless(プロジェクトなし)** で動作します — プロジェクトが必要なのは `res://`
> の解決だけです。[設定](#configuration) を参照してください。

**実行中のゲームを Live で操作します。** Live 操作はプロジェクトの **メインシーン** を実行します。
そのため、いま構築したシーンを Godot の `application/run/main_scene` プロジェクト設定(エディタの
*Application → Run → Main Scene*)で指定し、デーモンを起動します(macOS/Linux、Godot 4.6 以上)。

```bash
gda project set application/run/main_scene --value res://scenes/main.tscn --json  # a Godot project setting key
gda daemon start             # start the daemon for $GDA_PROJECT (installs the in-game harness)
gda game tree --json         # the runtime scene tree, after _ready
gda perf monitors --json     # live engine counters: fps, memory, node count
gda daemon stop
```

(`gda screen capture` も Live で動作しますが、ウィンドウ付きのセッションが必要です — `gda daemon
start --windowed` でデーモンを起動してください。)

---

<a id="choose-your-integration"></a>
## 統合方法を選ぶ

`gda` は **同じコマンド体系** を 3 通りで公開します — エージェント(またはあなた)が対応している
方法を選んでください。

| 入口 | 適した用途 | 方法 |
| --- | --- | --- |
| **CLI**(`gda`) | 人間、シェルスクリプト、CI、コマンドを実行できるエージェント | `gda <group> <command> --json` |
| **Skill**(`gda skill`) | Agent Skills に対応し、トークン消費の少ない CLI ワークフローを好むコーディングエージェント | `SKILL.md` を出力/インストール(下記) |
| **MCP**(`gda-mcp`) | Model Context Protocol 経由でツールを呼び出すエージェント | stdio サーバーを実行(下記) |

### Skill として使う

`gda` はエージェント **Skill** を同梱しています — `SKILL.md` であり、AI エージェントに CLI から Godot を
操作する *方法とタイミング* を教えます。これは最も軽量な入口で(登録するサーバーがありません)、
パッケージに同梱され、インストール済みのバージョンに固定されています。出力するか、エージェントの
スキルディレクトリにインストールします。

```bash
gda skill                                              # print SKILL.md (redirect it anywhere)
gda skill --install --provider claude --scope user     # resolve a known agent's skills dir
gda skill --install --dir ~/.claude/skills/gda         # …or give the directory yourself
```

[Skill レシピ](gda-skill.md) には各エージェントのスキルディレクトリが記載されています。あるいは同じファイルを
リポジトリから直接取得することもできます — Skill は `gda` を呼び出して動くので、`gda` 自体のインストールは引き続き必要です。

```bash
curl --create-dirs -o ~/.claude/skills/gda/SKILL.md \
  https://raw.githubusercontent.com/aigengame/godot-agent/main/src/gda/skill/SKILL.md
```

### MCP サーバーとして使う

`gda` は `[mcp]` エクストラの背後に stdio の [MCP](https://modelcontextprotocol.io) サーバーを同梱しており、
あらゆる MCP エージェント(Claude Code、Codex、Cursor など)が Godot を操作できます。インストールせずに
試すには:

```bash
uvx --from "gda[mcp]" gda-mcp
```

サーバーは、操作する Godot **プロジェクト**と、実行する Godot **バイナリ**の 2 つを決めます
（MCP では呼び出しごとにフラグを渡せません）。

- **プロジェクト** — `GDA_PROJECT` を設定します。未設定の場合、`gda-mcp` はクライアントから送られたワークスペースの
  **roots**（エディタで開いているフォルダ）を使います。ただし MCP 2026-07-28 改訂版では roots が非推奨になったため、
  クライアントを更新しても同じプロジェクトを使えるよう、`GDA_PROJECT` を固定してください。[設定](#configuration) を参照してください。
- **エンジン** — `GDA_GODOT` に Godot バイナリを設定します。例: `"GDA_GODOT": "/path/to/Godot"`。

`gda-mcp` は、2026 年以前の MCP と **2026-07-28 改訂版**の両方に対応しています。ただし、プロジェクトの
決め方は異なります。2026 年以前のクライアントは roots を送りますが、新しい改訂版のクライアントは送らないため、
`gda-mcp` は `GDA_PROJECT` またはサーバーの cwd からプロジェクトを決めます。クライアントを移行する前に
`GDA_PROJECT` を固定してください。新しい改訂版では、`gda-mcp` は `tools/list` がキャッシュ可能（TTL 1 時間）であることも示します。

#### コーディングエージェントへの登録

<details>
<summary>Claude Code</summary>

プロジェクトスコープ。リポジトリルートの `.mcp.json`(`roots` 経由でプロジェクトを自動検出):

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

ユーザースコープ(すべてのプロジェクト)— `~/.claude.json` に書き込む CLI:

```bash
claude mcp add --scope user gda-mcp -- uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Codex</summary>

プロジェクトスコープ。リポジトリルートの `.codex/config.toml`(プロジェクトが信頼済みである必要が
あります):

```toml
[mcp_servers.gda-mcp]
command = "uvx"
args = ["--from", "gda[mcp]", "gda-mcp"]

[mcp_servers.gda-mcp.env]
GDA_PROJECT = "/absolute/path/to/your/godot/project"
```

ユーザースコープ(どこでも利用可能だが、1 つのプロジェクトに固定)— `~/.codex/config.toml` に同じ
テーブルを置くか、CLI で追加します。Codex にはワークスペース変数がないため、`GDA_PROJECT` は絶対
パスになります。複数のプロジェクトをまたいで作業する場合はプロジェクトスコープを使ってください。

```bash
codex mcp add gda-mcp --env GDA_PROJECT=/absolute/path/to/your/godot/project -- \
  uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Cursor</summary>

プロジェクトスコープ。リポジトリルートの `.cursor/mcp.json`(`${workspaceFolder}` が開いている
プロジェクトを追跡):

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

ユーザースコープ(どこでも利用可能だが、1 つのプロジェクトに固定)— `~/.cursor/mcp.json` に同じ設定を
置き、`GDA_PROJECT` を絶対パスに設定します(`${workspaceFolder}` はプロジェクトスコープでのみ機能
します。複数のプロジェクトにはプロジェクトスコープを使ってください)。Cursor には `mcp add` コマンドが
ないため、上記の JSON か Settings → MCP の UI から登録します。

> Cursor は最小限の `PATH` で GUI から起動されるため、素の `uvx` は解決できないことがあります —
> 上記で絶対パスの `command` を使っているのはこのためです。`which uvx` の出力で埋めてください。
> 完全なレシピ — PATH の注入、Claude Desktop、ユーザースコープ対プロジェクトスコープ、エージェント
> ごとのプロジェクト固定 — は [登録レシピ](gda-mcp-registration.md) にあります。
</details>

---

<a id="how-it-works"></a>
## 仕組み

`gda` は、2 つのモードで操作を提供する 3 つのコンポーネントから成ります。

| コンポーネント | 役割 |
| ---------------- | --------------------------------------------------------------------- |
| **`gda`**        | エージェント向けの CLI — Godot を構造化された `--json` 出力で公開します。 |
| **`gda-mcp`**    | 同じ操作を `--schema` からツールとして公開する MCP サーバー。 |
| **`gda-daemon`** | Live 操作のために実行中ゲームを監督する、プロジェクトごとのプロセス。 |

- **Headless 操作** はワンショットで実行されます — デーモンも、インストールするものも不要です
  (シーンの作成、スクリプトの編集、エクスポート、解析)。
- **Live 操作** には実行中のゲームが必要です — `gda-daemon` がそれを起動し、不活性なゲーム内ハーネスを
  注入し、Unix ドメインソケット経由でリクエストを仲介します(ランタイムツリー、入力、スクリーン
  ショット、パフォーマンス、診断)。

`gda-daemon` が注入するゲーム内ハーネスは **開発専用** です。`gda export run` は成果物からそれを完全に
取り除きます。また、それ以外の方法(エディタの GUI、素の `godot --export`)でビルドしても、エクスポート
済みゲーム内で自己無効化します — そのため、出荷されるゲームがデーモン関連のものを *実行する* ことは
決してありません(そして `gda export run` 経由なら、そもそも同梱すらされません)。

**プラットフォームとバージョンのサポート:**

| モード | Godot | プラットフォーム |
| ---- | ----- | --------- |
| **Headless** | 4.4+ | macOS · Linux · Windows¹ |
| **Live**(`gda-daemon` 経由) | 4.6+ | macOS · Linux² |

¹ Headless は設計上クロスプラットフォームです(ワンショットのプロセスで、プラットフォーム固有の
  依存がありません)— Windows でも Headless の全機能が使えますが、CI ではまだ検証されていません。
² Live 操作は Unix ドメインソケットを使うため、Windows はまだサポートされていません。

---

<a id="command-reference"></a>
## コマンドリファレンス

`gda` のコマンドは **Godot のドメインオブジェクトごとにグループ化** され、小さく一貫した動詞の語彙を
使います。そのため同じ動詞は、どのグループでも同じ意味を持ちます。

| 動詞                | 意味                                                           |
| ------------------- | ----------------------------------------------------------------- |
| `create` / `delete` | **独立した** エンティティ(シーン、スクリプト、リソース)を作成/削除します。 |
| `add` / `remove`    | コンテナ内の **サブエンティティ**(ノード → シーン)を追加/削除します。 |
| `get` / `list`      | 1 つのエンティティを読み取る/複数を列挙します。 |
| `set`               | プロパティを変更します。 |
| ドメイン固有の動詞  | `play`、`run`、`export`、`import` など、本来の意味のまま使います。 |

すべてのコマンドは `--json` と `--schema` をサポートします。`res://` パスを読み取りまたは変更するコマンドは
[プロジェクトコンテキスト](#configuration) を解決します。完全なフラグについては `gda <group> <command> --help`
を実行してください — `gda --help` がインストール済みのものを示す信頼できる一覧です。

**はじめての方へ:** おすすめの最初の流れ: `gda info` → `gda scene create` → `gda node add` →
`gda script validate` → `gda export run`。その後 `gda daemon start` → `gda game tree` で Live に進みます。

**Meta** — `gda` やエンジン自体について

| コマンド | 機能 |
| ------- | ------------ |
| `gda info`   | Godot エンジンのバージョンを報告します。 |
| `gda version` | インストールされている `gda` のバージョンとインストール元を報告します（`--json` で詳しいインストール来歴も出力）。 |
| `gda help`   | コマンドのヘルプ(`gda help scene get`)または CLI 全体のヘルプを表示します。 |
| `gda schema` | コマンド体系全体を 1 つの機械可読な JSON マニフェストとして出力します。 |
| `gda skill`  | エージェントに `gda` の操作方法を教える同梱の Agent Skill(`SKILL.md`)を出力またはインストールします。 |

### Headless コマンド — Godot 4.4 以上、全プラットフォーム

**`scene`** — シーンファイル(`.tscn`)

| コマンド | 機能 |
| ------- | ------------ |
| `scene create` | 指定したルートノードタイプで新しい `.tscn` を作成します。 |
| `scene get` | シーンを読み取り、その構造化されたノードツリーを報告します。 |
| `scene list` | 解決済みプロジェクト内の `.tscn` シーンを列挙します。 |
| `scene get-exports` | シーンのノードのスクリプトが宣言する `@export` プロパティを一覧します。 |
| `scene delete` | シーンファイルを削除し、削除された内容を報告します。 |
| `scene validate` | シーンを**静的に**検査します——依存が解決でき、バインドされたスクリプトがコンパイルできるかを、サブシーンも含めて調べます。シーンはインスタンス化しません（プロジェクトのオートロードは、他の `--project` コマンドと同じく起動します）。問題がある場合もエラー終了せず、検査結果（`valid: false`、終了コード `0`）として返します。 |
| `scene preflight` | シーンを**動的に**検査します——headless で起動して `_ready` を実行し、`started` と起動中に検出したスクリプトエラーを報告します。起動できなかった場合もエラー終了せず、検査結果として返します。 |

両方を実行してください。`scene get` では、スクリプトが欠けたシーンも問題なく読み取れてしまいます。そのファイルを
特定できるのは `validate` だけで、最初のフレームでの失敗を捕まえられるのは `preflight` だけです。

**`node`** — シーンファイル内のノード

| コマンド | 機能 |
| ------- | ------------ |
| `node add` | 親の下にノードを追加します。必要なら `--index` で位置を指定できます: 組み込みタイプ、`class_name` スクリプト、または `--instance` で別のシーンをインスタンス化した子として合成します。 |
| `node get` | ノードのプロパティを(ノードパスで指定して)型付き JSON として読み取ります。 |
| `node list` | シーンのノードツリーを、各ノードのルートからの相対パスとともに一覧します。 |
| `node set` | ノードのプロパティを設定します。値は宣言された Godot の型に変換されます。`Control` では `position` が 4 つの offset を書き込みます。`Container` の子はレイアウト管理下にあるため、offset を直接設定してください。 |
| `node remove` | ノード(およびそのサブツリー)をノードパスで指定して削除します。 |
| `node duplicate` | ノード(およびそのサブツリー)を親の下に複製します。 |
| `node move` | ノード(およびそのサブツリー)を新しい親の下に付け替えるか、`--index` で兄弟順を並べ替えます。 |
| `node connect-signal` | ソースノードのシグナルをターゲットノードのメソッドに接続します。 |
| `node disconnect-signal` | 既存のシグナル → メソッド接続を解除します。 |

**`script`** — GDScript ファイル(`.gd`)

| コマンド | 機能 |
| ------- | ------------ |
| `script create` | テンプレートまたはそのままの `--content` から新しい `.gd` スクリプトを作成します。 |
| `script get` | スクリプトのソースと、その `class_name` / `extends` メタデータを読み取ります。 |
| `script list` | 解決済みプロジェクト内の `.gd` スクリプトを列挙します。 |
| `script set` | 検索置換、行範囲指定、または全体上書きでスクリプトを編集します。 |
| `script delete` | スクリプトファイルを削除し、削除された内容を報告します。 |
| `script attach` | シーン内のノードに(ノードパスで指定して)`.gd` スクリプトをアタッチします。 |
| `script validate` | `.gd` スクリプトのコンパイルチェックを行います——PATH を複数渡せば 1 回のエンジン起動で済み、`--all` でプロジェクト全体を対象にできます。集約された `valid` と、`scripts` 内のスクリプトごとのエントリを報告します。コンパイルできないスクリプトがあってもエラー終了せず、検査結果（`valid: false`、終了コード `0`）として返します。 |
| `script run` | プロジェクトスクリプトをワンショットのエントリポイントとして headless 実行します。上限は `--timeout` です。スクリプトの `exit_status` と `stderr` はそのまま返され、`stdout` は 64 KiB までがインラインで返されます。切り詰められた場合は、完全な stdout が結果に示されたファイルに書き出されます。非ゼロの `quit()` は失敗ではなく結果データとして扱われ、`--strict` を渡したときだけ失敗になります。 |

**`project`** — プロジェクト全体(設定、オートロード、静的解析)

| コマンド | 機能 |
| ------- | ------------ |
| `project info` | プロジェクトのメタデータ(名前、メインシーン、ビューポート、エンジンバージョン)を報告します。 |
| `project get` | 単一のプロジェクト設定を section/key で指定し、型付き JSON として読み取ります。 |
| `project list` | プロジェクトの設定キーを一覧します(デフォルトはカスタマイズ済みのもの。`--all` でエンジンのデフォルトを追加、`--section` でプレフィックスによりフィルタ)。 |
| `project set` | プロジェクト設定を設定します。値は宣言された型に変換されます。 |
| `project add-autoload` | オートロードのシングルトンを登録します(名前 → スクリプト/シーン)。 |
| `project remove-autoload` | オートロードのシングルトンを名前で指定して登録解除します。 |
| `project add-input-action` | キーに割り当てた InputMap アクションを登録します(`--key` はキー名またはキーコード、`--deadzone`、`--physical`)。 |
| `project remove-input-action` | InputMap アクションを名前で指定して登録解除します。 |
| `project find-references` | 指定したリソースを参照するすべてのプロジェクトファイルを見つけます。 |
| `project dependencies` | 各シーン/リソースを、それが依存するリソースに対応付けます。 |
| `project find-unused-resources` | どこからも参照されていないリソースファイルを見つけます。 |
| `project statistics` | プロジェクトのファイル数/行数、オートロードなどを報告します。 |

**`resource`** — リソースファイル(`.tres`)とプロジェクトのインポート済みアセット

| コマンド | 機能 |
| ------- | ------------ |
| `resource create` | 指定したタイプの新しい `.tres` リソースを作成します。 |
| `resource get` | `.tres` リソースのプロパティを型付き JSON として読み取ります。 |
| `resource set` | `.tres` のプロパティを設定します。値は宣言された型に変換されます。 |
| `resource delete` | `.tres` リソースファイルを削除し、削除された内容を報告します。 |
| `resource uid` | リソースの UID とその `res://` パスを双方向で相互変換します。 |
| `resource import` | アセットをプロジェクトキャッシュにインポート済みにします(クリーンワークツリーでのロード)。 |

**`export`** — エクスポートのプリセットと成果物

| コマンド | 機能 |
| ------- | ------------ |
| `export list` | プロジェクトのエクスポートプリセット(名前、プラットフォームなど)を列挙します。 |
| `export get` | 1 つのプリセットの詳細と、エクスポートテンプレートのインストール状況を報告します。 |
| `export run` | 名前付きプリセット(`release` / `debug` / `pack`)を指定先にエクスポートします。 |

**`shader`** — シェーダーファイル(`.gdshader`)

| コマンド | 機能 |
| ------- | ------------ |
| `shader create` | テンプレートまたはそのままの `--content` から新しい `.gdshader` を作成します。 |
| `shader get` | シェーダーのソースと、その `shader_type` を読み取ります。 |
| `shader set` | 検索置換、行範囲指定、または全体上書きで `.gdshader` を編集します。 |

**`theme`** — テーマリソース(`.tres`)

| コマンド | 機能 |
| ------- | ------------ |
| `theme create` | ロード可能な新しい `.tres` テーマリソースを作成します(既存を上書きしません)。 |

### Live コマンド — `gda-daemon` 経由、Godot 4.6 以上、macOS/Linux

**`daemon`** — Live ランタイムのライフサイクル

| コマンド | 機能 |
| ------- | ------------ |
| `daemon start` | プロジェクトごとのデーモンを起動し、ゲーム内ハーネスをインストールします。エンジンセッションは、最初に必要になった操作で起動します（`screen` キャプチャには `--windowed`）。プロジェクトに `application/run/main_scene` が定義されているか、`--scene` を渡す必要があります。 |
| `daemon wait-ready` | エンジンセッションを今すぐ起動し、準備完了まで待ちます。`--timeout` はデーモンがこの起動に割り当てる予算であって、呼び出し自体の厳密な上限ではありません。読み取り専用の `diag` / `logger` はセッションを起動しないため、それが最初の Live コマンドになるときは先にこれを実行してください。 |
| `daemon stop` | プロジェクトのデーモンと、実行中のエンジンセッションを停止します。 |
| `daemon status` | デーモンの状態(実行中か、ウィンドウモードか、セッション)を報告します。 |
| `daemon install` | デーモンを起動せずにゲーム内ハーネスをインストールし、何を書き込んだかを報告します。冪等です。`daemon start` 自身がこれを行うため、`project.godot` の変更だけをレビューまたはコミットしたいときにだけ使います。 |
| `daemon uninstall` | ゲーム内ハーネス——オートロードのエントリ、ハーネスのファイル、`.uid` サイドカー——を削除して `project.godot` を元に戻し、削除した内容を報告します。開発ツールの撤去専用です。`gda export run` はエクスポート済みビルドからハーネスをすでに自動で取り除きます。 |

**`game`** — 実行中ゲームのランタイムシーングラフ

| コマンド | 機能 |
| ------- | ------------ |
| `game tree` | 実行中ゲームのランタイムシーンツリーを読み取ります(`_ready` の後)。 |
| `game get` | ランタイムノードのライブプロパティをノードパスで読み取ります。明示名ならアタッチ済みスクリプト変数も対象にできます。 |
| `game rect` | ランタイム Control のレンダリング済みビューポート矩形をノードパスで読み取ります。 |
| `game set` | 実行中ゲームのランタイムノードプロパティ、または明示名のアタッチ済みスクリプト変数を設定します。`verified` は読み戻し値が一致したかを報告します。 |
| `game call` | ノードのスクリプトが `GDA_CALLABLE` で宣言したメソッドを 1 つ呼び出し、その戻り値を構造化データとして返します。この宣言はプロジェクト自身による「読み取り専用」の約束であり、gda は検証できません。宣言されていないメソッドは呼び出しません。 |

`game call` は `game get` では読めないもの、つまりプロジェクトがメソッドとして公開する状態を読みます。
`game set --property position` は `node set` と同じ `Control` ルールに従います。

**`diag`** — ランタイム診断

| コマンド | 機能 |
| ------- | ------------ |
| `diag errors` | 実行中ゲームのランタイムエラーを(カテゴリ分けして)追尾します。 |

**`logger`** — 構造化されたランタイムログ

| コマンド | 機能 |
| ------- | ------------ |
| `logger tail` | 実行中ゲームのランタイムログ全体を、構造化されたレコードとして追尾します(`--level`、`--limit`、`--raw`)。 |

**`perf`** — パフォーマンス監視

| コマンド | 機能 |
| ------- | ------------ |
| `perf monitors` | エンジンのカウンタのスナップショットを取得します。`--frames` を付けるとフレームウィンドウをサンプリングし、集計統計とバジェット判定を出力します。 |
| `perf monitor` | ノードのプロパティまたはシグナルを、フレームのウィンドウ(タイムライン)にわたってサンプリングします。 |

**`input`** — 入力シミュレーション

| コマンド | 機能 |
| ------- | ------------ |
| `input key` | キーイベントを(修飾キー付きで)注入します。 |
| `input mouse-click` | `(x, y)` の位置に完全なクリックジェスチャ(移動、押下、解放)を注入します。 |
| `input mouse-move` | `(x, y)` へのマウス移動を注入します。 |
| `input action` | マッピング済みの入力アクションを押下/解放します。 |
| `input tap` | キーまたはアクションを 1 回タップします(押下、保持、解放を複数フレームで実行)。 |
| `input sequence` | 複数フレームにわたるイベントのタイムラインを注入します。 |

注入されたマウス座標は `event.position` から読み取ってください——デーモンセッションでは
`get_mouse_position()` / `get_global_mouse_position()` が古い値のままになることがあります。

**`screen`** — ビューポートのキャプチャ

| コマンド | 機能 |
| ------- | ------------ |
| `screen capture` | ビューポートの 1 フレームを PNG にキャプチャします。 |
| `screen frames` | N フレームの PNG シーケンスをキャプチャします(`--summary` でコンパクトな集約結果を返します)。 |

### グローバルフラグ

| フラグ       | 説明                                                          |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | 実行結果を stdout に単一の JSON オブジェクトとして出力します — 成功時は結果、失敗時は `{"error": {…}}` エンベロープです。指定しない場合、どちらも簡潔な人間可読のレンダリングとして出力されます。コマンドの前に置いても有効です。 |
| `--schema`  | コマンドの入出力 JSON Schema 契約を出力します(Godot は起動されません)。 |
| `--godot`   | Godot バイナリへのパス(`$GDA_GODOT` とデフォルトを上書きします)。 |
| `--project` | `res://` 解決のための Godot プロジェクトディレクトリ(`$GDA_PROJECT` を上書き。プロジェクトであればカレントディレクトリがデフォルト)。ドメインコマンドのみ。プロジェクトの解決はそのプロジェクトのコードを実行します — [プロジェクトコードの実行](#configuration) を参照してください。 |
| `--version` | インストール済みの `gda` のバージョンを表示します。`--json` を付けると、その出どころも出力します — インストール種別(`wheel`・`editable`・`unknown`)と、editable インストールの場合はソースチェックアウトの Git リビジョンです。 |
| `--help`    | `gda` または任意のコマンドの使い方を表示します。 |

---

<a id="configuration"></a>
## 設定

`gda` は Godot バイナリを **`--godot <path>`** フラグから、なければ **`GDA_GODOT`** 環境変数から
見つけます — `gda` がエンジンを見つけられるよう、どちらかを設定してください。

ドメインコマンドは、`res://` パスを解決するために、対象となる **Godot プロジェクト** を次の順で特定します。
明示的に指定したディレクトリがプロジェクトでなければ `gda` はエラーを報告します。どれにも当てはまらない
場合、`gda` は **projectless(プロジェクトなし)** で動作します — 通常のファイルシステムパスは使えますが、
`res://` は使えません。

| コンテキスト | プロジェクトの解決順序 |
| --- | --- |
| **CLI** | `--project` → `GDA_PROJECT`(どちらも厳格: 無効ならエラー)→ カレントディレクトリ(`project.godot` を含む場合)→ projectless |
| **MCP**(`gda-mcp`) | `GDA_PROJECT`(厳格)→ クライアントのワークスペース `root`(有効なものが送られてくる場合。2026 年以前のクライアントのみ)→ サーバーの cwd(プロジェクトである場合)→ projectless |

<details>
<summary>プロジェクトコードの実行 — プロジェクトを指定したときに何が実行されるか</summary>

`gda` をプロジェクトに向けると、そのプロジェクト自身のコードの一部が実行されます。プロジェクトは信頼済みとして
扱われるため、これは設計どおりです([ADR-0009](adr/0009-trust-boundary-trusted-project.md))。

- **オートロード**は、エンジンを起動するすべての `--project` 操作で実行されます。読み取り専用の操作も
  例外ではありません(キャッシュが完全な `resource import` は何も起動しません)。
- **シーンスクリプトの `_init`** は、シーンをインスタンス化する操作では必ず実行されます。すべての変更系
  `node` コマンドと `node get` が該当し、`scene get` / `scene list` / `node list` はインスタンス化せずに読み取ります。
- **`script run`** は指定したスクリプトをすべて実行し、**`scene preflight`** はシーンを起動して `_ready` を実行します。
- **`resource import`** はキャッシュ欠落時にエンジンのインポーター(およびプロジェクトのインポートプラグイン)を
  実行します。オートロードは実行されません。
- **`game call`** はノードの `GDA_CALLABLE` 宣言が指定した 1 つのメソッドだけを実行します。宣言されていない
  メソッドが呼ばれることはありません。

</details>

---

<details>
<summary><strong>内部の仕組み</strong> — 構造化出力の契約と終了コード</summary>

Headless の Godot は、バナー、警告、`print()` の出力を stdout に混在させます。`gda` はこれをセンチネル
契約で解決します([ADR-0002](adr/0002-headless-structured-output-contract.md))。

- GDScript ペイロードは **ちょうど 1 つ** の結果を、stdout 上で一意なセンチネルに包んで出力します。

  ```
  <<<GDA:RESULT>>>{ …json… }<<<GDA:END>>>
  ```

- 自身の診断出力は **すべて** stderr に流し、stdout は契約以外に何も載せません。
- `gda` はセンチネル間のバイトだけを抽出して解析し、周囲のエンジンノイズを無視します。そして検査用に
  stderr を提示します。

これが `gda` の出力をプログラム的に安全に扱える理由であり、デーモンが Live 操作に使うメッセージごとの
プロトコルにも一般化されています。

**終了コード(CLI ABI)。** 失敗した `gda` の実行は、小さく安定したコードで終了します。これにより、
シェルやエージェントは **JSON エラーを解析せずに** 失敗の **カテゴリ** で分岐できます。

| 終了コード | カテゴリ      | 条件                                                                  |
| --------- | ------------- | --------------------------------------------------------------------- |
| `0`       | —             | 成功。                                                              |
| `2`       | `usage`       | `gda` が要求内容を解決できませんでした — 認識できないコマンドまたはオプション。既知の近い綴りであれば、エンベロープの `hint` に使うべき呼び出しが入ります。 |
| `127`     | `environment` | Godot バイナリを起動できませんでした(シェルの慣例: not found)。 |
| `124`     | `environment` | Godot は起動したが、タイムアウト前に戻りませんでした(シェルの慣例: timed out)。エンベロープにはそれまでにキャプチャした部分出力が入ります。 |
| `3`       | `version`     | 検出された Godot のバージョンが、サポートされる最小値を下回っています。 |
| `4`       | `operation`   | エンジンは動作したが操作が失敗しました — 登録済みの操作エラー、エンジンのクラッシュ、または非構造の非ゼロ終了。 |
| `5`       | `parse`       | プロセスは成功を主張したが、構造化出力の契約に違反しました。 |
| `6`       | `live`        | Live 操作が失敗しました — 例: 実行中のデーモン/セッションがない、または Live のタイムアウト。 |

これらの値は公開 ABI であり、その信頼できる出典は [`src/gda/exit_codes.py`](../src/gda/exit_codes.py)
です。`{"error": {category, code, …}}` エンベロープは、各カテゴリ内に **より細かい `code`** を持ちます
(例: `path_not_found`、`already_exists`、`node_not_found` はいずれも `operation` / 終了コード `4` の下に
あります)。完全なレジストリは
[ADR-0002 の `GdaError.code` テーブル](adr/0002-headless-structured-output-contract.md#gdaerrorcode-registry)
にあります。
</details>

<details>
<summary><strong>開発</strong></summary>

```bash
uv sync                       # set up the environment

uv run pytest                 # run the full suite (includes e2e tests against a real Godot)
uv run pytest -m "not e2e"    # unit tests only (no Godot binary required)
uv run pytest -m e2e          # only the end-to-end tests (needs Godot 4.4+ on this machine)
uv run pytest -n 4 --dist loadgroup   # 上のどの階層も 4 ワーカーで実行 — CI が各階層をこう実行する

uv run ruff check .           # lint
uv run ruff format .          # auto-format (append --check to verify without writing)
uv run pyright                # type-check (src/ + tests/, basic mode)
```

`e2e` ティアは `uv run pytest` でデフォルトで実行され、そこに Godot バイナリが見つからない場合は、
スキップするのではなく **はっきり失敗します** — 解決されたパスと修正方法を示して。ティア全体を除外
するには `-m "not e2e"` を使います(CI の PR ごとのジョブはまさにこれを使っています)。

リンティングとフォーマットは [ruff](https://docs.astral.sh/ruff/) で強制されます — flake8 + black + isort を
1 つのツールで置き換えるもので、`pyproject.toml` の `[tool.ruff]` 配下で設定され、ローカルと CI が
一致するよう `uv.lock` で固定されています。CI の `lint` ジョブは、すべての PR で `ruff check .` と
`ruff format --check .` を実行します。グリーンを保つため、コミット前に `uv run ruff format .` を実行して
ください。

型は [pyright](https://microsoft.github.io/pyright/) の `basic` モードでチェックされ、`src/` と `tests/` を
対象に、`pyproject.toml` の `[tool.pyright]` 配下で設定されています(これも `uv.lock` で固定)。CI の
`type-check` ジョブは、すべての PR で `uv run --frozen pyright` を実行します。

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

`gda` には 2 つの外部境界があり、それぞれ高速なテストが注入するシーム(継ぎ目)の背後にあります。
ワンショットの Headless プロセスを起動すること(`runner.py`)と、デーモン経由で実行中ゲームと対話する
こと(`live_runner.py`)です。e2e スイートは、その両方にわたって実際のエンジンを駆動します。
</details>

---

<a id="contributing"></a>
## コントリビューション

コントリビューションを歓迎します。プロジェクトの共有言語に合わせるため [`CONTEXT.md`](../CONTEXT.md) を
読み、触れる領域に関連する [ADR](adr/) を確認してください。Issue と PRD は
[GitHub issues](https://github.com/aigengame/godot-agent/issues) として管理されています。コミットは
[Conventional Commits](https://www.conventionalcommits.org/) 仕様に従います。Python コードは
[ruff](https://docs.astral.sh/ruff/) でリント・フォーマットされ、[pyright](https://microsoft.github.io/pyright/)
で型チェックされます。どちらも CI で強制されます — コミット前に `uv run ruff format .` と
`uv run pyright` を実行してください(上記の **開発** を参照)。

> **AI コーディングエージェントと作業していますか?** このプロジェクトはエージェントが辿りやすいように
> 作られています — [`AGENTS.md`](../AGENTS.md) がコーディングエージェントの入口で、プロジェクトの
> ルール、ドメインドキュメント、スキルを束ねています。

<a id="license"></a>
## ライセンス

[MIT ライセンス](../LICENSE) の下でリリースされています。Copyright (c) 2026 aigengame.
