---
name: technical-figure
description: Design, build, review, and verify reproducible technical figures whose geometry explains a source-backed claim at a glance. Use for architecture and dependency diagrams, timelines, ownership and state explanations, spatial or coordinate illustrations, comparisons, annotated vector figures, 3D concept renders, and documentation visuals. Choose a semantic form before a drawing tool, preserve an editable source and exact rebuild command, inspect the rendered result, and reject labelled-box inventories or decoration that makes the reader reconstruct the mechanism.
---
<!-- Generated from _agents/skills/technical-figure/SKILL.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->

# Design a technical figure

Make the mechanism visible. A figure is a visual argument, not a component
inventory. The reader should recover its main conclusion before reading the
surrounding prose.

Every logical element, including subject, boundary, connector, position, size,
color, line style, repetition, annotation, and deliberate empty space, must
encode a source-backed fact or an accessibility aid. Text names exact things;
geometry explains their relationship. Remove any element whose purpose cannot
be stated.

Read [visual semantics](references/visual-semantics.md) completely before
composing or materially redesigning a figure. Use it during review when the
problem concerns meaning, hierarchy, or design rather than only export format.

## Model the claim before drawing

1. Read the host page, its truth sources, and nearby figures.
2. Write one reader question and one declarative immediate takeaway.
3. Decompose the claim into only the facts, relationships, limits, and status
   distinctions that actually apply. Do not invent a category to satisfy a
   template. Mark any absent, partial, planned, or deliberately schematic fact.
4. Choose one representative entity to trace when the claim involves flow or
   change.
5. Decide whether a figure removes mental reconstruction better than prose, a
   table, or a worked example. Do not make a figure merely to add visual variety.
6. When more than one semantic form is plausible, compare materially different
   label-free compositions. Record the selected form and why its geometry needs
   less interpretation; do not manufacture alternatives to satisfy a count.
   Add labels only after this choice. Unchanged bundles are exempt until they
   change.

If changing only the labels would make the same composition explain an
unrelated topic, redesign it.

## Choose the semantic form, then the tool

Choose the form from the truth: timeline for lifetime, nested region for
ownership, slots for a queue, before/after states for transformation, actual
axes for coordinates, or a matrix for coverage. Use a box only when a real
container, boundary, region, record, or graph node is part of the claim.

Then choose the smallest truthful implementation tool:

| Truth to express | Default tool |
| --- | --- |
| Nodes and edges are the subject | [Graphviz](references/graphviz.md) |
| Deliberately routed architecture, sequence, or topology | [draw.io](references/drawio.md) |
| Coordinates, cameras, culling, geometry, or spatial mechanisms | [scripted Blender](references/blender.md) |
| Bespoke vector explanation or annotated composition | [OpenPencil](references/openpencil.md) |
| Data-derived structure plus non-falsifying annotation | Deliberate hybrid |

Do not select Graphviz merely because the source mentions components. Use it
when graph topology is itself the explanation. Do not use a heavier tool merely
because it is available, or an interactive editor as the only source when a
deterministic script can own the result.

For setup details, read only the needed direct reference:

- [tool installation and diagnostics](references/toolchain-setup.md)
- [optional MCP connections](references/mcp-setup.md)

## Record the intent

Copy [the intent-ledger template](assets/figure-intent.template.json) beside the
editable source as `figure-intent.json`. Complete it before polishing the
figure.

Record `kind`, which names the shape of the figure. The field is optional,
because bundles predate it, and the template's placeholder is not a valid
value, so a bundle started from the template either names its kind or deletes
the line. The declared kinds are `contrast`, `decision`, `fan-out`, `flow`,
`layout`, `state`, and `timeline`. A bundle that declares any other word is
refused. Growing that list is an edit to `FIGURE_KINDS` in
`scripts/audit_figures.py`, so the vocabulary stays one decision rather than
one per author.

Give every logical element a stable semantic id. Record its meaning, role,
encoding choice, why that encoding is direct, evidence, and the information lost
if it is removed. Include connector classes, boundaries, status encodings,
repeated patterns, meaningful alignment or whitespace, and annotations, not
just named nodes. Map those ids to the source where the format supports ids.
Incidental renderer strokes are not logical elements and do not need ledger
entries.

Name each ledger role by the fact that the element contributes. The role
vocabulary is open; do not use a drawing primitive as the role merely because
the element happens to be rendered with that primitive.

Every element must record `whyThisEncoding`. For every connector class or
visible transition, record the one relation that it represents; split the class
when the meaning changes. Every enclosing shape must name the real boundary it
represents. Do not reuse one connector style for unrelated meanings.

The template intentionally starts trace and review statuses at `pending`, which
the audit must reject. Complete `representativeTrace` as either `pass` with an
entity and existing element ids in `steps`, or `not-applicable` with a reason.
Complete each core review as `pass` with an observation. A conditional review
may be `not-applicable` only when its mechanism is genuinely absent and the
ledger records why. A new or changed bundle cannot pass with a pending or
failed blind review. Keep
`review.trace` consistent with `representativeTrace`; when a review fails,
redesign and leave the ledger unaccepted until a fresh review passes.

An audit can confirm that a declared `svgId` exists, but it cannot prove that
every visible logical element was declared or that the drawing means what the
ledger claims. Review output-id coverage manually with the point-and-explain
test. For a raster-only bundle, omit `svgId`; raster output cannot be exhaustively
mapped to ids, so its ledger and rendered review are the coverage evidence.

## Compose the explanation

- Lead with one visual subject and one primary relationship. Let context recede.
- Encode distinction with position, containment, sequence, scale, silhouette,
  line style, or repetition before color or prose.
- Make the action visible: moving, transforming, blocking, splitting, retaining,
  publishing, or unwinding must change the visual state.
- Use aligned timelines or small multiples for change over time.
- Use before/after, cutaway, ghosted state, or side-by-side views for failure,
  occlusion, transformation, or comparison.
- Show partial or absent implementation as a limit, gap, open socket, or explicit
  stop. Do not draw a detailed phantom pipeline for behavior that does not exist.
- State when distance, proportion, order, or shape is schematic.
- Prefer focused figures over a poster. Move lookup detail to a table or prose.
- Keep exact identifiers subordinate to the visual explanation. Do not put
  paragraphs inside nodes.
- Make each visible label resolve the identity or relationship at its mark
  without forcing the reader to guess. Keep it locally scannable, but do not
  shorten it until the mark becomes ambiguous. Put explanation that applies to
  the whole figure in the caption or host prose.
- Design typography at the **final rendered article size**, not at the source
  canvas size or in a zoomed editor. Compare visible labels with the host's body
  copy and give every distinct typographic treatment a clear semantic job.
- Keep every visible label comfortably readable at every supported display
  size. Subordinate annotations must still pass the rendered host-page review;
  raster or Blender output is not exempt from legibility.
- Keep whole-figure explanation in the host heading, caption, or prose. The SVG
  must retain its non-visible accessible `<title>` and `<desc>`. Use direct local
  labels when they reduce lookup work, and move material that readers must read
  as a separate explanation outside the drawing.
- Author close to the host's real article width. If the truth genuinely needs a
  wider canvas, split it into focused figures or make the host preserve the
  authored size with horizontal scrolling. Never shrink a wide poster until its
  labels become footnotes.

## Keep a reproducible bundle

Follow the host pipeline while keeping these roles explicit:

```text
<figure-directory>/
  figure-intent.json                  # mandatory for a new or changed bundle
  build.py                            # mandatory committed build entry point
  source.dot | figure.drawio | figure.op
  scene.blend                         # optional authored Blender source
  figure.html                         # mandatory audit/review wrapper and caption
  figure.svg | figure.png             # at least one mandatory canonical output
  artifact.json or equivalent         # when the host requires provenance
  inputs/ and licenses/                # only for incorporated external material
```

An audited product bundle is incomplete without `build.py`, `figure.html`, and
at least one canonical `figure.svg` or `figure.png`. `build.py` is the mandatory
committed build authority: it must orchestrate the external renderer, or run as
its pinned scripted entry point, and normalize output before writing canonical
artifacts. Direct tool commands are exploratory unless they invoke or are
wrapped by that authority. The editable source and exact rebuild command are
mandatory; generated output must not be the only surviving source. Never
iterate an unordered set when emitting nodes, edges, layers, or labels. Pin
meaningful tool versions when pixel identity matters.

`figure.html` is the bundle's audit and review wrapper, not necessarily the
fragment a documentation host publishes. It remains mandatory under this
bundle contract so the canonical asset, visible conclusion caption,
accessibility, and embedding safety can be reviewed together. A host may ignore
the file and safely construct its own wrapper and caption when it preserves the
audited asset, equivalent caption meaning and accessibility, and the same
security constraints. Do not require a host to copy this wrapper verbatim.

For the wrapper safety audit, assume any renderer that consumes `figure.html`
may inline it and its SVG into the article DOM. An SVG `<style>` is therefore
page CSS, not a private stylesheet.
Give the root `<svg>` a stable bundle id and scope every selector beneath that
id (for example, `#provider-resolution-figure .label`). Never use `:root`, an
unscoped element selector such as `text`, or a generic selector such as
`.label`; define custom properties on the bundle root id. Presentation
attributes and element `style` attributes remain local, but must still be
deterministic and reviewable.

For sourced media, record the public HTTPS URL, author, retrieval date, exact
input digest, license, modification, and output digest. Never record private
hosts, URL credentials, or signed query strings. Do not use unclear,
noncommercial, no-derivatives, or otherwise incompatible material.

## Build and inspect

Check the available toolchain from the repository root:

```powershell
python -B _agents/skills/technical-figure/scripts/figure_tools.py doctor
```

The committed build must use direct CLI or scripts. MCP may help live
exploration but must not become hidden build state. Never install software, add
an MCP server, or edit global agent configuration without explicit permission.

Name every new or changed bundle explicitly in the figure audit; do not let an
implicit repository scan decide the change scope:

```powershell
python -B _agents/skills/technical-figure/scripts/audit_figures.py --repo-root . --bundle <figure-directory> [--bundle <figure-directory> ...]
```

The audit uses a neutral `704px` article slot to resolve SVG sizing declarations.
Pass `--article-width-px <measured-width>` when the host width is known. This
structural calculation does not establish readability or prove host CSS.

This audit supplies structural evidence only: required files, intent shape,
declared source paths, accessible metadata, declared output ids, caption
agreement, and review provenance. It does not infer meaning, prose quality,
legibility, or hierarchy from wording, punctuation, element names, font sizes,
or fixed numeric thresholds. A passing audit is never proof that the claim is
true, the composition communicates it, every label is readable, or every
rendered logical element is represented. Source review, host-page inspection,
and blind review remain mandatory.

1. Rebuild from the committed source in a clean or temporary output directory.
2. Inspect the actual SVG, PNG, and host page, not only a successful process.
3. Inspect every supported article layout, compare visible labels with body
   text, and record the display contexts and observations in
   `review.hostReadability` or the compatible `review.articleTypography` field.
   Also inspect every theme on which colors depend.
4. Confirm quantities, order, coordinates, boundaries, connectors, and status
   claims against their recorded authority.
5. Rebuild and compare bytes or semantic output when determinism is required.
6. Run the host documentation, link, accessibility, and provenance gates.

For a tool installation smoke test, run:

```powershell
python -B _agents/skills/technical-figure/scripts/figure_tools.py smoke --tool all
```

An unavailable optional tool is not a reason to substitute an inferior form.
Install the right tool when authorized or report the missing capability.

## Reject weak explanations

Run these tests on the rendered figure at its real display size. A failed core
test requires redesign, not another explanatory paragraph. Mark a conditional
test not applicable only with a reason in the intent ledger.

- **First-read:** The primary subject, contrast, and conclusion appear before
  detail.
- **Label-swap:** Replacing labels cannot turn the same picture into an unrelated
  explanation.
- **Label-off:** Without labels, the relation type and reading order remain
  recognizable even though exact names do not.
- **Point-and-explain:** Every logical element has an immediate meaning and a
  reason for its particular encoding.
- **Ablation:** Removing an element removes meaning or a necessary accessibility
  cue; otherwise remove it.
- **Counterfactual:** Reversing the central fact would require a visible change
  to the composition.
- **Arrow-verb:** Each important connector class expresses one named relation;
  adjacency alone is not drawn as an arrow.
- **Boundary:** Every enclosure or separation denotes a real scope, ownership,
  isolation, or spatial boundary, and crossings match reality.
- **Trace:** For flow or change, one representative entity can be followed from
  start through outcome without guessing.
- **Thumbnail:** At reduced size, the subject, hierarchy, and primary direction
  survive even when small labels do not.
- **Host readability:** At every supported layout, labels remain legible,
  hierarchy remains clear, and overflow or panning does not hide the initial
  takeaway. Record the inspected display contexts and observations rather than
  judging a zoomed source canvas.
- **Grayscale:** Meaning survives grayscale and common color-vision differences.
- **Prose-dependency:** The surrounding prose is not required to invent what the
  shapes, connectors, or layout mean.
- **Source-truth:** Every solid path, boundary, quantity, and state is supported
  by its recorded source; planned or absent behavior cannot resemble current
  assembled behavior.

For every new or changed figure, run a blind review: show the rendered asset
without its caption, host prose, or intent ledger to a fresh reviewer. Ask the
reviewer to explain the figure in their own words without supplying the intended
categories or interpretation. Record a non-identifying `reviewerLabel`, rendering
and display context, exact prompt, free recovered reading, and comparison in
`review.blindReview`. A materially different reading requires recomposition.
Never publish a person's name, email address, account id, chat id, or private
transcript. Use repository-relative artifact paths and public-safe review text.
Existing `artifact` records remain accepted as rendering provenance; do not
rewrite historical review evidence as if a new review had occurred. Unchanged
bundles remain exempt until they change.

Accept only when the visible `figcaption` matches the intent ledger and explains
the result or consequence in enough plain prose to make the figure useful on its
own. The result must also be legible at the real documentation size, and tracked
sources must reproduce it without hidden interactive state.
