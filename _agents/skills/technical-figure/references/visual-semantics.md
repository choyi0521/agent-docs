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

Classify each intent-ledger element with exactly one of these roles:

| Role | Use for |
| --- | --- |
| `subject` | The concrete entity followed, transformed, or compared |
| `action` | A visible operation that changes or moves the subject |
| `relationship` | A typed dependency, association, or comparison |
| `constraint` | A rule, condition, gate, or limit |
| `state` | A current, prior, partial, absent, planned, accepted, or failed condition |
| `boundary` | Real ownership, scope, isolation, containment, or spatial extent |
| `quantity` | A measured count, length, proportion, capacity, or magnitude |
| `sequence` | Order, lifetime, phase, or concurrency |
| `evidence` | A source-backed annotation attached to the fact it qualifies |
| `accessibility` | Intentional redundant encoding that makes another fact perceivable |
| `context` | Necessary orientation that is not the primary claim |

Classify a terminal outcome by the fact it presents, usually `state` or
`relationship`. Do not create visual-role synonyms such as `node`, `box`,
`arrow`, or `outcome`; those name marks or positions, not meaning.

Every ledger element must explain `whyThisEncoding` instead of merely naming
the mark. Every `action` and `relationship` must carry one exact verb. Use a
different element or connector class when the verb changes.

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

- Use one visual channel for one meaning within a figure. Do not reuse dashed
  lines for both optional behavior and async calls.
- Name each connector class with one verb or relation in the intent ledger:
  `imports`, `owns`, `publishes`, `calls`, `transforms`, or `rejects`.
- Let arrow direction describe the recorded relation, not merely reading order.
- Separate dependency, execution order, data movement, and state transition.
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

Layer comprehension by time: within three seconds expose the subject and
takeaway; within ten seconds let the reader follow one representative action or
contrast; within thirty seconds reveal exceptions, evidence, and status limits.
Do not make the first layer depend on reading the third.

Use whitespace to separate stages and reduce competition. Keep legends small
and local; prefer self-explaining encodings. Keep titles and captions outside
the mechanism. Put exact identifiers in secondary labels, not in the primary
silhouette. Split a poster into an overview and focused views when its smallest
meaningful label cannot be read at the host article width.

Typography belongs to the host page, not to an isolated drawing canvas. At the
final rendered article size, use the surrounding body text as the ordinary
label size. A normal technical
figure has one ordinary label size and, when hierarchy needs it, one restrained
emphasis size. Avoid a staircase of title, section, label, detail, and tiny
styles; it makes the drawing feel like a miniature poster and forces readers to
zoom. More than two visible sizes needs a source-backed semantic reason recorded
in the intent ledger. No visible label may become footnote-sized merely because
the source canvas is wide.

The visible drawing contains short identifiers and local action words. Put the
page heading, figure title, conclusion, explanation, and long legend in normal
HTML prose or the caption. This does not remove the SVG's non-visible accessible
`<title>` and `<desc>`. If labels do not fit at body-like size, reduce the number
of facts, split the figure, or move lookup detail to a table.

Author the coordinate canvas close to the actual host width. When a wider view
is essential, preserve its authored scale with a deliberate horizontal-scroll
container and provide a readable overview or caption; do not silently fit a
wide poster into a substantially narrower article column. Verify computed text
sizes on the rendered host page because SVG `viewBox` scaling changes every
authored font size. When the host cannot be measured during authoring, use only
a neutral preview fallback and re-check against the actual host before
acceptance.

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
an independent reviewer. Record only a non-identifying reviewer label. Accept
only when the recovered claim, subject, action, constraint, and status match
the ledger. Manually verify that every visible
logical element has an intent entry; declared SVG ids prove presence, not
complete coverage, and a raster image cannot expose an exhaustive
machine-checkable id map.
