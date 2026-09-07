# Repository instructions

This repository publishes reusable tools and agent guidance for technical
documentation, technical figures, and evidence-backed research. Keep every
change within that public, product-neutral scope.

## Source of truth

- Read [`../README.md`](../README.md) before changing an agent surface.
- Author skills only in their canonical packages under `_agents/skills/`.
- Treat `AGENTS.md`, `CLAUDE.md`, `.agents/`, and `.claude/` as generated files.
- Keep generation and publication IDs explicit; never introduce recursive
  package discovery.

## Change workflow

1. Change the smallest canonical instruction or skill package that owns the
   behavior.
2. Keep examples generic and safe for an unrestricted public repository.
3. Run `python -B tools/sync_agent_instructions.py --write`.
4. Run the agent-instruction unit tests, followed by
   `python -B tools/sync_agent_instructions.py --check` and
   `python -B tools/check_agent_instructions.py`.
5. Inspect generated changes and confirm that only the declared discovery
   files changed.

Do not add application code, organization-specific terminology, credentials,
private infrastructure, absolute user paths, or deployment instructions. A
publication allowlist controls the rendered documentation view; it does not
make any committed source private.

## Research boundary

Keep reusable research scripts, schemas, and synthetic examples in the
`research-corpus` package. Do not import another project's catalog, findings,
downloaded source trees, or indexes. Test acquisition and indexing in an
isolated workspace outside this repository; the public-boundary check also
inspects ignored files.

Source manifests and authored records are canonical. Downloaded code and
search indexes are local, reproducible data, never automatic publication
inputs or product dependencies. Preserve immutable source revisions and
distinguish observed evidence from interpretation and recommendations.
