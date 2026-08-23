# Build and preview the sample site

This guide produces a validated static site in `build/` and serves it on the
loopback interface for local inspection.

## Prerequisites

Start with a checkout of this repository and a .NET SDK compatible with
`global.json`. Version `10.0.100` is the minimum requested SDK. The restore step
also needs access to the package sources configured for your .NET installation.

Run every command from the repository root, which contains `AgentDocs.slnx`
and `agent-docs.json`.

## Verify the SDK

Check which SDK the repository selects:

```powershell
dotnet --version
```

The command should print `10.0.100` or a compatible .NET 10 feature-band
version. If `dotnet` is not found or reports an incompatible SDK, install the
requested SDK and rerun this checkpoint before restoring packages.

## Restore the solution

Restore the projects declared by the solution:

```powershell
dotnet restore AgentDocs.slnx
```

The command should finish successfully and report that each project is
restored or already up to date. A package-source failure leaves the checkout
unchanged. Correct the source or network configuration, then rerun the same
command.

## Build the solution

Compile the library, CLI, tests, and source-backed example:

```powershell
dotnet build AgentDocs.slnx --configuration Release --no-restore
```

The command should finish with zero warnings and zero errors. A compile failure
leaves the generated site untouched. Correct the reported project or source
file, then rerun the build before rendering.

## Render with content gates

Build the static site and fail the command if a content gate reports a problem:

```powershell
dotnet run --project src/AgentDocs.Cli --configuration Release -- render --repo . --config agent-docs.json --out build --check
```

The final summary should report `0 gate errors`. The `build/` directory should
contain `index.html`, `index.json`, `search.json`, and `build-report.json`.
Rendering prepares a fresh copy of sentinel-owned output, so the same command
is safe to retry after correcting content.

## Preview the generated site

Serve the validated output without rebuilding it:

```powershell
dotnet run --project src/AgentDocs.Cli --configuration Release -- serve --repo . --config agent-docs.json --out build --port 4173 --no-render
```

Open `http://127.0.0.1:4173/`. The preview listens only on the loopback
interface and accepts read-only requests. Stop it with Ctrl+C.

## Diagnose a failed render

Use the first reported category to choose the repair:

- `navigation`, `unlisted document`, `broken link`, or `broken anchor` names a
  Markdown relationship that must be corrected before the gate can pass.
- `snippet` names a source path, marker, or publication-boundary problem. Check
  the configured source root and allowlists before changing the fence.
- `figure` names an invalid or unsafe SVG bundle. Keep the figure self-contained
  and remove active or remote content.
- An `error:` line indicates invalid configuration, an unsafe path, or another
  input refusal. Correct the input rather than bypassing the refusal.

The renderer refuses to clean a nonempty output directory that lacks its
ownership sentinel. Choose a new empty output path, or return to the generated
`build/` directory from the successful checkpoint. Do not point `--out` at the
repository root, documentation tree, source tree, or another input directory.

## Continue authoring

Add a page through [Navigation and links](/authoring/navigation), then use the
[authoring extensions](/authoring/extensions) only where they improve
the published explanation.
