# Source snippets

A `snippet` fence lifts one named source region configured for public use. Use
it when an exact declaration, executable example, or compact transition
materially supports a claim. Use an ordinary code fence for illustrative code.

## Mark a region

Use exact whole-line markers within the source language's normal comment form:

```text
# docs:begin create-item
source lines
# docs:end create-item
```

The id is case-sensitive and contains ASCII letters, digits, underscores, or
hyphens. A referenced id has exactly one begin marker followed by one end
marker. Keep regions small and compilable. Never include secrets, credentials,
private endpoints, generated output, customer data, private provider payloads,
or unrelated members.

## Lift a region

Name the configured source id before a path relative to that source root's
configured `source_roots[].path` directory:

````text
```snippet library:src/example.py#create-item
title: Create an item
lang: python
fold: false
```
````

When exactly one source root is configured, the source id may be omitted. A
meaningful `title` is required. `lang` may override extension-based highlighting.
`fold: true` collapses supporting evidence.

Introduce the question the source answers before the block and interpret the
consequential detail nearby. Do not place adjacent snippets without prose or a
table explaining their relationship. More than 24 visible nonblank lines is a
review signal; more than 40 visible lines fails the default audit.

Never put a current-source snippet inside a Plan. Also list the complete owning
file in the page's final `References` section without a line fragment.

Build or test the owning source. Successful extraction proves neither
compilation nor behavior. Run the configured documentation build after marker,
fence, path, or source-root changes and inspect the rendered block and link.
