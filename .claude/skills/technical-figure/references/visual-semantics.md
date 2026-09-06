<!-- Generated from _agents/skills/technical-figure/references/visual-semantics.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Visual semantics

Use this reference to decide what a figure should look like before choosing a
drawing tool. The visual form must expose the mechanism; it must not merely
hold labels.

## Contents

- [Core grammar](#core-grammar)
- [Assign logical roles](#assign-logical-roles)
- [Match form to truth](#match-form-to-truth)
- [Encode relationships](#encode-relationships)
- [Expose status and absence](#expose-status-and-absence)
- [Establish hierarchy](#establish-hierarchy)
- [Avoid mental reconstruction](#avoid-mental-reconstruction)

## Core grammar

Prefer the most direct channel that truthfully expresses a fact:

1. a form that behaves like the domain concept;
2. spatial relationship such as order, containment, alignment, or separation;
3. a consistent shape, connector, or texture convention;
4. redundant color;
5. exact text labels.

Text should identify a thing, value, or action. It should not be responsible
for making an otherwise generic shape meaningful. A queue labelled `Queue` is
still only a box; occupied ordered slots make queueing visible.

Do not add realistic or varied shapes indiscriminately. Use a domain-like form
only when its geometry makes the claimed behavior easier to decode. Prefer an
unadorned abstraction to a metaphor the reader must learn.

## Assign logical roles

Name each intent-ledger role by the fact that the element contributes to the
claim. The vocabulary is open because different domains expose different
facts. A role must describe semantic purpose rather than repeat the name of the
drawing primitive used to render it.

Every ledger element must explain `whyThisEncoding` instead of merely naming
the mark. Every connector class and visible transition must carry one
unambiguous relation. Use a different element or connector class when that
relation changes.

## Match form to truth

| Truth | Prefer | Avoid |
| --- | --- | --- |
| Dependency or graph topology | Nodes and typed edges | Flow direction implied only by page order |
| Ownership, scope, or isolation | Containment, enclosure, or separated regions | Decorative group boxes |
| Time, lifetime, or concurrency | Timeline, aligned lanes, overlapping intervals | Unordered component row |
| State transition | The same subject in aligned before/after states | Different boxes that hide identity |
| Transformation | A recognizable input, visible operation, and changed output | A box named after the operation |
| Queue, stack, or buffer | Slots, occupancy, order, and the operation being discussed | A container labelled with the data-structure name |
| Validation or authority | Gate, accepted and refused outcomes, retained prior state | A generic arrow labelled `validate` |
| Coordinate or spatial rule | Actual axes, frame, volume, ray, region, or measured relation | Prose describing space inside boxes |
| Coverage or lookup comparison | Matrix, aligned small multiples, or table | Dense cross-linked graph |
| Quantity or proportion | A common quantitative scale | Arbitrary size used only for emphasis |
| Reversal or unwind | One ordered structure read in the opposite direction | A second unrelated list |
| Branch or choice | One path that visibly splits at its cause | Parallel boxes with unexplained arrows |

If readers primarily need exact values or compare many cells, use a table. If
they need only a definition, use prose. Use a figure when spatial encoding
removes work the reader would otherwise perform mentally.

## Encode relationships

- Use one visual channel for one meaning within a figure. Do not reuse the same
  styling for relations that mean different things.
- Name each connector class with its relation in the intent ledger.
- Let arrow direction describe the recorded relation, not merely reading order.
- Separate relations whose direction, timing, ownership, or effect differs.
- Make crossings rare. If crossings carry meaning, expose their junction or
  non-junction explicitly; otherwise recompose.
- Use an enclosing boundary only for actual ownership, scope, containment,
  isolation, or space. Name that boundary in the ledger.
- Use alignment for comparison or shared phase. Do not align unrelated items
  merely for symmetry.
- Use distance or empty space to express separation only when that separation
  is intentional and recorded.
- Use repetition to encode count, stages, or equivalence. Do not repeat motifs
  to fill space.
- Use size quantitatively only with a common scale. Otherwise keep peers equal
  and establish emphasis through hierarchy.

## Expose status and absence

Prefer structural status cues over a color-only legend:

- **Current:** draw the actual subject and continuous path with its normal
  boundary.
- **Partial:** draw the supported path up to the exact seam, then show an
  explicit limit or stop.
- **Absent:** show a meaningful gap, empty slot, open socket, or terminal marker;
  do not invent internal components.
- **Planned:** separate the plan spatially from current behavior. If it must be
  shown, use a labelled outline without a detailed phantom execution path.
- **Rejected or failed:** preserve the prior state and show a distinct refusal
  exit or terminal outcome rather than recoloring a success path.

Encode status redundantly with structure or line style plus text. Color may
reinforce status but cannot carry it alone. Never make planned behavior more
concrete or visually dominant than implemented behavior.

## Establish hierarchy

Treat the composition as one visual sentence:

- `subject`: the first focal point;
- `action` or `relationship`: the dominant visual change or path;
- `constraint`: the second focal point;
- `state` or `relationship`: a clear terminal outcome;
- `context`: lower-contrast support;
- `evidence`: adjacent to the fact it qualifies.

Layer comprehension so the first read exposes the subject and takeaway, the
next read exposes the representative relation or contrast, and deeper inspection
reveals exceptions, evidence, and status limits. Do not make an earlier layer
depend on a later one.

Use whitespace to separate stages and reduce competition. Keep legends small
and local; prefer self-explaining encodings. Keep titles and captions outside
the mechanism. Put exact identifiers in secondary labels, not in the primary
silhouette. Split a poster into an overview and focused views when its smallest
meaningful label cannot be read at the host article width.

Typography belongs to the host page, not to an isolated drawing canvas. At the
final rendered article size, compare labels with the surrounding body text and
make every distinct typographic treatment serve a clear part of the hierarchy.
Avoid decorative variation that competes with the mechanism or forces readers
to zoom.

Visible labels should resolve the local identity or relationship at their mark.
Put explanation that applies to the whole figure in normal HTML prose or the
`figcaption`. This does not remove the SVG's non-visible accessible `<title>`
and `<desc>`. If unambiguous labels do not fit at a readable host size, reduce
the number of facts, split the figure, or move lookup detail to a table.

Write `figcaption` in the same language as the host page. It must explain the
result or consequence that the geometry exposes, in enough plain prose to make
the figure useful when encountered on its own. Do not reduce it to a category
name or status tag. Use as many sentences as the meaning needs, and revise by
reader comprehension rather than by a word or sentence quota. Keep the ledger's
`caption` text and the visible `figcaption` identical so review and published
meaning cannot drift.

Author the coordinate canvas close to the actual host width. When a wider view
is essential, preserve its authored scale with a deliberate horizontal-scroll
container and provide a readable overview or caption; do not silently shrink a
wide composition until its labels are difficult to read. Verify the result on
the rendered host page because SVG `viewBox` scaling changes authored text.

At narrow width, preserve the takeaway before requiring horizontal panning. A
scrollable detail view is acceptable only when a visible overview or caption
already gives the relation and conclusion.

## Avoid mental reconstruction

Reject these compositions:

- a row of nouns whose relationships exist only in nearby prose;
- interchangeable rectangles joined by untyped arrows;
- paragraphs inside nodes that readers must summarize for themselves;
- a pipeline assembled from independently exercised systems;
- a detailed future path that does not exist in the current product;
- color, shadows, icons, or repeated ornaments without a semantic role;
- a polished 3D render whose camera hides the relevant spatial relation;
- a wall-sized graph reduced until labels become footnotes;
- a diagram that becomes truthful only after reading a qualification below it.

When a label-free sketch fails, do not solve it by adding labels. Change the
spatial model. When a figure needs a long legend, simplify or split it. When a
table expresses the truth more directly, use the table.

A structural audit cannot judge these failures. For every new or changed
figure, give the rendered asset without its caption, prose, or intent ledger to
a fresh reviewer. Record only a non-identifying reviewer label and public-safe
review text. Ask for an explanation in the reviewer's own words without
supplying the intended semantic categories. Accept only when that recovered
reading agrees with the applicable parts of the ledger. Manually verify that
every visible logical element has an intent entry; declared SVG ids prove
presence, not complete coverage, and a raster image cannot expose an exhaustive
machine-checkable id map.
