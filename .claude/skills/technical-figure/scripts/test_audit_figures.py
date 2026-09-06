#!/usr/bin/env python3
"""Tests for the strict, opt-in figure bundle audit."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from audit_figures import PNG_SIGNATURE, audit_bundle, main  # noqa: E402
import figure_tools as FIGURE_TOOLS  # noqa: E402


def _png_chunk(kind: bytes, payload: bytes, *, crc: int | None = None) -> bytes:
    assert len(kind) == 4
    chunk = kind + payload
    checksum = zlib.crc32(chunk) if crc is None else crc
    return (
        len(payload).to_bytes(4, "big")
        + chunk
        + checksum.to_bytes(4, "big")
    )


def _png_bytes(
    width: int,
    height: int,
    *,
    raw_scanlines: bytes | None = None,
    compressed: bytes | None = None,
    idat_parts: int = 1,
    chunks_before_idat: tuple[bytes, ...] = (),
    chunks_after_idat: tuple[bytes, ...] = (),
    include_iend: bool = True,
    iend_payload: bytes = b"",
    trailing: bytes = b"",
) -> bytes:
    """Build a complete, decodable 8-bit RGBA PNG for structural tests."""

    ihdr_data = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 6, 0, 0, 0))
    )
    if raw_scanlines is None:
        row = b"\x00" + bytes(max(width, 0) * 4)
        raw_scanlines = row * max(height, 0)
    if compressed is None:
        compressed = zlib.compress(raw_scanlines)
    assert idat_parts >= 1
    quotient, remainder = divmod(len(compressed), idat_parts)
    idat_payloads: list[bytes] = []
    offset = 0
    for index in range(idat_parts):
        part_size = quotient + int(index < remainder)
        idat_payloads.append(compressed[offset : offset + part_size])
        offset += part_size

    result = bytearray(PNG_SIGNATURE)
    result.extend(_png_chunk(b"IHDR", ihdr_data))
    for chunk in chunks_before_idat:
        result.extend(chunk)
    for payload in idat_payloads:
        result.extend(_png_chunk(b"IDAT", payload))
    for chunk in chunks_after_idat:
        result.extend(chunk)
    if include_iend:
        result.extend(_png_chunk(b"IEND", iend_payload))
    result.extend(trailing)
    return bytes(result)


def _rgba_ihdr(width: int = 1, height: int = 1) -> bytes:
    return _png_chunk(
        b"IHDR",
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 6, 0, 0, 0)),
    )


def _corrupt_png_chunk_crc(content: bytes, kind: bytes) -> bytes:
    corrupted = bytearray(content)
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(corrupted):
        length = int.from_bytes(corrupted[offset : offset + 4], "big")
        chunk_type = bytes(corrupted[offset + 4 : offset + 8])
        chunk_end = offset + 12 + length
        if chunk_end > len(corrupted):
            break
        if chunk_type == kind:
            corrupted[chunk_end - 1] ^= 0x01
            return bytes(corrupted)
        offset = chunk_end
    raise AssertionError(f"PNG contains no {kind!r} chunk")


class FigureToolPrivacyTests(unittest.TestCase):
    def test_doctor_redacts_discovered_paths_by_default(self) -> None:
        report = {
            tool: {
                "available": True,
                "path": f"sensitive/location/{tool}.exe",
                "version": "test-version",
                "capability": "test-capability",
                "override": FIGURE_TOOLS.ENV_OVERRIDES[tool],
            }
            for tool in FIGURE_TOOLS.TOOL_NAMES
        }
        output = io.StringIO()
        arguments = SimpleNamespace(json=True, show_paths=False, require=[])

        with mock.patch.object(FIGURE_TOOLS, "probe", return_value=report):
            with redirect_stdout(output):
                result = FIGURE_TOOLS.command_doctor(arguments)

        self.assertEqual(0, result)
        rendered = output.getvalue()
        self.assertNotIn("sensitive/location", rendered)
        self.assertIn("graphviz.exe", rendered)


class FigureAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo_root = Path(self.temporary_directory.name).resolve()
        (self.repo_root / "docs").mkdir()
        (self.repo_root / "docs" / "evidence.md").write_text(
            (
                "# Evidence\n\n"
                "## Authority owner\n\n"
                "## Exact locator\n\n"
                "## Four measured levels\n"
            ),
            encoding="utf-8",
        )

    def _valid_intent(self) -> dict[str, object]:
        return {
            "version": 1,
            "id": "authority-boundary",
            "question": "What crosses the authority boundary?",
            "claim": "Only a validated candidate becomes authoritative.",
            "subject": "candidate artifact",
            "threeSecondTakeaway": "Validation is the only path to authority.",
            "caption": "Only a validated candidate becomes authoritative.",
            "decomposition": {
                "subject": "A candidate artifact.",
                "action": "Validation accepts or refuses it.",
                "constraint": "The owner boundary changes authority.",
                "state": "Candidate or authoritative.",
                "outcome": "Accepted publication or retained prior state.",
            },
            "labelFreeCompositions": [
                {"id": "candidate-a", "model": "A narrow validation gate."},
                {"id": "candidate-b", "model": "Before and after owner states."},
            ],
            "selectedComposition": {
                "id": "candidate-a",
                "reason": "The gate exposes the only authority-changing boundary.",
            },
            "readingOrder": ["candidate", "validation-gate", "authority"],
            "representativeTrace": {
                "status": "pass",
                "entity": "candidate artifact",
                "steps": ["candidate", "validation-gate", "authority"],
            },
            "elements": [
                {
                    "id": "candidate",
                    "meaning": "An untrusted candidate.",
                    "role": "subject",
                    "encoding": "A loose artifact before the boundary.",
                    "whyThisEncoding": "It remains visibly outside the owner.",
                    "evidence": ["docs/evidence.md#authority-owner"],
                    "removalLoss": "The input to validation would disappear.",
                    "svgId": "candidate-shape",
                },
                {
                    "id": "validation-gate",
                    "meaning": "The only authority-changing constraint.",
                    "role": "constraint",
                    "encoding": "A narrow gate with accept and refuse exits.",
                    "whyThisEncoding": "A gate makes refusal spatially explicit.",
                    "evidence": ["https://example.com/contract"],
                    "removalLoss": "Candidate and authority would look equivalent.",
                    "svgId": "gate-shape",
                },
                {
                    "id": "authority",
                    "meaning": "The currently authoritative artifact.",
                    "role": "state",
                    "encoding": "An artifact enclosed by the owner boundary.",
                    "whyThisEncoding": "Enclosure directly expresses ownership.",
                    "evidence": ["docs/evidence.md"],
                    "removalLoss": "The outcome would be absent.",
                    "svgId": "authority-shape",
                },
            ],
            "review": {
                "threeSecond": {
                    "status": "pass",
                    "observation": "The validation gate dominates the composition.",
                },
                "labelSwap": {
                    "status": "pass",
                    "observation": "The boundary geometry is claim-specific.",
                },
                "labelOff": {
                    "status": "pass",
                    "observation": "The gate and two states remain identifiable.",
                },
                "pointAndExplain": {
                    "status": "pass",
                    "observation": "Every logical mark maps to an intent element.",
                },
                "ablation": {
                    "status": "pass",
                    "observation": "Removing any element loses a recorded fact.",
                },
                "counterfactual": {
                    "status": "pass",
                    "observation": "Bypass would require a visible second opening.",
                },
                "thumbnail": {
                    "status": "pass",
                    "observation": "The gate remains the focal point when reduced.",
                },
                "articleTypography": {
                    "status": "pass",
                    "observation": (
                        "At the 704px host width, both visible sizes render between "
                        "15.5px and 18px; the smallest label is 15.5px."
                    ),
                },
                "grayscale": {
                    "status": "pass",
                    "observation": "Containment and position preserve the distinction.",
                },
                "proseDependency": {
                    "status": "pass",
                    "observation": "The state change is visible without page prose.",
                },
                "sourceTruth": {
                    "status": "pass",
                    "observation": "Evidence confirms the sole validation boundary.",
                },
                "arrowVerb": {
                    "status": "not-applicable",
                    "reason": "The composition uses no connector arrows.",
                },
                "boundary": {
                    "status": "pass",
                    "observation": "The enclosing shape is the real owner boundary.",
                },
                "trace": {
                    "status": "pass",
                    "observation": "One artifact can be followed through all states.",
                },
                "blindReview": {
                    "status": "pass",
                    "reviewerLabel": "independent-reviewer",
                    "rendering": "figure.svg rendered at the host article width",
                    "prompt": "Explain what this figure communicates in your own words.",
                    "recovered": {
                        "claim": "Validation is required for authority.",
                        "subject": "candidate artifact",
                        "action": "validation",
                        "constraint": "owner boundary",
                        "status": "candidate becomes authoritative",
                    },
                    "comparison": "The recovered claim matches the authored intent.",
                },
            },
            # Unknown fields are intentionally allowed for richer design records.
            "extraDesignRecord": {"author": "test"},
        }

    def _write_bundle(
        self,
        name: str = "example",
        *,
        intent: dict[str, object] | None = None,
        html: str | None = None,
        svg: str | None = None,
        png_only: bool = False,
    ) -> Path:
        bundle = self.repo_root / "docs" / "figures" / name
        bundle.mkdir(parents=True)
        (bundle / "build.py").write_text("# reproducible build\n", encoding="utf-8")
        (bundle / "figure-intent.json").write_text(
            json.dumps(intent if intent is not None else self._valid_intent()),
            encoding="utf-8",
        )
        asset_name = "figure.png" if png_only else "figure.svg"
        (bundle / "figure.html").write_text(
            html
            if html is not None
            else (
                f'<figure><img src="{asset_name}" alt="">'
                "<figcaption>Only a validated candidate becomes authoritative."
                "</figcaption></figure>"
            ),
            encoding="utf-8",
        )
        if png_only:
            (bundle / "figure.png").write_bytes(_png_bytes(640, 360))
        else:
            (bundle / "figure.svg").write_text(
                svg
                if svg is not None
                else """<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>""",
                encoding="utf-8",
            )
        return bundle

    @staticmethod
    def _codes(diagnostics: list[object]) -> set[str]:
        return {diagnostic.code for diagnostic in diagnostics}

    def test_valid_bundle_passes_and_unknown_fields_are_allowed(self) -> None:
        bundle = self._write_bundle()

        diagnostics = audit_bundle(bundle, self.repo_root)

        self.assertEqual([], diagnostics)

    def test_open_role_vocabulary_passes(self) -> None:
        intent = self._valid_intent()
        elements = []
        order = []
        svg_groups = []
        roles = ("input-authority", "decision-boundary", "retained-outcome")
        for index, role in enumerate(roles):
            element_id = f"element-{index}"
            order.append(element_id)
            elements.append(
                {
                    "id": element_id,
                    "meaning": role,
                    "role": role,
                    "encoding": f"Encoding for {role}.",
                    "whyThisEncoding": f"It directly exposes the {role} fact.",
                    "evidence": ["docs/evidence.md"],
                    "removalLoss": f"The {role} meaning would be lost.",
                    "svgId": f"shape-{index}",
                }
            )
            svg_groups.append(f'<g id="shape-{index}" />')
        intent["elements"] = elements
        intent["readingOrder"] = order
        intent["representativeTrace"] = {
            "status": "pass",
            "entity": "test subject",
            "steps": order,
        }
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 704 300" style="width:100%" '
            'aria-labelledby="title desc"><title id="title">Title</title>'
            '<desc id="desc">Description</desc>'
            + "".join(svg_groups)
            + "</svg>"
        )
        bundle = self._write_bundle(intent=intent, svg=svg)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_current_open_intent_fields_pass(self) -> None:
        intent = self._valid_intent()
        intent["immediateTakeaway"] = intent.pop("threeSecondTakeaway")
        intent["decomposition"] = [
            {
                "id": "authority-change",
                "meaning": "Validation is the only authority-changing boundary.",
            }
        ]
        intent["compositions"] = [
            {"id": "candidate-a", "model": "A narrow validation gate."}
        ]
        intent.pop("labelFreeCompositions")
        review = intent["review"]  # type: ignore[assignment]
        review["firstRead"] = review.pop("threeSecond")  # type: ignore[union-attr]
        review["hostReadability"] = review.pop("articleTypography")  # type: ignore[union-attr]
        review["blindReview"]["recovered"] = (  # type: ignore[index]
            "A candidate becomes authoritative only after validation."
        )
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_kind_is_optional_and_a_declared_kind_passes(self) -> None:
        intent = self._valid_intent()
        intent["kind"] = "contrast"

        self.assertEqual([], audit_bundle(self._write_bundle(intent=intent),
                                          self.repo_root))

    def test_undeclared_kind_is_reported(self) -> None:
        intent = self._valid_intent()
        intent["kind"] = "poster"
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)

        self.assertIn("intent.kind", self._codes(diagnostics))

    def test_empty_kind_is_reported(self) -> None:
        intent = self._valid_intent()
        intent["kind"] = ""
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)

        self.assertIn("intent.kind", self._codes(diagnostics))

    def test_malformed_json_reports_location(self) -> None:
        bundle = self._write_bundle()
        (bundle / "figure-intent.json").write_text(
            '{"question": ', encoding="utf-8"
        )

        diagnostics = audit_bundle(bundle, self.repo_root)

        self.assertIn("intent.json", self._codes(diagnostics))
        self.assertIn("line 1", diagnostics[0].message)

    def test_json_value_and_memory_errors_become_diagnostics(self) -> None:
        bundle = self._write_bundle()
        for error in (ValueError("decoder recursion"), MemoryError()):
            with self.subTest(error=type(error).__name__):
                with mock.patch("audit_figures.json.loads", side_effect=error):
                    diagnostics = audit_bundle(bundle, self.repo_root)
                self.assertIn("intent.json", self._codes(diagnostics))
                self.assertIn(type(error).__name__, diagnostics[0].message)

    def test_version_stable_id_and_caption_are_required(self) -> None:
        intent = self._valid_intent()
        intent["version"] = True
        intent["id"] = "Not Stable"
        intent["caption"] = "  "
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("intent.version", codes)
        self.assertIn("intent.id", codes)
        self.assertIn("intent.field", codes)

    def test_decomposition_is_open_but_must_record_content(self) -> None:
        for name, decomposition, should_pass in (
            ("open-object", {"authority-change": "Validation changes authority."}, True),
            ("open-array", [{"meaning": "Validation changes authority."}], True),
            ("empty-object", {}, False),
            ("empty-array", [], False),
            ("empty-text", {"custom": "  "}, False),
        ):
            with self.subTest(name=name):
                intent = self._valid_intent()
                intent["decomposition"] = decomposition
                bundle = self._write_bundle(name=name, intent=intent)
                codes = self._codes(audit_bundle(bundle, self.repo_root))
                if should_pass:
                    self.assertNotIn("intent.decomposition", codes)
                else:
                    self.assertIn("intent.decomposition", codes)

    def test_composition_entries_and_selected_reference_are_validated(self) -> None:
        intent = self._valid_intent()
        intent["labelFreeCompositions"] = [
            {"id": "candidate-a", "model": "First."},
            {"id": "candidate-a", "model": ""},
        ]
        intent["selectedComposition"] = {"id": "missing", "reason": ""}
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("composition.id-duplicate", codes)
        self.assertIn("composition.model", codes)
        self.assertIn("composition.selected-unknown", codes)
        self.assertIn("composition.selected-reason", codes)

    def test_composition_array_accepts_the_selected_candidate_alone(self) -> None:
        intent = self._valid_intent()
        intent["labelFreeCompositions"] = [
            {"id": "only-one", "model": "Only one composition."}
        ]
        intent["selectedComposition"] = {
            "id": "only-one",
            "reason": "There is no real comparison.",
        }
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_missing_required_top_level_and_element_fields_are_reported(self) -> None:
        intent = self._valid_intent()
        del intent["claim"]
        del intent["elements"][0]["encoding"]  # type: ignore[index]
        intent["elements"][0]["evidence"] = []  # type: ignore[index]
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)
        messages = "\n".join(item.message for item in diagnostics)

        self.assertIn("claim must be a non-empty string", messages)
        self.assertIn("elements[0].encoding", messages)
        self.assertIn("elements[0].evidence must be a non-empty array", messages)

    def test_duplicate_invalid_and_unknown_element_ids_are_reported(self) -> None:
        intent = self._valid_intent()
        first = intent["elements"][0]  # type: ignore[index]
        second = intent["elements"][1]  # type: ignore[index]
        second["id"] = first["id"]  # type: ignore[index]
        intent["elements"][2]["id"] = "Not Stable"  # type: ignore[index]
        intent["readingOrder"] = ["candidate", "candidate", "missing-element"]
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("element.id-duplicate", codes)
        self.assertIn("element.id-format", codes)
        self.assertIn("reading-order.duplicate", codes)
        self.assertIn("reading-order.unknown", codes)

    def test_arbitrary_semantic_role_is_accepted(self) -> None:
        intent = self._valid_intent()
        intent["elements"][0]["role"] = "authority-source"  # type: ignore[index]
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_elements_require_encoding_intent_and_validate_declared_verbs(self) -> None:
        intent = self._valid_intent()
        del intent["elements"][0]["whyThisEncoding"]  # type: ignore[index]
        intent["elements"][1]["verb"] = ""  # type: ignore[index]
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)
        codes = self._codes(diagnostics)

        self.assertIn("element.field", codes)
        self.assertIn("element.verb", codes)

    def test_role_name_does_not_imply_a_verb_field(self) -> None:
        intent = self._valid_intent()
        intent["elements"][1]["role"] = "relationship"  # type: ignore[index]
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_svg_id_mappings_must_be_unique(self) -> None:
        intent = self._valid_intent()
        intent["elements"][1]["svgId"] = "candidate-shape"  # type: ignore[index]
        bundle = self._write_bundle(intent=intent)

        self.assertIn(
            "element.svg-id-duplicate",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_passing_representative_trace_requires_entity_and_known_steps(self) -> None:
        intent = self._valid_intent()
        intent["representativeTrace"] = {
            "status": "pass",
            "entity": "",
            "steps": ["candidate", "unknown-step", 7],
        }
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("trace.entity", codes)
        self.assertIn("trace.step-unknown", codes)
        self.assertIn("trace.step", codes)

    def test_not_applicable_trace_requires_reason_and_pending_is_rejected(self) -> None:
        for name, trace, expected_code in (
            (
                "trace-no-reason",
                {"status": "not-applicable", "reason": ""},
                "trace.reason",
            ),
            ("trace-pending", {"status": "pending"}, "trace.status"),
        ):
            with self.subTest(name=name):
                intent = self._valid_intent()
                intent["representativeTrace"] = trace
                bundle = self._write_bundle(name=name, intent=intent)
                self.assertIn(
                    expected_code,
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_trace_review_status_matches_representative_trace(self) -> None:
        intent = self._valid_intent()
        intent["representativeTrace"] = {
            "status": "not-applicable",
            "reason": "This is a static comparison.",
        }
        bundle = self._write_bundle(intent=intent)

        self.assertIn(
            "review.trace-consistency",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_consistent_not_applicable_trace_is_accepted(self) -> None:
        intent = self._valid_intent()
        intent["representativeTrace"] = {
            "status": "not-applicable",
            "reason": "This is a static comparison.",
        }
        intent["review"]["trace"] = {  # type: ignore[index]
            "status": "not-applicable",
            "reason": "No entity moves or changes state.",
        }
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_core_reviews_require_pass_and_nonempty_observation(self) -> None:
        intent = self._valid_intent()
        intent["review"]["threeSecond"] = {"status": "pending"}  # type: ignore[index]
        intent["review"]["labelSwap"] = {"status": "not-applicable"}  # type: ignore[index]
        intent["review"]["labelOff"] = {  # type: ignore[index]
            "status": "pass",
            "observation": "",
        }
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("review.status", codes)
        self.assertIn("review.observation", codes)

    def test_host_readability_review_or_compatible_alias_is_required(self) -> None:
        intent = self._valid_intent()
        del intent["review"]["articleTypography"]  # type: ignore[index]
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)

        self.assertIn("review.entry", self._codes(diagnostics))
        self.assertIn(
            "review.hostReadability",
            "\n".join(item.message for item in diagnostics),
        )

    def test_conditional_review_n_a_requires_reason(self) -> None:
        intent = self._valid_intent()
        intent["review"]["arrowVerb"] = {  # type: ignore[index]
            "status": "not-applicable",
            "reason": "",
        }
        bundle = self._write_bundle(intent=intent)

        self.assertIn(
            "review.reason", self._codes(audit_bundle(bundle, self.repo_root))
        )

    def test_blind_review_requires_provenance_free_recovery_and_comparison(self) -> None:
        intent = self._valid_intent()
        intent["review"]["blindReview"] = {  # type: ignore[index]
            "status": "pending",
            "reviewerLabel": "",
            "rendering": "",
            "prompt": "",
            "recovered": {"custom": ""},
            "comparison": "",
        }
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("blind-review.status", codes)
        self.assertIn("blind-review.reviewer-label", codes)
        self.assertIn("blind-review.rendering", codes)
        self.assertIn("blind-review.prompt", codes)
        self.assertIn("blind-review.recovered", codes)
        self.assertIn("blind-review.comparison", codes)

    def test_blind_review_accepts_free_recovered_reading(self) -> None:
        for index, recovered in enumerate(
            (
                "A candidate crosses a validation gate before it becomes authoritative.",
                {"reading": "Validation gates the change in authority."},
                ["A candidate crosses the gate.", "The approved result is retained."],
            )
        ):
            with self.subTest(recovered=recovered):
                intent = self._valid_intent()
                intent["review"]["blindReview"]["recovered"] = recovered
                bundle = self._write_bundle(name=f"free-reading-{index}", intent=intent)

                self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_blind_review_rejects_empty_or_nontext_recovery(self) -> None:
        for index, recovered in enumerate(("", "  ", {}, [], {"reading": []}, True, 1)):
            with self.subTest(recovered=recovered):
                intent = self._valid_intent()
                intent["review"]["blindReview"]["recovered"] = recovered
                bundle = self._write_bundle(name=f"empty-reading-{index}", intent=intent)

                self.assertIn(
                    "blind-review.recovered", self._codes(audit_bundle(bundle, self.repo_root))
                )

    def test_blind_review_requires_each_provenance_field(self) -> None:
        for field in ("rendering", "prompt"):
            with self.subTest(field=field):
                intent = self._valid_intent()
                del intent["review"]["blindReview"][field]
                bundle = self._write_bundle(name=f"missing-{field}", intent=intent)

                self.assertIn(
                    f"blind-review.{field}", self._codes(audit_bundle(bundle, self.repo_root))
                )

    def test_existing_artifact_provenance_is_accepted_without_rewriting_it(self) -> None:
        intent = self._valid_intent()
        review = intent["review"]["blindReview"]
        review["artifact"] = review.pop("rendering")
        bundle = self._write_bundle(name="existing-artifact", intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

        review["rendering"] = ""
        bundle = self._write_bundle(name="empty-rendering", intent=intent)
        self.assertIn(
            "blind-review.rendering", self._codes(audit_bundle(bundle, self.repo_root))
        )

    def test_legacy_review_alias_cannot_hide_a_failed_current_review(self) -> None:
        for field in ("firstRead", "hostReadability"):
            with self.subTest(field=field):
                intent = self._valid_intent()
                intent["review"][field] = {"status": "fail", "observation": "Needs review."}
                bundle = self._write_bundle(name=f"failed-{field.lower()}", intent=intent)

                self.assertIn("review.status", self._codes(audit_bundle(bundle, self.repo_root)))

    def test_blind_review_rejects_identifying_reviewer_metadata(self) -> None:
        intent = self._valid_intent()
        intent["review"]["blindReview"]["reviewerLabel"] = (  # type: ignore[index]
            "person@example.com"
        )
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("blind-review.reviewer-label", codes)

    def test_local_evidence_must_exist_and_remain_inside_repo(self) -> None:
        outside = self.repo_root.parent / "outside-evidence.txt"
        outside.write_text("outside", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "../outside-evidence.txt",
            "docs/missing.md",
        ]
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("evidence.outside-root", codes)
        self.assertIn("evidence.missing", codes)

    def test_local_evidence_allows_an_exact_locator_fragment(self) -> None:
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/evidence.md#exact-locator"
        ]
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_local_evidence_accepts_line_heading_marker_and_symbol_locators(self) -> None:
        source = self.repo_root / "docs" / "evidence.cpp"
        source.write_text(
            (
                "namespace evidence {\n"
                "// docs: begin validation-route\n"
                "void publish_candidate();\n"
                "// docs: end validation-route\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/evidence.cpp#L2-L4",
            "docs/evidence.md#authority-owner",
            "docs/evidence.cpp#validation-route",
            "docs/evidence.cpp#publish_candidate",
        ]
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_markdown_evidence_rejects_arbitrary_prose_tokens_only(self) -> None:
        markdown = self.repo_root / "docs" / "locator-surface.md"
        markdown.write_text(
            (
                "# Supported heading\n\n"
                "This prose contains arbitrary-prose-token, but prose is not "
                "an addressable Markdown locator.\n"
            ),
            encoding="utf-8",
        )
        source = self.repo_root / "docs" / "locator-surface.cpp"
        source.write_text(
            (
                "namespace locator_surface {\n"
                "// docs: begin supported-marker\n"
                "void supported_symbol();\n"
                "// docs: end supported-marker\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/locator-surface.md#supported-heading",
            "docs/locator-surface.md#L1-L3",
            "docs/locator-surface.cpp#supported-marker",
            "docs/locator-surface.cpp#supported_symbol",
            "docs/locator-surface.md#arbitrary-prose-token",
        ]
        bundle = self._write_bundle(intent=intent)

        missing = [
            item
            for item in audit_bundle(bundle, self.repo_root)
            if item.code == "evidence.fragment-missing"
        ]

        self.assertEqual(1, len(missing))
        self.assertIn("arbitrary-prose-token", missing[0].message)

    def test_markdown_evidence_ignores_headings_and_ids_in_fenced_code(self) -> None:
        markdown = self.repo_root / "docs" / "fenced-locators.md"
        markdown.write_text(
            (
                "# Real heading\n\n"
                "## Real explicit {#RealExplicit}\n\n"
                "```markdown\n"
                "# Fenced ATX\n\n"
                "Fenced setext\n"
                "=============\n\n"
                "## Fenced explicit {#FencedExplicit}\n"
                '<span id="FencedHtmlId"></span>\n'
                "```\n\n"
                "~~~md\n"
                "# Tilde fenced heading\n"
                "~~~\n"
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/fenced-locators.md#real-heading",
            "docs/fenced-locators.md#RealExplicit",
            "docs/fenced-locators.md#fenced-atx",
            "docs/fenced-locators.md#fenced-setext",
            "docs/fenced-locators.md#FencedExplicit",
            "docs/fenced-locators.md#FencedHtmlId",
            "docs/fenced-locators.md#tilde-fenced-heading",
        ]
        bundle = self._write_bundle(name="fenced-evidence", intent=intent)

        missing = [
            item
            for item in audit_bundle(bundle, self.repo_root)
            if item.code == "evidence.fragment-missing"
        ]

        self.assertEqual(5, len(missing))
        messages = "\n".join(item.message for item in missing)
        for fragment in (
            "fenced-atx",
            "fenced-setext",
            "FencedExplicit",
            "FencedHtmlId",
            "tilde-fenced-heading",
        ):
            self.assertIn(fragment, messages)

    def test_markdown_evidence_ignores_headings_and_ids_in_html_comments(self) -> None:
        markdown = self.repo_root / "docs" / "commented-locators.md"
        markdown.write_text(
            (
                "# Visible heading\n\n"
                "<!--\n"
                "# Commented ATX\n\n"
                "Commented setext\n"
                "-----------------\n\n"
                "## Commented explicit {#CommentExplicit}\n"
                '<span id="CommentHtmlId"></span>\n'
                "-->\n"
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/commented-locators.md#visible-heading",
            "docs/commented-locators.md#commented-atx",
            "docs/commented-locators.md#commented-setext",
            "docs/commented-locators.md#CommentExplicit",
            "docs/commented-locators.md#CommentHtmlId",
        ]
        bundle = self._write_bundle(name="commented-evidence", intent=intent)

        missing = [
            item
            for item in audit_bundle(bundle, self.repo_root)
            if item.code == "evidence.fragment-missing"
        ]

        self.assertEqual(4, len(missing))
        messages = "\n".join(item.message for item in missing)
        for fragment in (
            "commented-atx",
            "commented-setext",
            "CommentExplicit",
            "CommentHtmlId",
        ):
            self.assertIn(fragment, messages)

    def test_markdown_explicit_ids_are_case_sensitive(self) -> None:
        markdown = self.repo_root / "docs" / "case-sensitive-locators.md"
        markdown.write_text(
            (
                "# Visible heading\n\n"
                "## Explicit heading {#MixedCaseId}\n\n"
                '<span id="HtmlMixedCaseId"></span>\n'
                '<a name="RawMixedCaseName"></a>\n'
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/case-sensitive-locators.md#visible-heading",
            "docs/case-sensitive-locators.md#MixedCaseId",
            "docs/case-sensitive-locators.md#HtmlMixedCaseId",
            "docs/case-sensitive-locators.md#RawMixedCaseName",
            "docs/case-sensitive-locators.md#mixedcaseid",
            "docs/case-sensitive-locators.md#htmlmixedcaseid",
            "docs/case-sensitive-locators.md#rawmixedcasename",
        ]
        bundle = self._write_bundle(name="case-sensitive-evidence", intent=intent)

        missing = [
            item
            for item in audit_bundle(bundle, self.repo_root)
            if item.code == "evidence.fragment-missing"
        ]

        self.assertEqual(3, len(missing))
        messages = "\n".join(item.message for item in missing)
        self.assertIn("mixedcaseid", messages)
        self.assertIn("htmlmixedcaseid", messages)
        self.assertIn("rawmixedcasename", messages)

    def test_markdown_evidence_rejects_ids_inside_inline_and_indented_code(
        self,
    ) -> None:
        markdown = self.repo_root / "docs" / "code-span-locators.md"
        markdown.write_text(
            (
                "# Visible heading\n\n"
                "Inline `{#InlineBraceId}` and "
                "`<a id=\"InlineHtmlId\"></a>` are code.\n\n"
                "Double-backtick ``<span id='DoubleInlineId'></span> "
                "{#DoubleBraceId}`` is code too.\n\n"
                "    ## Indented heading {#IndentedHeadingId}\n"
                "    <a id=\"IndentedHtmlId\"></a>\n"
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/code-span-locators.md#visible-heading",
            "docs/code-span-locators.md#InlineBraceId",
            "docs/code-span-locators.md#InlineHtmlId",
            "docs/code-span-locators.md#DoubleInlineId",
            "docs/code-span-locators.md#DoubleBraceId",
            "docs/code-span-locators.md#IndentedHeadingId",
            "docs/code-span-locators.md#IndentedHtmlId",
        ]
        bundle = self._write_bundle(name="code-span-evidence", intent=intent)

        missing = [
            item
            for item in audit_bundle(bundle, self.repo_root)
            if item.code == "evidence.fragment-missing"
        ]

        self.assertEqual(6, len(missing))
        messages = "\n".join(item.message for item in missing)
        for fragment in (
            "InlineBraceId",
            "InlineHtmlId",
            "DoubleInlineId",
            "DoubleBraceId",
            "IndentedHeadingId",
            "IndentedHtmlId",
        ):
            self.assertIn(fragment, messages)

    def test_markdown_evidence_rejects_escaped_html_and_prose_ids(self) -> None:
        markdown = self.repo_root / "docs" / "pseudo-id-locators.md"
        markdown.write_text(
            (
                "# Visible heading\n\n"
                '&lt;a id="EscapedNamedId"&gt;&lt;/a&gt;\n\n'
                "&#60;span id='EscapedNumericId'&#62;&#60;/span&#62;\n\n"
                '&lt;a name="EscapedAnchorName"&gt;&lt;/a&gt;\n\n'
                "Ordinary prose can mention {#ProseBraceId} without creating "
                "a fragment target.\n"
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/pseudo-id-locators.md#visible-heading",
            "docs/pseudo-id-locators.md#EscapedNamedId",
            "docs/pseudo-id-locators.md#EscapedNumericId",
            "docs/pseudo-id-locators.md#EscapedAnchorName",
            "docs/pseudo-id-locators.md#ProseBraceId",
        ]
        bundle = self._write_bundle(name="pseudo-id-evidence", intent=intent)

        missing = [
            item
            for item in audit_bundle(bundle, self.repo_root)
            if item.code == "evidence.fragment-missing"
        ]

        self.assertEqual(4, len(missing))
        messages = "\n".join(item.message for item in missing)
        self.assertIn("EscapedNamedId", messages)
        self.assertIn("EscapedNumericId", messages)
        self.assertIn("EscapedAnchorName", messages)
        self.assertIn("ProseBraceId", messages)

    def test_markdown_evidence_accepts_rendered_heading_and_raw_html_ids(
        self,
    ) -> None:
        markdown = self.repo_root / "docs" / "rendered-id-locators.md"
        markdown.write_text(
            (
                "# Visible heading\n\n"
                "## Explicit heading {#HeadingExplicitId}\n\n"
                '<a class="permalink" id="RawAnchorId"></a>\n'
                '<a name="RawAnchorName"></a>\n'
                "<span id='RawSpanId'></span>\n"
                "<div id=RawUnquotedId></div>\n"
                "<a name=RawUnquotedName></a>\n"
            ),
            encoding="utf-8",
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/rendered-id-locators.md#visible-heading",
            "docs/rendered-id-locators.md#HeadingExplicitId",
            "docs/rendered-id-locators.md#RawAnchorId",
            "docs/rendered-id-locators.md#RawAnchorName",
            "docs/rendered-id-locators.md#RawSpanId",
            "docs/rendered-id-locators.md#RawUnquotedId",
            "docs/rendered-id-locators.md#RawUnquotedName",
        ]
        bundle = self._write_bundle(name="rendered-id-evidence", intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_local_evidence_rejects_missing_and_out_of_range_locators(self) -> None:
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "docs/evidence.md#not-a-real-heading-marker-or-symbol",
            "docs/evidence.md#L999-L1000",
        ]
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)

        missing = [
            item for item in diagnostics if item.code == "evidence.fragment-missing"
        ]
        self.assertEqual(2, len(missing))

    def test_local_evidence_must_be_repo_relative_and_name_a_file(self) -> None:
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            str((self.repo_root / "docs" / "evidence.md").resolve()),
            "docs",
        ]
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("evidence.absolute", codes)
        self.assertIn("evidence.not-file", codes)

    def test_malformed_web_url_and_unsupported_scheme_are_rejected(self) -> None:
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "https:///missing-host",
            "file:" + "///etc/local-record",
        ]
        bundle = self._write_bundle(intent=intent)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("evidence.url", codes)
        self.assertIn("evidence.scheme", codes)

    def test_public_evidence_urls_reject_private_or_secret_bearing_forms(self) -> None:
        intent = self._valid_intent()
        private_label = "".join(
            chr(code) for code in (105, 110, 116, 101, 114, 110, 97, 108)
        )
        private_host_url = "".join(
            ("https", ":", "//", "docs", ".", private_label, ".", "example", ".", "com", "/", "contract")
        )
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "http://example.com/plaintext",
            "https://" + "user:placeholder" + "@example.com/contract",
            "https://example.com/contract?signature=placeholder",
            "https://" + "local" + "host/contract",
            "https://" + ".".join(("127", "0", "0", "1")) + "/contract",
            "https://" + ".".join(("10", "0", "0", "1")) + "/contract",
            private_host_url,
            "https://example.com:8443/contract",
        ]
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)

        policy_errors = [
            item for item in diagnostics if item.code == "evidence.url-policy"
        ]
        self.assertEqual(8, len(policy_errors))
        self.assertTrue(
            all("placeholder" not in item.message for item in policy_errors)
        )

    def test_public_https_evidence_with_a_fragment_is_allowed(self) -> None:
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "https://example.com/contract#published-section"
        ]
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_broader_source_languages_support_symbol_evidence(self) -> None:
        source_root = self.repo_root / "src"
        source_root.mkdir()
        (source_root / "library.rs").write_text(
            "pub fn publish_candidate() {}\n", encoding="utf-8"
        )
        (source_root / "library.go").write_text(
            "package sample\nfunc ValidateCandidate() {}\n", encoding="utf-8"
        )
        (source_root / "library.ts").write_text(
            "export function retainPriorState() {}\n", encoding="utf-8"
        )
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "src/library.rs#publish_candidate",
            "src/library.go#ValidateCandidate",
            "src/library.ts#retainPriorState",
        ]
        bundle = self._write_bundle(intent=intent)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_malformed_evidence_does_not_crash_the_audit(self) -> None:
        intent = self._valid_intent()
        intent["elements"][0]["evidence"] = [  # type: ignore[index]
            "https://" + "[broken-host",
            "docs/\x00bad-path",
        ]
        bundle = self._write_bundle(intent=intent)

        diagnostics = audit_bundle(bundle, self.repo_root)

        self.assertGreaterEqual(len(diagnostics), 2)
        self.assertIn("evidence.url", self._codes(diagnostics))
        self.assertIn("evidence.path", self._codes(diagnostics))

    def test_bundle_itself_must_be_inside_repo(self) -> None:
        other_root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: shutil.rmtree(other_root))

        diagnostics = audit_bundle(other_root, self.repo_root)

        self.assertEqual({"bundle.outside-root"}, self._codes(diagnostics))

    def test_required_bundle_children_must_not_be_symlinks(self) -> None:
        targets = self.repo_root / "symlink-targets"
        targets.mkdir()
        children = (
            ("build", "build.py", False),
            ("intent", "figure-intent.json", False),
            ("html", "figure.html", False),
            ("svg", "figure.svg", False),
            ("png", "figure.png", True),
        )
        for label, filename, png_only in children:
            with self.subTest(filename=filename):
                intent = self._valid_intent()
                if png_only:
                    for element in intent["elements"]:  # type: ignore[union-attr]
                        element.pop("svgId")
                bundle = self._write_bundle(
                    name=f"symlink-{label}", intent=intent, png_only=png_only
                )
                child = bundle / filename
                target = targets / f"{label}-{filename}"
                target.write_bytes(child.read_bytes())
                child.unlink()
                try:
                    os.symlink(target, child)
                except (NotImplementedError, OSError):
                    child.write_bytes(target.read_bytes())

                    def simulated_reparse(root: Path, path: Path) -> Path | None:
                        return path if path == child else None

                    with mock.patch(
                        "audit_figures._first_reparse_below",
                        side_effect=simulated_reparse,
                    ):
                        codes = self._codes(audit_bundle(bundle, self.repo_root))
                else:
                    codes = self._codes(audit_bundle(bundle, self.repo_root))

                self.assertIn(f"{label}.reparse", codes)

    def test_reparse_detection_fails_closed_even_when_the_platform_cannot_link(self) -> None:
        bundle = self._write_bundle()
        svg_path = bundle / "figure.svg"

        def simulated_reparse(root: Path, path: Path) -> Path | None:
            return path if path == svg_path else None

        with mock.patch(
            "audit_figures._first_reparse_below", side_effect=simulated_reparse
        ):
            codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("svg.reparse", codes)

    def test_caption_must_exist_be_visible_and_contain_text(self) -> None:
        variants = {
            "missing": ("<figure></figure>", "caption.missing"),
            "hidden": (
                '<figure hidden><figcaption>A conclusion</figcaption></figure>',
                "caption.hidden",
            ),
            "class-hidden": (
                '<figure><figcaption class="sr-only">A conclusion</figcaption></figure>',
                "caption.hidden",
            ),
            "empty": ("<figure><figcaption>  </figcaption></figure>", "caption.empty"),
        }
        for name, (html, expected_code) in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(name=name, html=html)
                self.assertIn(
                    expected_code, self._codes(audit_bundle(bundle, self.repo_root))
                )

    def test_visible_caption_must_match_the_intent_ledger(self) -> None:
        bundle = self._write_bundle(
            html=(
                '<figure><img src="figure.svg" alt="">'
                "<figcaption>A different conclusion.</figcaption></figure>"
            )
        )

        self.assertIn(
            "caption.intent-mismatch",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_html_requires_figure_and_places_caption_inside_it(self) -> None:
        bundle = self._write_bundle(
            html=(
                '<img src="figure.svg" alt="">'
                "<figcaption>A caption outside any figure.</figcaption>"
            )
        )

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("html.figure", codes)
        self.assertIn("caption.missing", codes)
        self.assertIn("html.figure-content", codes)

    def test_html_requires_canonical_output_or_accessible_inline_svg(self) -> None:
        bundle = self._write_bundle(
            html="<figure><div>Decoration</div><figcaption>Conclusion.</figcaption></figure>"
        )

        self.assertIn(
            "html.figure-content",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_html_keeps_content_and_caption_in_the_same_figure(self) -> None:
        bundle = self._write_bundle(
            html=(
                '<figure><img src="figure.svg" alt=""></figure>'
                "<figure><figcaption>Detached conclusion.</figcaption></figure>"
            )
        )

        self.assertIn(
            "html.figure-association",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_html_rejects_object_reference_even_to_canonical_output(self) -> None:
        bundle = self._write_bundle(
            html=(
                '<figure><object data="./figure.svg#view"></object>'
                "<figcaption>Conclusion.</figcaption></figure>"
            )
        )

        self.assertIn(
            "html.active-content",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_html_rejects_active_elements_and_event_handlers(self) -> None:
        variants = {
            "script": '<script>document.body.dataset.compromised = "1"</script>',
            "iframe": '<iframe src="https://attacker.invalid/frame"></iframe>',
            "object": '<object data="figure.svg"></object>',
            "event": '<span oNcLiCk="document.body.remove()">click</span>',
            "svg-event": '<svg onload="fetch(\'https://attacker.invalid\')"></svg>',
        }
        for name, injected in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"active-{name}",
                    html=(
                        '<figure><img src="figure.svg" alt="">'
                        + injected
                        + "<figcaption>Conclusion.</figcaption></figure>"
                    ),
                )
                codes = self._codes(audit_bundle(bundle, self.repo_root))
                expected = (
                    "html.event-handler"
                    if name in {"event", "svg-event"}
                    else "html.active-content"
                )
                self.assertIn(expected, codes)

    def test_html_rejects_duplicate_attributes_before_security_interpretation(self) -> None:
        variants = {
            "remote-first": (
                '<img src="https://attacker.invalid/figure.svg" '
                'src="figure.svg" alt="">'
            ),
            "remote-last": (
                '<img src="figure.svg" '
                'src="https://attacker.invalid/figure.svg" alt="">'
            ),
            "event-first": '<span onclick="steal()" onclick="">label</span>',
            "event-last": '<span onclick="" ONCLICK="steal()">label</span>',
        }
        for name, injected in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"duplicate-attribute-{name}",
                    html=(
                        '<figure><img src="figure.svg" alt="">'
                        + injected
                        + "<figcaption>Conclusion.</figcaption></figure>"
                    ),
                )

                self.assertIn(
                    "html.duplicate-attribute",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_html_rejects_remote_or_overriding_image_sources(self) -> None:
        variants = {
            "remote-src": (
                '<img src="https://attacker.invalid/figure.svg" alt="">',
                "html.asset-url",
            ),
            "protocol-relative-src": (
                '<img src="//attacker.invalid/figure.svg" alt="">',
                "html.asset-url",
            ),
            "srcset": (
                '<img src="figure.svg" '
                'srcset="https://attacker.invalid/tracker.svg 1x" alt="">',
                "html.srcset",
            ),
            "remote-href": (
                '<img src="figure.svg" alt=""><a href="https://attacker.invalid">x</a>',
                "html.external-reference",
            ),
        }
        for name, (content, expected) in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"external-{name}",
                    html=(
                        f"<figure>{content}"
                        "<figcaption>Conclusion.</figcaption></figure>"
                    ),
                )
                self.assertIn(
                    expected,
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_html_rejects_page_global_and_inline_svg_global_css(self) -> None:
        variants = {
            "page-style": (
                '<style>body { display:none }</style>'
                '<figure><img src="figure.svg" alt="">'
                "<figcaption>Conclusion.</figcaption></figure>",
                "html.page-style",
            ),
            "inline-global": (
                '<figure><svg id="inline-figure" '
                'aria-labelledby="inline-title inline-desc">'
                '<title id="inline-title">Authority</title>'
                '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                '<style>body { display:none }</style></svg>'
                "<figcaption>Conclusion.</figcaption></figure>",
                "html.inline-svg.style-unscoped",
            ),
            "inline-import": (
                '<figure><svg id="inline-figure" '
                'aria-labelledby="inline-title inline-desc">'
                '<title id="inline-title">Authority</title>'
                '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                '<style>@import url("https://attacker.invalid/global.css");</style>'
                "</svg><figcaption>Conclusion.</figcaption></figure>",
                "html.inline-svg.style-syntax",
            ),
            "inline-external-url": (
                '<figure><svg id="inline-figure" '
                'aria-labelledby="inline-title inline-desc">'
                '<title id="inline-title">Authority</title>'
                '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                '<style>#inline-figure { '
                'background-image:url("https://attacker.invalid/pixel") }</style>'
                "</svg><figcaption>Conclusion.</figcaption></figure>",
                "html.inline-svg.external-reference",
            ),
        }
        for name, (content, expected) in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(name=f"css-{name}", html=content)
                self.assertIn(
                    expected,
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_html_and_svg_reject_xml_stylesheet_processing_instructions(self) -> None:
        html = (
            '<?xml-stylesheet href="https://attacker.invalid/figure.css" '
            'type="text/css"?>'
            '<figure><img src="figure.svg" alt="">'
            "<figcaption>Only a validated candidate becomes authoritative.</figcaption>"
            "</figure>"
        )
        html_bundle = self._write_bundle(name="html-xml-stylesheet", html=html)
        self.assertIn(
            "html.declaration",
            self._codes(audit_bundle(html_bundle, self.repo_root)),
        )

        svg = """<?xml version="1.0"?>
        <?xml-stylesheet href="https://attacker.invalid/figure.css" type="text/css"?>
        <svg xmlns="http://www.w3.org/2000/svg" id="test-figure"
            viewBox="0 0 704 300" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        svg_bundle = self._write_bundle(name="svg-xml-stylesheet", svg=svg)
        self.assertIn(
            "svg.declaration",
            self._codes(audit_bundle(svg_bundle, self.repo_root)),
        )

    def test_css_escapes_cannot_hide_imports_or_external_urls(self) -> None:
        stylesheet_variants = {
            "escaped-import": (
                r'@\69mport url("https://attacker.invalid/figure.css");'
            ),
            "escaped-url-function": (
                r"#test-figure { "
                r"background-image:u\72l(https://attacker.invalid/pixel); }"
            ),
            "escaped-url-target": (
                r"#test-figure { "
                r"background-image:url(\68ttps://attacker.invalid/pixel); }"
            ),
        }
        for name, css in stylesheet_variants.items():
            with self.subTest(surface="stylesheet", name=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    id="test-figure" viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"css-escape-{name}", svg=svg)
                self.assertIn(
                    "svg.style-syntax",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

        svg = r"""<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <rect style="fill:u\72l(https://attacker.invalid/pixel)" />
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(name="css-escape-inline-style", svg=svg)
        self.assertIn(
            "svg.external-reference",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_css_image_set_string_urls_are_rejected_in_inline_styles(self) -> None:
        functions = {
            "image-set": "image-set('https://attacker.invalid/one.png' 1x)",
            "webkit-image-set": (
                "-webkit-image-set('https://attacker.invalid/one.png' 1x)"
            ),
            "nested-url": (
                "image-set(url('https://attacker.invalid/one.png') 1x)"
            ),
        }
        for name, image_value in functions.items():
            with self.subTest(surface="svg-inline-style", function=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300"
                    style="width:100%;background-image:{image_value}"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(
                    name=f"image-set-svg-inline-{name}", svg=svg
                )
                self.assertIn(
                    "svg.external-reference",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

            with self.subTest(surface="html-inline-style", function=name):
                html = (
                    '<figure><img src="figure.svg" alt="">'
                    f'<span style="background-image:{image_value}">label</span>'
                    "<figcaption>Only a validated candidate becomes authoritative."
                    "</figcaption></figure>"
                )
                bundle = self._write_bundle(
                    name=f"image-set-html-inline-{name}", html=html
                )
                self.assertIn(
                    "html.external-reference",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_css_image_set_string_urls_are_rejected_in_scoped_stylesheets(
        self,
    ) -> None:
        functions = {
            "image-set": "image-set('https://attacker.invalid/one.png' 1x)",
            "webkit-image-set": (
                "-webkit-image-set('https://attacker.invalid/one.png' 1x)"
            ),
            "nested-url": (
                "image-set(url('https://attacker.invalid/one.png') 1x)"
            ),
        }
        for name, image_value in functions.items():
            with self.subTest(surface="svg-style-element", function=name):
                svg = f"""<svg id="test-figure"
                    xmlns="http://www.w3.org/2000/svg" viewBox="0 0 704 300"
                    style="width:100%" aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>#test-figure {{ background-image:{image_value}; }}</style>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(
                    name=f"image-set-svg-scoped-{name}", svg=svg
                )
                self.assertIn(
                    "svg.external-reference",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

            with self.subTest(surface="html-inline-svg-style", function=name):
                html = (
                    '<figure><svg id="inline-figure" '
                    'aria-labelledby="inline-title inline-desc">'
                    '<title id="inline-title">Authority</title>'
                    '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                    f'<style>#inline-figure {{ background-image:{image_value}; }}</style>'
                    "</svg><figcaption>Conclusion.</figcaption></figure>"
                )
                bundle = self._write_bundle(
                    name=f"image-set-html-scoped-{name}", html=html
                )
                self.assertIn(
                    "html.inline-svg.external-reference",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_html_and_svg_reject_xml_base(self) -> None:
        html = (
            '<figure xml:base="https://attacker.invalid/">'
            '<img src="figure.svg" alt="">'
            "<figcaption>Conclusion.</figcaption></figure>"
        )
        html_bundle = self._write_bundle(name="html-xml-base", html=html)
        self.assertIn(
            "html.external-reference",
            self._codes(audit_bundle(html_bundle, self.repo_root)),
        )

        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            xml:base="https://attacker.invalid/" viewBox="0 0 704 300"
            style="width:100%" aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        svg_bundle = self._write_bundle(name="svg-xml-base", svg=svg)
        self.assertIn(
            "svg.external-reference",
            self._codes(audit_bundle(svg_bundle, self.repo_root)),
        )

    def test_symbol_and_use_sizing_are_rejected_in_svg_and_inline_html(self) -> None:
        variants = {
            "symbol-width-height": (
                '<symbol id="reusable-shape" width="10" height="10" '
                'viewBox="0 0 100 100"><path d="M0 0h100v100z" /></symbol>'
            ),
            "use-width-height": (
                '<defs><g id="reusable-shape"><path d="M0 0h100v100z" />'
                '</g></defs><use href="#reusable-shape" width="10" height="10" />'
            ),
        }
        for name, injected in variants.items():
            with self.subTest(surface="figure.svg", variant=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {injected}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"reuse-svg-{name}", svg=svg)
                self.assertIn(
                    "svg.unsupported-context",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

            with self.subTest(surface="inline-svg", variant=name):
                html = (
                    '<figure><svg aria-labelledby="inline-title inline-desc">'
                    '<title id="inline-title">Authority</title>'
                    '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                    f"{injected}</svg>"
                    "<figcaption>Conclusion.</figcaption></figure>"
                )
                bundle = self._write_bundle(name=f"reuse-html-{name}", html=html)
                self.assertIn(
                    "html.svg-context",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_transformed_use_of_defs_text_is_rejected_on_both_surfaces(self) -> None:
        injected = (
            '<defs><text id="reused-label" font-size="16">Candidate</text></defs>'
            '<use href="#reused-label" transform="scale(0.01)" />'
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          {injected}
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        svg_bundle = self._write_bundle(name="defs-text-use-svg", svg=svg)
        svg_codes = self._codes(audit_bundle(svg_bundle, self.repo_root))
        self.assertIn("svg.unsupported-context", svg_codes)
        self.assertIn("svg.definition-text", svg_codes)

        html = (
            '<figure><svg aria-labelledby="inline-title inline-desc">'
            '<title id="inline-title">Authority</title>'
            '<desc id="inline-desc">A candidate crosses the gate.</desc>'
            f"{injected}</svg>"
            "<figcaption>Conclusion.</figcaption></figure>"
        )
        html_bundle = self._write_bundle(name="defs-text-use-html", html=html)
        html_codes = self._codes(audit_bundle(html_bundle, self.repo_root))
        self.assertIn("html.svg-context", html_codes)
        self.assertIn("html.svg-definition-text", html_codes)

    def test_embedded_and_secondary_svg_contexts_are_rejected_on_both_surfaces(
        self,
    ) -> None:
        variants = {
            "foreign-object": "<foreignObject><div>embedded</div></foreignObject>",
            "switch": '<switch><path d="M0 0h10v10z" /></switch>',
            "view": '<view id="alternate-view" viewBox="0 0 10 10" />',
            "pattern": (
                '<pattern id="tile" width="10" height="10">'
                '<path d="M0 0h10v10z" /></pattern>'
            ),
            "image": '<image width="10" height="10" />',
            "filter-image": '<filter id="fx"><feImage /></filter>',
            "tref": "<text><tref /></text>",
            "mpath": "<mpath />",
        }
        for name, injected in variants.items():
            with self.subTest(surface="figure.svg", variant=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {injected}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"context-svg-{name}", svg=svg)
                self.assertIn(
                    "svg.unsupported-context",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

            with self.subTest(surface="inline-svg", variant=name):
                html = (
                    '<figure><svg aria-labelledby="inline-title inline-desc">'
                    '<title id="inline-title">Authority</title>'
                    '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                    f"{injected}</svg>"
                    "<figcaption>Conclusion.</figcaption></figure>"
                )
                bundle = self._write_bundle(name=f"context-html-{name}", html=html)
                self.assertIn(
                    "html.svg-context",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_text_inside_svg_definition_contexts_is_rejected(self) -> None:
        variants = {
            "defs": "<defs><text font-size=\"16\">Candidate</text></defs>",
            "marker": (
                '<defs><marker id="arrow"><text font-size="16">'
                "Candidate</text></marker></defs>"
            ),
            "clip-path": (
                '<defs><clipPath id="clip"><text font-size="16">'
                "Candidate</text></clipPath></defs>"
            ),
            "mask": (
                '<defs><mask id="mask"><text font-size="16">'
                "Candidate</text></mask></defs>"
            ),
            "filter": (
                '<defs><filter id="filter"><text font-size="16">'
                "Candidate</text></filter></defs>"
            ),
        }
        for name, injected in variants.items():
            with self.subTest(surface="figure.svg", context=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {injected}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"definition-text-svg-{name}", svg=svg)
                self.assertIn(
                    "svg.definition-text",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

            with self.subTest(surface="inline-svg", context=name):
                html = (
                    '<figure><svg aria-labelledby="inline-title inline-desc">'
                    '<title id="inline-title">Authority</title>'
                    '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                    f"{injected}</svg>"
                    "<figcaption>Conclusion.</figcaption></figure>"
                )
                bundle = self._write_bundle(
                    name=f"definition-text-html-{name}", html=html
                )
                self.assertIn(
                    "html.svg-definition-text",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_path_only_marker_geometry_remains_allowed(self) -> None:
        marker = (
            '<defs><marker id="arrow" markerWidth="10" markerHeight="10" '
            'refX="9" refY="5" orient="auto">'
            '<path d="M0 0L10 5L0 10z" /></marker></defs>'
            '<path d="M10 10L100 10" marker-end="url(#arrow)" />'
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          {marker}
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        svg_bundle = self._write_bundle(name="marker-geometry-svg", svg=svg)
        self.assertEqual([], audit_bundle(svg_bundle, self.repo_root))

        html = (
            '<figure><svg aria-labelledby="inline-title inline-desc">'
            '<title id="inline-title">Authority</title>'
            '<desc id="inline-desc">A candidate crosses the gate.</desc>'
            f"{marker}</svg>"
            "<figcaption>Only a validated candidate becomes authoritative.</figcaption>"
            "</figure>"
        )
        html_bundle = self._write_bundle(name="marker-geometry-html", html=html)
        self.assertEqual([], audit_bundle(html_bundle, self.repo_root))

    def test_visible_text_allows_only_the_reviewed_svg_ancestry(self) -> None:
        variants = {
            "root-text": '<text x="10" y="30" font-size="16">Candidate</text>',
            "group-text": (
                '<g><text x="10" y="30" font-size="16">Candidate</text></g>'
            ),
            "link-text": (
                '<a><text x="10" y="30" font-size="16">Candidate</text></a>'
            ),
            "full-reviewed-chain": (
                '<g><a><text x="10" y="30" font-size="16">'
                "<tspan>Candidate</tspan></text></a></g>"
            ),
        }
        for name, text_markup in variants.items():
            with self.subTest(surface="figure.svg", ancestry=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {text_markup}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"text-ancestry-svg-{name}", svg=svg)
                self.assertEqual([], audit_bundle(bundle, self.repo_root))

            with self.subTest(surface="inline-svg", ancestry=name):
                html = (
                    '<figure><svg aria-labelledby="inline-title inline-desc">'
                    '<title id="inline-title">Authority</title>'
                    '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                    f"{text_markup}</svg>"
                    "<figcaption>Only a validated candidate becomes authoritative."
                    "</figcaption></figure>"
                )
                bundle = self._write_bundle(
                    name=f"text-ancestry-html-{name}", html=html
                )
                self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_visible_text_rejects_unreviewed_svg_ancestor_containers(self) -> None:
        variants = {
            "text-path": (
                '<text x="10" y="30" font-size="16">'
                "<textPath>Candidate</textPath></text>"
            ),
            "shape": (
                '<text x="10" y="30" font-size="16">'
                "<rect>Candidate</rect></text>"
            ),
            "unknown": (
                '<text x="10" y="30" font-size="16">'
                "<unknown-container>Candidate</unknown-container></text>"
            ),
        }
        for name, text_markup in variants.items():
            with self.subTest(surface="figure.svg", ancestry=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {text_markup}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(
                    name=f"text-context-svg-{name}", svg=svg
                )
                self.assertIn(
                    "svg.text-context",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

            with self.subTest(surface="inline-svg", ancestry=name):
                html = (
                    '<figure><svg aria-labelledby="inline-title inline-desc">'
                    '<title id="inline-title">Authority</title>'
                    '<desc id="inline-desc">A candidate crosses the gate.</desc>'
                    f"{text_markup}</svg>"
                    "<figcaption>Conclusion.</figcaption></figure>"
                )
                bundle = self._write_bundle(
                    name=f"text-context-html-{name}", html=html
                )
                self.assertIn(
                    "html.svg-text-context",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_html_accepts_accessible_inline_svg(self) -> None:
        bundle = self._write_bundle(
            html="""<figure>
              <svg aria-labelledby="inline-title inline-desc">
                <title id="inline-title">Authority boundary</title>
                <desc id="inline-desc">A candidate crosses a validation gate.</desc>
                <path d="M0 0" />
              </svg>
              <figcaption>Only a validated candidate becomes authoritative.</figcaption>
            </figure>"""
        )

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_html_rejects_nested_svg_viewports(self) -> None:
        bundle = self._write_bundle(
            html="""<figure>
              <svg aria-labelledby="inline-title inline-desc">
                <title id="inline-title">Authority boundary</title>
                <desc id="inline-desc">A candidate crosses a validation gate.</desc>
                <svg width="10" height="10" viewBox="0 0 704 100">
                  <text font-size="16">Candidate</text>
                </svg>
              </svg>
              <figcaption>Only a validated candidate becomes authoritative.</figcaption>
            </figure>"""
        )

        self.assertIn(
            "html.nested-viewport",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_html_rejects_inaccessible_inline_svg(self) -> None:
        bundle = self._write_bundle(
            html=(
                "<figure><svg><title>Only a title</title></svg>"
                "<figcaption>Conclusion.</figcaption></figure>"
            )
        )

        self.assertIn(
            "html.figure-content",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_svg_typography_does_not_infer_legibility_from_pixel_size(self) -> None:
        svg = """<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 1100 500" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <style>#test-figure .label { font-size: 16px; }</style>
          <text class="label" x="20" y="40">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_svg_typography_uses_the_supplied_host_width(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 1100 500" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <text x="20" y="40" font-size="16">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        diagnostics = audit_bundle(bundle, self.repo_root, article_width_px=1100)

        self.assertEqual([], diagnostics)

    def test_body_sized_two_step_svg_type_scale_passes(self) -> None:
        svg = """<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <style>
            #test-figure .label { font-size: 15.5px; }
            #test-figure .emphasis { font-size: 18px; }
            @media (prefers-color-scheme: dark) {
              #test-figure .label { fill: #eee; }
            }
          </style>
          <text class="label" x="20" y="40">Candidate</text>
          <text class="emphasis" x="20" y="80">Accepted</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_inline_svg_styles_must_be_scoped_to_the_bundle_root(self) -> None:
        svg = """<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <style>
            :root { --ink: #111; }
            text { fill: var(--ink); }
          </style>
          <text x="20" y="40" font-size="16">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("svg.style-root", codes)
        self.assertIn("svg.style-unscoped", codes)

    def test_inline_svg_style_requires_a_root_id(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <style>.local-label { font-size: 16px; }</style>
          <text class="local-label" x="20" y="40">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        self.assertIn(
            "svg.style-scope-root",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_svg_css_rejects_imports_and_unknown_or_unconsumed_rules(self) -> None:
        variants = {
            "import": '@import url("https://attacker.invalid/global.css");',
            "supports": (
                "@supports (display:grid) { "
                "#test-figure .label { font-size:16px; } }"
            ),
            "keyframes": "@keyframes pulse { from { opacity:0; } to { opacity:1; } }",
            "unknown-media": (
                "@media print { #test-figure .label { font-size:16px; } }"
            ),
            "trailing": "#test-figure .label { font-size:16px; } unparsed",
        }
        for name, css in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  <text class="label" x="20" y="40" font-size="16">Candidate</text>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"css-syntax-{name}", svg=svg)
                self.assertIn(
                    "svg.style-syntax",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_svg_css_rejects_unknown_properties_and_functions(self) -> None:
        variants = {
            "unknown-property": "mystery-rendering-mode:enabled;",
            "unknown-function": "fill:mystery-paint(#fff);",
        }
        for name, declaration in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>#test-figure {{ {declaration} }}</style>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"css-unknown-{name}", svg=svg)
                self.assertIn(
                    "svg.style-syntax",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_svg_typography_fails_closed_for_unsupported_selectors(self) -> None:
        selectors = {
            "pseudo": "#test-figure text:first-of-type",
            "attribute": '#test-figure text[data-kind="label"]',
            "child": "#test-figure > text",
        }
        for name, selector in selectors.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{selector} {{ font-size:1px; }}</style>
                  <text data-kind="label" x="20" y="40">Candidate</text>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"font-selector-{name}", svg=svg)
                self.assertIn(
                    "svg.typography-unverifiable",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_svg_typography_fails_closed_for_unmeasurable_font_values(self) -> None:
        variants = {
            "var": (
                "#test-figure { --tiny:1px; } "
                "#test-figure .label { font-size:var(--tiny); }"
            ),
            "calc": "#test-figure .label { font-size:calc(2px - 1px); }",
            "font-shorthand": "#test-figure .label { font:1px sans-serif; }",
            "important": "#test-figure .label { font-size:1px !important; }",
        }
        for name, css in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  <text class="label" x="20" y="40">Candidate</text>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"font-value-{name}", svg=svg)
                self.assertIn(
                    "svg.typography-unverifiable",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_svg_typography_fails_closed_for_unmeasurable_root_widths(self) -> None:
        variants = {
            "inline-calc": (
                'style="width:calc(100% - 1px)"',
                "",
            ),
            "inline-var": (
                'style="--diagram-width:704px;width:var(--diagram-width)"',
                "",
            ),
            "inline-font-relative": (
                'style="width:1em"',
                "",
            ),
            "attribute-calc": (
                'width="calc(100% - 1px)"',
                "",
            ),
            "scoped-css-calc": (
                "",
                "#test-figure { width:calc(100% - 1px); }",
            ),
            "scoped-css-var": (
                "",
                (
                    "#test-figure { --diagram-width:704px; "
                    "width:var(--diagram-width); }"
                ),
            ),
        }
        for name, (root_sizing, css) in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" {root_sizing}
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  <text x="20" y="40" font-size="16">Candidate</text>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"root-width-{name}", svg=svg)
                self.assertIn(
                    "svg.typography-unverifiable",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_measurable_scoped_root_width_is_structurally_accepted(self) -> None:
        svg = """<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <style>#test-figure { width:1px; }</style>
          <text x="20" y="40" font-size="16">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(name="root-width-scoped-css", svg=svg)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_measurable_root_height_is_structurally_accepted(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%;height:1px"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <text x="20" y="40" font-size="16">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(name="root-height", svg=svg)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_nested_svg_presentation_viewports_fail_closed(self) -> None:
        variants = {
            "tiny-width": (
                '<svg width="10" height="100" viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>'
            ),
            "tiny-height": (
                '<svg width="100" height="10" viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>'
            ),
            "large-viewbox": (
                '<svg width="100" height="100" viewBox="0 0 1000 1000">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>'
            ),
            "identity": (
                '<svg width="100" height="100" viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>'
            ),
            "larger-explicit-meet": (
                '<svg width="200" height="200" viewBox="0 0 100 100" '
                'preserveAspectRatio="xMidYMid meet">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>'
            ),
        }
        for name, nested_svg in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {nested_svg}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"nested-present-{name}", svg=svg)
                self.assertIn(
                    "svg.nested-viewport",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_nested_svg_inline_and_scoped_css_viewports_fail_closed(self) -> None:
        variants = {
            "inline-width": (
                "",
                '<svg width="100" height="100" viewBox="0 0 100 100" '
                'style="width:10px;height:100px">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "inline-height": (
                "",
                '<svg width="100" height="100" viewBox="0 0 100 100" '
                'style="width:100px;height:10px">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "scoped-width": (
                "#test-figure .nested { width:10px;height:100px; }",
                '<svg class="nested" width="100" height="100" '
                'viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "scoped-height": (
                "#test-figure .nested { width:100px;height:10px; }",
                '<svg class="nested" width="100" height="100" '
                'viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
        }
        for name, (css, nested_svg) in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  {nested_svg}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"nested-css-{name}", svg=svg)
                self.assertIn(
                    "svg.nested-viewport",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_nested_svg_cumulative_and_unsupported_paths_fail_closed(self) -> None:
        variants = {
            "multi-level-cumulative": (
                "",
                '<svg width="80" height="80" viewBox="0 0 100 100">'
                '<svg width="80" height="80" viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text>'
                "</svg></svg>",
            ),
            "presentation-percent": (
                "",
                '<svg width="50%" height="50%" viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "inline-percent": (
                "",
                '<svg viewBox="0 0 100 100" '
                'style="width:50%;height:50%">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "inline-calc": (
                "",
                '<svg viewBox="0 0 100 100" '
                'style="width:calc(100% - 1px);height:10px">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "inline-var": (
                "",
                '<svg viewBox="0 0 100 100" '
                'style="--nested-width:10px;width:var(--nested-width);height:10px">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "scoped-calc": (
                "#test-figure .nested { width:calc(100% - 1px);height:10px; }",
                '<svg class="nested" viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "scoped-var": (
                "#test-figure .nested { --nested-width:10px; "
                "width:var(--nested-width);height:10px; }",
                '<svg class="nested" viewBox="0 0 100 100">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "preserve-none": (
                "",
                '<svg width="10" height="100" viewBox="0 0 100 100" '
                'preserveAspectRatio="none">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
            "preserve-slice": (
                "",
                '<svg width="10" height="100" viewBox="0 0 100 100" '
                'preserveAspectRatio="xMidYMid slice">'
                '<text x="5" y="20" font-size="16">Candidate</text></svg>',
            ),
        }
        for name, (css, nested_svg) in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  {nested_svg}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"nested-unsupported-{name}", svg=svg)
                self.assertIn(
                    "svg.nested-viewport",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_svg_typography_rejects_inline_root_logical_sizing(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%;inline-size:10px"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <text x="20" y="40" font-size="16">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(name="root-inline-size", svg=svg)

        self.assertIn(
            "svg.typography-unverifiable",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_svg_typography_rejects_css_scale_on_text_or_ancestors(self) -> None:
        variants = {
            "inline-text": (
                "",
                '<text class="label" x="20" y="40" '
                'style="font-size:16px;scale:0.01">Candidate</text>',
            ),
            "inline-ancestor": (
                "",
                '<g style="scale:0.01"><text class="label" x="20" y="40" '
                'font-size="16">Candidate</text></g>',
            ),
            "scoped-text": (
                "#test-figure .label { font-size:16px;scale:0.01; }",
                '<text class="label" x="20" y="40">Candidate</text>',
            ),
            "scoped-ancestor": (
                "#test-figure .scaled { scale:0.01; }",
                '<g class="scaled"><text class="label" x="20" y="40" '
                'font-size="16">Candidate</text></g>',
            ),
        }
        for name, (css, text_markup) in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  {text_markup}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"css-scale-{name}", svg=svg)
                self.assertIn(
                    "svg.typography-unverifiable",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_css_comments_cannot_split_font_size_property_tokens(self) -> None:
        variants = {
            "inline": (
                "",
                '<text x="20" y="40" '
                'style="font-size/**/:1px">Candidate</text>',
                "svg.typography-unverifiable",
            ),
            "scoped": (
                "#test-figure .label { font-size/**/:1px; }",
                '<text class="label" x="20" y="40">Candidate</text>',
                "svg.style-syntax",
            ),
        }
        for name, (css, text_markup, expected) in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  {text_markup}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"css-comment-{name}", svg=svg)
                self.assertIn(
                    expected,
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_color_scheme_font_sizes_are_left_to_host_readability_review(
        self,
    ) -> None:
        variants = {
            "dark-tiny-first": (
                "@media (prefers-color-scheme: dark) { "
                "#test-figure .label { font-size:1px; } } "
                "@media (prefers-color-scheme: light) { "
                "#test-figure .label { font-size:16px; } }"
            ),
            "light-tiny-first": (
                "@media (prefers-color-scheme: light) { "
                "#test-figure .label { font-size:1px; } } "
                "@media (prefers-color-scheme: dark) { "
                "#test-figure .label { font-size:16px; } }"
            ),
        }
        for name, css in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  <style>{css}</style>
                  <text class="label" x="20" y="40">Candidate</text>
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"media-font-{name}", svg=svg)
                self.assertNotIn(
                    "svg.text-too-small",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_tspan_font_sizes_are_left_to_host_readability_review(self) -> None:
        variants = {
            "inherited-tspan": (
                '<text x="20" y="40" font-size="1">'
                "<tspan>tiny inherited text</tspan></text>"
            ),
            "parent-tail": (
                '<text x="20" y="40" font-size="1">'
                '<tspan font-size="16">Readable child</tspan>'
                "tiny parent tail</text>"
            ),
            "nested-tspan-tail": (
                '<text x="20" y="40" font-size="16">'
                '<tspan font-size="1"><tspan font-size="16">Readable child</tspan>'
                "tiny nested tail</tspan></text>"
            ),
        }
        for name, text_markup in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {text_markup}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"text-tail-{name}", svg=svg)
                self.assertNotIn(
                    "svg.text-too-small",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_container_font_sizes_are_left_to_host_readability_review(self) -> None:
        variants = {
            "direct-link": (
                '<text x="20" y="40" font-size="1">'
                "<a>Candidate</a></text>"
            ),
            "nested-groups-and-link": (
                '<g font-size="1"><g><text x="20" y="40">'
                "<a>Candidate</a></text></g></g>"
            ),
        }
        for name, text_markup in variants.items():
            with self.subTest(name=name):
                svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 704 300" style="width:100%"
                    aria-labelledby="figure-title figure-desc">
                  <title id="figure-title">Authority boundary</title>
                  <desc id="figure-desc">A candidate crosses a validation gate.</desc>
                  {text_markup}
                  <g id="candidate-shape" />
                  <g id="gate-shape" />
                  <g id="authority-shape" />
                </svg>"""
                bundle = self._write_bundle(name=f"text-container-{name}", svg=svg)
                self.assertNotIn(
                    "svg.text-too-small",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_unverifiable_css_remains_a_structural_failure(self) -> None:
        svg = """<svg id="test-figure" xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <style>#test-figure .label { font-size:var(--unknown); }</style>
          <text class="label" x="20" y="40">Candidate</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        self.assertIn(
            "svg.typography-unverifiable",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_svg_type_count_is_left_to_host_readability_review(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 300" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <text x="20" y="40" font-size="15.5">One</text>
          <text x="20" y="70" font-size="16.5">Two</text>
          <text x="20" y="100" font-size="17.5">Three</text>
          <text x="20" y="130" font-size="18.5">Four</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)
        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_svg_text_is_not_classified_by_words_punctuation_or_class_names(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 704 400" style="width:100%"
            aria-labelledby="figure-title figure-desc">
          <title id="figure-title">Authority boundary</title>
          <desc id="figure-desc">A candidate crosses a validation gate.</desc>
          <text class="title" x="20" y="40" font-size="16">Visible diagram title</text>
          <text x="20" y="80" font-size="16">solid = independently exercised today | dashed = target path absent today</text>
          <text x="20" y="120" font-size="16">This explanatory paragraph contains far too many words and forces the reader to summarize prose that should remain outside the visible drawing mechanism entirely.</text>
          <g id="candidate-shape" />
          <g id="gate-shape" />
          <g id="authority-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_svg_requires_title_desc_and_aria_labelledby(self) -> None:
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        bundle = self._write_bundle(
            intent=intent,
            svg='<svg xmlns="http://www.w3.org/2000/svg"><g /></svg>',
        )

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("svg.title", codes)
        self.assertIn("svg.desc", codes)
        self.assertIn("svg.aria-labelledby", codes)

    def test_svg_aria_references_and_intent_svg_ids_must_exist(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg"
            aria-labelledby="missing-title desc-id">
          <title id="title-id">Title</title>
          <desc id="desc-id">Description</desc>
          <g id="candidate-shape" />
          <g id="gate-shape" />
        </svg>"""
        bundle = self._write_bundle(svg=svg)

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertIn("svg.aria-reference", codes)
        self.assertIn("svg.aria-title", codes)
        self.assertIn("element.svg-id-missing", codes)

    def test_png_only_is_allowed_when_no_svg_id_is_declared(self) -> None:
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        bundle = self._write_bundle(intent=intent, png_only=True)

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_png_only_rejects_declared_svg_id(self) -> None:
        bundle = self._write_bundle(png_only=True)

        self.assertIn(
            "element.svg-id-no-svg",
            self._codes(audit_bundle(bundle, self.repo_root)),
        )

    def test_png_requires_signature_and_ihdr(self) -> None:
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        variants = {
            "bad-signature": b"not a png at all",
            "bad-ihdr": PNG_SIGNATURE + _png_chunk(b"NOPE", b"0" * 12),
        }
        for name, content in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(name=name, intent=intent, png_only=True)
                (bundle / "figure.png").write_bytes(content)
                codes = self._codes(audit_bundle(bundle, self.repo_root))
                self.assertTrue({"png.signature", "png.ihdr"} & codes)

    def test_png_ihdr_dimensions_must_be_positive(self) -> None:
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        bundle = self._write_bundle(intent=intent, png_only=True)
        (bundle / "figure.png").write_bytes(_png_bytes(0, 360))

        self.assertIn(
            "png.dimensions", self._codes(audit_bundle(bundle, self.repo_root))
        )

    def test_complete_png_and_consecutive_split_idat_chunks_pass(self) -> None:
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        bundle = self._write_bundle(intent=intent, png_only=True)
        (bundle / "figure.png").write_bytes(_png_bytes(3, 2, idat_parts=3))

        self.assertEqual([], audit_bundle(bundle, self.repo_root))

    def test_png_rejects_corrupt_crc_chunk_type_and_truncation(self) -> None:
        valid_raw = b"\x00" + bytes(4)
        valid_idat = _png_chunk(b"IDAT", zlib.compress(valid_raw))
        variants = {
            "crc": (_corrupt_png_chunk_crc(_png_bytes(1, 1), b"IDAT"), "png.chunk-crc"),
            "chunk-type": (
                PNG_SIGNATURE
                + _rgba_ihdr()
                + _png_chunk(b"ID@T", zlib.compress(valid_raw))
                + _png_chunk(b"IEND", b""),
                "png.chunk-type",
            ),
            "unknown-critical": (
                PNG_SIGNATURE
                + _rgba_ihdr()
                + _png_chunk(b"ABCD", b"")
                + valid_idat
                + _png_chunk(b"IEND", b""),
                "png.unknown-critical",
            ),
            "truncated": (_png_bytes(1, 1)[:-5], "png.chunk-truncated"),
            "declared-past-end": (
                PNG_SIGNATURE
                + _rgba_ihdr()
                + (100).to_bytes(4, "big")
                + b"IDAT"
                + b"\x00\x00\x00\x00",
                "png.chunk-length",
            ),
        }
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        for name, (content, expected) in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"png-corrupt-{name}", intent=intent, png_only=True
                )
                (bundle / "figure.png").write_bytes(content)
                self.assertIn(
                    expected,
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_png_rejects_invalid_chunk_order(self) -> None:
        raw = b"\x00" + bytes(4)
        compressed = zlib.compress(raw)
        split = max(1, len(compressed) // 2)
        variants = {
            "nonconsecutive-idat": (
                PNG_SIGNATURE
                + _rgba_ihdr()
                + _png_chunk(b"IDAT", compressed[:split])
                + _png_chunk(b"tEXt", b"key\x00value")
                + _png_chunk(b"IDAT", compressed[split:])
                + _png_chunk(b"IEND", b"")
            ),
            "palette-after-idat": (
                PNG_SIGNATURE
                + _rgba_ihdr()
                + _png_chunk(b"IDAT", compressed)
                + _png_chunk(b"PLTE", bytes((0, 0, 0)))
                + _png_chunk(b"IEND", b"")
            ),
            "iend-before-idat": (
                PNG_SIGNATURE + _rgba_ihdr() + _png_chunk(b"IEND", b"")
            ),
        }
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        for name, content in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"png-order-{name}", intent=intent, png_only=True
                )
                (bundle / "figure.png").write_bytes(content)
                self.assertIn(
                    "png.order",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_png_rejects_invalid_or_ambiguous_zlib_streams(self) -> None:
        raw = b"\x00" + bytes(4)
        variants = {
            "invalid": b"not-a-zlib-stream",
            "second-stream": zlib.compress(raw) + zlib.compress(raw),
            "trailing-zlib-data": zlib.compress(raw) + b"trailing",
        }
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        for name, compressed in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"png-zlib-{name}", intent=intent, png_only=True
                )
                (bundle / "figure.png").write_bytes(
                    _png_bytes(1, 1, compressed=compressed)
                )
                self.assertIn(
                    "png.zlib",
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_png_rejects_scanline_size_and_filter_corruption(self) -> None:
        variants = {
            "short-row": (b"\x00" + bytes(3), "png.scanline-length"),
            "long-row": (b"\x00" + bytes(5), "png.scanline-length"),
            "bad-filter": (b"\x05" + bytes(4), "png.filter-byte"),
        }
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        for name, (raw, expected) in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"png-scanline-{name}", intent=intent, png_only=True
                )
                (bundle / "figure.png").write_bytes(
                    _png_bytes(1, 1, raw_scanlines=raw)
                )
                self.assertIn(
                    expected,
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_png_rejects_missing_nonempty_and_followed_iend(self) -> None:
        variants = {
            "missing": (_png_bytes(1, 1, include_iend=False), "png.iend"),
            "nonempty": (_png_bytes(1, 1, iend_payload=b"x"), "png.iend"),
            "trailing-byte": (
                _png_bytes(1, 1, trailing=b"x"),
                "png.trailing-data",
            ),
            "trailing-chunk": (
                _png_bytes(1, 1, trailing=_png_chunk(b"tEXt", b"after\x00iend")),
                "png.trailing-data",
            ),
        }
        intent = self._valid_intent()
        for element in intent["elements"]:  # type: ignore[union-attr]
            element.pop("svgId")
        for name, (content, expected) in variants.items():
            with self.subTest(name=name):
                bundle = self._write_bundle(
                    name=f"png-iend-{name}", intent=intent, png_only=True
                )
                (bundle / "figure.png").write_bytes(content)
                self.assertIn(
                    expected,
                    self._codes(audit_bundle(bundle, self.repo_root)),
                )

    def test_missing_bundle_files_are_reported_together(self) -> None:
        bundle = self.repo_root / "empty-bundle"
        bundle.mkdir()

        codes = self._codes(audit_bundle(bundle, self.repo_root))

        self.assertEqual(
            {"build.missing", "intent.missing", "html.missing", "output.missing"},
            codes,
        )

    def test_cli_is_strict_only_for_explicit_bundles(self) -> None:
        good_bundle = self._write_bundle(name="good")
        untouched_legacy_bundle = self.repo_root / "docs" / "figures" / "legacy"
        untouched_legacy_bundle.mkdir()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "--repo-root",
                    str(self.repo_root),
                    "--bundle",
                    str(good_bundle.relative_to(self.repo_root)),
                ]
            )

        self.assertEqual(0, result)
        self.assertIn("1 explicitly selected bundle", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_cli_reports_all_selected_bundle_failures_and_returns_one(self) -> None:
        first = self.repo_root / "bad-one"
        second = self.repo_root / "bad-two"
        first.mkdir()
        second.mkdir()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "--repo-root",
                    str(self.repo_root),
                    "--bundle",
                    "bad-one",
                    "--bundle",
                    "bad-two",
                ]
            )

        self.assertEqual(1, result)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("[bad-one]", stderr.getvalue())
        self.assertIn("[bad-two]", stderr.getvalue())
        self.assertIn("2 explicitly selected bundle", stderr.getvalue())

    def test_cli_rejects_nonpositive_or_nonfinite_article_width(self) -> None:
        bundle = self._write_bundle()
        for value in ("0", "nan", "inf"):
            with self.subTest(value=value):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = main(
                        [
                            "--repo-root",
                            str(self.repo_root),
                            "--bundle",
                            str(bundle.relative_to(self.repo_root)),
                            "--article-width-px",
                            value,
                        ]
                    )
                self.assertEqual(2, result)
                self.assertEqual("", stdout.getvalue())
                self.assertIn("positive finite number", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
