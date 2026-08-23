# Security policy

## Supported version

Security fixes are applied to the current `main` branch. Until versioned
releases exist, older commits are not maintained separately.

## Reporting a vulnerability

Use the repository's private security-advisory form in the hosting service's
Security tab. Do not open a public issue for an unpatched vulnerability and do
not include live credentials, private documents, or personal data in a report.

Include:

- the affected command, configuration field, or authored construct;
- a minimal neutral reproduction;
- the security impact and affected platforms;
- any proposed mitigation, if known.

Maintainers will acknowledge a complete report, reproduce it in an isolated
fixture, and coordinate disclosure after a fix is available.

## Security model

Agent Docs is a build tool for repository content trusted by the site owner.
Authored Markdown and figure fragments are not an isolation boundary for
hostile input. Review contributions before rendering or hosting them.

Security-sensitive guarantees include:

- configured source, documentation, and output paths remain inside their
  permitted roots;
- snippet and figure reads do not follow symlinks or junctions;
- generated-output cleanup refuses repository, source, documentation, and other
  unsafe targets;
- the reserved repository-root `.agent-docs/` subtree is Git-ignored local
  state and is hard-excluded from rendering, source publication, snippets,
  browsable root files, and agent-workflow inputs;
- the preview server binds only to loopback; its review endpoint is an
  unauthenticated local write API for repository-local authoring state;
- the public-boundary check examines authored and generated repository files.

Run the review-enabled preview only on a trusted local workstation. Any local
process that can connect to the loopback port can submit a review write, so the
endpoint is not an authorization boundary between users or processes on the
same operating system. Requiring JSON, checking a matching `Origin` when one is
present, rejecting cross-site fetch metadata, and omitting CORS protect against
ordinary browser cross-site request forgery; they do not authenticate a local
client or protect against another process on the same operating system. Stop
the preview when review work is finished, and never expose it through a proxy,
port forward, shared host, or production deployment. Static `render` output
contains neither review data nor the writable review API.

Review files may exist only beneath `.agent-docs/`. The preview and the
docs-authoring helper serialize writes with a persistent sibling operating-
system lock, retrying every 50 milliseconds for at most 5 seconds. The lock's
exact UTF-8 content is `agent-docs-review-lock-v1` followed by one LF byte and
it remains in place after release; do not remove it as stale state.

Run `python -B tools/check_public_boundary.py` before publishing a tree. Treat
any credential committed to version control as compromised even if a later
commit removes it; revoke it and follow the hosting provider's history-cleanup
procedure.

## Deployment

This repository does not define or authorize a production deployment. Operators
are responsible for TLS termination, authentication where needed, content
security policy, request limits, dependency patching, and access logging in
their own environment.
