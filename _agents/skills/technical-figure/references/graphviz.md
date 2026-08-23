# Graphviz path

Use Graphviz when the truth is nodes, edges, clusters, ranks, or a dependency
relation that should be regenerated from data.

## Build

Keep a `.dot` source or a deterministic generator that emits one. Sort every
node and edge before emission. Give stable ids to nodes; labels are presentation
and may change independently.

The direct command is useful only for exploration:

```powershell
dot -Tsvg -o preview.svg source.dot
```

Do not commit that direct export as the canonical artifact. An audited product
bundle must expose `build.py` as its committed entry point. The script must run
Graphviz with explicit options, normalize unstable metadata and ordering, add
the required accessibility and semantic ids, and write canonical `figure.svg`
and `figure.html` outputs.

Use `dot` for ranked directed graphs, `neato` or `fdp` only when force-directed
geometry communicates something real. Encode semantic differences with edge
style, arrowhead, cluster, rank, or shape as well as color.

## Avoid

- manually positioning every data-derived node;
- using Graphviz for an illustration whose core claim is physical space,
  camera geometry, or material appearance;
- putting paragraphs into nodes;
- allowing unstable input iteration to reorder the generated file;
- assuming the automatic layout is readable without inspecting the SVG.

## Verify

Check that every expected node and edge appears exactly once, clusters reflect
the intended boundary, arrow direction matches dependency meaning, and labels
remain readable at the embedded width. For a large graph, provide a focused
overview plus local views instead of shrinking a wall-sized poster.
