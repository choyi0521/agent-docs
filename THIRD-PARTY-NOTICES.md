# Third-party notices

This notice identifies components that are incorporated into generated output
or named as direct dependencies in project manifests. It is not an exhaustive
software bill of materials for transitive development dependencies. Project
manifests are authoritative for direct versions, the npm lock file records its
resolved graph, and NuGet restore determines the transitive .NET graph.

| Component | Version | Scope | License and notice | Upstream |
|---|---:|---|---|---|
| Markdig | 0.37.0 | Runtime Markdown rendering | [BSD-2-Clause](third_party_licenses/Markdig-BSD-2-Clause.txt) | <https://github.com/xoofx/markdig> |
| Tailwind CSS | 3.4.17 | Build-time stylesheet generation; generated Preflight CSS is distributed | [Tailwind MIT](third_party_licenses/Tailwind-CSS-MIT.txt) and [Preflight MIT](third_party_licenses/Tailwind-Preflight-MIT.txt) | <https://tailwindcss.com/> |
| jsdom | 26.1.0 | Test-only browser emulation; not part of generated sites | MIT | <https://github.com/jsdom/jsdom> |
| xunit.v3.mtp-v2 | 3.2.2 | Test-only package; not part of generated sites | Apache-2.0 | <https://github.com/xunit/xunit> |

The xUnit adapter restores Microsoft.Testing.Platform 2.0.2 (MIT). NuGet and
npm restore additional transitive test and build packages recorded in their
resolved dependency graphs. Those package contents are not committed to this
repository or copied into generated documentation sites.

Dependency licenses apply to those components only and do not grant a license
to the Agent Docs project itself.
