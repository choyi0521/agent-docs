from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).with_name("review_comments.py")
SPEC = importlib.util.spec_from_file_location("docs_authoring_review_comments", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class ReviewCommentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temporary.name)
        self.data_path = self.repo / ".agent-docs/review-comments.json"
        self.data_path.parent.mkdir()
        self.comment = {
            "id": "rc_0123456789abcdef0123456789abcdef",
            "route": "/guides/getting-started",
            "anchor": "install",
            "quote": "Run the documented command.",
            "body": "Clarify which directory owns this command.",
            "status": "open",
            "createdAt": "2026-08-24T01:02:03.1234567Z",
            "updatedAt": "2026-08-24T01:02:03.1234567Z",
        }
        self.write({"schemaVersion": 1, "comments": [self.comment]})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, value: object) -> None:
        self.data_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def load(self) -> dict[str, object]:
        return json.loads(self.data_path.read_text(encoding="utf-8"))

    def args(self, *values: str):
        return REVIEW.build_parser().parse_args(
            ["--repo-root", str(self.repo), *values]
        )

    def test_validates_and_reports_a_valid_store(self) -> None:
        document, original = REVIEW.load_document(self.data_path)

        self.assertEqual(document["comments"][0]["id"], self.comment["id"])
        self.assertEqual(original, self.data_path.read_bytes())
        self.assertEqual(
            REVIEW.run(self.args("validate")), "review comments: 1 comment(s), valid\n"
        )

    def test_rejects_unknown_missing_and_duplicate_json_fields(self) -> None:
        cases = []
        unknown_root = {"schemaVersion": 1, "comments": [], "extra": True}
        cases.append((json.dumps(unknown_root), "unknown extra"))
        missing_root = {"schemaVersion": 1}
        cases.append((json.dumps(missing_root), "missing comments"))
        unknown_comment = copy.deepcopy(self.comment)
        unknown_comment["owner"] = "someone"
        cases.append(
            (json.dumps({"schemaVersion": 1, "comments": [unknown_comment]}), "unknown owner")
        )
        cases.append(
            ('{"schemaVersion":1,"schemaVersion":1,"comments":[]}', "duplicate JSON field")
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                self.data_path.write_text(raw, encoding="utf-8")
                with self.assertRaisesRegex(REVIEW.ReviewCommentError, expected):
                    REVIEW.load_document(self.data_path)

    def test_deep_json_fails_closed_without_a_traceback(self) -> None:
        self.data_path.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
        with self.assertRaises(REVIEW.ReviewCommentError):
            REVIEW.load_document(self.data_path)

    def test_oversized_json_integer_fails_closed_without_a_traceback(self) -> None:
        self.data_path.write_text(
            '{"schemaVersion":' + "9" * 5000 + ',"comments":[]}', encoding="utf-8"
        )
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "strict UTF-8 JSON"):
            REVIEW.load_document(self.data_path)

    def test_rejects_invalid_ids_duplicates_status_and_answer_without_reply(self) -> None:
        cases = []
        bad_id = copy.deepcopy(self.comment)
        bad_id["id"] = "0123456789abcdef0123456789abcdef"
        cases.append(([bad_id], "32 lowercase hex"))
        cases.append(([self.comment, copy.deepcopy(self.comment)], "duplicate comment id"))
        bad_status = copy.deepcopy(self.comment)
        bad_status["status"] = "pending"
        cases.append(([bad_status], "status must be one of"))
        unanswered = copy.deepcopy(self.comment)
        unanswered["status"] = "answered"
        cases.append(([unanswered], "reply is required"))
        unresolved = copy.deepcopy(self.comment)
        unresolved["status"] = "resolved"
        cases.append(([unresolved], "reply is required"))
        for comments, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(REVIEW.ReviewCommentError, expected):
                    REVIEW.validate_document({"schemaVersion": 1, "comments": comments})

    def test_optional_persisted_fields_must_be_omitted_instead_of_null(self) -> None:
        for field in ("anchor", "quote", "reply"):
            with self.subTest(field=field):
                comment = copy.deepcopy(self.comment)
                comment[field] = None
                with self.assertRaisesRegex(REVIEW.ReviewCommentError, "must be a string"):
                    REVIEW.validate_document({"schemaVersion": 1, "comments": [comment]})

    def test_shared_schema_limits_match_the_cli_contract(self) -> None:
        schema_path = MODULE_PATH.parents[4] / "schemas/review-comments.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        comment = schema["$defs"]["comment"]
        properties = comment["properties"]

        self.assertEqual(schema["properties"]["schemaVersion"]["const"], REVIEW.SCHEMA_VERSION)
        self.assertEqual(schema["properties"]["comments"]["maxItems"], REVIEW.MAX_COMMENTS)
        self.assertEqual(properties["id"]["pattern"], REVIEW.ID_PATTERN.pattern)
        self.assertEqual(properties["route"]["maxLength"], REVIEW.MAX_ROUTE_UNITS)
        self.assertEqual(properties["anchor"]["maxLength"], REVIEW.MAX_ANCHOR_UNITS)
        self.assertEqual(schema["$defs"]["quoteText"]["maxLength"], REVIEW.MAX_QUOTE_UNITS)
        self.assertEqual(schema["$defs"]["bodyText"]["maxLength"], REVIEW.MAX_BODY_UNITS)
        self.assertEqual(properties["status"]["enum"], list(REVIEW.STATUSES))

    def test_validates_route_anchor_and_text_contracts(self) -> None:
        mutations = [
            ("route", "relative", "absolute site path"),
            ("route", "/a//b", "absolute site path"),
            ("route", "/a?b", "query"),
            ("route", "/a b", "whitespace"),
            ("route", "/a/", "trailing slash"),
            ("route", "/a/../b", "dot path"),
            ("anchor", "#part", "must not contain"),
            ("anchor", "two parts", "whitespace"),
            ("quote", "\u0000", "control"),
            ("body", " padded ", "trimmed"),
            ("body", "\n\t", "must not be blank"),
            ("reply", " padded ", "trimmed"),
        ]
        for field, value, expected in mutations:
            with self.subTest(field=field, value=value):
                comment = copy.deepcopy(self.comment)
                comment[field] = value
                with self.assertRaisesRegex(REVIEW.ReviewCommentError, expected):
                    REVIEW.validate_document({"schemaVersion": 1, "comments": [comment]})

    def test_counts_lengths_as_utf16_code_units(self) -> None:
        valid = copy.deepcopy(self.comment)
        astral = chr(0x1F642)
        valid["route"] = "/" + astral * 255
        valid["body"] = astral * 4000
        REVIEW.validate_document({"schemaVersion": 1, "comments": [valid]})

        invalid_route = copy.deepcopy(valid)
        invalid_route["route"] += astral
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "1..512 UTF-16"):
            REVIEW.validate_document({"schemaVersion": 1, "comments": [invalid_route]})

        invalid_body = copy.deepcopy(valid)
        invalid_body["body"] += astral
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "8000 UTF-16"):
            REVIEW.validate_document({"schemaVersion": 1, "comments": [invalid_body]})

    def test_rejects_invalid_and_reversed_timestamps(self) -> None:
        invalid = copy.deepcopy(self.comment)
        invalid["createdAt"] = "2026-02-30T01:02:03.1234567Z"
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "valid UTC timestamp"):
            REVIEW.validate_document({"schemaVersion": 1, "comments": [invalid]})

        reversed_time = copy.deepcopy(self.comment)
        reversed_time["updatedAt"] = "2026-08-23T01:02:03.1234567Z"
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "must not precede"):
            REVIEW.validate_document({"schemaVersion": 1, "comments": [reversed_time]})

    def test_rejects_oversized_store_and_comment_count(self) -> None:
        self.data_path.write_bytes(b" " * (REVIEW.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "1048576-byte"):
            REVIEW.load_document(self.data_path)

        comments = [copy.deepcopy(self.comment) for _ in range(REVIEW.MAX_COMMENTS + 1)]
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "1000-record"):
            REVIEW.validate_document({"schemaVersion": 1, "comments": comments})

    def test_path_must_remain_in_repo_and_not_cross_reparse_points(self) -> None:
        outside = self.repo.parent / "outside-review-comments.json"
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "inside the repository"):
            REVIEW.resolve_review_data(str(self.repo), str(outside))
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "trimmed nonempty"):
            REVIEW.resolve_review_data(str(self.repo), " data/comments.json ")
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "must be a file"):
            REVIEW.resolve_review_data(str(self.repo), ".agent-docs")

        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "under .agent-docs"):
            REVIEW.resolve_review_data(str(self.repo), "private/comments.json")

        link = self.data_path.parent / "linked"
        target = self.repo / "target"
        target.mkdir()
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symbolic links unavailable: {error}")
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "symlink or reparse"):
            REVIEW.resolve_review_data(str(self.repo), ".agent-docs/linked/comments.json")
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "repository root crosses"):
            REVIEW.resolve_review_data(str(link), "comments.json")

    def test_broken_symlink_in_review_path_is_rejected(self) -> None:
        link = self.data_path.parent / "broken"
        try:
            os.symlink(self.repo / "missing", link, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symbolic links unavailable: {error}")
        self.assertTrue(os.path.lexists(link))
        self.assertFalse(link.exists())
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "symlink or reparse"):
            REVIEW.resolve_review_data(str(self.repo), ".agent-docs/broken/comments.json")

    @unittest.skipUnless(os.name == "nt", "Windows path comparison only")
    def test_absolute_path_containment_is_case_insensitive_on_windows(self) -> None:
        _repo, path = REVIEW.resolve_review_data(
            str(self.repo), str(self.data_path).swapcase()
        )
        self.assertEqual(os.path.normcase(path), os.path.normcase(self.data_path))

    def test_custom_review_data_is_allowed_inside_reserved_directory(self) -> None:
        _repo, path = REVIEW.resolve_review_data(
            str(self.repo), ".agent-docs/team-review.json"
        )
        self.assertEqual(path, self.repo / ".agent-docs/team-review.json")

    def test_path_must_not_be_inside_owned_generated_output(self) -> None:
        output = self.repo / ".agent-docs/generated"
        nested = output / "data"
        nested.mkdir(parents=True)
        (output / REVIEW.OUTPUT_SENTINEL_NAME).write_bytes(REVIEW.OUTPUT_SENTINEL_VALUE)

        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "inside generated output"):
            REVIEW.resolve_review_data(
                str(self.repo), ".agent-docs/generated/data/comments.json"
            )

        (output / REVIEW.OUTPUT_SENTINEL_NAME).write_text("invalid\n", encoding="utf-8")
        _repo, path = REVIEW.resolve_review_data(
            str(self.repo), ".agent-docs/generated/data/comments.json"
        )
        self.assertEqual(path, nested / "comments.json")

    def test_list_is_stably_sorted_and_filterable_and_show_is_exact(self) -> None:
        earlier = copy.deepcopy(self.comment)
        earlier["id"] = "rc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        earlier["createdAt"] = "2026-08-23T01:02:03.1234567Z"
        earlier["updatedAt"] = earlier["createdAt"]
        answered = copy.deepcopy(self.comment)
        answered["id"] = "rc_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        answered["status"] = "answered"
        answered["reply"] = "Updated the guide."
        self.write({"schemaVersion": 1, "comments": [answered, earlier]})

        listed = json.loads(REVIEW.run(self.args("list")))
        self.assertEqual([item["id"] for item in listed], [earlier["id"], answered["id"]])
        filtered = json.loads(REVIEW.run(self.args("list", "--status", "answered")))
        self.assertEqual(filtered, [answered])
        shown = json.loads(REVIEW.run(self.args("show", earlier["id"])))
        self.assertEqual(shown, earlier)

    def test_show_uses_canonical_field_order_independent_of_source_order(self) -> None:
        scrambled = {
            field: self.comment[field]
            for field in reversed(tuple(self.comment))
        }
        self.write({"schemaVersion": 1, "comments": [scrambled]})

        shown = json.loads(
            REVIEW.run(self.args("show", self.comment["id"])),
            object_pairs_hook=dict,
        )
        self.assertEqual(
            list(shown),
            [field for field in REVIEW.COMMENT_FIELD_ORDER if field in self.comment],
        )

    def test_reply_defaults_to_answered_and_writes_atomically(self) -> None:
        timestamp = "2026-08-24T02:03:04.7654321Z"
        with mock.patch.object(REVIEW, "utc_now_timestamp", return_value=timestamp):
            output = json.loads(
                REVIEW.run(self.args("reply", self.comment["id"], "--reply", "Fixed and verified."))
            )

        saved = self.load()["comments"][0]
        self.assertEqual(output["status"], "answered")
        self.assertEqual(saved["reply"], "Fixed and verified.")
        self.assertEqual(saved["updatedAt"], timestamp)
        self.assertEqual(list(self.load()), ["schemaVersion", "comments"])
        self.assertEqual(list(saved), ["id", "route", "anchor", "quote", "body", "status", "reply", "createdAt", "updatedAt"])
        self.assertEqual(list(self.data_path.parent.glob(".*.tmp")), [])
        lock_path = REVIEW._lock_path(self.data_path)
        self.assertTrue(lock_path.is_file())
        self.assertEqual(lock_path.read_bytes(), REVIEW.LOCK_HEADER)

    def test_reply_survives_clock_rollback_without_reversing_updated_at(self) -> None:
        future = "2099-01-01T00:00:00.0000000Z"
        comment = copy.deepcopy(self.comment)
        comment["createdAt"] = future
        comment["updatedAt"] = future
        self.write({"schemaVersion": 1, "comments": [comment]})

        with mock.patch.object(
            REVIEW, "utc_now_timestamp", return_value="2026-01-01T00:00:00.0000000Z"
        ):
            output = json.loads(
                REVIEW.run(self.args("reply", comment["id"], "--reply", "Handled."))
            )
        self.assertEqual(output["updatedAt"], future)
        self.assertEqual(self.load()["comments"][0]["updatedAt"], future)

    def test_keep_open_resolve_and_reopen_preserve_reply(self) -> None:
        with mock.patch.object(
            REVIEW, "utc_now_timestamp", return_value="2026-08-24T02:03:04.0000000Z"
        ):
            kept = json.loads(
                REVIEW.run(
                    self.args(
                        "reply",
                        self.comment["id"],
                        "--reply",
                        "Blocked until the cited source is available.",
                        "--keep-open",
                    )
                )
            )
            self.assertEqual(kept["status"], "open")
            resolved = json.loads(REVIEW.run(self.args("resolve", self.comment["id"])))
            self.assertEqual(resolved["status"], "resolved")
            reopened = json.loads(REVIEW.run(self.args("reopen", self.comment["id"])))
        self.assertEqual(reopened["status"], "open")
        self.assertEqual(reopened["reply"], "Blocked until the cited source is available.")

    def test_resolve_requires_reply_and_reply_requires_reopen_after_resolution(self) -> None:
        original = self.data_path.read_bytes()
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "requires a saved reply"):
            REVIEW.run(self.args("resolve", self.comment["id"]))
        self.assertEqual(self.data_path.read_bytes(), original)

        resolved = copy.deepcopy(self.comment)
        resolved["status"] = "resolved"
        resolved["reply"] = "Previously handled."
        self.write({"schemaVersion": 1, "comments": [resolved]})
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "must be reopened"):
            REVIEW.run(self.args("reply", resolved["id"], "--reply", "Late reply"))

    def test_reply_enforces_request_byte_limit(self) -> None:
        reply = chr(0x754C) * 6000
        with self.assertRaisesRegex(REVIEW.ReviewCommentError, "16384-byte"):
            REVIEW.run(self.args("reply", self.comment["id"], "--reply", reply))

    def test_atomic_update_detects_concurrent_change_and_cleans_temporary_file(self) -> None:
        document, original = REVIEW.load_document(self.data_path)
        with mock.patch.object(REVIEW, "_read_bytes", side_effect=[original, b"changed"]):
            with self.assertRaisesRegex(REVIEW.ReviewCommentError, "changed during"):
                REVIEW.atomic_write(
                    self.repo, self.data_path, expected=original, document=document
                )
        self.assertEqual(self.data_path.read_bytes(), original)
        self.assertEqual(list(self.data_path.parent.glob(".*.tmp")), [])

    def test_atomic_replace_failure_preserves_original_and_cleans_temporary_file(self) -> None:
        document, original = REVIEW.load_document(self.data_path)
        with mock.patch.object(REVIEW.os, "replace", side_effect=OSError("busy")):
            with self.assertRaisesRegex(REVIEW.ReviewCommentError, "atomically update"):
                REVIEW.atomic_write(
                    self.repo, self.data_path, expected=original, document=document
                )
        self.assertEqual(self.data_path.read_bytes(), original)
        self.assertEqual(list(self.data_path.parent.glob(".*.tmp")), [])

    def test_lock_contention_times_out_without_mutating_the_store(self) -> None:
        original = self.data_path.read_bytes()
        with REVIEW.acquire_review_data_lock(self.repo, self.data_path):
            code = (
                "import importlib.util,pathlib,sys;"
                "p=pathlib.Path(sys.argv[1]);"
                "s=importlib.util.spec_from_file_location('review_lock_child',p);"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                "repo=pathlib.Path(sys.argv[2]);data=pathlib.Path(sys.argv[3]);"
                "\ntry:m.acquire_review_data_lock(repo,data,timeout_seconds=0.05)"
                "\nexcept m.ReviewCommentError as e:"
                "\n sys.exit(7 if 'timed out' in str(e) else 8)"
                "\nelse:sys.exit(0)"
            )
            child = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    code,
                    str(MODULE_PATH),
                    str(self.repo),
                    str(self.data_path),
                ],
                check=False,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(child.returncode, 7, child.stderr.decode(errors="replace"))
        self.assertEqual(self.data_path.read_bytes(), original)
        self.assertEqual(REVIEW._lock_path(self.data_path).read_bytes(), REVIEW.LOCK_HEADER)

    def test_abandoned_empty_lock_file_is_initialized_and_reused(self) -> None:
        lock_path = REVIEW._lock_path(self.data_path)
        lock_path.write_bytes(b"")

        with REVIEW.acquire_review_data_lock(self.repo, self.data_path):
            pass
        self.assertEqual(lock_path.read_bytes(), REVIEW.LOCK_HEADER)

    def test_persistent_lock_rejects_invalid_content(self) -> None:
        lock_path = REVIEW._lock_path(self.data_path)
        for invalid in (b"\0", b"not-an-agent-docs-lock\n"):
            with self.subTest(invalid=invalid):
                lock_path.write_bytes(invalid)
                with self.assertRaisesRegex(REVIEW.ReviewCommentError, "invalid content"):
                    REVIEW.acquire_review_data_lock(self.repo, self.data_path)
                self.assertEqual(lock_path.read_bytes(), invalid)

    def test_cli_returns_two_and_does_not_emit_success_on_validation_error(self) -> None:
        self.data_path.write_text("not json", encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = REVIEW.main(["--repo-root", str(self.repo), "validate"])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("review comments error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
