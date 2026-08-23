from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest


TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import sync_agent_instructions as sync  # noqa: E402


class AgentSurfaceGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temporary.name)
        (self.repo / "_agents/instructions").mkdir(parents=True)
        (self.repo / "_agents/skills/demo/references").mkdir(parents=True)
        (self.repo / "_agents/skills/demo/scripts").mkdir(parents=True)
        (self.repo / "schemas").mkdir()
        (self.repo / "_agents/policy.md").write_text("# Public policy\n", encoding="utf-8")
        (self.repo / "_agents/instructions/repository.md").write_text(
            "# Instructions\n\nRead the [policy](../policy.md).\n",
            encoding="utf-8",
        )
        (self.repo / "_agents/skills/demo/SKILL.md").write_text(
            "---\n"
            "name: demo\n"
            "description: Exercise deterministic package generation.\n"
            "---\n\n"
            "# Demo\n\n"
            "Read the [guide](references/guide.md) and "
            "[policy](../../policy.md).\n",
            encoding="utf-8",
        )
        (self.repo / "_agents/skills/demo/references/guide.md").write_text(
            "# Guide\n\nReturn to the [skill](../SKILL.md).\n",
            encoding="utf-8",
        )
        (self.repo / "_agents/skills/demo/scripts/run.py").write_text(
            "print('demo')\r\n", encoding="utf-8", newline=""
        )
        (self.repo / "_agents/skills/demo/interface.json").write_text(
            json.dumps(
                {
                    "display_name": "Demo",
                    "short_description": "Exercise generated skill packages",
                    "default_prompt": "Use $demo to exercise deterministic generation.",
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

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_manifests(self) -> None:
        (self.repo / "_agents/generation.json").write_text(
            json.dumps(self.generation), encoding="utf-8"
        )
        (self.repo / "_agents/publication.json").write_text(
            json.dumps(self.publication), encoding="utf-8"
        )

    def build(self) -> sync.BuildResult:
        return sync.build_outputs(self.repo)

    def test_generates_complete_vendor_copies_and_rebases_links(self) -> None:
        result = self.build()
        written, removed = sync.write_outputs(self.repo, result)

        self.assertEqual(removed, 0)
        self.assertEqual(written, len(result.outputs))
        self.assertEqual(sync.check_outputs(self.repo, result), [])
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        codex_skill = (self.repo / ".agents/skills/demo/SKILL.md").read_text(
            encoding="utf-8"
        )
        claude_skill = (self.repo / ".claude/skills/demo/SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("[policy](_agents/policy.md)", agents)
        self.assertIn("[guide](references/guide.md)", codex_skill)
        self.assertEqual(codex_skill, claude_skill)
        self.assertEqual(
            (self.repo / ".agents/skills/demo/scripts/run.py").read_bytes(),
            b"print('demo')\n",
        )
        self.assertTrue((self.repo / ".agents/skills/demo/agents/openai.yaml").is_file())
        self.assertFalse((self.repo / ".claude/skills/demo/agents/openai.yaml").exists())
        self.assertFalse((self.repo / ".agents/skills/demo/interface.json").exists())

    def test_write_is_byte_idempotent(self) -> None:
        result = self.build()
        sync.write_outputs(self.repo, result)
        before = {
            path: self.repo.joinpath(*path.parts).read_bytes() for path in result.outputs
        }
        sync.write_outputs(self.repo, self.build())
        after = {
            path: self.repo.joinpath(*path.parts).read_bytes() for path in result.outputs
        }
        self.assertEqual(before, after)

    def test_actual_managed_inventory_exactly_matches_manifest_outputs(self) -> None:
        result = self.build()
        sync.write_outputs(self.repo, result)

        actual = sync._actual_managed_files(self.repo, result.managed_roots)

        self.assertEqual(actual, set(result.outputs) - set(result.managed_files))
        self.assertEqual(sync.check_outputs(self.repo, result), [])

    def test_codex_and_claude_packages_have_full_content_parity(self) -> None:
        result = self.build()
        sync.write_outputs(self.repo, result)

        def package(root: pathlib.Path) -> dict[str, bytes]:
            return {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

        codex = package(self.repo / ".agents/skills/demo")
        claude = package(self.repo / ".claude/skills/demo")
        adapter = codex.pop("agents/openai.yaml")

        self.assertIn(b"interface:", adapter)
        self.assertEqual(codex, claude)

    def test_check_reports_stale_and_unexpected_outputs(self) -> None:
        result = self.build()
        sync.write_outputs(self.repo, result)
        (self.repo / "AGENTS.md").write_text("edited\n", encoding="utf-8")
        extra = self.repo / ".claude/skills/extra.txt"
        extra.write_text("extra\n", encoding="utf-8")

        problems = sync.check_outputs(self.repo, result)

        self.assertIn("stale: AGENTS.md", problems)
        self.assertIn("unexpected: .claude/skills/extra.txt", problems)

    def test_cleanup_is_confined_to_exact_generated_roots(self) -> None:
        result = self.build()
        sync.write_outputs(self.repo, result)
        inside = self.repo / ".agents/skills/obsolete.txt"
        outside = self.repo / "do-not-remove.txt"
        inside.write_text("obsolete\n", encoding="utf-8")
        outside.write_text("owned elsewhere\n", encoding="utf-8")

        _written, removed = sync.write_outputs(self.repo, self.build())

        self.assertEqual(removed, 1)
        self.assertFalse(inside.exists())
        self.assertEqual(outside.read_text(encoding="utf-8"), "owned elsewhere\n")

    def test_refuses_unknown_manifest_fields(self) -> None:
        self.generation["recursive_roots"] = ["_agents/skills"]
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "unknown recursive_roots"):
            self.build()

    def test_refuses_duplicate_json_keys(self) -> None:
        manifest = self.repo / "_agents/generation.json"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(text.replace('"version": 2,', '"version": 2, "version": 2,'), encoding="utf-8")

        with self.assertRaisesRegex(sync.GenerationError, "duplicate key 'version'"):
            self.build()

    def test_refuses_paths_that_escape_the_repository(self) -> None:
        self.generation["instructions"][0]["source"] = "../outside.md"
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "repository-relative path"):
            self.build()

    def test_refuses_case_insensitive_target_collisions(self) -> None:
        self.generation["instructions"][0]["targets"][1]["path"] = "agents.md"
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "case-insensitive target collision"):
            self.build()

    def test_refuses_stale_source_path_casing(self) -> None:
        source = self.repo / "_agents/instructions/repository.md"
        text = source.read_text(encoding="utf-8")
        temporary = source.with_name("temporary.md")
        source.rename(temporary)
        temporary.rename(source.with_name("Repository.md"))
        self.assertIn("Instructions", text)

        with self.assertRaisesRegex(sync.GenerationError, "stale path casing"):
            self.build()

    def test_refuses_expanded_managed_cleanup_authority(self) -> None:
        self.generation["managed"]["roots"] = ["_agents", ".claude/skills"]
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "cleanup authority cannot be expanded"):
            self.build()

    def test_refuses_protected_output_target(self) -> None:
        self.generation["skills"][0]["targets"][0]["path"] = "_agents/skills/demo"
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "skill target"):
            self.build()

    def test_refuses_unsafe_key_and_environment_files(self) -> None:
        for filename in (".env", "client.pem", "certificate.crt"):
            with self.subTest(filename=filename):
                unsafe = self.repo / "_agents/skills/demo/scripts" / filename
                unsafe.write_text("placeholder\n", encoding="utf-8")
                try:
                    with self.assertRaisesRegex(
                        sync.GenerationError, "unsafe credential/key file"
                    ):
                        self.build()
                finally:
                    unsafe.unlink()

    def test_refuses_literal_secret(self) -> None:
        instruction = self.repo / "_agents/instructions/repository.md"
        instruction.write_text("# Unsafe\n\nPASSWORD=hunter2\n", encoding="utf-8")

        with self.assertRaisesRegex(sync.GenerationError, "literal secret"):
            self.build()

    def test_refuses_machine_local_user_path(self) -> None:
        instruction = self.repo / "_agents/instructions/repository.md"
        paths = [
            "C:" + "\\Users\\person\\private\\settings.json",
            "D:" + "\\work\\private-repository\\settings.json",
        ]
        for local_path in paths:
            with self.subTest(local_path=local_path):
                instruction.write_text(
                    f"# Unsafe\n\nRead `{local_path}`.\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(sync.GenerationError, "machine-local"):
                    self.build()

    def test_refuses_private_service_address(self) -> None:
        private_url = "https://" + "docs." + "corp"
        instruction = self.repo / "_agents/instructions/repository.md"
        instruction.write_text(
            f"# Unsafe\n\nService: {private_url}\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(sync.GenerationError, "private service address"):
            self.build()

    def test_refuses_authorization_credential(self) -> None:
        header = "Authorization" + ": Bearer " + "actual-value"
        instruction = self.repo / "_agents/instructions/repository.md"
        instruction.write_text(f"# Unsafe\n\n{header}\n", encoding="utf-8")

        with self.assertRaisesRegex(sync.GenerationError, "authorization credential"):
            self.build()

    def test_refuses_unknown_publication_id(self) -> None:
        self.publication["skills"] = ["not-configured"]
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "outside the generation manifest"):
            self.build()

    def test_refuses_unknown_publication_fields(self) -> None:
        self.publication["recursive"] = True
        self.write_manifests()

        with self.assertRaisesRegex(sync.GenerationError, "unknown recursive"):
            self.build()

    def test_refuses_interface_unknown_fields(self) -> None:
        interface = self.repo / "_agents/skills/demo/interface.json"
        data = json.loads(interface.read_text(encoding="utf-8"))
        data["vendor"] = "specific"
        interface.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(sync.GenerationError, "unknown vendor"):
            self.build()

    def test_refuses_symlinked_package_entry(self) -> None:
        target = self.repo / "outside.py"
        target.write_text("print('outside')\n", encoding="utf-8")
        link = self.repo / "_agents/skills/demo/scripts/linked.py"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symbolic links unavailable: {error}")

        with self.assertRaisesRegex(sync.GenerationError, "symlink or reparse point"):
            self.build()


if __name__ == "__main__":
    unittest.main()
