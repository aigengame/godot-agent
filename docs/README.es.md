<!-- gda-readme-i18n: source=README.md sha256=f65e91d217d6ee043126bb18ddf00ea4665f327f1bfe7a753a638a782702b56e -->

# gda — Automatización de Godot para agentes de IA

[![gda — Automatización de Godot para agentes de IA](https://raw.githubusercontent.com/aigengame/godot-agent/main/assets/godot-agent-title.png)](https://aigengame.xyz/)

**Otros idiomas:** [English](../README.md) · [简体中文](README.zh-CN.md) · **Español** · [日本語](README.ja.md)

[Descripción del producto](https://aigengame.xyz/) ·
[¿CLI, Agent Skill o MCP?](https://aigengame.xyz/godot-mcp/) ·
[PyPI](https://pypi.org/project/gda/)

> **Crea y verifica proyectos de Godot desde agentes de programación con IA, scripts de shell y CI.**
> `gda` ofrece el mismo conjunto de operaciones nativas de Godot mediante una CLI, una
> Agent Skill incluida y un servidor MCP, con resultados estructurados que los agentes pueden usar.

[![pre-1.0](https://img.shields.io/badge/status-pre--1.0-orange)](https://pypi.org/project/gda/)
[![CI](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/aigengame/godot-agent/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Godot](https://img.shields.io/badge/godot-4.4%2B%20(live%204.6%2B)-478CBF)](https://godotengine.org)
[![Platform](https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-lightgrey)](#how-it-works)
[![MCP](https://img.shields.io/badge/MCP-server-000)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

Editar un archivo no significa que el cambio en el juego esté verificado. `gda` cierra
ese ciclo con dos modos complementarios:

- **Headless** — crea y edita contenido del proyecto, compila scripts, valida e inicia
  escenas, analiza la estructura del proyecto y exporta builds sin plugin de editor ni daemon.
- **Live** — inspecciona y controla el juego en ejecución mediante un daemon por proyecto:
  árbol y estado de runtime, simulación de entrada, captura de frames, registros, errores y rendimiento.

> `gda` está en **pre-1.0**: hoy cada comando funciona de extremo a extremo, pero la superficie de comandos
> todavía puede cambiar antes de 1.0.

---

## Índice

- [¿Por qué `gda`?](#why-gda)
- [Capacidades de un vistazo](#capabilities-at-a-glance)
- [Instalación](#installation)
- [Inicio rápido](#quick-start)
- [Elige tu integración](#choose-your-integration)
- [Cómo funciona](#how-it-works)
- [Referencia de comandos](#command-reference)
- [Configuración](#configuration)
- [Contribuir](#contributing)
- [Licencia](#license)

---

<a id="why-gda"></a>
## ¿Por qué `gda`?

- **Verificación a lo largo del ciclo de vida del desarrollo de juegos.** La validación Headless confirma
  que el proyecto está listo; las operaciones Live aportan evidencia del comportamiento real.
- **Resultados estructurados y esquemas consultables.** Con `--json`, cada comando emite
  exactamente un objeto de resultado en stdout. Los modelos tipados de entrada y salida
  también sustentan `--schema` y la superficie de herramientas MCP generada.
- **Operaciones nativas de Godot.** Los comandos siguen los objetos y el vocabulario de
  Godot, como `gda scene create`, `gda node add` y `gda game get`.
- **Tres vías de acceso complementarias.** Ejecuta la CLI directamente desde un agente,
  shell o CI; instala la Agent Skill incluida para obtener orientación reutilizable; o
  expón las mismas operaciones como herramientas MCP. Consulta
  [¿CLI, Agent Skill o MCP?](https://aigengame.xyz/godot-mcp/) para comparar las
  opciones y sus diferencias.
- **Automatización acotada y fallos útiles.** Los timeouts, los límites de salida, los
  fallos tipados, los diagnósticos y los informes de cambios ayudan al agente a saber qué
  ocurrió y cómo recuperarse.

Estas capacidades se perfeccionaron mediante un
[registro público de uso en la producción de un juego real](https://github.com/aigengame/godot-agent/milestone/10).

---

<a id="capabilities-at-a-glance"></a>
## Capacidades de un vistazo

| Objetivo | Lo que ofrece `gda` | Empieza por |
| --- | --- | --- |
| Crear contenido de proyectos Godot (Headless) | Crear y editar escenas, nodos, scripts, recursos, ajustes del proyecto, shaders y temas | `scene` / `node` / `script` / `resource` / `project` / `shader` / `theme` |
| Verificar que el proyecto está listo (Headless) | Compilar scripts, validar dependencias, iniciar escenas con un preflight acotado, analizar la estructura del proyecto y exportar builds | `script validate` / `scene validate` / `scene preflight` / `project` / `export` |
| Verificar el comportamiento en runtime (Live) | Leer el estado de runtime, llamar a métodos declarados, simular entradas, capturar frames, recopilar registros y errores, y medir el rendimiento | `gda daemon start`, luego `game` / `input` / `screen` / `diag` / `logger` / `perf` |
| Conectar un agente de programación con IA | Usar la CLI directamente, la orientación reutilizable de Agent Skill o el descubrimiento y las llamadas de herramientas MCP | `gda` / `gda skill` / `gda-mcp` |
| Ejecutar automatización de forma fiable | Recibir resultados estructurados, esquemas y fallos tipados, ejecución acotada, registros aislados y diagnósticos útiles | `--json` / `--schema` / `--user-data-root` / timeouts |

---

<a id="installation"></a>
## Instalación

**Requisitos:** Python 3.13+ y un binario de [Godot](https://godotengine.org) — 4.4+ para
los comandos headless, 4.6+ en macOS/Linux para los comandos live (daemon).

Instala la CLI desde PyPI en tu `PATH`:

```bash
uv tool install gda      # or: pipx install gda
gda --help
```

<details>
<summary>Otras formas de instalar (pip, desde el código fuente)</summary>

En un entorno existente:

```bash
pip install gda
```

Desde el código fuente (para desarrollo o cambios no publicados):

```bash
git clone https://github.com/aigengame/godot-agent.git
cd godot-agent
uv sync                  # create the environment + install dependencies
uv run gda --help
```
</details>

---

<a id="quick-start"></a>
## Inicio rápido

**Apunta `gda` a tu binario de Godot** y luego pregúntale al motor su versión — sin necesidad de proyecto:

```bash
export GDA_GODOT="/path/to/Godot"   # or pass --godot to any command
gda info --json
# {"major":4,"minor":6,"patch":3,"status":"stable","string":"4.6.3-stable (official)",…}
```

stdout siempre es JSON limpio que puedes canalizar; todos los diagnósticos del motor y de los scripts van a stderr:

```bash
gda info --json | jq .major   # → 4
```

**Construye una escena en modo headless.** Apunta `gda` a un proyecto de Godot (un directorio con `project.godot`)
una vez; las rutas relativas se resuelven entonces *dentro* de él, y los nodos se direccionan por su ruta relativa
a la raíz de la escena:

```bash
export GDA_PROJECT="/path/to/your/godot-project"   # or pass --project to any command
gda scene create scenes/main.tscn --root-type Node2D --json
gda node add  scenes/main.tscn --type Sprite2D --name Hero --json
gda node set  scenes/main.tscn --node Hero --property position --value 10,20 --json
gda scene get scenes/main.tscn --json
# {"path":"scenes/main.tscn","root":{"name":"main","type":"Node2D","children":[{"name":"Hero",…}]}}
```

> ¿Sin proyecto? `gda` igualmente se ejecuta **sin proyecto** (projectless) sobre rutas simples del sistema de
> archivos (relativas a tu directorio actual) — solo la resolución de `res://` necesita un proyecto. Consulta [Configuración](#configuration).

**Controla un juego *en ejecución* en vivo.** Las operaciones live ejecutan la **escena principal** del proyecto, así que
apúntala a la que acabas de construir mediante el ajuste de proyecto `application/run/main_scene` de Godot (el
*Application → Run → Main Scene* del editor), y luego arranca el daemon (macOS/Linux, Godot 4.6+):

```bash
gda project set application/run/main_scene --value res://scenes/main.tscn --json  # a Godot project setting key
gda daemon start             # start the daemon for $GDA_PROJECT (installs the in-game harness)
gda game tree --json         # the runtime scene tree, after _ready
gda perf monitors --json     # live engine counters: fps, memory, node count
gda daemon stop
```

(`gda screen capture` también funciona en vivo, pero necesita una sesión con ventana — arranca el daemon
con `gda daemon start --windowed`.)

---

<a id="choose-your-integration"></a>
## Elige tu integración

`gda` expone la **misma superficie de comandos** de tres formas — elige la que tu agente (o tú) admita:

| Punto de entrada | Ideal para | Cómo |
| --- | --- | --- |
| **CLI** (`gda`) | humanos, scripts de shell, CI y agentes que pueden ejecutar comandos | `gda <group> <command> --json` |
| **Skill** (`gda skill`) | agentes de programación que admiten Agent Skills y prefieren un flujo de CLI ligero en tokens | imprimir/instalar `SKILL.md` (abajo) |
| **MCP** (`gda-mcp`) | agentes que invocan herramientas mediante el Model Context Protocol | ejecutar el servidor stdio (abajo) |

### Úsalo como Skill

`gda` incluye una **Skill** para agentes — un `SKILL.md` que enseña a un agente de IA *cómo y cuándo* manejar
Godot desde la CLI. Es la forma más ligera de entrar (no hay servidor que registrar), viene incluida en el paquete y
queda fijada a la versión de tu instalación. Imprímela, o instálala en el directorio de skills de tu agente:

```bash
gda skill                                              # print SKILL.md (redirect it anywhere)
gda skill --install --provider claude --scope user     # resolve a known agent's skills dir
gda skill --install --dir ~/.claude/skills/gda         # …or give the directory yourself
```

Las [recetas de skills](gda-skill.md) listan el directorio de skills de cada agente. O bien obtén el
mismo archivo directamente del repositorio — aun así instalas `gda`, ya que la Skill lo invoca:

```bash
curl --create-dirs -o ~/.claude/skills/gda/SKILL.md \
  https://raw.githubusercontent.com/aigengame/godot-agent/main/src/gda/skill/SKILL.md
```

### Úsalo como servidor MCP

`gda` incluye un servidor [MCP](https://modelcontextprotocol.io) por stdio detrás de un extra `[mcp]`,
de modo que cualquier agente MCP (Claude Code, Codex, Cursor, …) puede manejar Godot. Pruébalo sin instalar nada:

```bash
uvx --from "gda[mcp]" gda-mcp
```

El servidor necesita saber qué **proyecto** de Godot debe manejar y qué **binario** de Godot debe
ejecutar (MCP no permite pasar flags en cada llamada):

- **Proyecto** — define `GDA_PROJECT`. Sin él, `gda-mcp` usa los **roots** del workspace que envía el
  cliente (la carpeta que tienes abierta). Sin embargo, la revisión MCP 2026-07-28 marca los roots como obsoletos;
  fija `GDA_PROJECT` para que la configuración siga funcionando cuando actualices el cliente. Consulta [Configuración](#configuration).
- **Motor** — define `GDA_GODOT` con tu binario de Godot, p. ej. `"GDA_GODOT": "/path/to/Godot"`.

`gda-mcp` es compatible con ambas generaciones del protocolo — el MCP anterior a 2026 y la **revisión
2026-07-28** — pero cada una determina el proyecto de forma distinta: un cliente anterior a 2026 sigue
enviando roots; uno de la nueva revisión ya no, así que `gda-mcp` recurre a `GDA_PROJECT` o al cwd del servidor.
Fija `GDA_PROJECT` antes de que tu cliente pase a la nueva revisión. Con la nueva revisión, `gda-mcp`
también marca `tools/list` como cacheable (TTL de 1 hora).

#### Registrar con agentes de programación

<details>
<summary>Claude Code</summary>

Ámbito de proyecto, `.mcp.json` en la raíz del repositorio (detecta automáticamente el proyecto vía `roots`):

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

Ámbito de usuario (todos los proyectos) — la CLI, que escribe `~/.claude.json`:

```bash
claude mcp add --scope user gda-mcp -- uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Codex</summary>

Ámbito de proyecto, `.codex/config.toml` en la raíz del repositorio (el proyecto debe ser de confianza):

```toml
[mcp_servers.gda-mcp]
command = "uvx"
args = ["--from", "gda[mcp]", "gda-mcp"]

[mcp_servers.gda-mcp.env]
GDA_PROJECT = "/absolute/path/to/your/godot/project"
```

Ámbito de usuario (disponible en todas partes, pero fijado a un solo proyecto) — la misma tabla en
`~/.codex/config.toml`, o añádela con la CLI. Codex no tiene variable de workspace, así que
`GDA_PROJECT` es una ruta absoluta; usa el ámbito de proyecto si trabajas en varios proyectos:

```bash
codex mcp add gda-mcp --env GDA_PROJECT=/absolute/path/to/your/godot/project -- \
  uvx --from "gda[mcp]" gda-mcp
```

</details>

<details>
<summary>Cursor</summary>

Ámbito de proyecto, `.cursor/mcp.json` en la raíz del repositorio (`${workspaceFolder}`
sigue al proyecto abierto):

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

Ámbito de usuario (disponible en todas partes, pero fijado a un solo proyecto) — la misma configuración en
`~/.cursor/mcp.json` con `GDA_PROJECT` definido como una ruta absoluta (`${workspaceFolder}` solo
funciona en el ámbito de proyecto; usa el ámbito de proyecto para varios proyectos). Cursor no tiene comando `mcp add`
— regístralo mediante el JSON de arriba o la interfaz Settings → MCP.

> Cursor se lanza desde la GUI con un `PATH` mínimo, así que un `uvx` a secas puede no resolverse — de ahí el
> `command` absoluto de arriba; rellénalo con la salida de `which uvx`. Las recetas completas — inyección de PATH,
> Claude Desktop, ámbito de usuario vs proyecto, fijación de proyecto por agente — están en las
> [recetas de registro](gda-mcp-registration.md).
</details>

---

<a id="how-it-works"></a>
## Cómo funciona

`gda` son tres componentes que sirven operaciones en dos modos:

| Componente       | Rol                                                                   |
| ---------------- | --------------------------------------------------------------------- |
| **`gda`**        | La CLI orientada a agentes — expone Godot con salida estructurada `--json`. |
| **`gda-mcp`**    | Un servidor MCP que expone las mismas operaciones como herramientas, a partir de `--schema`. |
| **`gda-daemon`** | Un proceso por proyecto que supervisa un juego en ejecución para las operaciones live. |

- **Las operaciones headless** se ejecutan de una sola pasada — sin daemon, nada que instalar (crear una escena, editar
  un script, exportar, analizar).
- **Las operaciones live** requieren un juego en ejecución — `gda-daemon` lo lanza, inyecta un harness inerte
  dentro del juego e intermedia las peticiones a través de un socket de dominio Unix (árbol de runtime, entrada,
  capturas de pantalla, rendimiento, diagnósticos).

El harness dentro del juego que `gda-daemon` inyecta es **solo para desarrollo**: `gda export run` lo elimina por
completo del artefacto y, si se compila de cualquier otra forma (GUI del editor, `godot --export` directo), igualmente
se autodeshabilita en el juego exportado — de modo que un juego publicado nunca *ejecuta* nada relacionado con el daemon
(y a través de `gda export run`, ni siquiera lo lleva).

**Soporte de plataformas y versiones:**

| Modo | Godot | Plataformas |
| ---- | ----- | --------- |
| **Headless** | 4.4+ | macOS · Linux · Windows¹ |
| **Live** (vía `gda-daemon`) | 4.6+ | macOS · Linux² |

¹ Headless es multiplataforma por diseño (procesos de una sola pasada, sin dependencias específicas de
  plataforma) — Windows conserva toda la superficie headless, aunque la CI todavía no la ejercita.
² Las operaciones live usan sockets de dominio Unix, por lo que Windows todavía no es compatible.

---

<a id="command-reference"></a>
## Referencia de comandos

Los comandos de `gda` están **agrupados por objeto de dominio de Godot** y usan un vocabulario de verbos pequeño
y consistente, de modo que el mismo verbo significa lo mismo en cada grupo:

| Verbo               | Significado                                                       |
| ------------------- | ----------------------------------------------------------------- |
| `create` / `delete` | Crear / eliminar una entidad **independiente** (escena, script, recurso).  |
| `add` / `remove`    | Añadir / quitar una **subentidad** dentro de un contenedor (nodo → escena).  |
| `get` / `list`      | Leer una entidad / enumerar muchas.                               |
| `set`               | Mutar una propiedad.                                              |
| verbos de dominio   | `play`, `run`, `export`, `import`, … conservan su significado natural. |

Cada comando admite `--json` y `--schema`. Los comandos que leen o mutan una ruta `res://`
resuelven un [contexto de proyecto](#configuration). Ejecuta `gda <group> <command> --help` para ver todos los
flags — `gda --help` es la lista autoritativa de lo que está instalado.

**¿Nuevo por aquí?** Un buen primer recorrido: `gda info` → `gda scene create` → `gda node add` →
`gda script validate` → `gda export run`; luego pasa a vivo con `gda daemon start` → `gda game tree`.

**Meta** — sobre `gda` / el propio motor

| Comando | Qué hace |
| ------- | ------------ |
| `gda info`   | Informa la versión del motor Godot. |
| `gda version` | Informa qué `gda` está instalado y de dónde viene (`--json` añade la procedencia de la instalación). |
| `gda help`   | Muestra la ayuda de un comando (`gda help scene get`) o la de toda la CLI. |
| `gda schema` | Emite toda la superficie de comandos como un único manifiesto JSON legible por máquina. |
| `gda skill`  | Emite o instala la Agent Skill incluida (`SKILL.md`) que enseña a un agente cómo manejar `gda`. |

### Comandos headless — Godot 4.4+, todas las plataformas

**`scene`** — archivos de escena (`.tscn`)

| Comando | Qué hace |
| ------- | ------------ |
| `scene create` | Crea un nuevo `.tscn` con el tipo de nodo raíz indicado. |
| `scene get` | Lee una escena e informa su árbol de nodos estructurado. |
| `scene list` | Enumera las escenas `.tscn` del proyecto resuelto. |
| `scene get-exports` | Lista las propiedades `@export` que declaran los scripts de los nodos de una escena. |
| `scene delete` | Elimina un archivo de escena e informa qué se eliminó. |
| `scene validate` | Comprueba una escena **de forma estática** — resuelve sus dependencias y compila los scripts vinculados, incluidas las subescenas — sin instanciarla (los autoloads del proyecto siguen arrancando, como en todo comando `--project`); si encuentra problemas, los devuelve como resultado (`valid: false`, salida `0`) en lugar de producir un error. |
| `scene preflight` | Comprueba una escena **de forma dinámica** — la arranca en headless, ejecuta `_ready` e informa de `started` y de los errores de script detectados; si no puede arrancar, lo indica en el resultado en lugar de producir un error. |

Ejecuta ambas comprobaciones: `scene get` puede leer sin problemas una escena cuyo script falta; solo `validate`
identifica el archivo y solo `preflight` detecta un fallo en el primer fotograma.

**`node`** — nodos dentro de un archivo de escena

| Comando | Qué hace |
| ------- | ------------ |
| `node add` | Añade un nodo bajo un padre, opcionalmente en `--index`: un tipo integrado, un script con `class_name`, o `--instance` para componer otra escena como hijo instanciado. |
| `node get` | Lee las propiedades de un nodo (por ruta de nodo) como JSON tipado. |
| `node list` | Lista el árbol de nodos de una escena con la ruta de cada nodo relativa a la raíz. |
| `node set` | Define una propiedad de nodo, forzando el valor a su tipo de Godot declarado. En un `Control`, `position` escribe los cuatro offsets; el layout coloca los hijos de un `Container`, así que define sus offsets directamente. |
| `node remove` | Elimina un nodo (y su subárbol) por ruta de nodo. |
| `node duplicate` | Duplica un nodo (y su subárbol) bajo su padre. |
| `node move` | Reasigna un nodo (y su subárbol) a un nuevo padre, o lo reordena con `--index`. |
| `node connect-signal` | Conecta la señal de un nodo origen al método de un nodo destino. |
| `node disconnect-signal` | Desconecta una conexión señal→método existente. |

**`script`** — archivos GDScript (`.gd`)

| Comando | Qué hace |
| ------- | ------------ |
| `script create` | Crea un nuevo script `.gd` a partir de una plantilla o de `--content` literal. |
| `script get` | Lee el código fuente de un script más sus metadatos `class_name` / `extends`. |
| `script list` | Enumera los scripts `.gd` del proyecto resuelto. |
| `script set` | Edita un script mediante buscar-reemplazar, rango de líneas o sobrescritura completa. |
| `script delete` | Elimina un archivo de script e informa qué se eliminó. |
| `script attach` | Adjunta un script `.gd` a un nodo (por ruta de nodo) en una escena. |
| `script validate` | Comprueba la compilación de scripts `.gd` — varias PATH en un único arranque del motor, o `--all` para todo el proyecto — e informa de un `valid` agregado y una entrada por script en `scripts`; si un script no compila, lo indica en el resultado (`valid: false`, salida `0`) en lugar de producir un error. |
| `script run` | Ejecuta un script del proyecto en headless como punto de entrada de un solo uso, bajo `--timeout`. Su `exit_status` y `stderr` se devuelven tal cual; `stdout` se incluye en el propio resultado hasta 64 KiB y, si se trunca, el `stdout` completo se escribe en el archivo que indica el resultado — un `quit()` distinto de cero es un dato, no un fallo, salvo que pases `--strict`. |

**`project`** — el proyecto en su conjunto (ajustes, autoloads, análisis estático)

| Comando | Qué hace |
| ------- | ------------ |
| `project info` | Informa los metadatos del proyecto (nombre, escena principal, viewport, versión del motor). |
| `project get` | Lee un único ajuste del proyecto por sección/clave como JSON tipado. |
| `project list` | Lista las claves de ajustes del proyecto (las personalizadas por defecto; `--all` añade los valores predeterminados del motor, `--section` filtra por prefijo). |
| `project set` | Define un ajuste del proyecto, forzando el valor a su tipo declarado. |
| `project add-autoload` | Registra un singleton autoload (nombre → script/escena). |
| `project remove-autoload` | Cancela el registro de un singleton autoload por nombre. |
| `project add-input-action` | Registra una acción del InputMap vinculada a teclas (`--key` nombre o keycode, `--deadzone`, `--physical`). |
| `project remove-input-action` | Cancela el registro de una acción del InputMap por nombre. |
| `project find-references` | Encuentra todos los archivos del proyecto que referencian un recurso dado. |
| `project dependencies` | Mapea cada escena/recurso a los recursos de los que depende. |
| `project find-unused-resources` | Encuentra archivos de recurso que nada referencia. |
| `project statistics` | Informa los recuentos de archivos/líneas del proyecto, los autoloads y más. |

**`resource`** — archivos de recurso (`.tres`) y los assets importados del proyecto

| Comando | Qué hace |
| ------- | ------------ |
| `resource create` | Crea un nuevo recurso `.tres` del tipo indicado. |
| `resource get` | Lee las propiedades de un recurso `.tres` como JSON tipado. |
| `resource set` | Define una propiedad `.tres`, forzando el valor a su tipo declarado. |
| `resource delete` | Elimina un archivo de recurso `.tres` e informa qué se eliminó. |
| `resource uid` | Resuelve un UID de recurso ↔ su ruta `res://` en ambas direcciones. |
| `resource import` | Garantiza que los assets estén importados en la caché del proyecto (carga en un worktree limpio). |

**`export`** — presets de exportación y artefactos

| Comando | Qué hace |
| ------- | ------------ |
| `export list` | Enumera los presets de exportación del proyecto (nombre, plataforma, …). |
| `export get` | Informa los detalles de un preset más el estado de instalación de la plantilla de exportación. |
| `export run` | Exporta un preset con nombre (`release` / `debug` / `pack`) a un destino. |

**`shader`** — archivos de shader (`.gdshader`)

| Comando | Qué hace |
| ------- | ------------ |
| `shader create` | Crea un nuevo `.gdshader` a partir de una plantilla o de `--content` literal. |
| `shader get` | Lee el código fuente de un shader más su `shader_type`. |
| `shader set` | Edita un `.gdshader` mediante buscar-reemplazar, rango de líneas o sobrescritura completa. |

**`theme`** — recursos de tema (`.tres`)

| Comando | Qué hace |
| ------- | ------------ |
| `theme create` | Crea un recurso Theme `.tres` nuevo y cargable (sin sobrescribir). |

### Comandos live — vía `gda-daemon`; Godot 4.6+, macOS/Linux

**`daemon`** — el ciclo de vida del runtime live

| Comando | Qué hace |
| ------- | ------------ |
| `daemon start` | Arranca el daemon por proyecto e instala el harness dentro del juego; la sesión del motor se inicia solo cuando una operación la necesita (`--windowed` para la captura de `screen`). |
| `daemon wait-ready` | Lanza la sesión del motor ahora y espera a que esté lista; `--timeout` es el presupuesto que el daemon dedica a ese lanzamiento y no limita estrictamente la duración total de la llamada. Las consultas de solo lectura `diag` / `logger` nunca lanzan una sesión, así que ejecútalo primero cuando una de ellas sea tu primer comando live. |
| `daemon stop` | Detiene el daemon del proyecto y cualquier sesión del motor en ejecución. |
| `daemon status` | Informa el estado del daemon (en ejecución, modo con ventana, sesión). |
| `daemon install` | Instala el harness dentro del juego sin iniciar un daemon e informa qué escribió. Idempotente; `daemon start` ya lo hace por su cuenta, así que úsalo solo para revisar o hacer commit por separado del cambio en `project.godot`. |
| `daemon uninstall` | Elimina el harness dentro del juego — entrada de autoload, archivos del harness, sidecar `.uid` — restaurando `project.godot`, e informa qué se eliminó. Solo desmontaje de herramientas de desarrollo: `gda export run` ya elimina el harness de las builds exportadas. |

**`game`** — el grafo de escena en runtime del juego en ejecución

| Comando | Qué hace |
| ------- | ------------ |
| `game tree` | Lee el árbol de escena en runtime del juego en ejecución (después de `_ready`). |
| `game get` | Lee las propiedades en vivo de un nodo de runtime por ruta de nodo; los nombres explícitos pueden acceder a variables del script adjunto. |
| `game rect` | Lee el rectángulo renderizado en viewport de un Control de runtime por ruta de nodo. |
| `game set` | Define una propiedad de un nodo de runtime, o una variable del script adjunto nombrada explícitamente, en el juego en ejecución; `verified` informa si la relectura coincidió. |
| `game call` | Invoca un método que el script del nodo declara en `GDA_CALLABLE` y devuelve su valor como datos estructurados. El propio proyecto declara que el método es de solo lectura, algo que gda no puede comprobar; nunca se invocan métodos no declarados. |

`game call` lee lo que `game get` no puede: estado que tu proyecto expone como método.
`game set --property position` sigue la misma regla de `Control` que `node set`.

**`diag`** — diagnósticos de runtime

| Comando | Qué hace |
| ------- | ------------ |
| `diag errors` | Muestra los errores de runtime del juego en ejecución a medida que aparecen (categorizados). |

**`logger`** — registro de runtime estructurado

| Comando | Qué hace |
| ------- | ------------ |
| `logger tail` | Muestra todo el registro de runtime del juego en ejecución a medida que se genera, como registros estructurados (`--level`, `--limit`, `--raw`). |

**`perf`** — monitorización de rendimiento

| Comando | Qué hace |
| ------- | ------------ |
| `perf monitors` | Toma una instantánea de los contadores del motor — o, con `--frames`, muestrea una ventana con estadísticas y veredictos de presupuesto. |
| `perf monitor` | Muestrea una propiedad o señal de nodo a lo largo de una ventana de frames (línea de tiempo). |

**`input`** — simulación de entrada

| Comando | Qué hace |
| ------- | ------------ |
| `input key` | Inyecta un evento de tecla (con modificadores). |
| `input mouse-click` | Inyecta el gesto de clic completo (movimiento, pulsación, liberación) en `(x, y)`. |
| `input mouse-move` | Inyecta un movimiento de ratón hacia `(x, y)`. |
| `input action` | Presiona/suelta una acción de entrada mapeada. |
| `input tap` | Toca una tecla o acción: pulsa, mantiene y suelta a lo largo de varios frames. |
| `input sequence` | Inyecta una línea de tiempo de eventos de varios frames. |

Lee las coordenadas de ratón inyectadas desde `event.position` — en una sesión del daemon
`get_mouse_position()` / `get_global_mouse_position()` pueden quedarse desactualizados.

**`screen`** — captura del viewport

| Comando | Qué hace |
| ------- | ------------ |
| `screen capture` | Captura un frame del viewport a un PNG. |
| `screen frames` | Captura una secuencia PNG de N frames (`--summary` devuelve un resultado agregado compacto). |

### Flags globales

| Flag       | Descripción                                                        |
| ---------- | ------------------------------------------------------------------- |
| `--json`    | Emite un único objeto JSON en stdout: el resultado si hay éxito, el sobre `{"error": {…}}` si hay fallo. Sin él, ambos se imprimen como una representación concisa y legible para humanos. También se acepta antes del comando. |
| `--schema`  | Emite el contrato JSON Schema de entrada/salida del comando (sin lanzar Godot). |
| `--godot`   | Ruta al binario de Godot (anula `$GDA_GODOT` y el valor por defecto). |
| `--project` | Directorio del proyecto de Godot para la resolución de `res://` (anula `$GDA_PROJECT`; por defecto, el directorio actual si es un proyecto). Solo comandos de dominio. Resolver un proyecto ejecuta el código de ese proyecto — consulta [Ejecución del código del proyecto](#configuration). |
| `--version` | Imprime la versión instalada de `gda`. Con `--json`, también de dónde viene: el tipo de instalación (`wheel`, `editable` o `unknown`) y, para una instalación editable, la revisión de Git del código fuente. |
| `--help`    | Muestra el uso de `gda` o de cualquier comando.                     |

---

<a id="configuration"></a>
## Configuración

`gda` encuentra el binario de Godot a partir del flag **`--godot <path>`**, o bien de la
variable de entorno **`GDA_GODOT`** — define una de las dos para que `gda` pueda localizar tu motor.

Los comandos de dominio determinan el **proyecto de Godot** con el que trabajan, para que las rutas `res://`
tengan sentido. Si indicas un directorio que no es un proyecto, `gda` devuelve un error; si no se determina
ninguno, `gda` funciona **sin proyecto** (projectless): las rutas del sistema de archivos funcionan, `res://` no.

| Contexto | Orden de resolución del proyecto |
| --- | --- |
| **CLI** | `--project` → `GDA_PROJECT` (ambos estrictos: uno inválido es un error) → el directorio actual, si contiene `project.godot` → sin proyecto |
| **MCP** (`gda-mcp`) | `GDA_PROJECT` (estricto) → el `root` de workspace del cliente, si envía uno válido (clientes anteriores a 2026) → el cwd del servidor, si es un proyecto → sin proyecto |

<details>
<summary>Ejecución del código del proyecto — qué se ejecuta cuando apuntas a un proyecto</summary>

Apuntar `gda` a un proyecto ejecuta parte del código propio de ese proyecto — a propósito, ya que el
proyecto es de confianza ([ADR-0009](adr/0009-trust-boundary-trusted-project.md)):

- **Los autoloads** arrancan en cada operación `--project` que inicia el motor, incluidas las de solo
  lectura (un `resource import` con la caché íntegra no arranca nada).
- **El `_init` de los scripts de la escena** se ejecuta allí donde se instancia una escena: todo comando
  `node` que modifica la escena y `node get`; `scene get` / `scene list` / `node list` leen sin instanciar.
- **`script run`** ejecuta íntegramente el script indicado; **`scene preflight`** arranca la escena y
  ejecuta su `_ready`.
- **`resource import`** ejecuta los importadores del motor (y los plugins de importación del proyecto)
  cuando falta la caché, sin autoloads.
- **`game call`** ejecuta el único método que nombra la declaración `GDA_CALLABLE` del nodo; nunca se
  invoca nada que no esté declarado.

</details>

---

<details>
<summary><strong>Bajo el capó</strong> — el contrato de salida estructurada y los códigos de salida</summary>

Godot en modo headless intercala su banner, sus advertencias y la salida de `print()` en stdout. `gda`
resuelve esto con un contrato de centinelas
([ADR-0002](adr/0002-headless-structured-output-contract.md)):

- El payload de GDScript emite **exactamente un** resultado, envuelto en centinelas únicos en stdout:

  ```
  <<<GDA:RESULT>>>{ …json… }<<<GDA:END>>>
  ```

- Enruta **todos** sus propios diagnósticos a stderr; stdout no transporta nada más que el contrato.
- `gda` extrae y analiza solo los bytes entre los centinelas, ignorando el ruido del motor circundante,
  y expone stderr para su inspección.

Esto es lo que hace que la salida de `gda` sea segura de consumir de forma programática, y se generaliza al
protocolo por mensaje que el daemon usa para las operaciones live.

**Códigos de salida (la ABI de la CLI).** Una ejecución fallida de `gda` termina con un código pequeño y estable
para que un shell o un agente pueda bifurcar según la **categoría del fallo sin analizar el error JSON**:

| Código de salida | Categoría     | Cuándo                                                                |
| --------- | ------------- | --------------------------------------------------------------------- |
| `0`       | —             | Éxito.                                                               |
| `2`       | `usage`       | `gda` no pudo resolver lo que se le pidió — un comando o una opción que no reconoce. Un caso cercano reconocido lleva en el `hint` del sobre la invocación que debe usarse. |
| `127`     | `environment` | No se pudo lanzar el binario de Godot (convención de shell: no encontrado). |
| `124`     | `environment` | Godot se lanzó pero no terminó antes del timeout (convención de shell: tiempo agotado); el sobre lleva la salida parcial capturada hasta entonces. |
| `3`       | `version`     | La versión de Godot detectada está por debajo del mínimo soportado.   |
| `4`       | `operation`   | El motor se ejecutó pero la operación falló — un error de operación registrado, una caída del motor o una salida no nula no estructurada. |
| `5`       | `parse`       | El proceso declaró éxito pero violó el contrato de salida estructurada. |
| `6`       | `live`        | Una operación live falló — p. ej. no hay daemon/sesión en ejecución, o un timeout live. |

Estos valores son la ABI pública; su fuente autoritativa es
[`src/gda/exit_codes.py`](../src/gda/exit_codes.py). El sobre `{"error": {category, code, …}}`
lleva un **`code` más fino** dentro de cada categoría (p. ej. `path_not_found`,
`already_exists`, `node_not_found` se ubican todos bajo `operation` / salida `4`). El registro
completo vive en
[la tabla `GdaError.code` de ADR-0002](adr/0002-headless-structured-output-contract.md#gdaerrorcode-registry).
</details>

<details>
<summary><strong>Desarrollo</strong></summary>

```bash
uv sync                       # set up the environment

uv run pytest                 # run the full suite (includes e2e tests against a real Godot)
uv run pytest -m "not e2e"    # unit tests only (no Godot binary required)
uv run pytest -m e2e          # only the end-to-end tests (needs Godot 4.4+ on this machine)
uv run pytest -n 4 --dist loadgroup   # cualquier nivel de arriba en cuatro workers, como la CI ejecuta cada uno

uv run ruff check .           # lint
uv run ruff format .          # auto-format (append --check to verify without writing)
uv run pyright                # type-check (src/ + tests/, basic mode)
```

El nivel `e2e` se ejecuta por defecto con `uv run pytest` y **falla de forma ruidosa** — nombrando la
ruta resuelta y cómo arreglarlo — si no se encuentra ahí ningún binario de Godot, en lugar de omitirse.
Deselecciona todo el nivel con `-m "not e2e"` (el job por PR de la CI usa exactamente esto).

El linting y el formateo los aplica [ruff](https://docs.astral.sh/ruff/) — una sola herramienta en
lugar de flake8 + black + isort, configurada bajo `[tool.ruff]` en `pyproject.toml` y
fijada vía `uv.lock` para que local y CI coincidan. El job `lint` de la CI ejecuta `ruff check .` y
`ruff format --check .` en cada PR; ejecuta `uv run ruff format .` antes de hacer commit para mantenerte
en verde.

Los tipos los comprueba [pyright](https://microsoft.github.io/pyright/) en modo `basic`, cubriendo
`src/` y `tests/` y configurado bajo `[tool.pyright]` en `pyproject.toml` (también fijado vía
`uv.lock`). El job `type-check` de la CI ejecuta `uv run --frozen pyright` en cada PR.

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

`gda` tiene dos fronteras externas, cada una detrás de una costura (seam) por la que inyectan las pruebas
rápidas: lanzar un proceso headless de una sola pasada (`runner.py`) y comunicarse con un juego en ejecución
a través del daemon (`live_runner.py`). La suite e2e maneja un motor real a través de ambas.
</details>

---

<a id="contributing"></a>
## Contribuir

Las contribuciones son bienvenidas. Lee [`CONTEXT.md`](../CONTEXT.md) para alinearte con el lenguaje
compartido del proyecto, y revisa los [ADRs](adr/) relevantes para el área que estás tocando.
Las issues y los PRDs viven como [issues de GitHub](https://github.com/aigengame/godot-agent/issues).
Los commits siguen la especificación [Conventional Commits](https://www.conventionalcommits.org/).
El código Python se lintea y formatea con [ruff](https://docs.astral.sh/ruff/) y se comprueban sus tipos
con [pyright](https://microsoft.github.io/pyright/), ambos aplicados en CI — ejecuta
`uv run ruff format .` y `uv run pyright` antes de hacer commit (consulta **Desarrollo** arriba).

> **¿Trabajas con un agente de programación con IA?** Este proyecto está construido para ser navegable por agentes —
> [`AGENTS.md`](../AGENTS.md) es el punto de entrada para los agentes de programación, integrando las reglas del
> proyecto, la documentación de dominio y las skills.

<a id="license"></a>
## Licencia

Publicado bajo la [Licencia MIT](../LICENSE). Copyright (c) 2026 aigengame.
