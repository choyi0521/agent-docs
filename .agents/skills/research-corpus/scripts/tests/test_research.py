from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1]
REAL_SCHEMA = Path(__file__).resolve().parents[2] / "assets" / "research-record.schema.json"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from research_index.corpus import CorpusError, CorpusPaths, load_catalog, load_corpus  # noqa: E402
from research_index.index import (  # noqa: E402
    build_index,
    current_snapshot,
    implementation_hash,
)
from research_index.query import response_as_json, search  # noqa: E402
from research_index.views import GENERATED_MARKER, render_views  # noqa: E402
from research import _attested_snapshot  # noqa: E402
from research import main as research_main  # noqa: E402


CURRENT_A = "1" * 40
CURRENT_B = "2" * 40
RECORD_A = "cr-2026-08-13-plugin-isolation-a1b2c3d4"
RECORD_B = "cr-2026-08-13-related-boundary-b1c2d3e4"
RECORD_OLD = "cr-2026-08-13-retired-plugin-c1d2e3f4"
GENERAL_RECORD = "rr-2026-08-15-published-method-d1e2f3a4"


class ResearchIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.corpus = Path(self.temporary.name) / "code-research"
        (self.corpus / "catalog").mkdir(parents=True)
        (self.corpus / "docs" / "records").mkdir(parents=True)
        (self.corpus / "schemas").mkdir(parents=True)
        self._write_catalog("source-a", "Source A", CURRENT_A)
        self._write_catalog("source-b", "Source B", CURRENT_B)
        shutil.copyfile(
            REAL_SCHEMA, self.corpus / "schemas" / "research-record.schema.json"
        )
        self._write_json(
            self.corpus / "schemas" / "taxonomy.json",
            {
                "schema": "research-taxonomy/v1",
                "axes": {
                    "domains": {
                        "editor-authoring": {
                            "label": "Editor and authoring",
                            "aliases": ["editor", "에디터"],
                        }
                    },
                    "mechanisms": {
                        "plugin-isolation": {
                            "label": "Plugin isolation",
                            "aliases": ["extension boundary", "플러그인 격리"],
                        },
                        "dependency-boundary": {
                            "label": "Dependency boundary",
                            "aliases": ["module boundary", "모듈 경계"],
                        },
                    },
                    "qualities": {
                        "safety": {"label": "Safety", "aliases": ["safe", "안전성"]}
                    },
                    "platforms": {
                        "desktop": {
                            "label": "Desktop",
                            "aliases": ["desktop", "데스크톱"],
                        }
                    },
                },
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _make_directory_link(self, link: Path, target: Path) -> None:
        if os.name == "nt":
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create Windows junction: {result.stderr}")
        else:
            link.symlink_to(target, target_is_directory=True)

    def _remove_directory_link(self, link: Path) -> None:
        if not os.path.lexists(link):
            return
        if os.name == "nt" and link.is_dir():
            link.rmdir()
        else:
            link.unlink()

    def _write_catalog(self, source_id: str, name: str, commit: str) -> None:
        self._write_json(
            self.corpus / "catalog" / f"{source_id}.json",
            {
                "schema": 2,
                "id": source_id,
                "name": name,
                "kind": "git-repository",
                "url": f"https://example.org/repositories/{source_id}.git",
                "license": "MIT",
                "access": "public",
                "topics": ["editor"],
                "notes": "Fixture",
                "revision": {"kind": "git-commit", "value": commit},
                "retrieved_at": "2026-08-13T00:00:00+00:00",
                "tracking": {
                    "kind": "git-ref",
                    "ref": "HEAD",
                    "default_branch": "main",
                },
            },
        )

    def _write_publication(self, digest: str = "a" * 64) -> None:
        self._write_json(
            self.corpus / "catalog" / "paper.json",
            {
                "schema": 2,
                "id": "paper",
                "name": "A research paper",
                "kind": "publication",
                "url": "https://example.test/paper",
                "license": "CC-BY-4.0",
                "access": "public",
                "topics": ["research"],
                "notes": "Fixture publication",
                "revision": {
                    "kind": "content-digest",
                    "value": "sha256:" + digest,
                },
                "revision_label": "edition 2",
                "retrieved_at": "2026-08-15T00:00:00+00:00",
                "tracking": {
                    "kind": "manual",
                    "note": "Check the publisher edition page",
                },
            },
        )

    def _metadata(
        self,
        record_id: str,
        *,
        title: str,
        mechanism: str = "plugin-isolation",
        status: str = "reviewed",
        source_id: str = "source-a",
        commit: str = CURRENT_A,
        relations: dict[str, list[str]] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": "research/v2",
            "id": record_id,
            "kind": "study",
            "status": status,
            "title": title,
            "question": f"How does {title} work?",
            "summary": f"Evidence about {title}.",
            "facets": {
                "domains": ["editor-authoring"],
                "mechanisms": [mechanism],
                "qualities": ["safety"],
                "platforms": ["desktop"],
            },
            "sources": [
                {
                    "id": source_id,
                    "revision": {"kind": "git-commit", "value": commit},
                    "role": "primary",
                    "locators": [
                        {
                            "id": "entry-point",
                            "kind": "source-tree",
                            "path": "src/extensions/entry.cc",
                            "symbol": "ExtensionHost::Start",
                        }
                    ],
                }
            ],
            "claims": [
                {
                    "id": "boundary-observation",
                    "type": "observation",
                    "statement": "The extension host owns the isolated entry point.",
                    "evidence": [f"{source_id}:entry-point"],
                }
            ],
            "relations": relations
            or {
                "supports": [],
                "contradicts": [],
                "refines": [],
                "supersedes": [],
                "superseded_by": [],
                "related": [],
            },
            "consumers": ["src/editor"],
            "verified_at": "2026-08-13",
            "revalidate_when": ["The pinned source changes"],
        }

    def _write_record(
        self, metadata: dict[str, object], body: str = "Detailed evidence.\n"
    ) -> None:
        path = self.corpus / "docs" / "records" / f"{metadata['id']}.md"
        text = "---\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n---\n"
        text += f"# {metadata['title']}\n\n{body}"
        path.write_text(text, encoding="utf-8")

    def _load(self):
        return load_corpus(CorpusPaths(self.corpus))

    def test_declared_external_docs_root_is_contained_and_keeps_logical_paths(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        central_docs = Path(self.temporary.name) / "published-docs"
        central_docs.mkdir()
        shutil.move(str(self.corpus / "docs" / "records"), central_docs / "records")

        corpus = load_corpus(CorpusPaths(self.corpus, central_docs))

        self.assertEqual(
            f"docs/records/{RECORD_A}.md",
            corpus.records[RECORD_A].relative_path,
        )
        changed = render_views(corpus)
        self.assertTrue(changed)
        self.assertTrue((central_docs / "records" / "_index.md").is_file())
        self.assertTrue((central_docs / "views" / "_index.md").is_file())

    def test_cli_render_reports_logical_paths_for_an_external_docs_root(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        central_docs = Path(self.temporary.name) / "published-docs"
        central_docs.mkdir()
        shutil.move(str(self.corpus / "docs" / "records"), central_docs / "records")
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = research_main(
                [
                    "--corpus",
                    str(self.corpus),
                    "--docs-root",
                    str(central_docs),
                    "render",
                ]
            )
        self.assertEqual(0, exit_code)
        self.assertIn("docs/records/_index.md", output.getvalue())

    def test_clean_rebuild_depends_only_on_tracked_inputs(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        corpus = self._load()
        index_root = self.corpus / "derived-index"
        first = build_index(corpus, index_root, clean=True)
        first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        first_records = (first / "records.jsonl").read_bytes()

        shutil.rmtree(index_root)
        second = build_index(self._load(), index_root, clean=True)
        second_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(first_records, (second / "records.jsonl").read_bytes())

    def test_repeated_clean_build_reuses_only_the_verified_identical_snapshot(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        index_root = self.corpus / "index"
        first = build_index(self._load(), index_root, clean=True)
        for _ in range(5):
            self.assertEqual(first, build_index(self._load(), index_root, clean=True))
        snapshots = [path for path in (index_root / "snapshots").iterdir() if path.is_dir()]
        self.assertEqual([first], snapshots)

    def test_build_uses_one_executable_generation_hash(self) -> None:
        index_root = self.corpus / "index"
        expected = implementation_hash()
        with patch(
            "research_index.index.implementation_hash",
            side_effect=(expected, "f" * 64),
        ) as mocked:
            snapshot = build_index(self._load(), index_root)
        self.assertEqual(1, mocked.call_count)
        self.assertEqual(snapshot, current_snapshot(index_root))

    def test_clean_rebuild_repairs_a_damaged_same_id_snapshot(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        corpus = self._load()
        index_root = self.corpus / "index"
        first = build_index(corpus, index_root, clean=True)
        (first / "search.sqlite3").unlink()

        repaired = build_index(self._load(), index_root, clean=True)
        self.assertNotEqual(first, repaired)
        self.assertFalse((first / "search.sqlite3").exists())
        self.assertTrue((repaired / "search.sqlite3").is_file())
        self.assertTrue(search(repaired, "Plugin isolation").results)

    def test_clean_rebuild_replaces_semantically_tampered_sqlite(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Canonical title"))
        index_root = self.corpus / "index"
        snapshot = build_index(self._load(), index_root, clean=True)
        connection = sqlite3.connect(snapshot / "search.sqlite3")
        try:
            connection.execute(
                "UPDATE records SET title = 'Tampered title' WHERE id = ?", (RECORD_A,)
            )
            connection.commit()
        finally:
            connection.close()
        tampered = search(snapshot, "Tampered title")
        self.assertEqual("Tampered title", tampered.results[0].record["title"])

        rebuilt = build_index(self._load(), index_root, clean=True)
        self.assertNotEqual(snapshot, rebuilt)
        response = search(rebuilt, "Canonical title")
        self.assertEqual("Canonical title", response.results[0].record["title"])
        fallback = search(rebuilt, "Tampered title")
        self.assertNotEqual("Tampered title", fallback.results[0].record["title"])

    def test_read_only_sqlite_uri_encodes_path_metacharacters(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        index_root = self.corpus / "index#fragment"
        snapshot = build_index(self._load(), index_root)
        self.assertEqual(snapshot, current_snapshot(index_root))
        result = search(snapshot, "Plugin isolation")
        self.assertEqual(RECORD_A, result.results[0].record["id"])
        self.assertFalse((self.corpus / "index").exists())

    def test_stale_builder_cannot_roll_back_the_current_pointer(self) -> None:
        metadata = self._metadata(RECORD_A, title="Generation A")
        self._write_record(metadata)
        stale = self._load()
        metadata["title"] = "Generation B"
        self._write_record(metadata)
        current = self._load()
        index_root = self.corpus / "index"
        latest = build_index(current, index_root)

        with self.assertRaisesRegex(CorpusError, "changed during index build"):
            build_index(stale, index_root)
        self.assertEqual(latest, current_snapshot(index_root))

    def test_clean_repair_never_removes_the_snapshot_visible_to_readers(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        index_root = self.corpus / "index"
        first = build_index(self._load(), index_root)
        (first / "records.jsonl").write_text("damaged\n", encoding="utf-8")
        repaired = build_index(self._load(), index_root, clean=True)

        self.assertNotEqual(first, repaired)
        self.assertTrue(first.is_dir())
        self.assertTrue(repaired.is_dir())
        self.assertEqual(repaired, current_snapshot(index_root))

    def test_index_build_refuses_a_junction_mutation_root(self) -> None:
        outside = Path(self.temporary.name) / "outside-index"
        outside.mkdir()
        nominal = self.corpus / "linked-index"
        self._make_directory_link(nominal, outside)
        try:
            with self.assertRaisesRegex(CorpusError, "link or reparse point"):
                build_index(self._load(), nominal, clean=True)
            self.assertEqual([], list(outside.iterdir()))
        finally:
            self._remove_directory_link(nominal)

    def test_index_lock_refuses_a_hardlink_without_writing_its_other_name(self) -> None:
        index_root = self.corpus / "index"
        index_root.mkdir()
        outside = Path(self.temporary.name) / "outside-lock"
        outside.write_bytes(b"")
        os.link(outside, index_root / ".build.lock")

        with self.assertRaisesRegex(CorpusError, "shared research index lock"):
            build_index(self._load(), index_root, clean=True)
        self.assertEqual(b"", outside.read_bytes())

    def test_pointer_writer_retries_a_transient_sharing_violation(self) -> None:
        index_root = self.corpus / "index"
        original_replace = os.replace
        denied = 0

        def flaky_replace(source: object, destination: object) -> None:
            nonlocal denied
            if Path(destination).name == "current.json" and denied < 2:
                denied += 1
                raise PermissionError("simulated sharing violation")
            original_replace(source, destination)

        with patch("research_index.index.os.replace", new=flaky_replace):
            snapshot = build_index(self._load(), index_root)
        self.assertEqual(2, denied)
        self.assertEqual(snapshot, current_snapshot(index_root))

    def test_pointer_reader_retries_a_transient_sharing_violation(self) -> None:
        index_root = self.corpus / "index"
        snapshot = build_index(self._load(), index_root)
        original_read_text = Path.read_text
        denied = 0

        def flaky_read_text(path: Path, *args: object, **kwargs: object) -> str:
            nonlocal denied
            if path.name == "current.json" and denied < 2:
                denied += 1
                raise PermissionError("simulated sharing violation")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", flaky_read_text):
            self.assertEqual(snapshot, current_snapshot(index_root))
        self.assertEqual(2, denied)

    def test_current_snapshot_rejects_incompatible_manifest_and_database_versions(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        index_root = self.corpus / "index"
        snapshot = build_index(self._load(), index_root)
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["index_schema"] = 999
        self._write_json(manifest_path, manifest)
        connection = sqlite3.connect(snapshot / "search.sqlite3")
        try:
            connection.execute(
                "UPDATE metadata SET value = '999' WHERE key = 'index_schema'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(CorpusError, "incompatible index_schema"):
            current_snapshot(index_root)

        snapshot = build_index(self._load(), index_root, clean=True)
        connection = sqlite3.connect(snapshot / "search.sqlite3")
        try:
            connection.execute(
                "UPDATE metadata SET value = '999' WHERE key = 'ranker_version'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(
            CorpusError, "artifact hash mismatch|SQLite metadata has incompatible ranker_version"
        ):
            current_snapshot(index_root)

    def test_current_snapshot_rejects_semantically_tampered_artifacts(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Canonical title"))
        index_root = self.corpus / "index"
        snapshot = build_index(self._load(), index_root)
        connection = sqlite3.connect(snapshot / "search.sqlite3")
        try:
            connection.execute(
                "UPDATE catalog_sources SET name = 'Tampered source' WHERE id = 'source-a'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(CorpusError, "artifact hash mismatch for search.sqlite3"):
            current_snapshot(index_root)

        snapshot = build_index(self._load(), index_root, clean=True)
        with (snapshot / "records.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("tamper\n")
        with self.assertRaisesRegex(CorpusError, "artifact hash mismatch for records.jsonl"):
            current_snapshot(index_root)

    def test_canonical_attestation_rejects_coordinated_artifact_rehash(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Canonical title"))
        index_root = self.corpus / "index"
        snapshot = build_index(self._load(), index_root)
        database = snapshot / "search.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE catalog_sources SET name = 'Coordinated tamper' WHERE id = 'source-a'"
            )
            connection.execute(
                "UPDATE catalog_sources_fts SET name = 'Coordinated tamper' "
                "WHERE source_id = 'source-a'"
            )
            connection.commit()
        finally:
            connection.close()

        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifact_hashes"]["search.sqlite3"] = hashlib.sha256(
            database.read_bytes()
        ).hexdigest()
        self._write_json(manifest_path, manifest)

        self.assertEqual(snapshot, current_snapshot(index_root))
        with self.assertRaisesRegex(CorpusError, "canonical rebuild"):
            with _attested_snapshot(self._load(), index_root):
                pass

    def test_attested_search_uses_the_private_canonical_candidate(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Canonical title"))
        index_root = self.corpus / "index"
        shared = build_index(self._load(), index_root)
        with _attested_snapshot(self._load(), index_root) as attested:
            self.assertNotEqual(shared, attested)
            connection = sqlite3.connect(shared / "search.sqlite3")
            try:
                connection.execute(
                    "UPDATE records SET title = 'Post verify mutation' WHERE id = ?",
                    (RECORD_A,),
                )
                connection.commit()
            finally:
                connection.close()
            response = search(attested, "Canonical title")
            self.assertEqual("Canonical title", response.results[0].record["title"])

    def test_catalog_source_candidates_are_not_presented_as_research_records(self) -> None:
        snapshot = build_index(self._load(), self.corpus / "index")
        response = search(snapshot, "source-a")
        self.assertEqual((), response.results)
        self.assertEqual("no-record-source-candidates", response.coverage)
        self.assertEqual("source-a", response.source_candidates[0]["id"])

    def test_cli_refuses_an_index_after_a_canonical_document_changes(self) -> None:
        metadata = self._metadata(RECORD_A, title="Original title")
        self._write_record(metadata)
        index_root = self.corpus / "index"
        build_index(self._load(), index_root)

        metadata["title"] = "Changed title"
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "index is stale"):
            with _attested_snapshot(self._load(), index_root):
                pass

    def test_ephemeral_search_leaves_no_index_in_the_corpus(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        with redirect_stdout(io.StringIO()):
            exit_code = research_main(
                ["--corpus", str(self.corpus), "search", "Plugin isolation", "--ephemeral"]
            )
        self.assertEqual(0, exit_code)
        self.assertFalse((self.corpus / "cache").exists())

    def test_alias_search_exact_locator_and_inactive_filter(self) -> None:
        self._write_record(
            self._metadata(
                RECORD_A,
                title="Plugin isolation",
                relations={
                    "supports": [],
                    "contradicts": [],
                    "refines": [],
                    "supersedes": [],
                    "superseded_by": [],
                    "related": [RECORD_B],
                },
            )
        )
        self._write_record(
            self._metadata(
                RECORD_B, title="Related boundary", mechanism="dependency-boundary"
            )
        )
        self._write_record(
            self._metadata(RECORD_OLD, title="Retired plugin note", status="retired")
        )
        corpus = self._load()
        snapshot = build_index(corpus, self.corpus / "index")

        response = search(snapshot, "플러그인 격리", limit=10)
        ids = [result.record["id"] for result in response.results]
        self.assertEqual(RECORD_A, ids[0])
        self.assertIn("mechanisms:plugin-isolation", response.results[0].matched_facets)
        self.assertNotIn(RECORD_OLD, ids)
        self.assertIn(RECORD_B, ids, "explicit relation expansion should remain discoverable")

        exact = search(snapshot, "source-a:entry-point")
        self.assertEqual(RECORD_A, exact.results[0].record["id"])
        self.assertTrue(exact.results[0].exact)

        inactive = search(snapshot, "Retired plugin note", include_inactive=True)
        self.assertEqual(RECORD_OLD, inactive.results[0].record["id"])

    def test_natural_korean_particles_and_english_inflections_infer_facets(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        snapshot = build_index(self._load(), self.corpus / "index")

        korean = search(
            snapshot,
            "에디터에서 플러그인 격리를 데스크톱에서 안전성을 높이는 설계",
        )
        self.assertEqual(("editor-authoring",), korean.interpreted_facets["domains"])
        self.assertEqual(("plugin-isolation",), korean.interpreted_facets["mechanisms"])
        self.assertEqual(("safety",), korean.interpreted_facets["qualities"])
        self.assertEqual(("desktop",), korean.interpreted_facets["platforms"])

        english = search(snapshot, "How can plugins be isolated safely?")
        self.assertEqual(("plugin-isolation",), english.interpreted_facets["mechanisms"])
        self.assertEqual(("safety",), english.interpreted_facets["qualities"])

    def test_catalog_candidate_scope_discloses_that_record_filters_do_not_apply(self) -> None:
        snapshot = build_index(self._load(), self.corpus / "index")
        response = search(
            snapshot,
            "source-a",
            filters={"platforms": ["desktop"]},
        )
        self.assertTrue(response.source_candidates)
        self.assertIn("facet filters do not apply", response.source_candidate_scope)
        encoded = response_as_json(response)
        self.assertIn("facet filters do not apply", encoded["source_candidate_scope"])

    def test_hard_filter_is_applied_before_the_fts_candidate_cap(self) -> None:
        for index in range(201):
            record_id = f"cr-2026-08-13-aa-noise-{index:08x}"
            self._write_record(self._metadata(record_id, title="Plugin isolation"))
        target_id = "cr-2026-08-13-zz-target-deadbeef"
        self._write_record(
            self._metadata(
                target_id,
                title="Plugin isolation",
                mechanism="dependency-boundary",
            )
        )
        snapshot = build_index(self._load(), self.corpus / "index")
        response = search(
            snapshot,
            "Plugin isolation",
            filters={"mechanisms": ["dependency-boundary"]},
        )
        self.assertEqual(target_id, response.results[0].record["id"])

    def test_incoming_relation_explanation_preserves_edge_direction(self) -> None:
        self._write_record(
            self._metadata(
                RECORD_A,
                title="Alpha evidence",
                relations={
                    "supports": [RECORD_B],
                    "contradicts": [],
                    "refines": [],
                    "supersedes": [],
                    "superseded_by": [],
                    "related": [],
                },
            )
        )
        self._write_record(self._metadata(RECORD_B, title="Supported record"))
        snapshot = build_index(self._load(), self.corpus / "index")
        response = search(snapshot, "Supported record")
        neighbor = next(result for result in response.results if result.record["id"] == RECORD_A)
        self.assertIn(f"{RECORD_A} --supports--> {RECORD_B}", neighbor.relation_paths)

    def test_empty_query_does_not_match_an_omitted_locator_symbol(self) -> None:
        metadata = self._metadata(RECORD_A, title="Plugin isolation")
        del metadata["sources"][0]["locators"][0]["symbol"]  # type: ignore[index]
        self._write_record(metadata)
        snapshot = build_index(self._load(), self.corpus / "index")
        self.assertEqual((), search(snapshot, "").results)

    def test_source_revision_movement_is_derived_health_not_data_loss(self) -> None:
        self._write_record(
            self._metadata(RECORD_A, title="Historical evidence", commit="a" * 40)
        )
        record = self._load().records[RECORD_A]
        self.assertEqual(("source-revision-stale:source-a",), record.health)

    def test_status_names_the_cited_and_catalog_revisions_for_revalidation(self) -> None:
        self._write_record(
            self._metadata(RECORD_A, title="Historical evidence", commit="a" * 40)
        )
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = research_main(
                ["--corpus", str(self.corpus), "status", "--json"]
            )

        self.assertEqual(0, exit_code)
        status = json.loads(output.getvalue())[0]
        self.assertEqual("revalidation-required", status["state"])
        self.assertEqual("a" * 40, status["sources"][0]["cited_revision"]["value"])
        self.assertEqual(CURRENT_A, status["sources"][0]["catalog_revision"]["value"])

    def test_non_git_publication_revision_and_document_locator_are_indexed(self) -> None:
        self._write_publication()
        metadata = self._metadata(GENERAL_RECORD, title="Published method")
        metadata["sources"] = [
            {
                "id": "paper",
                "revision": {
                    "kind": "content-digest",
                    "value": "sha256:" + "a" * 64,
                },
                "role": "primary",
                "locators": [
                    {
                        "id": "method-section",
                        "kind": "document",
                        "page": "12-14",
                        "section": "3.2 Method",
                        "quote_digest": "sha256:" + "b" * 64,
                    }
                ],
            }
        ]
        metadata["claims"][0]["evidence"] = ["paper:method-section"]  # type: ignore[index]
        self._write_record(metadata)

        corpus = self._load()
        self.assertEqual((), corpus.records[GENERAL_RECORD].health)
        snapshot = build_index(corpus, self.corpus / "index")
        response = search(snapshot, "paper:method-section")
        self.assertEqual(GENERAL_RECORD, response.results[0].record["id"])
        locator = response.results[0].record["locators"][0]
        self.assertEqual("document", locator["kind"])
        self.assertEqual("12-14", locator["page"])

    def test_non_git_revision_movement_is_derived_health(self) -> None:
        self._write_publication("a" * 64)
        metadata = self._metadata(RECORD_A, title="Historical paper")
        metadata["sources"] = [
            {
                "id": "paper",
                "revision": {
                    "kind": "content-digest",
                    "value": "sha256:" + "c" * 64,
                },
                "role": "primary",
                "locators": [
                    {"id": "method", "kind": "document", "section": "Method"}
                ],
            }
        ]
        metadata["claims"][0]["evidence"] = ["paper:method"]  # type: ignore[index]
        self._write_record(metadata)

        self.assertEqual(
            ("source-revision-stale:paper",), self._load().records[RECORD_A].health
        )

    def test_document_locator_requires_a_precise_coordinate(self) -> None:
        self._write_publication()
        metadata = self._metadata(RECORD_A, title="Imprecise paper")
        metadata["sources"] = [
            {
                "id": "paper",
                "revision": {
                    "kind": "content-digest",
                    "value": "sha256:" + "a" * 64,
                },
                "role": "primary",
                "locators": [{"id": "method", "kind": "document"}],
            }
        ]
        metadata["claims"][0]["evidence"] = ["paper:method"]  # type: ignore[index]
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "requires page, section, or quote_digest"):
            self._load()

    def test_unknown_evidence_locator_is_rejected(self) -> None:
        metadata = self._metadata(RECORD_A, title="Broken evidence")
        metadata["claims"][0]["evidence"] = ["source-a:missing"]  # type: ignore[index]
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "unknown locator"):
            self._load()

    def test_taxonomy_views_link_to_single_canonical_record(self) -> None:
        phrase = "UNIQUE-NARRATIVE-MUST-NOT-BE-COPIED"
        self._write_record(
            self._metadata(RECORD_A, title="Plugin isolation"), body=f"{phrase}\n"
        )
        corpus = self._load()
        changed = render_views(corpus)
        self.assertTrue(changed)
        leaf = self.corpus / "docs" / "views" / "by-mechanism" / "plugin-isolation" / "_index.md"
        text = leaf.read_text(encoding="utf-8")
        self.assertIn(f"../../../records/{RECORD_A}.md", text)
        self.assertNotIn(phrase, text)
        self.assertEqual((), render_views(self._load(), check=True))

        leaf.write_text(text + "drift\n", encoding="utf-8")
        self.assertIn(leaf, render_views(self._load(), check=True))

    def test_draft_date_is_not_published_as_completed_evidence_review(self) -> None:
        metadata = self._metadata(RECORD_A, title="Unreviewed question", status="draft")
        self._write_record(metadata)
        render_views(self._load())
        record = self.corpus / "docs" / "records" / f"{RECORD_A}.md"
        rendered = record.read_text(encoding="utf-8")
        self.assertIn("**Evidence last verified** Not reviewed (draft)", rendered)
        index = (self.corpus / "docs" / "records" / "_index.md").read_text(encoding="utf-8")
        self.assertIn("Not reviewed (draft)", index)
        self.assertEqual("2026-08-13", self._load().records[RECORD_A].verified_at)

    def test_renderer_refuses_unique_content_inside_generated_views(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="Unchanged research"))
        record = self.corpus / "docs" / "records" / f"{RECORD_A}.md"
        before = record.read_bytes()
        manual = self.corpus / "docs" / "views" / "manual.md"
        manual.parent.mkdir(parents=True)
        manual.write_text("# Unique prose\n", encoding="utf-8")
        with self.assertRaisesRegex(CorpusError, "non-generated"):
            render_views(self._load())
        self.assertEqual(before, record.read_bytes())
        self.assertEqual("# Unique prose\n", manual.read_text(encoding="utf-8"))

    def test_catalog_reader_is_independent_of_schemas_and_record_storage(self) -> None:
        sources = load_catalog(self.corpus)
        self.assertEqual({"source-a", "source-b"}, set(sources))
        (self.corpus / "schemas" / "taxonomy.json").unlink()
        self.assertEqual(sources, load_catalog(self.corpus))

    def test_source_identity_accepts_custom_https_host_without_authorizing_acquisition(self) -> None:
        path = self.corpus / "catalog" / "source-a.json"
        item = json.loads(path.read_text(encoding="utf-8"))
        item["url"] = "https://code.example.test/team/source-a.git"
        self._write_json(path, item)
        self.assertEqual(item["url"], load_catalog(self.corpus)["source-a"].url)
        self.assertEqual(item["url"], self._load().sources["source-a"].url)

    def test_source_search_and_jsonl_preserve_retrieval_timestamp(self) -> None:
        snapshot = build_index(self._load(), self.corpus / "cache" / "index")
        result = search(snapshot, "Source A")
        self.assertEqual("2026-08-13T00:00:00+00:00", result.source_candidates[0]["retrieved_at"])
        rows = [json.loads(line) for line in (snapshot / "sources.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual("2026-08-13T00:00:00+00:00", rows[0]["retrieved_at"])

    def test_renderer_refuses_a_view_tree_linked_outside_the_corpus(self) -> None:
        outside = Path(self.temporary.name) / "outside-views"
        outside.mkdir()
        views = self.corpus / "docs" / "views"
        self._make_directory_link(views, outside)
        try:
            with self.assertRaisesRegex(CorpusError, "link or reparse point"):
                render_views(self._load())
            self.assertEqual([], list(outside.iterdir()))
        finally:
            self._remove_directory_link(views)

    def test_renderer_replaces_a_hardlink_without_overwriting_its_other_name(self) -> None:
        outside = Path(self.temporary.name) / "outside-marker.md"
        original = f"{GENERATED_MARKER}\nOUTSIDE-MARKER\n"
        outside.write_text(original, encoding="utf-8")
        view = self.corpus / "docs" / "views" / "_index.md"
        view.parent.mkdir(parents=True)
        os.link(outside, view)

        render_views(self._load())
        self.assertEqual(original, outside.read_text(encoding="utf-8"))
        self.assertNotEqual(original, view.read_text(encoding="utf-8"))
        self.assertFalse(os.path.samefile(outside, view))

    def test_loader_refuses_a_record_tree_linked_outside_the_corpus(self) -> None:
        self._write_record(self._metadata(RECORD_A, title="External record"))
        records = self.corpus / "docs" / "records"
        outside = Path(self.temporary.name) / "outside-records"
        outside.mkdir()
        shutil.move(str(records / f"{RECORD_A}.md"), outside / f"{RECORD_A}.md")
        records.rmdir()
        self._make_directory_link(records, outside)
        try:
            with self.assertRaisesRegex(CorpusError, "link or reparse point"):
                self._load()
        finally:
            self._remove_directory_link(records)
            records.mkdir()

    def test_schema_changes_cannot_be_silently_ignored(self) -> None:
        schema_path = self.corpus / "schemas" / "research-record.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["minItems"] = 1
        self._write_json(schema_path, schema)
        with self.assertRaisesRegex(CorpusError, "unsupported JSON Schema keyword"):
            self._load()

    def test_supported_schema_constraint_next_to_ref_is_enforced(self) -> None:
        schema_path = self.corpus / "schemas" / "research-record.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["properties"]["title"]["pattern"] = "^NEVER$"
        self._write_json(schema_path, schema)
        self._write_record(self._metadata(RECORD_A, title="Plugin isolation"))
        with self.assertRaisesRegex(CorpusError, "does not match"):
            self._load()

    def test_supported_schema_keywords_reject_unimplemented_value_shapes(self) -> None:
        schema_path = self.corpus / "schemas" / "research-record.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["additionalProperties"] = {"type": "string"}
        self._write_json(schema_path, schema)
        with self.assertRaisesRegex(CorpusError, "only boolean values are supported"):
            self._load()

    def test_repository_paths_reject_drive_and_noncanonical_segments(self) -> None:
        for bad_path in ("".join(("Z", ":", "/outside")), "a/./b", "a//b"):
            with self.subTest(path=bad_path):
                metadata = self._metadata(RECORD_A, title="Plugin isolation")
                metadata["sources"][0]["locators"][0]["path"] = bad_path  # type: ignore[index]
                self._write_record(metadata)
                with self.assertRaisesRegex(CorpusError, "repository-relative path"):
                    self._load()

        metadata = self._metadata(RECORD_A, title="Plugin isolation")
        metadata["consumers"] = ["".join(("Z", ":", "/outside"))]
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "repository-relative path"):
            self._load()

    def test_nested_record_is_rejected_instead_of_ignored(self) -> None:
        nested = self.corpus / "docs" / "records" / "2026" / "ignored.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("not a record\n", encoding="utf-8")
        with self.assertRaisesRegex(CorpusError, "nested research records are not supported"):
            self._load()

    def test_nested_catalog_content_is_rejected_instead_of_ignored(self) -> None:
        nested = self.corpus / "catalog" / "nested"
        nested.mkdir()
        (nested / "hidden.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(CorpusError, "flat JSON manifests"):
            self._load()

    def test_duplicate_json_keys_are_rejected(self) -> None:
        metadata = self._metadata(RECORD_A, title="First title")
        encoded = json.dumps(metadata, ensure_ascii=False, indent=2)
        encoded = encoded.replace(
            '"title": "First title"',
            '"title": "First title",\n  "title": "Second title"',
            1,
        )
        path = self.corpus / "docs" / "records" / f"{RECORD_A}.md"
        path.write_text(f"---\n{encoded}\n---\n# Duplicate\n", encoding="utf-8")
        with self.assertRaisesRegex(CorpusError, "duplicate object key 'title'"):
            self._load()

    def test_nonstandard_json_constants_are_rejected(self) -> None:
        path = self.corpus / "catalog" / "source-a.json"
        text = path.read_text(encoding="utf-8").replace('"notes": "Fixture"', '"notes": NaN')
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(CorpusError, "non-standard JSON constant 'NaN'"):
            self._load()

    def test_input_change_during_capture_is_rejected(self) -> None:
        metadata = self._metadata(RECORD_A, title="Generation A")
        self._write_record(metadata)
        record_path = self.corpus / "docs" / "records" / f"{RECORD_A}.md"
        original_read_bytes = Path.read_bytes
        changed = False

        def racing_read(path: Path) -> bytes:
            nonlocal changed
            data = original_read_bytes(path)
            if path == record_path and not changed:
                changed = True
                metadata["title"] = "Generation B"
                self._write_record(metadata)
            return data

        with patch.object(Path, "read_bytes", racing_read):
            with self.assertRaisesRegex(CorpusError, "changed while being read"):
                self._load()

    def test_reviewed_record_requires_structured_observation_evidence(self) -> None:
        metadata = self._metadata(RECORD_A, title="Reviewed evidence")
        metadata["sources"][0]["locators"] = []  # type: ignore[index]
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "source requires a precise locator"):
            self._load()

        metadata = self._metadata(RECORD_A, title="Reviewed evidence")
        metadata["claims"] = [
            {
                "id": "recommendation-only",
                "type": "recommendation",
                "statement": "Adopt the pattern.",
                "evidence": [],
            }
        ]
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "evidence-backed observation"):
            self._load()

        metadata = self._metadata(RECORD_A, title="Reviewed evidence")
        metadata["revalidate_when"] = []
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "revalidation trigger"):
            self._load()

    def test_verified_at_requires_rfc_full_date_shape(self) -> None:
        metadata = self._metadata(RECORD_A, title="Plugin isolation")
        metadata["verified_at"] = "20260813"
        self._write_record(metadata)
        with self.assertRaisesRegex(CorpusError, "YYYY-MM-DD|full-date"):
            self._load()

    def _write_local_catalog(self, pinned: str = "3" * 40) -> None:
        self._write_json(
            self.corpus / "catalog" / "workspace.json",
            {
                "schema": 2,
                "id": "workspace",
                "name": "This repository",
                "kind": "local-repository",
                "license": "proprietary",
                "access": "restricted",
                "topics": ["editor"],
                "notes": "Fixture local repository",
                "revision": {"kind": "git-commit", "value": pinned},
                "retrieved_at": "2026-08-15T00:00:00+00:00",
                "tracking": {"kind": "local-head"},
            },
        )

    def test_local_repository_citations_are_not_graded_by_the_catalog_pin(self) -> None:
        # The local repository advances every commit; a record citing an
        # older commit is graded by per-path drift, never by pin comparison.
        self._write_local_catalog(pinned="3" * 40)
        metadata = self._metadata(
            RECORD_A, title="Local evidence", source_id="workspace", commit="4" * 40
        )
        self._write_record(metadata)
        corpus = self._load()
        self.assertEqual((), corpus.records[RECORD_A].health)

    def test_local_repository_without_url_builds_search_index(self) -> None:
        self._write_local_catalog()

        snapshot = build_index(self._load(), self.corpus / "index", clean=True)
        connection = sqlite3.connect(snapshot / "search.sqlite3")
        try:
            row = connection.execute(
                "SELECT source_kind, url FROM catalog_sources WHERE id = ?",
                ("workspace",),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(("local-repository", None), row)

    def test_local_repository_manifest_rules(self) -> None:
        self._write_local_catalog()
        manifest = json.loads(
            (self.corpus / "catalog" / "workspace.json").read_text(encoding="utf-8")
        )

        with_url = dict(manifest, url="https://example.test/self")
        self._write_json(self.corpus / "catalog" / "workspace.json", with_url)
        with self.assertRaisesRegex(CorpusError, "must omit url"):
            self._load()

        manual = dict(manifest, tracking={"kind": "manual", "note": "no"})
        self._write_json(self.corpus / "catalog" / "workspace.json", manual)
        with self.assertRaisesRegex(CorpusError, "cannot use manual tracking"):
            self._load()

        digest = dict(
            manifest, revision={"kind": "content-digest", "value": "sha256:" + "a" * 64}
        )
        self._write_json(self.corpus / "catalog" / "workspace.json", digest)
        with self.assertRaisesRegex(CorpusError, "requires revision.kind 'git-commit'"):
            self._load()


class LocalDriftTests(unittest.TestCase):
    """Per-path status in an explicit consumer repository; never re-pin evidence."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self._run("init", "--quiet", "--initial-branch=main")
        self._run("config", "user.email", "fixture@example.test")
        self._run("config", "user.name", "Fixture")
        (self.repo / "cited.txt").write_text("v1\n", encoding="utf-8")
        (self.repo / "untouched.txt").write_text("stable\n", encoding="utf-8")
        self._run("add", ".")
        self._run("commit", "--quiet", "-m", "first")
        self.first = self._run("rev-parse", "HEAD").strip()
        (self.repo / "cited.txt").write_text("v2\n", encoding="utf-8")
        self._run("add", "cited.txt")
        self._run("commit", "--quiet", "-m", "second")
        self.head = self._run("rev-parse", "HEAD").strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            capture_output=True, text=True, check=True, errors="replace",
        )
        return result.stdout

    def test_drift_is_graded_per_cited_path(self) -> None:
        import research

        cache: dict[tuple[str, str], dict[str, object]] = {}
        moved = research._local_path_drift(self.first, "cited.txt", cache, repository_root=self.repo)
        stable = research._local_path_drift(self.first, "untouched.txt", cache, repository_root=self.repo)
        unknown = research._local_path_drift("f" * 40, "cited.txt", cache, repository_root=self.repo)
        self.assertEqual({"state": "drifted", "changes": 1}, moved)
        self.assertEqual({"state": "current"}, stable)
        self.assertEqual("unverifiable", unknown["state"])

    def test_local_status_requires_an_explicit_repository(self) -> None:
        import research
        result = research._local_path_drift(self.first, "cited.txt", {})
        self.assertEqual("unverifiable", result["state"])
        self.assertIn("--repository-root", result["detail"])

    def test_dirty_referenced_path_is_drifted_without_committing(self) -> None:
        import research
        (self.repo / "untouched.txt").write_text("uncommitted\n", encoding="utf-8")
        result = research._local_path_drift(self.head, "untouched.txt", {}, repository_root=self.repo)
        self.assertEqual({"state": "drifted", "changes": 0, "dirty": True}, result)

    def test_ambient_git_directory_does_not_redirect_local_status(self) -> None:
        import research
        with patch.dict(os.environ, {"GIT_DIR": str(self.repo / "missing.git"),
                                     "GIT_WORK_TREE": str(self.repo / "missing")}):
            result = research._local_path_drift(self.first, "untouched.txt", {},
                                                repository_root=self.repo)
        self.assertEqual({"state": "current"}, result)

    def test_missing_cited_path_is_unverifiable(self) -> None:
        import research
        result = research._local_path_drift(self.first, "missing.txt", {}, repository_root=self.repo)
        self.assertEqual("unverifiable", result["state"])

    def test_hidden_worktree_flags_cannot_claim_current_evidence(self) -> None:
        import research
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                self._run("update-index", flag, "untouched.txt")
                try:
                    result = research._local_path_drift(self.head, "untouched.txt", {},
                                                        repository_root=self.repo)
                    self.assertEqual("unverifiable", result["state"])
                finally:
                    self._run("update-index", "--no-assume-unchanged", "--no-skip-worktree",
                              "untouched.txt")

    def test_missing_worktree_path_does_not_claim_freshness(self) -> None:
        import research
        (self.repo / "untouched.txt").unlink()
        result = research._local_path_drift(self.head, "untouched.txt", {}, repository_root=self.repo)
        self.assertEqual("unverifiable", result["state"])
        self.assertIn("working tree", result["detail"])

    def test_git_timeout_is_unverifiable(self) -> None:
        import research
        with patch.object(research, "_git", side_effect=subprocess.TimeoutExpired("git", 15)):
            result = research._local_path_drift(self.head, "untouched.txt", {}, repository_root=self.repo)
        self.assertEqual("unverifiable", result["state"])


class PortableWorkspaceTests(unittest.TestCase):
    def test_init_and_new_work_from_an_external_consumer_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            corpus = Path(temporary) / "consumer" / "research"
            prefix = [sys.executable, "-B", str(TOOLS / "research.py"), "--corpus", str(corpus)]
            init = subprocess.run([*prefix, "init"], cwd=temporary, capture_output=True, text=True)
            self.assertEqual(0, init.returncode, init.stderr)
            self.assertEqual({}, load_catalog(corpus))
            self.assertEqual({}, load_corpus(CorpusPaths(corpus)).records)
            landing = (corpus / "docs" / "_index.md").read_bytes()
            self.assertIn(b"  - records/\n  - views/", landing)
            render_views(load_corpus(CorpusPaths(corpus)))
            self.assertEqual(landing, (corpus / "docs" / "_index.md").read_bytes())
            new = subprocess.run([*prefix, "new", "borrow-lifetime", "--title", "Borrow lifetime",
                                  "--question", "When does a borrowed view expire?"],
                                 cwd=temporary, capture_output=True, text=True)
            self.assertEqual(0, new.returncode, new.stderr)
            loaded = load_corpus(CorpusPaths(corpus))
            record = next(iter(loaded.records.values()))
            self.assertEqual("draft", record.status)
            self.assertEqual((), record.sources)
            self.assertEqual(corpus / "cache" / "index", loaded.paths.default_index)
            search_run = subprocess.run([*prefix, "search", "Borrow lifetime", "--ephemeral", "--json"],
                                        cwd=temporary, capture_output=True, text=True)
            self.assertEqual(0, search_run.returncode, search_run.stderr)
            found = json.loads(search_run.stdout)
            self.assertEqual(record.id, found["results"][0]["id"])
            self.assertEqual("partial-or-stale-candidates", found["coverage"])
            self.assertFalse((corpus / "cache").exists())
            self.assertIn("/cache/", (corpus / ".gitignore").read_text(encoding="utf-8"))

    def test_init_refuses_existing_directory_without_changing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "existing"
            target.mkdir()
            original = target / "keep.txt"
            original.write_text("keep", encoding="utf-8")
            self.assertEqual(1, research_main(["--corpus", str(target), "init"]))
            self.assertEqual([original], list(target.iterdir()))
            self.assertEqual("keep", original.read_text(encoding="utf-8"))

    def test_init_refuses_an_existing_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(1, research_main(["--corpus", temporary, "init"]))
            self.assertEqual([], list(Path(temporary).iterdir()))



if __name__ == "__main__":
    unittest.main()
