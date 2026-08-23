# Development

Development documentation helps maintainers change or govern a repository. It
belongs in a section configured with the `development` role when the result
changes implementation, tests, build declarations, repository structure,
documentation policy, or another maintainer-owned contract.

## Executable workflow

1. State the maintained result and exact starting state.
2. Name the repository location, required tools and versions, generated inputs,
   credential type, and supported platform assumptions. Never publish a
   credential value.
3. Give one supported sequence of commands.
4. Add observable checkpoints after consequential steps.
5. Explain diagnostics, recovery, cleanup, and safe retry behavior.
6. Run the final configured gate after the last edit or manual review.

## Convention or maintainer model

1. State which changes the rule governs and why it exists.
2. Show the smallest correct and incorrect examples that expose the boundary.
3. Name enforcement, exceptions, and the public owner allowed to change it.
4. Link product interfaces to Reference and reusable models to Concepts.

Run commands from the documented directory and confirm that each command does
the intended work. Keep platform variants beside the step that differs. If a
gate cannot run, report the limitation instead of silently omitting it.

A non-procedural Development page may own Plans for future tooling, repository
contracts, source policy, or missing enforcement. Do not place unavailable
commands in a current executable workflow.
