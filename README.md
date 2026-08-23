# Agent Docs

Agent Docs is a repository-aware Markdown documentation builder and authoring
workflow toolkit. It renders a curated documentation tree into a searchable
static site and checks the source relationships that ordinary Markdown builds
usually leave unchecked.

## What it provides

- Curated navigation with explicit ordering and unlisted-page detection.
- Internal route and heading-anchor validation.
- Source-backed snippets delimited by `// docs:begin` and `// docs:end`.
- Reproducible technical figure bundles and structural figure audits.
- Multiple documentation spaces, repository source links, and optional source
  browsing.
- A responsive static reader with search, line-addressable code browsing, and
  base-path mounting.
- Vendor-neutral agent instructions and documentation-authoring skills that can
  be generated for supported coding agents.

The repository contains only neutral toolkit documentation and examples. Do
not add private product material, credentials, machine-specific paths, or
generated build output.

## Requirements

- .NET SDK 10
- Python 3.11 or newer
- Node.js 20 or newer for rebuilding the stylesheet

The renderer itself does not require Node.js after the web assets have been
built.

## Quick start

Restore, build, and validate the included neutral documentation site:

```powershell
dotnet restore AgentDocs.slnx
dotnet build AgentDocs.slnx --configuration Release --no-restore
dotnet test AgentDocs.slnx --configuration Release --no-build
dotnet run --project src/AgentDocs.Cli --configuration Release -- `
  render --repo . --config agent-docs.json --out build --check
```

Start a local preview at `http://127.0.0.1:4173`:

```powershell
dotnet run --project src/AgentDocs.Cli --configuration Release -- `
  serve --repo . --config agent-docs.json --out build --port 4173
```

The preview server is intended for local, trusted authoring content. Generated
output is written under `build/` and is not committed. The standalone output
includes the reader assets, third-party notices, and exact license texts needed
to distribute its generated stylesheet.

## Configuration

`agent-docs.json` defines the site title and documentation spaces. A space maps
an authored Markdown directory to a route prefix and can independently enable
curated navigation, snippets, and source browsing. The accompanying
`agent-docs.schema.json` is the machine-readable configuration contract.

Each section can use `_index.md` front matter to state navigation:

```yaml
---
nav:
  - getting-started
  - configuration
---
```

Source snippets reference a region relative to the configured source root:

````markdown
```snippet examples/source/GreetingFormatter.cs#greeting-format
title: A source-backed greeting formatter
```
````

The matching source contains whole-line markers:

```csharp
// docs:begin greeting-format
public static string Format(string name)
{
    ArgumentException.ThrowIfNullOrWhiteSpace(name);
    return $"Hello, {name.Trim()}.";
}
// docs:end greeting-format
```

Run the render command with `--check` after changing navigation, headings,
snippet markers, figures, or source files.

## CLI and library API

The CLI has three commands:

| Command | Purpose | Command-specific options |
|---|---|---|
| `render` | Build the static site; this is the default command | `--check` fails when the report contains validation errors |
| `serve` | Build and serve a loopback-only, read-only preview | `--port`, `--base`, `--no-render`, `--check` |
| `probe` | Check a running preview endpoint | `--port`, `--base` |

`--repo`, `--config`, and `--out` select the repository, configuration, and
output paths for rendering. Relative configuration and output paths are
resolved from the repository root. The output directory is prepared for a
fresh build, so it must be a disposable directory that does not overlap any
input.

The renderer can also be called from .NET through its public entry point:

```csharp
using AgentDocs;

BuildReport report = AgentDocsBuilder.Build(
    repoRoot: Directory.GetCurrentDirectory(),
    configPath: "agent-docs.json",
    outputPath: "build");

Console.WriteLine($"{report.Documents} documents; {report.Broken} errors");
return report.Broken == 0 ? 0 : 1;
```

`BuildReport` contains document, fragment, and browsable-code counts plus a
result for each configured space. Each space exposes categorized diagnostics
for links, anchors, navigation, unlisted documents, snippets, and figures.

## Agent authoring workflows

Canonical agent instructions and skills live under `_agents/`. Generated
vendor surfaces are complete copies and are checked as public repository
content; they are not independent authoring locations.

```powershell
python -B tools/sync_agent_instructions.py --check
python -B tools/check_agent_instructions.py
```

The repository's neutral documentation also dogfoods the authoring audit:

```powershell
python -B _agents/skills/docs-authoring/scripts/audit_docs.py `
  --config docs-audit.json --repo-root . --check
python -B _agents/skills/technical-figure/scripts/audit_figures.py `
  --repo-root . --bundle docs/_assets/figures/document-flow `
  --article-width-px 704
```

Use `--write` on the synchronization command after changing a canonical
instruction, skill, reference, script, or interface, then include every
generated update in the same change.

## Repository layout

```text
agent-docs.json          renderer configuration
docs-audit.json          documentation-authoring audit configuration
_agents/                 canonical agent instructions and skills
docs/                    neutral documentation authored with the toolkit
examples/                neutral snippet and source-browser fixtures
src/AgentDocs/           renderer library
src/AgentDocs.Cli/       command-line renderer and preview server
tests/AgentDocs.Tests/   isolated renderer and security tests
styles/                  Tailwind source and lock file
third_party_licenses/    required upstream license texts
web/                     dependency-free reader shell and generated CSS
tools/                   agent-surface and public-boundary checks
```

## Public boundary

The public-boundary check walks the entire candidate tree, including generated
agent surfaces. It rejects generated output, archives and binary media, Git LFS
pointers, submodule metadata, symlinks and junctions, credential material,
local user paths, private hosts, mutable workflow actions, unapproved GitHub
repositories, and reserved private identifiers.

```powershell
python -B -m unittest discover -s tools/tests -p "test_check_public_boundary.py" -v
python -B tools/check_public_boundary.py
```

See `CONTRIBUTING.md` for the complete verification sequence and `SECURITY.md`
for reporting security issues.

## License status

No project license has been selected yet. Copyright law therefore reserves the
rights to use, copy, modify, and redistribute this repository unless the rights
holder grants them separately. Third-party components retain their own
licenses; see `THIRD-PARTY-NOTICES.md`.
