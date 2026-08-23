<!-- Generated from _agents/skills/technical-figure/references/drawio.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# draw.io path

Use draw.io for a deliberately composed architecture, sequence, topology, or
boundary diagram whose routing and grouping benefit from visual editing.

## Source and export

Keep the native `.drawio` XML. This direct draw.io Desktop export is exploratory:

```powershell
draw.io --export --format svg --embed-diagram --border 10 `
  --output preview.svg figure.drawio
```

Do not commit the direct export as the canonical artifact. An audited product
bundle must expose `build.py` as its committed entry point. The script must run
the exporter with explicit options, normalize unstable metadata and output,
preserve or add the required accessibility and semantic ids, and write
canonical `figure.svg` (or deliberately rasterized `figure.png`) and
`figure.html` outputs.

An SVG/PNG/PDF with embedded diagram data remains editable, but keep the native
source. Use stable cell ids, explicit parent relationships, and well-formed
uncompressed `mxGraphModel` XML.

The official optional MCP server is documented in
[MCP setup](mcp-setup.md). It is useful for opening a draft in the editor, not
for deriving a graph from registry data.

## Compose

- Use containers only for real boundaries.
- Route the primary path first and secondary relations around it.
- Keep crossing count low; use line jumps only when a crossing is unavoidable.
- Distinguish ownership from data flow and dependency from sequence.
- Use a small legend only for encodings the reader cannot infer.

## Verify

Open the native file and exported asset. Confirm the export has no clipped text,
font substitution, dangling connector, hidden off-canvas element, or local
filesystem image reference. Linux Electron export may require a virtual display;
do not call it server-native merely because it has CLI flags.
