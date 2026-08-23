---
nav:
  - guides/
  - authoring/
---
# Agent Docs

Agent Docs turns a curated Markdown tree into a searchable documentation site.
It validates navigation, local links, heading anchors, source snippets, and
figure bundles as part of the build.

Start with the [build guide](/guides/getting-started). Use the
[authoring documentation](/authoring) when you add or reorganize content.

## Published boundary {#published-boundary}

The checked-in sample publishes only these explicit inputs:

- Markdown below `docs/`, in the order declared by each directory index.
- Named snippet regions and code files below `examples/source/`.
- Self-contained SVG figure bundles below `docs/_assets/figures/`.
- The static reader assets required to open the generated JSON and HTML.

Source publication stays off unless a space opts in with explicit paths and
file extensions. This checked-in sample makes that opt-in for the single
`examples/source` tree so its harmless snippet and code page can be exercised.

## Choose your next task

- [Build and preview the sample site](/guides/getting-started).
- [Define explicit navigation and durable links](/authoring/navigation).
- [Use tabs, source snippets, figures, and Plans](/authoring/extensions).
- [Limit which source files may be published](/authoring/source-publication).
