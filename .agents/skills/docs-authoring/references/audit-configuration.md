<!-- Generated from _agents/skills/docs-authoring/references/audit-configuration.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Audit configuration

The auditor reads one JSON file and has no built-in product, language, build
system, or repository layout. Resolve all configured paths relative to the
repository root and keep them inside it.

```json
{
  "docs_root": "documentation",
  "index_file": "_index.md",
  "sections": [
    {"path": "tasks", "role": "guide", "allow_plans": false},
    {"path": "models", "role": "concept", "allow_plans": true},
    {"path": "catalog", "role": "reference", "allow_plans": true, "require_references": true},
    {"path": "maintenance", "role": "development", "allow_plans": true}
  ],
  "asset_roots": ["_assets"],
  "retired_roots": ["old-docs"],
  "plan_anchor_prefix": "plan-public-",
  "source_roots": [
    {"id": "library", "path": "src", "code_route": "/code/library/"}
  ],
  "evidence_rules": [
    {"role": "Tests", "patterns": ["**/tests/**", "**/*_test.*"]},
    {"role": "Build", "patterns": ["pyproject.toml", "package.json"]}
  ],
  "build_commands": [
    {"name": "render", "cwd": ".", "argv": ["python", "tools/render_docs.py", "--check"]}
  ]
}
```

## Fields

- `docs_root` is required and points to the rendered Markdown tree.
- `repo_root` may point from the configuration file to its repository. Prefer
  the explicit `--repo-root` CLI argument in automation.
- `index_file` defaults to `_index.md`.
- `sections` is an ordered nonempty list. Each entry has a relative `path`, a
  reader `role`, and optional `allow_plans` and `require_references` flags. Both
  flags default to `false` when omitted. A false `require_references` value only
  means the section does not require References by itself; snippets and linked
  evidence can still require a final References section.
- `asset_roots` lists allowed non-section directories under the documentation
  root.
- `retired_roots` lists directories that must not contain files.
- `plan_anchor_prefix` is required, ends with `-`, and contains lowercase ASCII
  letters, digits, and hyphens.
- `source_roots` contains unique ids, safe repository-relative paths, and an
  optional absolute site route ending with `/`.
- `evidence_rules` classifies source-root-relative paths by configured glob.
  The first matching rule wins; unmatched files are `Source`.
- `build_commands` contains unique names, safe repository-relative working
  directories, and nonempty argv arrays. Commands run without a shell and only
  when `--run-build` is passed.

Use `--build-command <name>` to select configured build commands. Without a
selector, `--run-build` runs all configured commands in order and stops only
after recording each result. Every command receives the positive timeout from
`--build-timeout-seconds`; the default is 300 seconds. A timeout records only
the command name and limit, not potentially sensitive process output.

The auditor fails configuration that escapes the repository, duplicates ids or
sections, uses ambiguous routes, or supplies unsupported evidence roles.
