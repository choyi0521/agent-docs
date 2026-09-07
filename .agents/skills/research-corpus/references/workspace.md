<!-- Generated from _agents/skills/research-corpus/references/workspace.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Workspace and derived outputs

## Paths and prerequisites

Run the bundled `scripts/research.py` with Python 3.11+ and SQLite FTS5.
Commands are independent of Git except local-source status. No renderer,
network service, package installation, or downloaded source is required for
record validation and search.

Global options precede the subcommand:

```text
python -B <skill>/scripts/research.py --corpus <corpus> [--docs-root <docs>] [--index-root <index>] [--repository-root <repo>] <command>
```

The corpus contains `catalog/` and `schemas/`. Documentation defaults to
`<corpus>/docs`; the persistent index defaults to `<corpus>/cache/index`.
Choose a separate external index directory when working in a repository whose
publication gate inspects ignored files. Source acquisition has its own
explicit cache root; it does not reuse the index.

To create a new workspace, use `--corpus <new-directory> init`. Initialization
refuses an existing target and writes a neutral taxonomy, record schema,
empty catalog, documentation scaffold, and local ignore rules. Do not copy
another project's findings or controlled vocabulary as an implicit default.

To use a different documentation root, initialize first, deliberately move
the authored documentation, and then pass `--docs-root` consistently. The
tool does not rewrite a consumer's renderer configuration or root agent
instructions.

## Canonical and generated ownership

| Path or object | Owner | Commit or regenerate |
| --- | --- | --- |
| `catalog/<source-id>.json` | Researcher | Commit after source/rights review |
| `schemas/*.json` | Corpus maintainer | Commit controlled schema and vocabulary |
| `docs/records/<record-id>.md` | Researcher, except marked provenance | Commit authored question, claims, evidence, prose |
| `docs/records/_index.md`, `docs/views/**` | Renderer | Regenerate; do not add unique prose |
| Marked provenance inside records | Renderer | Regenerate; preserve the rest of each record |
| Index snapshots and pointer | Indexer | Rebuild locally; do not commit |
| Acquired source trees | Source acquisition tool | Reacquire exact pin; do not edit or commit |

`render` owns only navigation, view pages, and each
`<!-- research:provenance -->` block. It refuses hand-authored collisions in
generated destinations. Do not remove a generated ownership marker to edit
that page; put unique explanation in an authored record or landing page.

## Commands and maintenance order

| Command | Result and side effect |
| --- | --- |
| `init` | Creates a new corpus; refuses existing targets |
| `new <slug> --title <title> --question <question>` | Creates one draft with a stable ID |
| `validate` | Checks canonical shape, taxonomy, pins, evidence keys, and relations |
| `status --all --json` | Reports catalog movement and local citation health without rewriting pins |
| `search <query> --ephemeral --explain` | Searches a private temporary snapshot; no persistent index needed |
| `render` | Regenerates navigation/views and record provenance |
| `render --check` | Reports drift without writing |
| `build` | Builds and atomically publishes a complete immutable search snapshot |
| `build --clean` | Reconstructs a full candidate; does not delete the corpus |
| `search <query> --explain` | Attests persistent state against current canonical inputs before querying |

After editing records, catalog, or taxonomy: validate; inspect evidence;
render; build; run representative searches; then check rendering is current.
Rendering changes record bytes through generated provenance, so building
before rendering makes the persistent index stale.

Default search omits retired and superseded records. Explicit `--domain`,
`--mechanism`, `--quality`, and `--platform` filters are hard constraints;
query-inferred facets affect ranking instead. `--include-inactive` is for
historical investigations. `--json` exposes structured results; `--explain`
shows ranking channels and relation expansion.

Exact identities and locator coordinates, controlled aliases, full text,
and one-hop relations contribute to ranking. Catalog candidates are discovery
leads, not findings. Record facet filters do not assert that a catalog lead
has those facets. Inspect the result category before citing it.

The persistent index is not trusted as a database of record. Search rebuilds
a private candidate and compares the full manifest before querying trusted
bytes. This prioritizes integrity over the usual cached-query performance.
If stale or corrupt state is refused, use `build --clean` and retry; do not
edit snapshot hashes to bypass attestation.

## Installing and publishing

A complete generated `research-corpus` directory can operate independently
under a consumer's agent discovery directory, subject to the repository's
license terms. Keep `scripts/`, `assets/`, and `references/` together. Do not
copy the toolkit's root `AGENTS.md` over the consumer's instructions.

Generated `_index.md` files use Agent Docs' explicit `nav` convention.
Markdown records remain portable, but another renderer may need navigation
adaptation. Installing this skill does not install reader assets or publish
anything. In a prepared Agent Docs site, select the intended note directory
as a documentation space. Do not select downloaded code or index directories
as source trees. Code publication can expose every eligible file in an
allowlisted tree, not only lines cited in a note.
