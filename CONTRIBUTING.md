# Contributing

Agent Docs accepts changes that improve generic documentation authoring,
research evidence management, validation, rendering, and the reader experience. Keep examples and terminology
independent of any private product or organization.

## Before starting

- Open an issue before a large API, format, or output-schema change.
- Confirm that you have the right to contribute every source, example, image,
  and dataset in the change.
- Do not copy private documentation, internal deployment procedures, customer
  data, credentials, or machine-specific configuration into the repository.
- The project does not yet carry an open-source license. Discuss substantial
  contributions with the maintainers until licensing and contribution terms
  have been selected.

## Development setup

Install .NET SDK 10, Python 3.11 or newer, and Node.js 20 or newer. From a
clean checkout, run the public-boundary gate before dependency restore creates
ignored output. The verification sequence below is ordered accordingly.

Canonical agent workflow sources live under `_agents/`. Do not edit generated
files under `.agents/`, `.claude/`, or generated root instruction files by
themselves.

## Verification

Run the following from the repository root:

```powershell
python -B -m unittest discover -s tools/tests -p "test_*agent_instructions.py" -v
python -B -m unittest discover -s tools/tests -p "test_check_public_boundary.py" -v
python -B tools/check_public_boundary.py
python -B -m unittest discover -s _agents/skills/docs-authoring/scripts -p "test_*.py" -v
python -B -m unittest discover -s _agents/skills/technical-figure/scripts -p "test_*.py" -v
python -B -m unittest discover -s _agents/skills/research-corpus/scripts/tests -p "test_*.py" -v
python -B _agents/skills/technical-figure/scripts/audit_figures.py `
  --repo-root . --bundle docs/_assets/figures/document-flow `
  --article-width-px 704
python -B _agents/skills/docs-authoring/scripts/audit_docs.py `
  --config docs-audit.json --repo-root . --check
python -B tools/sync_agent_instructions.py --check
python -B tools/check_agent_instructions.py

dotnet restore AgentDocs.slnx
dotnet build AgentDocs.slnx --configuration Release --no-restore
dotnet test AgentDocs.slnx --configuration Release --no-build
dotnet run --project src/AgentDocs.Cli --configuration Release --no-build -- `
  render --repo . --config agent-docs.json --out build --check

npm ci --prefix styles
npm run build --prefix styles
npm test --prefix styles
git diff --exit-code -- web/app.css web/prism.js
```

The public-boundary check must run before build commands create ignored output
directories. Use a clean candidate checkout for later publication checks;
do not delete another contributor's ignored output to make the gate pass.

Research tests must use synthetic corpora and disposable directories outside
the repository. Test a complete copied skill package from another working
directory; imports, schema paths, and local Git status must not depend on
this checkout. Keep network acquisition out of the default offline suite.
When exercising a real download, use an explicitly approved public host and
immutable commit, an external cache, and do not run the downloaded code.

The source tool deliberately has no pin, sync, prune, or repair operation.
Do not add destructive source lifecycle behavior without its own design,
ownership, concurrency, filesystem, and isolated Git configuration tests.

## Documentation changes

- Write for one reader question at a time.
- Keep task-oriented guides, explanatory concepts, lookup reference, and
  contributor development material distinct.
- Update `_index.md` navigation whenever a page is added, moved, or removed.
- Use source-backed snippets instead of retyping executable examples.
- Keep figures reproducible and record the source and licensing of incorporated
  material.
- Inspect the rendered page at wide and narrow viewports; a green structural
  check does not prove that prose or figures communicate correctly.

## Pull requests

Keep each pull request focused. Describe the reader or API outcome, list the
verification commands run, and disclose any check that could not be completed.
Do not include generated build output, dependency directories, or unrelated
formatting changes.
