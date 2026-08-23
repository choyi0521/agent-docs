#!/usr/bin/env python3
"""Regression tests for the configurable public documentation auditor."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).with_name("audit_docs.py")
SPEC = importlib.util.spec_from_file_location("docs_audit_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class RepositoryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name)
        self.docs = self.repository / "manual"
        self.source = self.repository / "library"
        self.docs.mkdir()
        self.source.mkdir()
        self.config_path = self.repository / "docs-audit.json"
        self.data = {
            "docs_root": "manual",
            "index_file": "_index.md",
            "nav_key": "nav",
            "sections": [
                {
                    "path": "walkthroughs",
                    "role": "guide",
                    "allow_plans": False,
                    "require_references": False,
                },
                {
                    "path": "architecture",
                    "role": "concept",
                    "allow_plans": True,
                    "require_references": False,
                },
                {
                    "path": "catalog",
                    "role": "reference",
                    "allow_plans": True,
                    "require_references": True,
                },
                {
                    "path": "maintenance",
                    "role": "development",
                    "allow_plans": True,
                    "require_references": False,
                },
            ],
            "asset_roots": ["media"],
            "retired_roots": ["archive"],
            "plan_anchor_prefix": "plan-public-",
            "source_roots": [
                {"id": "library", "path": "library", "code_route": "/code/library/"}
            ],
            "evidence_rules": [
                {"role": "Tests", "patterns": ["checks/**", "**/*_spec.*"]},
                {"role": "Build", "patterns": ["metadata/**"]},
            ],
            "build_commands": [],
        }
        self.write_config()

    def write_config(self) -> None:
        self.config_path.write_text(
            json.dumps(self.data, indent=2) + "\n", encoding="utf-8"
        )

    def load(self):
        return AUDIT.load_config(self.config_path)

    def write_source(self, relative: str, text: str) -> Path:
        path = self.source / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_page(self, relative: str, text: str) -> Path:
        path = self.docs / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def scaffold(self) -> None:
        ordered = [item["path"] for item in self.data["sections"]]
        self.write_page(
            "_index.md",
            "---\nnav:\n"
            + "".join(f"  - {name}/\n" for name in ordered)
            + "---\n\n# Sample product\n",
        )
        for item in self.data["sections"]:
            section = item["path"]
            self.write_page(
                f"{section}/_index.md",
                "---\nnav:\n  - page.md\n---\n\n# Section\n",
            )
            body = "# Page\n\nPublished behavior.\n"
            if item["require_references"]:
                body += (
                    "\n## References\n\n"
                    "- **Project authorities:** [Public contract](../_index.md)\n"
                )
            self.write_page(f"{section}/page.md", body)

    def run_main(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = AUDIT.main(list(arguments))
        return result, output.getvalue()


class ConfigurationTests(RepositoryCase):
    def test_arbitrary_layout_and_routes_load(self) -> None:
        config = self.load()
        self.assertEqual("manual", config.docs_path)
        self.assertEqual(
            ("walkthroughs", "architecture", "catalog", "maintenance"),
            tuple(section.path for section in config.sections),
        )
        self.assertEqual("plan-public-", config.plan_anchor_prefix)
        self.assertEqual("/code/library/", config.source_roots[0].code_route)

    def test_repository_override_is_explicit(self) -> None:
        other = self.repository / "checkout"
        other.mkdir()
        (other / "manual").mkdir()
        config = AUDIT.load_config(self.config_path, other)
        self.assertEqual(other.resolve(), config.repository)
        self.assertEqual((other / "manual").resolve(), config.docs)

    def test_unknown_fields_and_escaping_paths_are_rejected(self) -> None:
        for key, value, expected in (
            ("unexpected", True, "unknown field"),
            ("docs_root", "../private", "must not be absolute"),
            ("plan_anchor_prefix", "PublicPlan", "lowercase hyphenated"),
        ):
            with self.subTest(key=key):
                original = self.data.get(key)
                present = key in self.data
                self.data[key] = value
                self.write_config()
                with self.assertRaisesRegex(AUDIT.ConfigurationError, expected):
                    self.load()
                if present:
                    self.data[key] = original
                else:
                    self.data.pop(key)

    def test_duplicate_sections_sources_routes_and_commands_are_rejected(self) -> None:
        variants = []
        duplicate_section = json.loads(json.dumps(self.data))
        duplicate_section["sections"].append(dict(duplicate_section["sections"][0]))
        variants.append((duplicate_section, "duplicate section"))
        duplicate_source = json.loads(json.dumps(self.data))
        duplicate_source["source_roots"].append(
            {"id": "library", "path": "other", "code_route": "/code/other/"}
        )
        variants.append((duplicate_source, "duplicate source root id"))
        overlap_route = json.loads(json.dumps(self.data))
        overlap_route["source_roots"].append(
            {"id": "extra", "path": "other", "code_route": "/code/library/nested/"}
        )
        variants.append((overlap_route, "overlapping code route"))
        overlap_path = json.loads(json.dumps(self.data))
        overlap_path["source_roots"].append(
            {"id": "nested", "path": "library/nested", "code_route": "/code/nested/"}
        )
        variants.append((overlap_path, "overlapping source root paths"))
        duplicate_command = json.loads(json.dumps(self.data))
        command = {"name": "render", "cwd": ".", "argv": [sys.executable, "-c", "pass"]}
        duplicate_command["build_commands"] = [command, dict(command)]
        variants.append((duplicate_command, "duplicate build command"))
        for data, message in variants:
            with self.subTest(message=message):
                self.config_path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(AUDIT.ConfigurationError, message):
                    self.load()

    def test_build_commands_use_argv_and_safe_working_directories(self) -> None:
        self.data["build_commands"] = [
            {"name": "verify", "cwd": ".", "argv": [sys.executable, "-c", "pass"]}
        ]
        self.write_config()
        command = self.load().build_commands[0]
        self.assertEqual((sys.executable, "-c", "pass"), command.argv)
        self.data["build_commands"][0]["cwd"] = "../outside"
        self.write_config()
        with self.assertRaisesRegex(AUDIT.ConfigurationError, "must not be absolute"):
            self.load()


class MarkdownParsingTests(RepositoryCase):
    def test_comments_and_fenced_examples_do_not_supply_headings(self) -> None:
        page = self.docs / "architecture" / "page.md"
        text = (
            "# Visible\n\n"
            "<!-- # Hidden -->\n\n"
            "```markdown\n# Example\n:::plan Example\n```\n"
        )
        errors, _ = AUDIT.page_checks(page, self.load()) if page.exists() else ([], [])
        self.assertEqual([], errors)
        self.assertEqual(["Visible"], AUDIT.H1.findall(AUDIT.mask_fenced_blocks(text)))
        self.assertEqual([], AUDIT.plan_checks(page, text, self.load()))

    def test_heading_jump_filler_and_em_dash_are_hard_errors(self) -> None:
        page = self.write_page(
            "architecture/page.md",
            "# Topic\n\n### Detail\n\nThis obviously works — every time.\n",
        )
        errors, _ = AUDIT.page_checks(page, self.load())
        for expected in ("heading level jumps", "discouraged filler", "em dash"):
            self.assertTrue(any(expected in item for item in errors), expected)

    def test_long_paragraph_is_a_review_warning(self) -> None:
        page = self.write_page(
            "architecture/page.md",
            "# Topic\n\n" + " ".join(["word"] * 121) + "\n",
        )
        _, warnings = AUDIT.page_checks(page, self.load())
        self.assertTrue(any("121 words" in item for item in warnings))


class PlanTests(RepositoryCase):
    VALID_PLAN = """# Publication

## Available behavior

The library saves a draft locally.

:::plan Publish saved drafts
### Send a saved draft {#plan-public-send-draft}

**Current:** Saving succeeds, but publication is unavailable.
**Source:** [Published rationale](#available-behavior)

- [ ] Connect the public publish operation.
- [ ] Verify recovery after a rejected request.

**Done when:** The integration test observes publication and recovery.
:::
"""

    def test_valid_plan_uses_configured_prefix(self) -> None:
        page = self.docs / "architecture" / "page.md"
        self.assertEqual([], AUDIT.plan_checks(page, self.VALID_PLAN, self.load()))

    def test_wrong_prefix_and_disallowed_section_fail(self) -> None:
        wrong = self.VALID_PLAN.replace("plan-public-", "plan-sample-")
        architecture = self.docs / "architecture" / "page.md"
        walkthrough = self.docs / "walkthroughs" / "page.md"
        self.assertTrue(
            any("must use prefix" in item for item in AUDIT.plan_checks(architecture, wrong, self.load()))
        )
        self.assertTrue(
            any("does not allow Plans" in item for item in AUDIT.plan_checks(walkthrough, self.VALID_PLAN, self.load()))
        )

    def test_plan_rejects_placeholders_completed_steps_and_unlinked_source(self) -> None:
        invalid = (
            self.VALID_PLAN.replace(
                "**Current:** Saving succeeds, but publication is unavailable.",
                "**Current:** TBD",
            )
            .replace("- [ ] Connect the public publish operation.", "- [ ] Do it.")
            .replace("- [ ] Verify recovery", "- [x] Verify recovery")
            .replace(
                "**Done when:** The integration test observes publication and recovery.",
                "**Done when:** It works.",
            )
            .replace("[Published rationale](#available-behavior)", "rationale")
        )
        errors = AUDIT.plan_checks(
            self.docs / "architecture" / "page.md", invalid, self.load()
        )
        for expected in ("must not be 'TBD'", "step must be concrete", "must not retain", "observable", "must contain a link"):
            self.assertTrue(any(expected in item for item in errors), expected)

    def test_unclosed_container_does_not_consume_later_content(self) -> None:
        text = self.VALID_PLAN.replace(":::\n", "", 1) + "\n" + self.VALID_PLAN
        errors = AUDIT.plan_checks(
            self.docs / "architecture" / "page.md", text, self.load()
        )
        self.assertTrue(any("missing its closing" in item for item in errors))

    def test_duplicate_plan_anchors_are_tree_errors(self) -> None:
        self.scaffold()
        self.write_page("architecture/page.md", self.VALID_PLAN)
        self.write_page("maintenance/page.md", self.VALID_PLAN)
        errors = AUDIT.duplicate_plan_anchor_checks(self.load())
        self.assertEqual(1, len(errors))
        self.assertIn("plan-public-send-draft", errors[0])

    def test_index_cannot_own_a_plan(self) -> None:
        errors = AUDIT.plan_checks(
            self.docs / "architecture" / "_index.md", self.VALID_PLAN, self.load()
        )
        self.assertTrue(any("index must not own" in item for item in errors))


class SnippetTests(RepositoryCase):
    def test_valid_neutral_source_region_is_resolved(self) -> None:
        self.write_source(
            "src/sample.py",
            "# docs:begin make-item\n"
            "def make_item(value):\n"
            "    return {\"value\": value}\n"
            "# docs:end make-item\n",
        )
        page = self.docs / "catalog" / "item.md"
        text = (
            "# Item\n\n"
            "```snippet library:src/sample.py#make-item\n"
            "title: Make an item\n"
            "fold: false\n"
            "```\n"
        )
        self.assertEqual([], AUDIT.source_snippet_errors(page, text, self.load()))
        evidence = AUDIT.code_evidence(page, text, self.load())[0]
        self.assertEqual(2, evidence.line_count)
        self.assertEqual("src/sample.py", evidence.target.relative_path)

    def test_missing_target_title_markers_and_invalid_fold_fail(self) -> None:
        self.write_source("src/sample.py", "def make_item():\n    return None\n")
        page = self.docs / "catalog" / "item.md"
        text = (
            "# Item\n\n"
            "```snippet library:src/sample.py#missing\n"
            "title: Source\n"
            "fold: sometimes\n"
            "```\n"
        )
        errors = AUDIT.source_snippet_errors(page, text, self.load())
        for expected in ("exactly one begin", "meaningful title", "invalid fold"):
            self.assertTrue(any(expected in item for item in errors), expected)

    def test_path_escape_and_unknown_source_are_rejected(self) -> None:
        config = self.load()
        for target, expected in (
            ("library:../private.txt#item", "must not be absolute"),
            ("unknown:src/sample.py#item", "unknown source id"),
        ):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, expected):
                    AUDIT.parse_snippet_target(target, config)

    def test_multiple_source_roots_require_an_id(self) -> None:
        (self.repository / "examples").mkdir()
        self.data["source_roots"].append({"id": "examples", "path": "examples"})
        self.write_config()
        with self.assertRaisesRegex(ValueError, "must start with a configured source id"):
            AUDIT.parse_snippet_target("src/sample.py#item", self.load())

    def test_visible_region_over_limit_is_a_hard_error(self) -> None:
        body = "\n".join(f"value_{index} = {index}" for index in range(41))
        self.write_source(
            "src/large.py",
            f"# docs:begin large\n{body}\n# docs:end large\n",
        )
        text = (
            "# Large\n\n"
            "```snippet library:src/large.py#large\n"
            "title: Large lookup table\n"
            "```\n"
        )
        errors = AUDIT.source_snippet_errors(
            self.docs / "catalog" / "large.md", text, self.load()
        )
        self.assertTrue(any("renders 41" in item for item in errors))


class ReferencesTests(RepositoryCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_source(
            "src/sample.py",
            "# docs:begin make-item\ndef make_item():\n    return None\n# docs:end make-item\n",
        )
        self.page = self.docs / "catalog" / "item.md"

    def valid_text(self) -> str:
        return (
            "# Item\n\n"
            "The public [format](https://example.com/format) defines the record.\n\n"
            "```snippet library:src/sample.py#make-item\n"
            "title: Make an item\n"
            "```\n\n"
            "## References\n\n"
            "- **Source:** [sample.py](/code/library/src/sample.py)\n"
            "- **External sources:** [Public format](https://example.com/format)\n"
        )

    def test_valid_source_and_external_inventory_passes(self) -> None:
        self.assertEqual(
            [], AUDIT.reference_section_checks(self.page, self.valid_text(), self.load())
        )

    def test_references_must_be_final_and_repeat_inline_evidence(self) -> None:
        missing_external = self.valid_text().replace(
            "- **External sources:** [Public format](https://example.com/format)\n", ""
        )
        errors = AUDIT.reference_section_checks(self.page, missing_external, self.load())
        self.assertTrue(any("external source must also appear" in item for item in errors))
        not_final = self.valid_text() + "\n## More\n"
        errors = AUDIT.reference_section_checks(self.page, not_final, self.load())
        self.assertTrue(any("must be the final H2" in item for item in errors))

    def test_configured_evidence_rules_control_roles(self) -> None:
        self.write_source(
            "checks/item_spec.py",
            "# docs:begin verify\ndef verify():\n    return True\n# docs:end verify\n",
        )
        text = (
            "# Check\n\n"
            "```snippet library:checks/item_spec.py#verify\n"
            "title: Verify the item\n"
            "```\n\n"
            "## References\n\n"
            "- **Source:** [item_spec.py](/code/library/checks/item_spec.py)\n"
        )
        errors = AUDIT.reference_section_checks(self.page, text, self.load())
        self.assertTrue(any("expected Tests" in item for item in errors))

    def test_fragments_and_unknown_roles_fail(self) -> None:
        text = self.valid_text().replace(
            "/code/library/src/sample.py)", "/code/library/src/sample.py#line-1)"
        ).replace(
            "- **External sources:**", "- **Background reading:**"
        )
        errors = AUDIT.reference_section_checks(self.page, text, self.load())
        self.assertTrue(any("without a fragment" in item for item in errors))
        self.assertTrue(any("unknown References role" in item for item in errors))

    def test_source_without_code_route_uses_relative_link(self) -> None:
        self.data["source_roots"][0].pop("code_route")
        self.write_config()
        text = self.valid_text().replace(
            "/code/library/src/sample.py", "../../library/src/sample.py"
        )
        self.assertEqual(
            [], AUDIT.reference_section_checks(self.page, text, self.load())
        )

    def test_reference_leaf_requires_a_references_section(self) -> None:
        errors = AUDIT.reference_section_checks(
            self.page, "# Item\n\nPublished behavior.\n", self.load()
        )
        self.assertTrue(any("expected exactly one" in item for item in errors))


class TreeAndCliTests(RepositoryCase):
    def test_arbitrary_section_order_passes(self) -> None:
        self.scaffold()
        result, output = self.run_main(
            "--config", str(self.config_path), "--repo-root", str(self.repository), "--check"
        )
        self.assertEqual(0, result, output)
        self.assertIn("9 page(s), 0 error(s)", output)

    def test_root_navigation_uses_configured_order(self) -> None:
        self.scaffold()
        index = self.docs / "_index.md"
        text = index.read_text(encoding="utf-8").replace(
            "  - architecture/\n  - catalog/\n",
            "  - catalog/\n  - architecture/\n",
        )
        index.write_text(text, encoding="utf-8")
        errors = AUDIT.tree_checks(self.load())
        self.assertTrue(any("populated sections in this order" in item for item in errors))

    def test_retired_unexpected_and_nested_roots_are_checked(self) -> None:
        self.scaffold()
        self.write_page("archive/old.md", "# Old\n")
        self.write_page("misc/page.md", "# Misc\n")
        self.write_page("catalog/group/item.md", "# Item\n")
        errors = AUDIT.tree_checks(self.load())
        for expected in ("retired documentation root", "unexpected documentation root", "_index.md is missing"):
            self.assertTrue(any(expected in item for item in errors), expected)

    def test_missing_configured_source_root_is_a_tree_error(self) -> None:
        self.scaffold()
        self.source.rmdir()
        errors = AUDIT.tree_checks(self.load())
        self.assertTrue(any("configured source root is missing" in item for item in errors))

    def test_nested_index_requires_explicit_navigation(self) -> None:
        self.scaffold()
        self.write_page("catalog/group/item.md", "# Item\n")
        self.write_page("catalog/group/_index.md", "# Group\n")
        errors = AUDIT.nested_index_checks(self.load())
        self.assertTrue(any("has no explicit navigation" in item for item in errors))
        self.write_page(
            "catalog/group/_index.md",
            "---\nnav:\n  - item.md\n---\n\n# Group\n",
        )
        self.assertEqual([], AUDIT.nested_index_checks(self.load()))

    def test_review_path_cannot_escape_documentation_root(self) -> None:
        self.scaffold()
        _, error = AUDIT.resolve_review_page("../outside.md", self.load())
        self.assertIn("must not contain '..'", error)
        outside = self.repository / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        _, error = AUDIT.resolve_review_page(str(outside), self.load())
        self.assertIn("outside the documentation root", error)

    def test_build_commands_are_opt_in_selectable_and_report_failures(self) -> None:
        self.scaffold()
        self.data["build_commands"] = [
            {"name": "pass", "cwd": ".", "argv": [sys.executable, "-c", "pass"]},
            {"name": "fail", "cwd": ".", "argv": [sys.executable, "-c", "raise SystemExit(3)"]},
        ]
        self.write_config()
        result, output = self.run_main(
            "--config", str(self.config_path), "--check", "--run-build", "--build-command", "pass"
        )
        self.assertEqual(0, result, output)
        result, output = self.run_main(
            "--config", str(self.config_path), "--run-build", "--build-command", "fail"
        )
        self.assertEqual(1, result)
        self.assertIn("exited with 3", output)

    def test_unknown_selected_build_command_fails(self) -> None:
        self.scaffold()
        result, output = self.run_main(
            "--config", str(self.config_path), "--run-build", "--build-command", "missing"
        )
        self.assertEqual(1, result)
        self.assertIn("unknown build command", output)

    def test_build_timeout_is_positive_and_failure_closed(self) -> None:
        self.scaffold()
        self.data["build_commands"] = [
            {
                "name": "slow",
                "cwd": ".",
                "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
            }
        ]
        self.write_config()
        started = time.monotonic()
        result, output = self.run_main(
            "--config", str(self.config_path), "--run-build",
            "--build-timeout-seconds", "1",
        )
        elapsed = time.monotonic() - started
        self.assertEqual(1, result)
        self.assertLess(elapsed, 4)
        self.assertIn("exceeded 1 second(s)", output)
        parser = AUDIT.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--config", str(self.config_path), "--build-timeout-seconds", "0"])

    def test_running_an_empty_or_duplicate_build_selection_fails(self) -> None:
        self.scaffold()
        result, output = self.run_main(
            "--config", str(self.config_path), "--run-build"
        )
        self.assertEqual(1, result)
        self.assertIn("no build commands are configured", output)
        self.data["build_commands"] = [
            {"name": "verify", "cwd": ".", "argv": [sys.executable, "-c", "pass"]}
        ]
        self.write_config()
        result, output = self.run_main(
            "--config", str(self.config_path), "--run-build",
            "--build-command", "verify", "--build-command", "verify",
        )
        self.assertEqual(1, result)
        self.assertIn("selected only once", output)

    def test_config_error_returns_two(self) -> None:
        self.data["docs_root"] = "../hidden"
        self.write_config()
        result, output = self.run_main("--config", str(self.config_path), "--check")
        self.assertEqual(2, result)
        self.assertIn("CONFIG ERROR", output)


if __name__ == "__main__":
    unittest.main()
