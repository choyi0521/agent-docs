from __future__ import annotations

import base64
import contextlib
import dataclasses
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import sources
from research_index.corpus import SourceRevision


@unittest.skipUnless(shutil.which("git"), "Git is required for synthetic offline object fixtures")
class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.corpus = self.root / "corpus"
        self.catalog = self.corpus / "catalog"
        self.catalog.mkdir(parents=True)
        self.manifest = {
            "schema": 2, "id": "example", "name": "Example source",
            "kind": "git-repository", "url": "https://example.org/repositories/project.git",
            "license": "MIT", "access": "public", "topics": ["documentation"],
            "notes": "Synthetic test source; no network access.",
            "revision": {"kind": "git-commit", "value": "1" * 40},
            "retrieved_at": "2026-01-01T00:00:00+00:00",
            "tracking": {"kind": "git-ref", "ref": "refs/heads/main"},
        }
        self.source = self.write_manifest()
        self.cache = sources.cache_root(self.root / "cache", self.corpus, create=True)

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self):
        (self.catalog / "example.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        return sources.load_catalog(self.corpus)["example"]

    def reader(self, name="fixture"):
        stage = self.root / name
        stage.mkdir()
        return sources.GitReader(stage)

    def populate(self, reader, files=None):
        if files is None:
            files = {"README.md": b"pinned bytes\r\n", "src/example.txt": b"example\x00bytes\n"}
        reader.run(["init", "--bare", "--object-format=sha1", "--template", str(reader.empty), str(reader.repository)])

        def put(kind, body):
            actual = reader.run(
                ["--git-dir", str(reader.repository), "hash-object", "-w", "--stdin", "-t", kind], data=body,
            ).decode("ascii").strip()
            self.assertEqual(sources.object_id(kind, body), actual)
            return actual

        nested = {}
        for path, body in files.items():
            target = nested
            parts = path.split("/")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = body

        def tree(items):
            entries = []
            for name, value in sorted(items.items()):
                mode = b"40000" if isinstance(value, dict) else b"100644"
                identity = tree(value) if isinstance(value, dict) else put("blob", value)
                entries.append(mode + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(identity))
            return put("tree", b"".join(entries))

        root = tree(nested)
        commit = put("commit", (
            f"tree {root}\nauthor Fixture <fixture@example.org> 0 +0000\n"
            "committer Fixture <fixture@example.org> 0 +0000\n\nSynthetic source\n"
        ).encode("ascii"))
        return dataclasses.replace(self.source, revision=SourceRevision("git-commit", commit))

    def snapshot(self, files=None):
        reader = self.reader()
        source = self.populate(reader, files)
        snapshot = self.root / "snapshot"
        sources.write_snapshot(reader, source, snapshot)
        return source, snapshot

    def test_exact_tree_round_trip_has_no_git_and_preserves_blob_bytes(self):
        source, snapshot = self.snapshot()
        tree = sources.verify_snapshot(snapshot, source)
        self.assertEqual(b"pinned bytes\r\n", (tree / "README.md").read_bytes())
        self.assertEqual(b"example\x00bytes\n", (tree / "src/example.txt").read_bytes())
        self.assertFalse((tree / ".git").exists())

    def test_cache_proof_is_authenticated_by_commit_not_editable_digest_metadata(self):
        source, snapshot = self.snapshot()
        proof_path = snapshot / "proof.json"
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        identity = next(iter(proof["trees"]))
        payload = base64.b64decode(proof["trees"].pop(identity)) + b"invalid"
        proof["trees"][sources.object_id("tree", payload)] = base64.b64encode(payload).decode("ascii")
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        with self.assertRaisesRegex(sources.CorpusError, "proof"):
            sources.verify_snapshot(snapshot, source)

    def test_tampered_ignored_named_file_is_not_hidden_by_git_status(self):
        source, snapshot = self.snapshot({".gitignore": b"ignored.txt\n", "ignored.txt": b"original"})
        (snapshot / "tree/ignored.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(sources.CorpusError, "bytes do not match"):
            sources.verify_snapshot(snapshot, source)

    def test_extra_and_missing_files_and_directories_are_rejected(self):
        source, snapshot = self.snapshot()
        extra = snapshot / "tree/.ignored-note"
        extra.write_bytes(b"local note")
        with self.assertRaisesRegex(sources.CorpusError, "extra file"):
            sources.verify_snapshot(snapshot, source)
        extra.unlink()
        (snapshot / "tree/empty").mkdir()
        with self.assertRaisesRegex(sources.CorpusError, "extra directory"):
            sources.verify_snapshot(snapshot, source)
        (snapshot / "tree/empty").rmdir()
        (snapshot / "tree/README.md").unlink()
        with self.assertRaisesRegex(sources.CorpusError, "missing"):
            sources.verify_snapshot(snapshot, source)

    def test_hardlinked_blob_is_rejected(self):
        source, snapshot = self.snapshot()
        blob = snapshot / "tree/README.md"
        try:
            os.link(blob, self.root / "outside-copy")
        except OSError as error:
            self.skipTest(f"hardlinks unavailable: {error}")
        with self.assertRaisesRegex(sources.CorpusError, "hardlinked"):
            sources.verify_snapshot(snapshot, source)

    def test_unreadable_expected_empty_subtree_cannot_hide_extra_content(self):
        empty_id = sources.object_id("tree", b"")
        root_body = b"40000 empty\0" + bytes.fromhex(empty_id)
        root_id = sources.object_id("tree", root_body)
        commit = f"tree {root_id}\n\nSynthetic empty subtree\n".encode("ascii")
        source = dataclasses.replace(self.source, revision=SourceRevision("git-commit", sources.object_id("commit", commit)))
        snapshot = self.root / "snapshot"
        empty = snapshot / "tree/empty"
        empty.mkdir(parents=True)
        proof = {
            "schema": 1, "source_id": source.id, "url": source.url,
            "commit": source.revision.value, "commit_object": base64.b64encode(commit).decode("ascii"),
            "trees": {root_id: base64.b64encode(root_body).decode("ascii"), empty_id: ""},
        }
        (snapshot / "proof.json").write_text(json.dumps(proof), encoding="utf-8")
        sources.verify_snapshot(snapshot, source)
        (empty / "hidden.txt").write_bytes(b"not part of the pinned tree")
        original_scandir = os.scandir

        def unreadable(path):
            if Path(path) == empty:
                raise PermissionError("synthetic unreadable directory")
            return original_scandir(path)

        with mock.patch.object(os, "scandir", side_effect=unreadable):
            with self.assertRaisesRegex(sources.CorpusError, "cannot inspect"):
                sources.verify_snapshot(snapshot, source)
            with self.assertRaisesRegex(sources.CorpusError, "cannot inspect"):
                sources.tree_bytes(snapshot)

    def test_hardlinked_proof_is_rejected(self):
        source, snapshot = self.snapshot()
        try:
            os.link(snapshot / "proof.json", self.root / "outside-proof")
        except OSError as error:
            self.skipTest(f"hardlinks unavailable: {error}")
        with self.assertRaisesRegex(sources.CorpusError, "hardlinked"):
            sources.verify_snapshot(snapshot, source)

    def test_reparse_metadata_is_rejected_even_without_symlink_mode(self):
        information = mock.Mock(st_mode=0o100644, st_nlink=1, st_file_attributes=0x400)
        path = mock.Mock()
        path.lstat.return_value = information
        with self.assertRaisesRegex(sources.CorpusError, "reparse"):
            sources.checked_path(path)

    def test_symlinked_snapshot_ancestor_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        linked = self.root / "linked"
        try:
            linked.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with self.assertRaisesRegex(sources.CorpusError, "linked"):
            sources.checked_ancestors(linked / "child")

    def test_public_fetch_requires_explicit_host_and_public_access(self):
        with self.assertRaisesRegex(sources.CorpusError, "--allow-host"):
            sources.allowed_url(self.source, [])
        with self.assertRaises(sources.CorpusError):
            sources.allowed_url(self.source, ["github.com"])
        with self.assertRaises(sources.CorpusError):
            sources.allowed_url(dataclasses.replace(self.source, access="authenticated"), ["example.org"])
        self.assertEqual(self.source.url, sources.allowed_url(self.source, ["example.org"]))

    def test_local_credential_port_redirect_and_option_urls_are_not_public_transport(self):
        credential_url = "https://" + ":".join(("fixture-user", "fixture-value")) + "@example.org/project"
        for url in (
            "file:" + "/" * 3 + "synthetic/source", "--upload-pack=bad", "ssh://example.org/project",
            credential_url, "https://example.org:443/project",
            "https://example.org/project?page=1", "https://example.org/project#fragment",
            "https://example.org/%2fproject", "https://example.org/project\\other",
        ):
            with self.subTest(url=url), self.assertRaises(sources.CorpusError):
                sources.allowed_url(dataclasses.replace(self.source, url=url), ["example.org"])

    def test_unsafe_paths_devices_collisions_and_non_regular_tree_modes_fail(self):
        for name in (b"..", b".git", b".GiT", b"CON.txt", b"COM1.cpp", b"name:stream", b"tail.", b"tail ", b"a\\b", b"name~1", b"\xff"):
            with self.subTest(name=name), self.assertRaises(sources.CorpusError):
                sources.path_component(name)
        for mode in (b"120000", b"160000"):
            with self.subTest(mode=mode), self.assertRaisesRegex(sources.CorpusError, "unsupported"):
                sources.tree_entries(mode + b" link\0" + b"\0" * 20)
        tree = b"100644 Name\0" + b"1" * 20 + b"100644 name\0" + b"2" * 20
        identity = sources.object_id("tree", tree)
        with self.assertRaisesRegex(sources.CorpusError, "colliding"):
            sources.expected_tree(identity, {identity: tree})

    def test_unicode_normalized_collisions_fail(self):
        tree = b"100644 " + "é".encode("utf-8") + b"\0" + b"1" * 20
        tree += b"100644 " + "e\u0301".encode("utf-8") + b"\0" + b"2" * 20
        identity = sources.object_id("tree", tree)
        with self.assertRaisesRegex(sources.CorpusError, "colliding"):
            sources.expected_tree(identity, {identity: tree})

    def test_exclusive_source_lock_is_not_reclaimed_or_removed_by_contender(self):
        with sources.source_lock(self.cache, "example"):
            lock = self.cache / "locks/example.lock"
            before = lock.read_bytes()
            with self.assertRaisesRegex(sources.CorpusError, "locked"):
                with sources.source_lock(self.cache, "example"):
                    self.fail("a second owner acquired the same lock")
            self.assertEqual(before, lock.read_bytes())
        self.assertFalse(lock.exists())

    def test_unowned_nonempty_cache_is_not_adopted(self):
        path = self.root / "unowned"
        path.mkdir()
        note = path / "notes.txt"
        note.write_bytes(b"mine")
        with self.assertRaisesRegex(sources.CorpusError, "nonempty"):
            sources.cache_root(path, self.corpus, create=True)
        self.assertEqual(b"mine", note.read_bytes())
        self.assertFalse((path / "cache.json").exists())

    def test_cache_is_outside_corpus_and_git_worktrees_including_gitfiles(self):
        with self.assertRaisesRegex(sources.CorpusError, "outside the canonical corpus"):
            sources.cache_root(self.corpus / "cache", self.corpus, create=True)
        repository = self.root / "worktree"
        repository.mkdir()
        (repository / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        with self.assertRaisesRegex(sources.CorpusError, "outside Git"):
            sources.cache_root(repository / "cache", self.corpus, create=True)
        self.assertFalse((repository / "cache").exists())

    def test_status_is_offline_and_does_not_create_a_cache(self):
        missing = self.root / "not-created"
        output = io.StringIO()
        with mock.patch.object(sources, "GitReader", side_effect=AssertionError("network or Git used")), contextlib.redirect_stdout(output):
            result = sources.main(["--corpus", str(self.corpus), "--cache-root", str(missing), "status"])
        self.assertEqual(0, result)
        self.assertIn("missing\texample", output.getvalue())
        self.assertFalse(missing.exists())

    def test_cli_requires_cache_and_never_exposes_old_mutators(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, sources.main(["--corpus", str(self.corpus), "status"]))
            for command in ("pin", "sync", "materialize", "prune", "reset"):
                with self.assertRaises(SystemExit):
                    sources.parser().parse_args(["--corpus", str(self.corpus), command])

    def test_hostile_ambient_git_configuration_does_not_reach_child(self):
        global_config = self.root / "hostile.gitconfig"
        global_config.write_text("[danger]\n injected = yes\n[credential]\n helper = !bad-command\n", encoding="utf-8")
        ambient = {
            "GIT_CONFIG_GLOBAL": str(global_config), "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "danger.injected", "GIT_CONFIG_VALUE_0": "yes",
            "GIT_DIR": str(self.root / "victim.git"), "GIT_OBJECT_DIRECTORY": str(self.root / "victim-objects"),
            "GIT_ASKPASS": "bad-command", "GIT_SSH_COMMAND": "bad-command",
            "HTTPS_PROXY": "https://" + ":".join(("fixture-user", "fixture-value")) + "@example.org", "SSLKEYLOGFILE": str(self.root / "secrets"),
            "LD_PRELOAD": "bad-library", "GIT_CONFIG_PARAMETERS": "'danger.injected=yes'",
        }
        with mock.patch.dict(os.environ, ambient):
            reader = self.reader()
            output = reader.run(["config", "--list"]).decode("utf-8")
        self.assertNotIn("danger.injected", output)
        self.assertNotIn("bad-command", output)
        for name in ("GIT_DIR", "GIT_OBJECT_DIRECTORY", "GIT_CONFIG_COUNT", "GIT_ASKPASS", "HTTPS_PROXY", "SSLKEYLOGFILE", "LD_PRELOAD"):
            self.assertNotIn(name, reader.environment)
        self.assertEqual("1", reader.environment["GIT_NO_REPLACE_OBJECTS"])
        self.assertEqual("https", reader.environment["GIT_ALLOW_PROTOCOL"])

    def test_transport_uses_exact_sha_no_filters_no_submodules_or_mutable_refs(self):
        reader = self.reader()
        with mock.patch.object(reader, "run", return_value=b"") as run:
            reader.fetch(self.source.url, self.source.revision.value)
        command = run.call_args_list[1].args[0]
        self.assertEqual([self.source.url, self.source.revision.value], command[-2:])
        self.assertIn("--depth=1", command)
        self.assertIn("--no-recurse-submodules", command)
        self.assertIn("--no-write-fetch-head", command)
        self.assertFalse(any("filter" in part for part in command))
        self.assertIn("http.followRedirects=false", reader.options)
        self.assertIn("credential.helper=", reader.options)

    def test_fetch_and_reuse_never_contact_transport_for_existing_verified_snapshot(self):
        initial = self.reader()
        source = self.populate(initial)

        def transport(reader, url, commit):
            self.assertEqual(source.url, url)
            self.assertEqual(source.revision.value, commit)
            self.assertEqual(commit, self.populate(reader).revision.value)

        with mock.patch.object(sources.GitReader, "fetch", new=transport):
            tree = sources.fetch(source, self.cache, ["example.org"])
        self.assertEqual(self.cache / "sources/example" / source.revision.value / "tree", tree)
        with mock.patch.object(sources, "GitReader", side_effect=AssertionError("transport used on cache hit")):
            self.assertEqual(tree, sources.fetch(source, self.cache, ["example.org"]))
        self.assertEqual([], list((self.cache / "staging").iterdir()))

    def test_fetch_does_not_repair_tampered_existing_snapshot(self):
        source, snapshot = self.snapshot()
        owner = self.cache / "sources/example"
        owner.mkdir(parents=True)
        destination = owner / source.revision.value
        snapshot.rename(destination)
        changed = destination / "tree/README.md"
        changed.write_bytes(b"my experiment")
        with mock.patch.object(sources, "GitReader", side_effect=AssertionError("transport used")), self.assertRaisesRegex(sources.CorpusError, "bytes do not match"):
            sources.fetch(source, self.cache, ["example.org"])
        self.assertEqual(b"my experiment", changed.read_bytes())

    def test_destination_appearing_during_fetch_is_never_overwritten(self):
        initial = self.reader()
        source = self.populate(initial)
        destination = sources.snapshot_path(self.cache, source)

        def transport(reader, url, commit):
            self.populate(reader)
            destination.mkdir()
            (destination / "keep.txt").write_bytes(b"mine")

        with mock.patch.object(sources.GitReader, "fetch", new=transport), self.assertRaisesRegex(sources.CorpusError, "refusing to overwrite"):
            sources.fetch(source, self.cache, ["example.org"])
        self.assertEqual(b"mine", (destination / "keep.txt").read_bytes())
        self.assertEqual({"keep.txt"}, {path.name for path in destination.iterdir()})
        self.assertFalse((self.cache / "locks/example.lock").exists())

    def test_blob_and_snapshot_resource_limits_refuse_before_publication(self):
        reader = self.reader()
        source = self.populate(reader, {"large.txt": b"0123456789"})
        snapshot = self.root / "snapshot"
        with mock.patch.object(sources, "MAX_FILE_BYTES", 4), self.assertRaisesRegex(sources.CorpusError, "file exceeds"):
            sources.write_snapshot(reader, source, snapshot)
        self.assertFalse(snapshot.exists())

    def test_git_output_and_deadline_limits_stop_the_owned_process(self):
        reader = self.reader()
        with self.assertRaisesRegex(sources.CorpusError, "output limit"):
            reader.run(["--version"], limit=1)
        reader.deadline = 0
        with self.assertRaisesRegex(sources.CorpusError, "time limit"):
            reader.run(["--version"])


if __name__ == "__main__":
    unittest.main()
