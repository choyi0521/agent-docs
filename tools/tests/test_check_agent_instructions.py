from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest


TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_agent_instructions as check  # noqa: E402
import sync_agent_instructions as sync  # noqa: E402


class AgentInstructionCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temporary.name)
        (self.repo / "_agents/instructions").mkdir(parents=True)
        (self.repo / "_agents/skills/demo/references").mkdir(parents=True)
        (self.repo / "schemas").mkdir()
        (self.repo / "_agents/README.md").write_text(
            "# Canonical guidance\n", encoding="utf-8"
        )
        (self.repo / "_agents/policy.md").write_text("# Policy\n", encoding="utf-8")
        (self.repo / "_agents/instructions/repository.md").write_text(
            "# Instructions\n\nRead the [policy](../policy.md).\n",
            encoding="utf-8",
        )
        (self.repo / "_agents/skills/demo/SKILL.md").write_text(
            "---\nname: demo\ndescription: Check a generated package.\n---\n\n"
            "# Demo\n\nRead the [guide](references/guide.md).\n",
            encoding="utf-8",
        )
        (self.repo / "_agents/skills/demo/references/guide.md").write_text(
            "# Guide\n", encoding="utf-8"
        )
        (self.repo / "_agents/skills/demo/interface.json").write_text(
            json.dumps(
                {
                    "display_name": "Demo",
                    "short_description": "Check generated guidance",
                    "default_prompt": "Use $demo to check this fixture.",
                }
            ),
            encoding="utf-8",
        )
        self.generation = {
            "$schema": sync.GENERATION_SCHEMA,
            "version": 2,
            "instructions": [
                {
                    "id": "repository",
                    "source": "_agents/instructions/repository.md",
                    "targets": [
                        {"path": "AGENTS.md", "vendor": "codex"},
                        {"path": "CLAUDE.md", "vendor": "claude"},
                    ],
                }
            ],
            "skills": [
                {
                    "id": "demo",
                    "source": "_agents/skills/demo",
                    "targets": [
                        {"path": ".agents/skills/demo", "vendor": "codex"},
                        {"path": ".claude/skills/demo", "vendor": "claude"},
                    ],
                }
            ],
            "managed": {
                "files": ["AGENTS.md", "CLAUDE.md"],
                "roots": [".agents/skills", ".claude/skills"],
            },
        }
        self.publication = {
            "$schema": sync.PUBLICATION_SCHEMA,
            "version": 2,
            "instructions": ["repository"],
            "skills": ["demo"],
        }
        self.write_manifests()
        result = sync.build_outputs(self.repo)
        sync.write_outputs(self.repo, result)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_manifests(self) -> None:
        (self.repo / "_agents/generation.json").write_text(
            json.dumps(self.generation), encoding="utf-8"
        )
        (self.repo / "_agents/publication.json").write_text(
            json.dumps(self.publication), encoding="utf-8"
        )

    def regenerate(self) -> None:
        result = sync.build_outputs(self.repo)
        sync.write_outputs(self.repo, result)

    def test_clean_repository_passes(self) -> None:
        files, problems = check.check_repository(self.repo)

        self.assertEqual(problems, [])
        relative = {
            pathlib.PurePosixPath(path.relative_to(self.repo).as_posix()) for path in files
        }
        self.assertIn(pathlib.PurePosixPath("_agents/README.md"), relative)
        self.assertIn(pathlib.PurePosixPath("_agents/skills/demo/SKILL.md"), relative)
        self.assertIn(pathlib.PurePosixPath(".agents/skills/demo/SKILL.md"), relative)

    def test_reports_dead_canonical_and_generated_links(self) -> None:
        instruction = self.repo / "_agents/instructions/repository.md"
        instruction.write_text(
            "# Instructions\n\nRead the [missing file](../missing.md).\n",
            encoding="utf-8",
        )
        self.regenerate()

        _files, problems = check.check_repository(self.repo)

        self.assertTrue(any("dead local link" in problem for problem in problems))
        self.assertTrue(any("_agents/instructions/repository.md" in problem for problem in problems))

    def test_reports_generated_drift(self) -> None:
        (self.repo / ".claude/skills/demo/SKILL.md").write_text(
            "edited\n", encoding="utf-8"
        )

        _files, problems = check.check_repository(self.repo)

        self.assertIn("stale: .claude/skills/demo/SKILL.md", problems)

    def test_reports_unexpected_managed_output(self) -> None:
        (self.repo / ".agents/skills/unexpected.md").write_text(
            "# Unexpected\n", encoding="utf-8"
        )

        _files, problems = check.check_repository(self.repo)

        self.assertIn("unexpected: .agents/skills/unexpected.md", problems)

    def test_refuses_unsafe_markdown_scheme(self) -> None:
        instruction = self.repo / "_agents/instructions/repository.md"
        instruction.write_text(
            "# Instructions\n\nRead the [unsafe](javascript:alert(1)).\n",
            encoding="utf-8",
        )
        self.regenerate()

        _files, problems = check.check_repository(self.repo)

        self.assertTrue(any("unsafe Markdown link scheme" in problem for problem in problems))

    def test_unlisted_directory_is_not_auto_discovered(self) -> None:
        unlisted = self.repo / "_agents/skills/unlisted"
        unlisted.mkdir()
        (unlisted / "SKILL.md").write_text(
            "# Unlisted\n\n[Missing](missing.md).\n", encoding="utf-8"
        )

        files, problems = check.check_repository(self.repo)

        self.assertEqual(problems, [])
        self.assertFalse(any("unlisted" in path.as_posix() for path in files))

    def test_publication_must_intersect_generation_by_id_and_kind(self) -> None:
        self.publication["instructions"] = ["demo"]
        self.publication["skills"] = ["repository"]
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "outside the generation manifest"):
            check.check_repository(self.repo)

    def test_generator_refuses_link_escape_before_check(self) -> None:
        outside = self.repo.parent / "outside-agent-docs-test.md"
        instruction = self.repo / "_agents/instructions/repository.md"
        instruction.write_text(
            "# Instructions\n\nRead [outside](../../../outside-agent-docs-test.md).\n",
            encoding="utf-8",
        )
        try:
            with self.assertRaisesRegex(sync.GenerationError, "escapes the repository"):
                check.check_repository(self.repo)
        finally:
            if outside.exists():
                outside.unlink()


if __name__ == "__main__":
    unittest.main()
