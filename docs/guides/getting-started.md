# Build and preview the sample site

This guide produces a validated static site in `build/` and serves it on the
loopback interface for local inspection and review comments.

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
interface. Its static files remain read-only, while its local review endpoint
can update `.agent-docs/review-comments.json`. The endpoint is an
unauthenticated local API: browser request checks do not protect it from other
processes on the same operating system. Use it only on a trusted workstation
and stop it with Ctrl+C when review work is finished.

The default review file is ignored by Git. To use another file, pass a path
under the reserved repository-root `.agent-docs/` directory:

```powershell
dotnet run --project src/AgentDocs.Cli --configuration Release -- serve --repo . --config agent-docs.json --out build --port 4173 --no-render --review-data .agent-docs/team-review.json
```

No override can escape `.agent-docs/`. Paths outside that reserved subtree,
symbolic-link or reparse paths, and paths under sentinel-owned generated output
trees are rejected. The entire `.agent-docs/` directory is Git-ignored local
state and is hard-excluded from rendered documents, published source and
snippets, browsable root files, and agent-workflow inputs. Preview preflight
rejects a configuration that attempts to publish the reserved subtree.

## Capture and process review comments

Open **Comments** in the preview to leave a page-level comment. To preserve the
specific context, select text in the document first and choose **Use selected
text**; the saved record includes the quote and nearest heading anchor when one
is available.

Ask an authoring agent to use `$docs-authoring` to inspect the local review
file. The workflow can save a reply and mark a comment `answered`, or mark it
`resolved` after the documentation has been updated. Both `answered` and
`resolved` require a saved reply. Reopen a resolved comment before writing a
new reply.

The preview and the docs-authoring helper serialize mutations with a persistent
sibling operating-system lock. A writer retries every 50 milliseconds for up
to 5 seconds; if that bounded wait expires, refresh the review state and retry.
The lock file remains beside the review data after use. Its exact UTF-8 header
is `agent-docs-review-lock-v1` followed by one LF byte; it is coordination
state, not a stale marker to delete.

Review data is an authoring input, not site content. A `render` contains no
comments and no writable review endpoint, even when the local preview has an
active thread.

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
