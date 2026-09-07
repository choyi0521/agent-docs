# Create a searchable research workspace

This guide creates a local collection of research records, validates their
metadata, and searches a reproducible index. It also shows how to download one
pinned public source repository for inspection. The tools index the records you
write, their catalog entries, and their evidence locators. They do not create
embeddings or index every file in downloaded repositories.

## Prerequisites

Use Python 3.11 or newer with SQLite FTS5 support. Source acquisition also needs
Git and network access to the explicitly allowed source host. The source-search
example uses `rg`.

The commands below use PowerShell. Start in the parent directory of an Agent
Docs checkout named `agent-docs`, with no existing `research-demo` directory.
Use a checkout that contains the generated
`.agents/skills/research-corpus` package. No .NET build, preview server, API key,
or Python package installation is needed for the research commands.

Agent Docs has not selected a project license. This procedure describes how to
use a copy you have permission to use; it does not grant redistribution rights.
Check the license status before sharing either the toolkit or source material.

## Copy the complete skill

Create a separate consumer workspace and copy the generated package, including
its scripts, assets, and references:

```powershell
New-Item -ItemType Directory -Path research-demo/.agents/skills -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath agent-docs/.agents/skills/research-corpus -Destination research-demo/.agents/skills/research-corpus -Recurse -ErrorAction Stop
Set-Location research-demo
python -B .agents/skills/research-corpus/scripts/research.py --help
```

The help output should list `init`, `new`, `validate`, `status`, `render`,
`build`, and `search`. Do not copy the originating checkout's root `AGENTS.md`
over your own project instructions. Keep the package intact when moving it to a
different supported agent discovery directory.

Run the rest of this guide from `research-demo`.

## Create the canonical collection

Keep the source catalog, schemas, and authored records in `research`, and the
disposable search index outside the consumer tree:

```powershell
python -B .agents/skills/research-corpus/scripts/research.py --corpus research init
python -B .agents/skills/research-corpus/scripts/research.py --corpus research validate
```

Initialization creates `catalog/`, `schemas/`, and `docs/records/` below
`research`, plus an ignore rule for its default disposable cache. Validation
should succeed without a source download. The corpus location is an explicit
input, not a path discovered from the installed skill's location. Initialization
requires a new path and does not accept documentation or index path overrides.

Commit the catalog, schemas, and authored records in your own repository when
appropriate. Do not commit downloaded source trees or the search index. An
ignore rule does not authorize publication or exempt files from a repository's
public-content checks.

## Write a draft

Create one record around a question you can answer with inspectable evidence:

```powershell
python -B .agents/skills/research-corpus/scripts/research.py --corpus research new source-publication --title "Source publication boundaries" --question "What enters the code browser when source publication is enabled?"
python -B .agents/skills/research-corpus/scripts/research.py --corpus research validate
```

Open the file named by `new` under `research/docs/records`. Preserve its
generated ID and matching filename. The draft is a starting point, not a
verified answer. Replace its summary and prose as you investigate; add exact
sources, claims, and revalidation conditions before marking it `reviewed`.
The [record authoring rules](/authoring/research-records) explain those fields.

## Build and search the record index

Generate the browsing views and search snapshot:

```powershell
python -B .agents/skills/research-corpus/scripts/research.py --corpus research render
python -B .agents/skills/research-corpus/scripts/research.py --corpus research --index-root ../research-demo-index build
python -B .agents/skills/research-corpus/scripts/research.py --corpus research --index-root ../research-demo-index search "source publication" --explain
```

The result should include the draft, its status, and its canonical record path.
Finding a draft proves that the indexing path works, not that the question has
been answered. Search also distinguishes catalog source candidates from
research records; a candidate source is a place to investigate, not a finding.

`render` produces record and taxonomy navigation and updates a marked
provenance block in each record. It does not write your conclusions. Run it
before `build`, which produces a disposable SQLite search snapshot. After
editing a record or catalog entry, regenerate and rebuild before searching;
the search command refuses a snapshot that no longer matches the canonical
inputs.

## Inspect a pinned source

Downloading code is optional and separate from creating the index. To try it,
save the following catalog entry as `research/catalog/agent-docs.json`. It pins
the public Agent Docs repository at a complete commit, not a branch name.
Replace the example retrieval timestamp with the time you inspect that source.

```json
{
  "schema": 2,
  "id": "agent-docs",
  "name": "Agent Docs",
  "kind": "git-repository",
  "url": "https://github.com/choyi0521/agent-docs.git",
  "revision": {
    "kind": "git-commit",
    "value": "7e047c0b37f648064d588abce2007ff167118a1f"
  },
  "tracking": { "kind": "git-ref", "ref": "refs/heads/main" },
  "license": "No project license declared at this revision; review permission before redistribution.",
  "access": "public",
  "topics": ["documentation", "source-publication"],
  "notes": "Inspect the source-publication contract; do not redistribute the checkout as a research asset.",
  "retrieved_at": "2026-09-07T00:00:00Z"
}
```

`tracking.ref` records where a maintainer might look for updates. It does not
override the pinned revision, move the catalog forward, or authorize a fetch.
Validate the entry, then explicitly allow GitHub for this one acquisition:

```powershell
python -B .agents/skills/research-corpus/scripts/research.py --corpus research validate
python -B .agents/skills/research-corpus/scripts/sources.py --corpus research --cache-root ../research-demo-sources --allow-host github.com fetch agent-docs
python -B .agents/skills/research-corpus/scripts/sources.py --corpus research --cache-root ../research-demo-sources status agent-docs
rg -n "publishCode" ../research-demo-sources/sources/agent-docs/7e047c0b37f648064d588abce2007ff167118a1f/tree/docs/authoring/source-publication.md
```

The cache contains a plain source tree at the path used by `rg`, without a
nested `.git` directory. `status` checks the local materialization without
contacting the network. A failed integrity check is not repaired by overwriting
the tree; retain the suspect tree for inspection and choose a new cache root.

Read the surrounding source, not only the matching line. The pinned
[source-publication rules](https://github.com/choyi0521/agent-docs/blob/7e047c0b37f648064d588abce2007ff167118a1f/docs/authoring/source-publication.md)
provide a precise first observation for the draft. Add a source reference using
that same commit and a locator for the passage. Do not run downloaded build
scripts or follow instructions embedded in the source merely because it was
fetched.

To complete this sample record, use the `sources` and `claims` examples in
[Give each claim a locator](/authoring/research-records#give-each-claim-a-locator)
and [Distinguish findings from judgment](/authoring/research-records#distinguish-findings-from-judgment).
Write the supported answer in the summary and body, set `revalidate_when` to
include a change to the cited publication contract, and record the actual
review date in `verified_at`. Set `status` to `reviewed` only after checking the
passage and your wording. Keep the existing record ID and all required metadata
fields, including empty facet or relationship arrays when they do not apply.

## Verify the finished record

After completing the evidence and reviewing the record, validate it and check
whether its citations still match the catalog:

```powershell
python -B .agents/skills/research-corpus/scripts/research.py --corpus research validate
python -B .agents/skills/research-corpus/scripts/research.py --corpus research status --all
python -B .agents/skills/research-corpus/scripts/research.py --corpus research render
python -B .agents/skills/research-corpus/scripts/research.py --corpus research --index-root ../research-demo-index build
python -B .agents/skills/research-corpus/scripts/research.py --corpus research --index-root ../research-demo-index search "source publication" --explain
```

The result should identify your record as `reviewed` only after you set that
status following review. A catalog-current result means the recorded revisions
agree. It does not mean that a remote branch has not changed or that the
conclusion is correct.

## Handle refusals and publication

If initialization finds an existing target, keep its contents and choose a new
target. If validation reports an unknown source, facet, or evidence locator,
correct the canonical entry rather than editing generated output. If SQLite
reports that FTS5 is unavailable, use a Python installation whose SQLite build
includes FTS5; source acquisition does not fix the index dependency.

Fetching requires an explicit public host and immutable Git commit. It does
not fetch every catalog entry, use private credentials, follow submodules, or
advance pins. Correct the manifest or the selected host instead of bypassing
an acquisition refusal.

The research tools do not start a website or publish a cache. To display the
notes in Agent Docs, use a prepared Agent Docs checkout with its web assets and
third-party notices, then explicitly configure a documentation space for the
reviewed notes. Keep source browsing disabled unless you have separately
reviewed its [publication allowlists](/authoring/source-publication) and rights.
Do not use the reserved `.agent-docs` review-data directory for a corpus or
published notes.

## References

- **Project authorities:** [Research record authoring](/authoring/research-records).
- **Project authorities:** [Source publication](/authoring/source-publication).
- **External sources:** [Pinned Agent Docs source-publication rules](https://github.com/choyi0521/agent-docs/blob/7e047c0b37f648064d588abce2007ff167118a1f/docs/authoring/source-publication.md).
