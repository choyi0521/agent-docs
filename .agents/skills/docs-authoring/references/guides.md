<!-- Generated from _agents/skills/docs-authoring/references/guides.md by tools/sync_agent_instructions.py. Do not edit this copy directly. -->
# Guides

A Guide helps a reader reach one concrete, supported result. The starting point
may be an installed product, an SDK, a command-line tool, or a checked-out source
tree. Classify the page by the result, not by the presence of a repository.

## Shape

1. State the result the reader will reach.
2. Name the exact starting state, prerequisites, and working directory.
3. Lead through one supported path in executable order.
4. Give an observable checkpoint after each consequential step.
5. Confirm the final result and cover likely diagnostics and recovery.
6. Link deeper Concepts, complete Reference, and useful next results.

Use imperative steps and sanitized concrete values. Every command must run as
written from the stated directory. Make replacement values unmistakable. Quote
an exact diagnostic when available, then state its cause and supported fix.

Do not offer competing paths in the main flow. Put a platform variant beside
the step that differs and optional improvements after the first success. Split
a page when it produces more than one independently useful result, but do not
split one procedure across pages that must be followed together.

Run the Guide from its documented starting state. Treat a command that performs
no intended work or silently uses an unintended default as failed verification.

Guide steps describe available behavior. Do not put unavailable commands in
the current procedure. Link intended workflow changes to the Concept,
Reference, or non-procedural Development page that owns the Plan.
