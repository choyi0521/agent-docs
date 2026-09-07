# Canonical agent guidance

This directory is the source of truth for the repository's agent instructions
and reusable documentation and research skills. Agent discovery files at the repository
root and under vendor directories are deterministic generated copies.

## Layout

- [`instructions/repository.md`](instructions/repository.md) contains the
  repository-wide working agreement.
- `skills/<id>/` contains one complete, vendor-neutral skill package. Every
  package has a `SKILL.md` and an `interface.json`.
- [`generation.json`](generation.json) explicitly maps canonical instruction
  and skill IDs to their generated discovery paths.
- [`publication.json`](publication.json) explicitly selects which configured
  IDs are part of the documented public surface.

No manifest discovers a directory recursively. Adding a package does nothing
until its ID and exact source path are reviewed and added to both manifests.

## Generated surfaces

Run these commands from the repository root:

```text
python -B tools/sync_agent_instructions.py --write
python -B tools/sync_agent_instructions.py --check
python -B tools/check_agent_instructions.py
```

The generator copies complete packages to `.agents/skills/` for Codex and
`.claude/skills/` for Claude. It renders Codex interface metadata from each
canonical `interface.json`; the neutral interface file itself is not copied.
Relative Markdown links are rebased and every generated Markdown file carries
a provenance notice.

Edit only canonical files under `_agents/`. Never patch `AGENTS.md`,
`CLAUDE.md`, `.agents/`, or `.claude/` directly.

## Public boundary

Everything committed to this repository is public, whether or not it appears
in `publication.json`. Canonical packages must therefore contain only reusable
documentation and research workflows and public examples. Do not add credentials, private
keys, machine-specific user paths, private service addresses, confidential
material, application source, deployment data, or generated caches.

The `research-corpus` package is self-contained: its generated copy includes
the record/index tools, bounded source acquisition, schemas, and workflow
references. Consumer catalogs, research findings, downloaded source, and local
indexes do not belong in this toolkit's packages. Installing the package does
not opt those inputs into reader publication.

The schemas at
[`schemas/agent-generation.schema.json`](../schemas/agent-generation.schema.json)
and
[`schemas/agent-publication.schema.json`](../schemas/agent-publication.schema.json)
document the manifest format. The Python loader enforces the same format
without requiring a third-party schema package.
