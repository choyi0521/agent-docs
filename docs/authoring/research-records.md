# Author research records

A research record preserves an answer together with the question, evidence,
constraints, and reasons that produced it. This page governs records maintained
with the `research-corpus` skill. It explains what authors must establish;
successful validation alone cannot establish that a conclusion is true.

For the executable setup and search workflow, use
[Create a searchable research workspace](/guides/research-workspace).

## Separate the three stores

The canonical collection contains source catalog entries, the taxonomy, the
record schema, and authored Markdown records. A catalog entry identifies a
source and the revision selected for research. A record preserves the revision
actually used for its own claims, even after the catalog advances.

The source cache contains reproducible copies of selected upstream bytes. It
is an inspection aid, not the authoritative location of a conclusion. Keep it
outside the toolkit and consumer repositories. Do not edit a verified cache
tree to make a citation or test work.

The search index and generated navigation are derived views. Rebuild them from
the canonical collection. Never fix a wrong claim, source pin, or taxonomy term
by patching an index or generated page.

| Data | Authoritative input | What it does not prove |
|---|---|---|
| Catalog entry | Origin, selected revision, access and license metadata | That the source answers a question |
| Research record | Question, claims, evidence and explicit limitations | That a recommendation was adopted |
| Verified source cache | Bytes of one selected source revision | Permission to redistribute those bytes |
| Search result | A match against indexed canonical records | Completeness, semantic truth, or current remote state |

## Frame one answerable question

Give the record one question with enough constraints to judge a useful answer.
“How does caching work?” has no stable boundary. “Does this cache invalidate
entries after a source revision changes?” names an observable condition and
outcome. State the implementation, version, workload, or platform when it
changes the answer.

Use `study` for a bounded investigation, `comparison` when the answer depends on
contrasting sources, and `synthesis` when the record combines findings into a
larger explanation. A reviewed comparison requires at least two catalog
sources. Adding two URLs for the same source does not create an independent
comparison.

The summary states the supported result and its important limit. The body
explains the mechanism, contrasts, evidence gaps, and consequences in readable
Markdown. Metadata enables retrieval; it does not replace that explanation.

## Preserve identity and classification

Records begin with JSON front matter between `---` lines, followed by Markdown.
Keep the generated record ID equal to its filename stem. Changing the title
does not require changing the ID. Reference that ID in record relationships so
an editorial rename does not break the evidence chain.

Agent Docs accepts this JSON-object front matter alongside its existing YAML
subset. JSON comments, trailing commas, and duplicate keys are refused. The
renderer removes the metadata from the page body; generated provenance makes
the relevant status and source pins visible to readers. Nested evidence objects
do not become navigation entries, and the page title still comes from its
Markdown H1. Keep the metadata title and that heading consistent when editing.

The four facet axes are `domains`, `mechanisms`, `qualities`, and `platforms`.
Use tokens declared in the collection's taxonomy, with labels and aliases that
readers actually search for. Extend the taxonomy deliberately when an existing
term does not fit; do not insert arbitrary synonyms into individual records.

`consumers` names repository-relative paths to documents or code that use a
record's findings. It is impact metadata, not an instruction to modify those
files and not evidence that a recommendation has been implemented. Omit
machine-specific paths and private ownership records from public collections.

## Record exact provenance

For each catalog entry, preserve its stable ID, name, source kind, origin,
revision, retrieval timestamp, license status, access classification, topics,
and a short scope note. Catalog IDs match their JSON filenames.

Git repositories use a complete lowercase 40-character `git-commit` revision.
A branch, tag label, or `tracking.ref` is not an immutable pin. Other source
kinds use a `content-digest` revision in `sha256:<64 lowercase hex characters>`
form. A digest identifies bytes; the author still needs to record enough
retrieval context to find and understand those bytes.

A local repository source omits a remote URL and uses local-head tracking.
Pass the intended `--repository-root` when asking the tool to check local
path drift. The installed skill directory is not the repository being studied.
Public Git acquisition is a narrower operation than cataloging: it fetches
only explicitly selected public Git sources with an allowed HTTPS host.

Every source reference inside a record repeats the revision inspected and
declares its role: `primary`, `contrast`, `counterexample`, or `context`.
This repetition is intentional. Otherwise changing the catalog pin would
silently rewrite the apparent evidence for old conclusions.

## Give each claim a locator

A locator identifies the smallest useful evidence location within a source.
It has an ID local to that source reference. Claims refer to it as
`source-id:locator-id`.

For example, the guide's pinned source documents that enabling source browsing
publishes every matching allowlisted file. The corresponding source reference
can be written as follows. This is the value of the record's `sources` field,
not a complete record:

```json
[
  {
    "id": "agent-docs",
    "revision": {
      "kind": "git-commit",
      "value": "7e047c0b37f648064d588abce2007ff167118a1f"
    },
    "role": "primary",
    "locators": [
      {
        "id": "publication-rules",
        "kind": "source-tree",
        "path": "docs/authoring/source-publication.md",
        "line_start": 8,
        "line_end": 13
      }
    ]
  }
]
```

The lines refer to that exact commit, not the same path on `main`. The
[pinned passage](https://github.com/choyi0521/agent-docs/blob/7e047c0b37f648064d588abce2007ff167118a1f/docs/authoring/source-publication.md)
supports a claim about the documented contract. Proving that all implementation
paths obey the contract requires separate code and test evidence.

Use the locator kind that matches the inspected material:

| Kind | Required location |
|---|---|
| `source-tree` | Repository-relative path; add a symbol or positive line coordinates when useful |
| `document` | At least a page, section, or quote digest |
| `web` | At least a fragment, selector, or quote digest |
| `dataset` | At least a table or query; add row and column where relevant |
| `media` | A timecode |
| `artifact` | At least a path or member |

Line ranges must start at one or later, and their end cannot precede the start.
Validation checks the coordinate shape and evidence references. It does not
open every upstream artifact and prove that the passage supports the claim.
Inspect the pinned source before recording coordinates, and keep enough nearby
context to avoid reversing its meaning.

## Distinguish findings from judgment

Every claim has an ID, a type, a statement, and an array of evidence references.
For the source reference above, the `claims` field can start with this one
observation:

```json
[
  {
    "id": "browsing-includes-the-allowed-tree",
    "type": "observation",
    "statement": "The publication guide states that code browsing includes every matching file in the allowed trees.",
    "evidence": ["agent-docs:publication-rules"]
  }
]
```

Use the claim types consistently:

- `observation`: what the inspected source or experiment establishes. For
  example, “The publication guide states that browsing includes every matching
  file in the allowed trees.” Cite `agent-docs:publication-rules`.
- `interpretation`: what follows from observations under stated assumptions.
  For example, a broad tree allowlist can expand the published surface when
  eligible files are added. State the assumption that the allowlist remains
  unchanged.
- `recommendation`: what a maintainer should choose given the question and
  constraints. Keeping a new source tree unpublished until rights review is a
  policy recommendation, not an upstream implementation fact.
- `non-finding`: what the investigation did not establish. Name the searched
  scope and method. “No matching implementation was found in the inspected
  directory” does not establish that no implementation exists elsewhere.

A reviewed observation must cite evidence. Interpretation and recommendation
should name their supporting observations and uncertainties in prose even
when their metadata can be validated without an evidence reference. Never
turn a source's proposed design into an observation about shipping behavior.

## Review and revalidate

`draft` means the investigation is not yet reviewed. `reviewed` requires source
references, precise locators for every cited source, at least one evidence-backed
observation, claims, and a revalidation trigger. Review also requires checking
the prose and conclusion, not merely satisfying these structural conditions.

The new-record scaffold uses its creation date in `verified_at` to satisfy
the required date field; its `draft` status does not claim completed review.
Set `verified_at` to the actual review date before marking it `reviewed`.
Use concrete `revalidate_when`
conditions, such as “the cited source-publication path changes” or “the proposed
consumer enables a different source tree.” Do not change the date merely to
make old evidence look recent.

When a catalog revision changes, old records retain their original pins and
may acquire a source-revision-stale health marker. That marker identifies work
to review; it does not prove that a conclusion is now wrong. Conversely,
catalog-current means only that recorded pins agree. It is not a remote update
check, and an unchanged pin does not establish current behavior.

For local repository citations, `status` checks committed path history and
ordinary Git working-tree status with an explicit repository root. It is not a
complete byte attestation of the working tree. A missing repository, path, or
commit, a timeout, or Git's `assume-unchanged` and `skip-worktree` flags can make
the evidence unverifiable. Treat that result as an evidence gap. The tools do
not automatically update pins, dates, or conclusions.

After a relevant change, inspect the new source, rerun any applicable
experiment, revise the claim if needed, and deliberately update the record's
pin and review date. Then validate, regenerate navigation, and rebuild the
index. Do not change every record pin just because a catalog entry moved.

## Relate and retire records

Use `supports`, `contradicts`, `refines`, and `related` to preserve relationships
between findings. These links help a reader follow the argument; they do not
automatically transfer evidence or review status between records.

Use `superseded` when another record replaces this answer. Name the successor
in `superseded_by` and the predecessor in the successor's `supersedes` field.
The reciprocal links are validated. Use `retired` for an answer that should no
longer guide work without asserting that a replacement exists.

Default search excludes superseded and retired records. Use
`--include-inactive` when tracing history. Drafts can still appear in ordinary
search, so inspect status and evidence health before using a result.

## Publish deliberately

Research collection, source acquisition, indexing, and website publication are
separate actions. A public source URL and a successful download do not grant
permission to redistribute full source, figures, datasets, or lengthy excerpts.
Preserve license and notice information; record unresolved rights rather than
guessing a permissive license.

Do not copy private research notes into a public collection by changing names.
Review the facts, examples, paths, relationships, and source rights themselves.
Keep credentials, private endpoints, customer data, source caches, and generated
databases out of the published toolkit.

Before rendering reviewed notes into a site, select their documentation space
explicitly. Source browsing is a separate opt-in governed by
[Source publication](/authoring/source-publication). Check the resulting
navigation and search output as well as the pages: both can expose indexed
content that a reader did not open directly.

## References

- **Project authorities:** [Create a searchable research workspace](/guides/research-workspace).
- **Project authorities:** [Source publication](/authoring/source-publication).
- **External sources:** [Pinned Agent Docs source-publication rules](https://github.com/choyi0521/agent-docs/blob/7e047c0b37f648064d588abce2007ff167118a1f/docs/authoring/source-publication.md).
