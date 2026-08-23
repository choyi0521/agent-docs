# Citations and references

Place evidence beside the claim that needs it. End an evidence-bearing leaf
page with one final `## References` section so readers can open complete source
files and primary authorities without rediscovering them.

## Section shape

```markdown
## References

- **Source:** [complete production-file link]
- **Tests:** [focused test-file link]
- **Build:** [owning build or package-file link]
- **Project authorities:** [published project contract]
- **External sources:** [official standard or vendor documentation]
```

Omit empty categories. Repeat a labeled row when that is clearer than joining
unrelated files. Every link must be accessible to the intended public reader.

- **Source** lists complete production files substantially explained by the
  page.
- **Tests** lists focused executable evidence and never substitutes for Source.
- **Build** lists build or package files only when inclusion supports a claim.
- **Project authorities** lists published normative contracts, not private
  ownership records or general related reading.
- **External sources** lists official standards, specifications, or vendor
  documentation actually used. Pin a version when the claim depends on it.

Use the configured code route for files under a source root. If no route exists,
use a repository-relative link that the public renderer supports. Link the
complete file without a line fragment in `References`; keep exact inline line
links beside claims when they add value.

Every inline external source must also appear under `External sources`, and
every final external source must be cited inline. Do not list search results,
unrelated neighboring pages, or every file inspected during discovery. Never
invent Source for an absent implementation.
