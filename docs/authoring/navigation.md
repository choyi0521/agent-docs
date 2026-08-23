# Navigation and links

Every populated directory has an `_index.md` landing page. Its `nav` front
matter lists every sibling page and child directory in reading order. Use a
trailing slash for a directory so the distinction remains visible to readers
of the source:

```yaml
---
nav:
  - overview.md
  - concepts/
---
```

In a curated space, the list must include every navigable neighbor exactly
once. Adding, moving, or deleting a page therefore requires an intentional
navigation change. The build reports an unlisted document, a missing target,
or a duplicate entry instead of choosing an implicit order.

The root index lists the configured sections in their declared order. A
section index orders the pages within that reader need. Nested indexes apply
the same rule to their own children.

## Links {#links}

Write links as ordinary relative Markdown links:

```markdown
[Read the extensions](extensions.md#figures)
```

The gate resolves both the document and the fragment. A renamed heading can
therefore break a build even when the target file still exists. Pin a durable
fragment when a heading is likely to change:

```markdown
## Stable concept name {#stable-concept}
```

After changing a page, its index, or a heading, run the checked render from the
[build guide](/guides/getting-started#render-with-content-gates).

Return to the [published boundary](/#published-boundary).
