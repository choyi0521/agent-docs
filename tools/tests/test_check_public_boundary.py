from __future__ import annotations

import importlib.util
import pathlib
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).parents[1] / "check_public_boundary.py"
SPEC = importlib.util.spec_from_file_location("check_public_boundary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BOUNDARY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BOUNDARY
SPEC.loader.exec_module(BOUNDARY)


class PublicBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, text: str = "safe\n") -> pathlib.Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def findings(self):
        return BOUNDARY.scan_tree(self.root)

    def test_clean_tree_includes_generated_agent_surfaces(self) -> None:
        self.write("README.md", "# Neutral toolkit\n\nhttps://github.com/example/project\n")
        self.write(".agents/skills/write-docs/SKILL.md", "# Write docs\n")
        self.write(".claude/skills/write-docs/SKILL.md", "# Write docs\n")
        self.write("config.json", '{"apiKey":"${DOCS_API_KEY}","preview":"http://localhost:4173"}\n')
        self.assertEqual([], self.findings())

    def test_generated_directories_are_rejected(self) -> None:
        for directory in (
            "build",
            "bin",
            "obj",
            "node_modules",
            "artifacts",
            ".tmp-cache",
            "coverage-report",
            ".coverage.results",
        ):
            with self.subTest(directory=directory):
                nested = self.root / directory
                nested.mkdir()
                self.assertTrue(any(finding.kind == "generated directory" for finding in self.findings()))
                nested.rmdir()

    def test_generated_directories_are_rejected_at_any_depth(self) -> None:
        (self.root / "safe" / "nested" / ".tmp-output").mkdir(parents=True)
        findings = self.findings()
        self.assertTrue(
            any(
                finding.kind == "generated directory" and finding.path == "safe/nested/.tmp-output"
                for finding in findings
            )
        )

    def test_binary_nul_and_non_utf8_files_are_rejected(self) -> None:
        (self.root / "nul.dat").write_bytes(b"text\x00payload")
        (self.root / "bytes.dat").write_bytes(b"\xff\xfe")
        findings = self.findings()
        self.assertEqual(2, sum(finding.kind == "binary file" for finding in findings))

    def test_reserved_product_identifier_is_case_insensitive(self) -> None:
        reserved = "Mi" + "ngLeAp"
        self.write(".agents/generated.md", f"private: {reserved}\n")
        self.assertTrue(any(finding.kind == "private identifier" for finding in self.findings()))

    def test_reserved_identifier_in_path_name_is_rejected(self) -> None:
        reserved = "mi" + "ngleap"
        self.write(f"notes/{reserved}-guide.md")
        self.assertTrue(any(finding.kind == "private identifier" for finding in self.findings()))

    def test_internal_host_and_secret_in_path_names_are_rejected(self) -> None:
        host = "service." + "internal"
        token = "AK" + "IA" + "A" * 16
        self.write(f"notes/{host}.md")
        self.write(f"notes/{token}.txt")
        kinds = {finding.kind for finding in self.findings()}
        self.assertIn("internal host", kinds)
        self.assertIn("secret", kinds)
        rendered = "\n".join(finding.render() for finding in self.findings())
        self.assertNotIn(token, rendered)
        self.assertNotIn(host, rendered)

    def test_finding_render_redacts_reserved_and_control_path_text(self) -> None:
        reserved = "Mi" + "ngLeap"
        rendered = BOUNDARY.Finding(f"notes/{reserved}\nname.md", 0, "test", "safe detail").render()
        self.assertNotIn(reserved.casefold(), rendered.casefold())
        self.assertNotIn("\n", rendered)
        self.assertIn("\\u000a", rendered)

    def test_retired_paths_and_prefixes_are_rejected(self) -> None:
        retired_path = "legacy" + "/engine/source"
        retired_prefix = "M" + "GL_TOKEN"
        self.write("notes.md", retired_path + "\n" + retired_prefix + "\n")
        kinds = {finding.kind for finding in self.findings()}
        self.assertIn("private path", kinds)
        self.assertIn("private identifier", kinds)

    def test_private_key_and_literal_credential_are_rejected(self) -> None:
        key_header = "-" * 5 + "BEGIN " + "PRIVATE" + " KEY" + "-" * 5
        credential = "api_" + "key = " + "Z" * 24
        self.write("unsafe.txt", key_header + "\n" + credential + "\n")
        self.assertGreaterEqual(sum(finding.kind == "secret" for finding in self.findings()), 2)

    def test_sensitive_file_name_is_rejected(self) -> None:
        self.write("nested/.env.local", "MODE=test\n")
        self.assertTrue(any(finding.kind == "sensitive file" for finding in self.findings()))

    def test_user_absolute_path_is_rejected(self) -> None:
        local_path = "C:" + "\\Users\\" + "case-user\\project"
        self.write("notes.md", local_path + "\n")
        self.assertTrue(any(finding.kind == "absolute user path" for finding in self.findings()))

    def test_private_hostname_is_rejected_but_local_preview_is_allowed(self) -> None:
        private_url = "https" + "://portal." + "corp/path"
        self.write("urls.md", private_url + "\nhttp://127.0.0.1:4173\n")
        findings = self.findings()
        self.assertEqual(1, sum(finding.kind == "internal host" for finding in findings))

    def test_plain_internal_hostname_and_private_address_are_rejected(self) -> None:
        private_host = "database." + "internal"
        private_address = ".".join(("10", "20", "30", "40"))
        documentation_address = ".".join(("192", "0", "2", "1"))
        self.write("network.txt", private_host + "\n" + private_address + "\n" + documentation_address + "\n")
        self.assertEqual(2, sum(finding.kind == "internal host" for finding in self.findings()))

    def test_github_urls_use_repository_allowlist(self) -> None:
        prefix = "https" + "://github.com/"
        unsupported_host = "https" + "://gist." + "github.com/example/identifier"
        self.write(
            "links.md",
            prefix
            + "example/project\n"
            + prefix
            + "PrismJS/prism\n"
            + prefix
            + "sponsors/example\n"
            + prefix
            + "unknown-owner/private-repo\n"
            + unsupported_host
            + "\n",
        )
        findings = self.findings()
        self.assertEqual(2, sum(finding.kind == "unapproved repository" for finding in findings))

    def test_remote_actions_require_allowlist_and_full_commit_hash(self) -> None:
        key = "- " + "us" + "es: "
        self.write(
            "workflow.yml",
            key
            + "actions/checkout@v4\n"
            + key
            + "'actions/setup-python/subdirectory@"
            + "a" * 40
            + "'\n"
            + key
            + "unknown-owner/unsafe-action@"
            + "b" * 40
            + "\n",
        )
        findings = self.findings()
        self.assertEqual(1, sum(finding.kind == "mutable action" for finding in findings))
        self.assertEqual(1, sum(finding.kind == "unapproved action" for finding in findings))

    def test_git_lfs_pointer_is_rejected(self) -> None:
        pointer = "version " + "https" + "://git-" + "lfs.github.com/spec/v1\n"
        self.write("pointer.txt", pointer + "oid sha256:" + "0" * 64 + "\nsize 1\n")
        self.assertTrue(any(finding.kind == "Git LFS pointer" for finding in self.findings()))

    def test_utf8_archive_or_media_suffix_is_rejected(self) -> None:
        self.write("payload.zip", "plain UTF-8 text\n")
        self.assertTrue(any(finding.kind == "unsupported file type" for finding in self.findings()))

    def test_submodule_metadata_is_rejected(self) -> None:
        self.write(".gitmodules", "[submodule \"example\"]\n")
        self.write("vendor/.git", "gitdir: ../metadata/modules/example\n")
        findings = self.findings()
        self.assertGreaterEqual(sum(finding.kind == "nested repository" for finding in findings), 2)

    def test_size_limits_cover_files_directories_and_complete_tree(self) -> None:
        self.write("one.txt", "12345")
        self.write("two.txt", "67890")
        with (
            mock.patch.object(BOUNDARY, "MAX_TEXT_BYTES", 4),
            mock.patch.object(BOUNDARY, "MAX_DIRECTORY_ENTRIES", 1),
            mock.patch.object(BOUNDARY, "MAX_DIRECTORY_BYTES", 8),
            mock.patch.object(BOUNDARY, "MAX_CANDIDATE_FILES", 1),
            mock.patch.object(BOUNDARY, "MAX_CANDIDATE_BYTES", 8),
        ):
            kinds = {finding.kind for finding in self.findings()}
        self.assertIn("oversized file", kinds)
        self.assertIn("oversized directory", kinds)
        self.assertIn("oversized tree", kinds)

    def test_windows_reparse_attribute_is_detected(self) -> None:
        fake_stat = types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        self.assertTrue(BOUNDARY._is_reparse(fake_stat))

    def test_symlink_is_reported_without_following_it(self) -> None:
        outside = pathlib.Path(self.temp.name).parent / (pathlib.Path(self.temp.name).name + "-outside")
        outside.write_text("outside\n", encoding="utf-8")
        link = self.root / "linked.txt"
        try:
            link.symlink_to(outside)
        except OSError as error:
            outside.unlink(missing_ok=True)
            self.skipTest(f"symlinks unavailable: {error}")
        try:
            self.assertTrue(any(finding.kind == "reparse point" for finding in self.findings()))
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
