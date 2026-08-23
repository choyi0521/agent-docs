<!-- Generated from _agents/skills/technical-figure/references/openpencil.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# OpenPencil path

Use the `ZSeven-W/openpencil` tool for bespoke vector explanations, annotated
concepts, and editable visual compositions that do not fit a graph layout or a
3D scene.

OpenPencil documents use the Git-friendly `.op` JSON format. Keep that document
as the editable source.

## Exploratory CLI workflow

Start a file-backed headless server:

```powershell
op start --headless --file figure.op
```

Apply a batch design file or sandboxed JavaScript:

```powershell
op design @figure.dsl
op design @figure.js
```

Export the selected node or an explicit item after the server is running:

```powershell
op export --item <node-id> --output figure.png --format png --scale 2
```

Install OpenPencil's own Codex integration when explicitly requested:

```powershell
op install --target codex
```

Use `op --help` and the installed version's command reference for any additional
export or inspection command. The CLI is evolving, so record the installed
version and exploratory commands alongside the `.op` source, then encode the
exact final invocation in `build.py`.

Treat the direct commands above as exploration. An audited product bundle must
expose `build.py` as its committed entry point; it must invoke the pinned CLI
operations, normalize the export, and write the canonical `figure.svg` or
`figure.png` plus `figure.html`.

## Compose

- Establish frames and a reading order before details.
- Use auto-layout for repeated structures, then make deliberate exceptions.
- Name layers and nodes by semantic role rather than visual appearance.
- Use variables for repeated visual tokens and keep light/dark variants
  coherent when both are required.
- Keep annotations close to the evidence they explain.

## Verify

Open the resulting `.op` file in the installed OpenPencil version, inspect every
page and theme, and verify the exported SVG/PNG at final size. MCP or a live
canvas can accelerate iteration, but it is not a substitute for a committed
document and an exact rebuild/export record.
