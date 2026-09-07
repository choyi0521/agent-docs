<!-- Generated from _agents/skills/research-corpus/references/sources.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Source identity and local acquisition

## Register a source

Use one reviewed JSON manifest per `catalog/<source-id>.json`. Both record
validation and source acquisition use the same catalog parser. Identity
validation is separate from network permission: a valid manifest does not
authorize a download.

Start from [source-example.json](../assets/source-example.json), saved as
`catalog/source-example.json`, and replace the illustrative identity with the
source actually inspected. Rename the file and `id` together. The sample URL
and commit are not a downloadable source; `NOASSERTION` grants no rights.
Required fields are `schema` (integer `2`), `id`, `name`, `kind`, `revision`,
`license`, `access`, `topics`, `notes`, and `retrieved_at` (an ISO 8601
timestamp with an offset).
`url` is required except for `local-repository`, which must omit it.
`revision_label` is optional. Git repositories require
`tracking: {"kind": "git-ref", "ref": "refs/heads/main"}` (use the source's
actual ref); local repositories require `tracking: {"kind": "local-head"}`.
Other source kinds can omit tracking or declare manual tracking with a note.
Unknown fields are rejected.

Sources can describe Git repositories, local repositories, publications, web
pages, datasets, or artifacts. Git revisions use complete lowercase
40-character commit IDs; non-Git revisions use `sha256:` plus 64 lowercase
hexadecimal digits. A moving branch, version label, or URL alone is not an
immutable revision. Record license, access, retrieval date, and the artifact
whose bytes the digest identifies. A digest is useful only if those exact
bytes remain inspectable.

Tracking is separate from the pin. Updating a catalog pin does not rewrite
record citations. Acquisition supports only public HTTPS Git sources; other
kinds can be cataloged and cited but are obtained manually within the user's
authorization. Do not put tokens, credentials, private URLs, or confidential
source metadata into a public catalog.

## Commands

Global options precede the command:

```text
python -B <skill>/scripts/sources.py --corpus <corpus> list
python -B <skill>/scripts/sources.py --corpus <corpus> verify
python -B <skill>/scripts/sources.py --corpus <corpus> --cache-root <external-cache> status <source-id>
python -B <skill>/scripts/sources.py --corpus <corpus> --cache-root <external-cache> --allow-host <approved-host> fetch <source-id>
```

`list` and `verify` inspect catalog metadata only. `status` checks local cache
bytes without contacting an upstream or rewriting a manifest. `fetch`
requires an explicit cache root and approved hostname, and obtains one exact
public revision. An allow-host option is a network boundary, not a license
or a statement that the host's contents are trustworthy.

The resulting source tree is at
`<cache>/sources/<source-id>/<full-commit>/tree`. Search it with `rg` and cite
paths relative to that tree. Do not edit it, build it, install dependencies
from it, or add it to the consumer's product build. Keep experiments in a
separate workspace and label them as experiments, not upstream evidence.

## What acquisition guarantees

The tool uses isolated Git configuration and environment, a fresh staging
repository, an exact commit, and Git tree/blob bytes. It does not use a
checkout or `git archive`, so filters, hooks, export substitutions, and
export-ignore rules do not silently change evidence. It does not follow
submodules, run Git LFS, fetch authenticated sources, or permit redirects to
another acquisition endpoint.

Only supported regular-file trees are materialized. Unsupported entries,
unsafe paths, resource-limit excesses, and origin/revision mismatches fail
explicitly. Existing cache entries are verified rather than reset or
overwritten. Source locks coordinate tool processes; staging is published
only after verification. A failed or modified cache is not silently repaired.

Acquisition is bounded to 20,000 entries, 64 MiB per file, and 512 MiB of
source bytes. Staging is sampled against a 1 GiB limit; each Git command has a
120-second limit within a 600-second session. These are refusal limits, not
promises that arbitrary upstream repositories fit. The proof retains Git
file modes, but exported reader files do not preserve executable permission.

These checks assume a trusted local filesystem and tool installation. They
are not a sandbox against an adversarial local process changing files during
inspection, a compromised Git executable, or a hostile network endpoint
exhausting resources inside Git. Do not describe a local verification result
as a cryptographic signature from the upstream author.

## Refusal and recovery

If an exact revision is unavailable, do not substitute the branch tip. Ask
for a corrected pin or another authorized artifact. If a cache entry fails
verification, preserve it and use a new explicitly selected cache directory
or ask the user how to handle it. Do not remove locks or delete directories
owned by another process on a timer.

There are no `pin`, `sync`, `prune`, or repair commands. Revise a manifest as a
reviewable authored change after source inspection. Do not introduce
destructive cleanup or shared mirror/worktree management to complete a
research task. Downloaded source retains its own notices and license;
acquisition never opts those bytes into publication.
