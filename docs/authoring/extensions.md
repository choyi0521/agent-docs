# Authoring extensions

The extensions remain readable in their source form and are validated during
the documentation build. Raw HTML is disabled. Links must be local or use an
allowed HTTP(S) or email scheme, and images must name a validated local SVG
figure bundle.

## Tabs {#tabs}

Use tabs when several representations explain the same idea. Each pane begins
with `==` followed by its label.

:::tabs
== Request

```json
{
  "name": "Ada"
}
```

== Response

```json
{
  "message": "Hello, Ada."
}
```
:::

## Local review comments {#local-review-comments}

The loopback-only `serve` command enables a local review panel alongside the
static reader. Select a passage before opening **Comments**, then choose **Use
selected text** to save the quote and its nearest heading anchor with the
comment. Page-level comments work without a selection.

Review records use the versioned data contract in
`schemas/review-comments.schema.json` and are stored by default in the ignored
file `.agent-docs/review-comments.json`. `--review-data PATH` can choose another
file only beneath the reserved repository-root `.agent-docs/` directory. The
entire directory is Git-ignored and hard-excluded from rendered documents,
published source and snippets, browsable root files, and agent-workflow inputs.
Paths outside it, symbolic-link or reparse paths, and paths under any
sentinel-owned generated output tree are rejected; preview preflight also
rejects a configuration that tries to publish the reserved subtree.

Ask an authoring agent to use `$docs-authoring` to answer the saved comments.
An answer is stored in `reply` with status `answered`; only a comment with a
saved reply can be `answered` or `resolved`. A resolved thread must be reopened
to `open` before its reply can be replaced. Refresh the panel after an agent
writes the file.

The preview and the docs-authoring helper share a persistent sibling
operating-system lock, so their mutations are serialized. Each writer retries
every 50 milliseconds for up to 5 seconds. If the bounded wait expires, refresh
the review state and retry. The lock file remains beside the data file and has
the exact UTF-8 header `agent-docs-review-lock-v1` followed by one LF byte; do
not delete it as though it were a stale sentinel.

A useful agent request is: “Use `$docs-authoring` to address the open saved
documentation review comments. Inspect each target and evidence, edit and
verify the docs, save a reply, and resolve only handled comments.” The skill's
repository-local helper exposes the same workflow explicitly:

```powershell
python -B _agents/skills/docs-authoring/scripts/review_comments.py --repo-root . validate
python -B _agents/skills/docs-authoring/scripts/review_comments.py --repo-root . list --status open
python -B _agents/skills/docs-authoring/scripts/review_comments.py --repo-root . show <comment-id>
python -B _agents/skills/docs-authoring/scripts/review_comments.py --repo-root . reply <comment-id> --reply "What changed and how it was verified."
python -B _agents/skills/docs-authoring/scripts/review_comments.py --repo-root . resolve <comment-id>
```

Add `--keep-open` to the `reply` command when the requested work is blocked.
Use `reopen <comment-id>` to return a thread to `open`. For an overridden store,
put `--review-data .agent-docs/<file-name>` before the subcommand. Reopen a
resolved comment before using `reply` to replace its saved response.

This feature is deliberately absent from static publication. `render` never
copies the review data or a writable API into `build/`; only the loopback
preview process exposes it. That endpoint is an unauthenticated local API.
JSON-only requests plus `Origin` and fetch-metadata checks reduce ordinary
browser cross-site writes, but cannot protect against another local operating-
system process. Use the preview only on a trusted workstation and stop it when
review work is complete.

## Snippets {#snippets}

A snippet fence lifts one named region from an allowed source file. The sample
below is backed by the code in `examples/source`, rather than a second copy in
this page. Its target is relative to the space's configured `sourceRoot`, which
is the repository root for this sample.

```snippet examples/source/GreetingFormatter.cs#greeting-format
title: Format a greeting
lang: csharp
```

The extracted method rejects a blank name, trims surrounding whitespace, and
returns the formatted greeting. The fence keeps this explanation tied to the
compiled example instead of maintaining a second implementation in Markdown.

Markers use whole-line comments in the source:

```text
// docs:begin region-name
// lines included in the documentation
// docs:end region-name
```

The gate rejects missing files, missing markers, duplicate markers, and source
paths outside the configured publication boundary.

## Figures {#figures}

A figure bundle at `_assets/figures/<name>/` keeps an intent ledger, an editable
source, a deterministic `build.py`, a review wrapper, and the canonical
`figure.svg`. The documentation renderer consumes only the SVG. Refer to it
with ordinary image syntax so the source remains useful in a basic Markdown
viewer.

![Only explicitly allowed source regions and passive SVG enter the rendered page; rejected inputs stop the checked build before its static site data is publishable.](../_assets/figures/document-flow/figure.svg)

Run `python -B docs/_assets/figures/document-flow/build.py` from the repository
root to rebuild this sample's SVG and `figure.html`. Figure SVG must be
self-contained. Scripts, event-handler attributes, embedded HTML, and external
references are rejected.

## Plans {#plans}

A titled Plan separates intended behavior from the available implementation.
Each H3 goal uses a durable explicit anchor with the prefix configured by the
documentation audit. Navigation derives its Plan count from the containers, so
authors do not maintain a separate status registry.

:::plan Publish translated documentation

### Publish a parallel language space {#plan-docs-publish-translated-space}

**Current:** The sample publishes one documentation space in one language.

- [ ] Add a second documentation space with an explicit route and navigation.
- [ ] Verify that equivalent cross-space links retain their durable fragments.

**Done when:** A checked render publishes both spaces and reports no broken
routes or heading anchors.
:::

## References

- **Source:** [Complete greeting formatter source](/code/examples/source/GreetingFormatter.cs)
