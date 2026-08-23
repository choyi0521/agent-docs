---
name: docs-authoring
description: Author, revise, reorganize, review, or audit public product and developer documentation. Use for task guides, conceptual explanations, API or behavior reference, maintainer documentation, documentation indexes and navigation, current-versus-planned behavior, source-backed snippets and citations, or configurable Markdown documentation validation.
---
<!-- Generated from _agents/skills/docs-authoring/SKILL.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->

# Author product documentation

Write for a reader who should not need repository or organizational knowledge
to understand the published product. Keep the workflow repository-neutral. Read
the documentation project's audit configuration before assuming paths, section
names, source roots, link routes, or validation commands.

Read [voice and style](references/voice-and-style.md) for every task. Then read
the reference that matches the reader's need:

| Reader need | Documentation form | Rules |
|---|---|---|
| Complete a supported task | Guide | [guides.md](references/guides.md) |
| Understand a mechanism or trade-off | Concept | [concepts.md](references/concepts.md) |
| Look up an exact surface or limit | Reference | [reference.md](references/reference.md) |
| Change or maintain the repository | Development | [development.md](references/development.md) |

Read [navigation.md](references/navigation.md) for indexes or any add, move,
split, merge, rename, or deletion. Read [plans.md](references/plans.md) whenever
intended behavior appears. Read [source-snippets.md](references/source-snippets.md)
and [citations-and-references.md](references/citations-and-references.md) when a
page relies on source, tests, standards, or external authorities.

## Workflow

1. Define one reader question, the intended reader, and the page that should
   own the answer.
2. Inspect published contracts, implementation, build or package registration,
   focused tests, and observable behavior relevant to the claim.
3. Separate available, partial, absent, and intended behavior. Never infer the
   whole product from one directory or a passing test.
4. Choose the documentation form from the reader's need. Outline in task,
   causal, lifecycle, or lookup order rather than discovery order.
5. Explain observable behavior in prose. Use the smallest source, command,
   example, table, or figure that materially supports the explanation.
6. Reconcile navigation, links, neighboring owners, snippets, references, and
   figures affected by the change. Remove duplicate authorities.
7. Run the configured audit and build commands, inspect rendered output, and
   report any claim or gate that could not be verified.

## Public boundary

- Publish only facts, paths, links, examples, and source regions that are meant
  for the public repository.
- Never copy secrets, credential values, private endpoints, customer data,
  unpublished product plans, private provider payloads, work logs, assignments,
  or internal-only ownership records.
- Replace sensitive values with explicit neutral placeholders. Do not disguise
  private product content by renaming it.
- Verify that every authored link is accessible to the intended reader.
- Treat source and tests as evidence, not automatic public navigation.

## Figures

Use a technical figure only when it removes material mental reconstruction of
sequence, state, ownership, dependency, spatial layout, or a current-versus-
intended distinction. Follow the
[`technical-figure`](../../../_agents/skills/technical-figure/SKILL.md) workflow and its
[`visual-semantics`](../../../_agents/skills/technical-figure/references/visual-semantics.md)
contract. Preserve an editable source, exact rebuild command, accessible text
alternative, and rendered inspection step.

Run the figure audit for every new or changed figure bundle:

```text
python -B _agents/skills/technical-figure/scripts/audit_figures.py --repo-root . --bundle <figure-directory>
```

## Audit configuration

Read [audit configuration](references/audit-configuration.md) before adding or
changing the audit file. The configuration owns repository-relative document
and source roots, section roles and order, Plan anchor prefix, code routes,
evidence classification patterns, and optional build commands.

Run the auditor from any working directory with explicit inputs:

```text
python <skill-dir>/scripts/audit_docs.py --config <config.json> --repo-root <repository> --check
```

Use `--review` to emit qualitative prompts. Use `--run-build` only when the
configured commands are trusted and the task authorizes their effects. Each
build command has a 300-second timeout by default; set a positive
`--build-timeout-seconds` value when a verified command needs a different
limit. Limit a review to named Markdown files by passing them after the options.

Run the skill's regression tests after changing its rules:

```text
python -B -m unittest discover -s <skill-dir>/scripts -p "test_*.py" -v
```

A successful structural audit or documentation build does not prove semantic
accuracy. Run every command presented as executable and test changed source
snippets through their owning project.
