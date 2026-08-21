# Playtest environment

The playtest launchers need Godot and the `gda-balancing` executable. Run the commands in this
document from `libs/gda-balancing`.

## Prepare the package environment

Create or update the package-local virtual environment:

```bash
cd libs/gda-balancing
uv sync
```

The package executable is then available at `.venv/bin/gda-balancing` on macOS and Linux. On
Windows, use `.venv/Scripts/gda-balancing.exe`.

## Launch an application with explicit paths

Set both executable paths on the launch command. Replace the Godot path with the executable path
for your installation.

```bash
GDA_GODOT=/absolute/path/to/Godot \
GDA_BALANCING_EXECUTABLE="$PWD/.venv/bin/gda-balancing" \
examples/schema2/playtest/scripts/run_reward_run.sh
```

Use the same environment for the other applications:

```bash
GDA_GODOT=/absolute/path/to/Godot \
GDA_BALANCING_EXECUTABLE="$PWD/.venv/bin/gda-balancing" \
examples/schema2/playtest/scripts/run_combat_cast.sh

GDA_GODOT=/absolute/path/to/Godot \
GDA_BALANCING_EXECUTABLE="$PWD/.venv/bin/gda-balancing" \
examples/schema2/playtest/scripts/run_periodic_effect.sh
```

On macOS, a typical Godot application path has this form:

```bash
GDA_GODOT=/absolute/path/to/Godot.app/Contents/MacOS/Godot \
GDA_BALANCING_EXECUTABLE="$PWD/.venv/bin/gda-balancing" \
examples/schema2/playtest/scripts/run_reward_run.sh
```

Each application starts its own loopback `gda-balancing serve` process and stops that process when
the application exits. Do not start the HTTP service separately.

## Reuse the settings in one terminal

Export the variables once when you want to launch more than one application from the same shell:

```bash
export GDA_GODOT=/absolute/path/to/Godot
export GDA_BALANCING_EXECUTABLE="$PWD/.venv/bin/gda-balancing"

examples/schema2/playtest/scripts/run_reward_run.sh
examples/schema2/playtest/scripts/run_combat_cast.sh
examples/schema2/playtest/scripts/run_periodic_effect.sh
```

The applications normally run one at a time. If you launch more than one, each application starts
an isolated service on a different loopback port.

## Executable discovery

| Variable | When it is not set | When it is set |
| --- | --- | --- |
| `GDA_GODOT` | The launcher searches `PATH` for `godot`, then `godot4`. | The launcher executes the supplied path. |
| `GDA_BALANCING_EXECUTABLE` | The launcher and Add-on search `PATH` for `gda-balancing`. | The launcher passes the supplied path to the Add-on. |

You can use `PATH` instead of `GDA_BALANCING_EXECUTABLE`:

```bash
PATH="$PWD/.venv/bin:$PATH" \
GDA_GODOT=/absolute/path/to/Godot \
examples/schema2/playtest/scripts/run_reward_run.sh
```

An explicit relative `GDA_BALANCING_EXECUTABLE` path is resolved from the directory where you run
the launcher. Prefer the absolute `$PWD/.venv/bin/gda-balancing` form shown above. If an explicit
path is invalid, the application shows a retry error and does not select a different installation.
