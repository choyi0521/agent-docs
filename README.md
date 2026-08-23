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
- A responsive static reader with search, syntax-highlighted line-addressable
  code browsing, and base-path mounting.
- Repository-local review comments for the loopback authoring preview, kept
  separate from generated static output.
- Vendor-neutral agent instructions and documentation-authoring skills that can
  be generated for supported coding agents.

The repository contains only neutral toolkit documentation and examples. Do
not add private product material, credentials, machine-specific paths, or
generated build output.

## Requirements

- .NET SDK 10
- Python 3.11 or newer
- Node.js 20 or newer for rebuilding the browser assets

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
to distribute its generated browser assets.

Comments created in the preview are stored by default in the ignored file
`.agent-docs/review-comments.json`. The write API exists only in the
loopback-only `serve` process; `render` never copies the comments or an API into
the static output. Use `--review-data PATH` to choose another file only under
the repository-root `.agent-docs/` directory. That entire reserved directory is
ignored by Git and hard-excluded from documentation, source-browser, snippet,
and agent-workflow publication. See
[`schemas/review-comments.schema.json`](schemas/review-comments.schema.json)
for the versioned local data contract.

The loopback review endpoint is an unauthenticated local API. Its JSON,
`Origin`, and fetch-metadata checks reduce ordinary browser cross-site writes,
but do not protect it from other processes on the same operating system. Run
the preview only on a trusted workstation and stop it when review work is done.

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
| `serve` | Build and serve a loopback-only preview with local review comments | `--port`, `--base`, `--review-data`, `--no-render`, `--check` |
| `probe` | Check a running preview endpoint | `--port`, `--base` |

`--repo`, `--config`, and `--out` select the repository, configuration, and
output paths for rendering. Relative configuration and output paths are
resolved from the repository root. The output directory is prepared for a
fresh build, so it must be a disposable directory that does not overlap any
input.

`--review-data` is valid only with `serve`. Its relative path is resolved from
the repository root; absolute overrides must still resolve beneath the reserved
repository-root `.agent-docs/` directory. Filesystem roots, outside paths,
symbolic-link or reparse paths, and paths under any sentinel-owned generated
output tree are rejected. The complete `.agent-docs/` subtree is Git-ignored
local state and is hard-excluded from rendered documents, published source and
snippets, browsable root files, and agent-workflow inputs. Serve preflight also
rejects any configuration that attempts to publish that reserved subtree.

Preview writes and the `$docs-authoring` review helper share a persistent
sibling operating-system lock. Writers retry every 50 milliseconds for up to
5 seconds, so concurrent mutations are serialized rather than silently
overwriting each other. An `answered` or `resolved` comment must retain a saved
reply; reopen a resolved comment before replacing its reply.

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
schemas/                 versioned repository-local data contracts
src/AgentDocs/           renderer library
src/AgentDocs.Cli/       command-line renderer and preview server
tests/AgentDocs.Tests/   isolated renderer and security tests
styles/                  Tailwind source and lock file
third_party_licenses/    required upstream license texts
web/                     self-contained reader shell and generated browser assets
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
