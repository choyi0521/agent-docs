<!-- Generated from _agents/skills/docs-authoring/references/plans.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Plans

Use a titled `:::plan <title>` container when an explanatory, lookup, or
non-procedural maintainer page owns intended public behavior that is not fully
implemented. A Plan is a local projection of intent, not a root section,
release promise, work log, or progress tracker.

The audit configuration declares which section roles permit Plans and supplies
the stable anchor prefix.

## Format

```markdown
:::plan Publish the result
### Complete the public path {#<configured-prefix>complete-path}

**Current:** <implemented cutoff or exact missing connection>

- [ ] <concrete implementation step>
- [ ] <another implementation step>

**Done when:** <observable result or executable acceptance test>
:::
```

Every Plan needs a meaningful plain-text title. Each H3 goal requires exactly
one `Current`, one or more unchecked steps, and exactly one `Done when`.
`Source`, `Depends on`, `Decision`, and `Out of scope` are optional and may each
appear once. A `Source` field contains an accessible link.

Keep implemented behavior outside the Plan and only the remaining target
inside it. Do not retain completed checklist items. When the goal is complete,
update current prose and remove the goal. Remove an empty Plan.

Do not put a current-source snippet, runnable unavailable command, numbered
procedure, or current lookup table inside a Plan. Never use Plans for private
roadmaps, assignments, dates, percentages, or unpublished commitments.

Keep each anchor unique in the documentation root and do not rename an anchor
after another page links to it. Count parsed Plan blocks rather than maintaining
parallel status fields or registries.
