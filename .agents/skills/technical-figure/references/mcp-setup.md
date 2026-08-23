<!-- Generated from _agents/skills/technical-figure/references/mcp-setup.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Optional MCP connections

MCP is an interaction path, not the source of reproducibility. Commit Graphviz
input, draw.io XML, an OpenPencil `.op` document, or a Blender Python recipe even
when an MCP server helped explore the result.

## OpenPencil

Start a file-backed HTTP MCP server:

```powershell
op start --headless --file path/to/figure.op
```

The local endpoint is:

```text
http://127.0.0.1:3100/mcp
```

An MCP client that supports HTTP servers can connect to that URL while the
process is running. The exact client configuration is intentionally kept out
of the project skill because it is user- and host-specific.

OpenPencil also ships its own agent skill:

```powershell
op install --target codex
```

That command installs OpenPencil-specific usage instructions; it does not
replace the running MCP endpoint. The `technical-figure` skill already covers
tool selection and reproducibility, so install the upstream skill only when its
full OpenPencil command catalogue is useful. Restart the agent after changing a
skill or MCP connection, then verify that the tools are visible. Keep `.op`
files inside the intended workspace.

## draw.io

The official draw.io MCP tool server can be launched over stdio. Replace the
placeholder with an exact reviewed version before saving the configuration:

```json
{
  "mcpServers": {
    "drawio": {
      "command": "npx",
      "args": ["-y", "@drawio/mcp@<reviewed-version>"]
    }
  }
}
```

It opens generated XML, CSV, or Mermaid in the editor. It does not replace the
native `.drawio` source or the desktop CLI export used by a reproducible build.
Prefer direct Graphviz generation for a registry-derived graph.

## Blender

Use MCP only for interactive inspection or exploratory scene editing. The
committed authority is a headless command such as:

```powershell
blender --background --factory-startup --python build.py -- --output figure.png
```

Do not make a figure depend on a live Blender window, a user's startup scene,
or an MCP-only edit history. If a project already provides a Blender MCP server,
reuse it instead of adding a second server with overlapping control.

## Graphviz

Graphviz needs no MCP server. Its text input and CLI already provide a smaller,
more deterministic interface for generated graphs.

## Configuration hygiene

- Prefer project configuration only when every contributor needs the server.
- Keep user-specific paths and credentials out of tracked MCP configuration.
- Pin packages in controlled environments; a floating `npx` package is useful
  for local exploration but not a byte-reproducible build authority.
- Never treat successful MCP connection as proof that an exported asset is
  correct. Render and inspect the output.

Upstream references: [OpenPencil](https://github.com/ZSeven-W/openpencil) and
the [official draw.io MCP server](https://github.com/jgraph/drawio-mcp).
