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
- the preview server binds to loopback by default and exposes no anonymous
  write API;
- the public-boundary check examines authored and generated repository files.

Run `python -B tools/check_public_boundary.py` before publishing a tree. Treat
any credential committed to version control as compromised even if a later
commit removes it; revoke it and follow the hosting provider's history-cleanup
procedure.

## Deployment

This repository does not define or authorize a production deployment. Operators
are responsible for TLS termination, authentication where needed, content
security policy, request limits, dependency patching, and access logging in
their own environment.
