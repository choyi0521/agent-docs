# Source publication

Documentation content and source publication are separate permissions. A space
can render Markdown without exposing any repository source.

## Publication rules {#publication-rules}

The safe defaults are `enableSnippets: false`, `publishCode: false`, and empty
allowlists. Enable only the surface the space needs:

- `enableSnippets` permits named regions from allowed files to appear in pages.
- `publishCode` exposes every matching file in the allowed trees through the
  code browser. It is not limited to files or regions referenced by a snippet.

Either opt-in requires nonempty `sourceTrees` and `sourceExtensions` lists.
Keep all applicable boundaries narrow:

- `sourceTrees` lists directories that may be walked.
- `sourceExtensions` lists exact filename extensions that may be published.
- `excludedSourcePaths` removes sensitive subtrees from both snippet lifting
  and browsing.
- `browsableRootFiles` allows individual files at the source root; it never
  enables a root-directory scan.

`docsDir` and `sourceRoot` are repository-relative. Source trees, exclusions,
snippet paths, and root-file entries are relative to `sourceRoot`. Every path is
normalized and required to stay below its trusted root. Symbolic links and
other filesystem redirections are rejected at publication boundaries.

The sample configuration makes that relationship explicit:

```json
{
  "sourceRoot": ".",
  "enableSnippets": true,
  "publishCode": true,
  "sourceTrees": ["examples/source"],
  "sourceExtensions": [".cs"]
}
```

Because `sourceRoot` is `.`, the corresponding snippet target is
`examples/source/GreetingFormatter.cs#greeting-format`. If a space instead uses
`sourceRoot: "examples"`, its target would be
`source/GreetingFormatter.cs#greeting-format`. A snippet target never starts
from `docsDir` or from the page's directory.

## Review checklist

Before enabling source publication:

1. Use the smallest source tree that contains the examples readers need.
2. Allow only textual extensions the renderer understands.
3. Exclude generated output, caches, credentials, and local settings.
4. Inspect the generated code-navigation index.
5. Run the checked render from the repository root.

The checked-in `examples/source` tree currently contains one `.cs` file, so the
[snippet example](/authoring/extensions#snippets) has a real, harmless source region.
Any future `.cs` file added below that allowed tree will also enter the code
browser until the configuration is narrowed.
