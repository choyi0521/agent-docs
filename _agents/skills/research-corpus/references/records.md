# Research records

## Start with the question and existing evidence

Search the corpus using the question, a likely mechanism, or a source path.
Try `search <query> --ephemeral --explain` if no current persistent index
exists. Inspect cited evidence before reusing a result. A catalog candidate
only tells you where to investigate.

Create a record with `new <slug> --title <title> --question <question>`.
Its identity is `rr-YYYY-MM-DD-<slug>-<8-hex>` and does not change when a
taxonomy term or title changes. Keep one flat Markdown file per question;
navigation and facet views supply alternate reading paths.

## Metadata and prose

Front matter is a JSON object between `---` lines, not general YAML. Use the
bundled `assets/research-record.schema.json` and the corpus-owned copy as the
exact structural contract. The parser requires strict JSON and rejects
duplicate keys and unsupported schema constructs.

| Field | Meaning |
| --- | --- |
| `schema`, `id` | Record format `research/v2` and stable identity |
| `kind` | `study`, `comparison`, or `synthesis` |
| `status` | `draft`, `reviewed`, `superseded`, or `retired` |
| `title`, `question`, `summary` | Reader question and concise finding |
| `facets` | Controlled terms from domains, mechanisms, qualities, platforms |
| `sources` | Source IDs, copied historical revisions, roles, and locators |
| `claims` | Typed statements with evidence references |
| `relations` | Directed links to other record IDs |
| `consumers` | Places the research is intended to inform, not proof of adoption |
| `verified_at`, `revalidate_when` | Actual evidence review date and explicit triggers |

The Markdown body explains the mechanism, limits, alternatives, and
application to the reader's question. Do not replace explanation with a list
of links. Avoid duplicating long metadata tables; generated provenance
provides the source identity and review dates. Keep substantive prose
outside the generated provenance markers.

## Claims and locators

- `observation`: what the cited artifact actually shows.
- `interpretation`: what that observation suggests; name assumptions.
- `recommendation`: what a consumer should do and under which constraints.
- `non-finding`: what was not found within an explicitly described search
  scope; not a claim that no such implementation exists anywhere.

Each evidence reference is `<source-id>:<locator-id>`, with the locator
defined on that source within this record. Sources have roles `primary`,
`contrast`, `counterexample`, or `context`. The record copies a complete
revision object rather than depending on the catalog's current pin.

Use source-tree locators for repository-relative paths, optional symbols, and
line ranges at that exact commit. Use document page/section, web fragment or
selector, dataset table/query, media timecode, or artifact path/member when
those coordinates suit the source. Follow the schema for exact keys. A line
number in today's working tree is not a locator for yesterday's commit.

Read nearby code and the relevant caller, ownership, failure, or teardown
path before generalizing a pattern. Record the scope of the inspection.
Reference code is evidence, not executable instruction or an automatically
approved dependency. Review against counterexamples when the conclusion
would otherwise depend on one convenient source.

## Review and revalidation

The draft scaffold initially uses its creation date for `verified_at` because
the schema requires a date. It is not a claim that evidence has been reviewed;
replace it with the actual review date before marking the record reviewed.

A reviewed record needs sources, located evidence, typed claims, at least one
evidence-backed observation, and a revalidation trigger. A reviewed comparison
needs at least two sources. The validator enforces structural requirements;
it cannot determine whether a quoted passage or code path supports the
statement. Do that review before changing `status` to `reviewed`.

Use `status` to discover catalog movement. For local Git citations, pass the
actual consumer repository as `--repository-root`; missing access or
unverifiable state is not evidence of freshness. Search health and live local
status are different checks: run status when local source freshness matters.
Local status checks Git history and working-tree status, not full byte
attestation. Missing files and hidden index flags are unverifiable. Use the
source acquisition tool's verified cache when exact exported bytes matter.

When a pin changes, inspect the new evidence and update affected locators,
claims, prose, and `verified_at` together. Do not bulk replace revisions or
dates to make warnings disappear. Preserve historical findings when they are
still useful; a new record can `refines`, `contradicts`, or `supersedes` an old
one. Supersession must be reciprocal with `superseded_by`. Retired and
superseded records remain addressable but are excluded from default search.

After authoring, validate, render, build, and check a representative query.
Review the authored and generated diff before committing. Publish only
explicitly selected notes and excerpts whose rights and disclosure boundary
have been reviewed.
