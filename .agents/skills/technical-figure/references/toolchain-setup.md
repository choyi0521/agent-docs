<!-- Generated from _agents/skills/technical-figure/references/toolchain-setup.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Figure toolchain setup

Run diagnostics first:

```powershell
python -B _agents/skills/technical-figure/scripts/figure_tools.py doctor
```

The diagnostic searches `PATH`, common Windows install locations, and these
optional process-local overrides:

| Tool | Override |
| --- | --- |
| Graphviz | `AGENT_DOCS_GRAPHVIZ` |
| draw.io Desktop | `AGENT_DOCS_DRAWIO` |
| Blender | `AGENT_DOCS_BLENDER` |
| OpenPencil CLI | `AGENT_DOCS_OPENPENCIL` |

An override points to the executable, not its containing directory. Prefer a
repository or CI wrapper over permanently changing a user's environment.
Absolute executable paths are redacted from diagnostic output by default. Use
`doctor --show-paths` only for local troubleshooting, not shared CI logs.

## Windows

Install tools through a reviewed package source after obtaining the user's
permission. Graphviz and draw.io publish the WinGet package ids shown below.
Install OpenPencil from a pinned official release and verify the published
digest before running its installer. This package intentionally does not ship
an installer that downloads and executes remote code.

Blender is intentionally not auto-upgraded. Figure output can change between
Blender versions, so install or retain the project-selected version and point
`AGENT_DOCS_BLENDER` at it when discovery is ambiguous. Prefer Blender 4.5 LTS
for long-lived recipes unless a figure requires a newer API.

Current package identifiers:

```text
Graphviz.Graphviz
JGraph.Draw
```

After installation, open a new terminal if the package manager changed `PATH`,
then rerun `doctor` and `smoke`.

## Linux and CI

Install Graphviz from the distribution package and use `dot -Tsvg`. draw.io
Desktop is an Electron application; its exporter may require a virtual display
such as Xvfb in a Linux container. Graphviz and Blender background mode are the
preferred server-native paths.

Install Blender at a pinned version and run it with `--background`. Install the
OpenPencil `op` CLI using the official release or installer for the runner.
Avoid floating `latest` downloads in reproducible CI.

## Smoke tests

Test one tool:

```powershell
python -B _agents/skills/technical-figure/scripts/figure_tools.py smoke --tool graphviz
```

Keep smoke outputs for inspection:

```powershell
python -B _agents/skills/technical-figure/scripts/figure_tools.py smoke `
  --tool all --output-dir dev/tmp/figure-tool-smoke
```

The OpenPencil smoke test verifies its CLI and headless command surface without
starting a long-lived server. A real `.op` task should additionally open and
inspect the document through OpenPencil.

Upstream references: [Graphviz downloads](https://graphviz.org/download/),
[draw.io Desktop releases](https://github.com/jgraph/drawio-desktop/releases),
[Blender downloads](https://www.blender.org/download/), and the
[OpenPencil repository](https://github.com/ZSeven-W/openpencil).
