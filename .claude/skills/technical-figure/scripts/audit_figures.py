#!/usr/bin/env python3
"""Run the structural gate for explicitly selected technical-figure bundles.

The audit is intentionally opt-in per bundle. Existing bundles are unaffected
until a caller names them with ``--bundle`` and supplies ``figure-intent.json``.
The gate validates declared structure and evidence files; it neither executes
``build.py`` nor substitutes for the required semantic and visual review. Only
the Python standard library is required.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
from html.parser import HTMLParser
import ipaddress
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys
from typing import Any, Sequence
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zlib


INTENT_FILENAME = "figure-intent.json"
REQUIRED_INTENT_STRINGS = (
    "question",
    "claim",
    "subject",
    "caption",
)
TAKEAWAY_FIELDS = ("immediateTakeaway", "threeSecondTakeaway")
# What shape of figure a bundle is. The field is optional, because bundles
# predate it. A bundle that does declare it is held to this closed list, so the
# vocabulary is one decision the space makes rather than one each author makes
# alone. Adding a word here is how the list grows.
FIGURE_KINDS = (
    "contrast",
    "decision",
    "fan-out",
    "flow",
    "layout",
    "state",
    "timeline",
)
REQUIRED_ELEMENT_STRINGS = (
    "id",
    "meaning",
    "role",
    "encoding",
    "whyThisEncoding",
    "removalLoss",
)
CORE_REVIEW_CHECKS = (
    "labelSwap",
    "labelOff",
    "pointAndExplain",
    "ablation",
    "counterfactual",
    "thumbnail",
    "grayscale",
    "proseDependency",
    "sourceTruth",
)
REVIEW_ALIASES = {
    "firstRead": ("firstRead", "threeSecond"),
    "hostReadability": ("hostReadability", "articleTypography"),
}
CONDITIONAL_REVIEW_CHECKS = ("arrowVerb", "boundary", "trace")
STABLE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
NON_IDENTIFYING_REVIEWER_LABEL = re.compile(
    r"^(?:anonymous|blind|independent|review-session)(?:-[a-z0-9]+)*$"
)
HIDDEN_CLASSES = frozenset(
    {"hidden", "sr-only", "screen-reader-only", "visually-hidden"}
)
VOID_HTML_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_FILE_BYTES = 256 * 1024 * 1024
MAX_PNG_DECOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_PNG_CHUNKS = 100_000
MAX_PNG_SCANLINES = 10_000_000
PNG_COLOR_DEPTHS = {
    0: frozenset({1, 2, 4, 8, 16}),
    2: frozenset({8, 16}),
    3: frozenset({1, 2, 4, 8}),
    4: frozenset({8, 16}),
    6: frozenset({8, 16}),
}
PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
ADAM7_PASSES = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)

ACTIVE_HTML_TAGS = frozenset(
    {
        "base",
        "button",
        "canvas",
        "embed",
        "form",
        "frame",
        "frameset",
        "iframe",
        "input",
        "link",
        "meta",
        "script",
        "select",
        "source",
        "template",
        "textarea",
        "track",
        "video",
        "audio",
        "animate",
        "animatemotion",
        "animatetransform",
        "applet",
        "discard",
        "foreignobject",
        "math",
        "object",
        "set",
    }
)
URL_ATTRIBUTES = frozenset(
    {
        "action",
        "data",
        "formaction",
        "href",
        "poster",
        "src",
        "srcset",
        "xlink:href",
        "xml:base",
    }
)
CSS_DANGEROUS_DECLARATIONS = frozenset({"behavior", "-moz-binding"})
ALLOWED_CSS_PROPERTIES = frozenset(
    {
        "color",
        "color-scheme",
        "display",
        "fill",
        "fill-opacity",
        "font-family",
        "font-size",
        "font-weight",
        "height",
        "margin",
        "max-width",
        "min-width",
        "stroke",
        "stroke-dasharray",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-opacity",
        "stroke-width",
        "vector-effect",
        "width",
    }
)
ALLOWED_CSS_FUNCTIONS = frozenset({"hsl", "hsla", "rgb", "rgba", "url", "var"})
UNSUPPORTED_ROOT_SIZING_PROPERTIES = frozenset(
    {
        "aspect-ratio",
        "block-size",
        "contain-intrinsic-block-size",
        "contain-intrinsic-inline-size",
        "contain-intrinsic-size",
        "flex-basis",
        "inline-size",
        "max-block-size",
        "max-inline-size",
        "min-block-size",
        "min-inline-size",
        "scale",
        "zoom",
    }
)
UNSUPPORTED_SVG_CONTEXT_TAGS = frozenset(
    {
        "feimage",
        "foreignobject",
        "image",
        "mpath",
        "pattern",
        "switch",
        "symbol",
        "tref",
        "use",
        "view",
    }
)
SVG_DEFINITION_CONTEXT_TAGS = frozenset(
    {"clippath", "defs", "filter", "marker", "mask"}
)
SVG_VISIBLE_TEXT_ANCESTRY = frozenset({"a", "g", "svg", "text", "tspan"})
SVG_NONRENDERED_TEXT_TAGS = frozenset({"desc", "metadata", "style", "title"})
SOURCE_EVIDENCE_SUFFIXES = frozenset(
    {
        ".asm",
        ".bash",
        ".c",
        ".cc",
        ".cmake",
        ".cpp",
        ".cppm",
        ".cs",
        ".cxx",
        ".dart",
        ".ex",
        ".exs",
        ".fs",
        ".fsx",
        ".go",
        ".h",
        ".hpp",
        ".hxx",
        ".ixx",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".lua",
        ".m",
        ".mm",
        ".php",
        ".ps1",
        ".py",
        ".rb",
        ".rs",
        ".scala",
        ".sh",
        ".sql",
        ".swift",
        ".ts",
        ".tsx",
        ".vue",
        ".zig",
    }
)
STRUCTURED_EVIDENCE_SUFFIXES = frozenset({".json", ".toml", ".yaml", ".yml"})
_CSS_URL = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_CSS_URL_OPEN = re.compile(r"url\s*\(", re.IGNORECASE)
_MARKDOWN_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
_MARKDOWN_EXPLICIT_ID = re.compile(r"\s*\{#([\w-]+)\}\s*$")
_LINE_LOCATOR = re.compile(r"L(\d+)(?:-L(\d+))?")
_SOURCE_MARKER = r"docs\s*:\s*(?:begin|end)\s+{}(?:\s|$)"

# A neutral 44rem prose column is used only to resolve SVG sizing declarations.
# Callers can pass the measured host width; host-page review owns readability
# and hierarchy judgments.
DEFAULT_ARTICLE_WIDTH_PX = 704.0
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_LENGTH = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(px|pt|em|rem|%)?$",
    re.IGNORECASE,
)
_SVG_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_PRIVATE_HOST_LABELS = frozenset(
    {"corp", "home", "internal", "intranet", "lan", "local", "private"}
)
_PRIVATE_HOST_SUFFIXES = (
    ".home.arpa",
    ".internal",
    ".intranet",
    ".lan",
    ".local",
    ".localhost",
    ".onion",
)


@dataclass(frozen=True)
class Diagnostic:
    """One actionable error associated with a bundle."""

    bundle: Path
    code: str
    message: str

    def format(self, repo_root: Path) -> str:
        try:
            bundle_label = self.bundle.relative_to(repo_root).as_posix()
        except ValueError:
            bundle_label = str(self.bundle)
        return f"ERROR [{bundle_label}] {self.code}: {self.message}"


@dataclass
class _Caption:
    visible: bool
    figure_index: int | None
    text_parts: list[str]


@dataclass
class _InlineSvg:
    figure_index: int
    root_id: str
    aria_labelledby: set[str]
    ids: set[str]
    title_ids: set[str]
    description_ids: set[str]
    title_text: list[str]
    description_text: list[str]
    styles: list[list[str]]
    local_references: set[str]


@dataclass
class _HtmlStackEntry:
    tag: str
    hidden: bool
    figure_index: int | None = None
    caption_index: int | None = None
    inline_svg_index: int | None = None
    svg_text: tuple[int, str] | None = None
    svg_style: tuple[int, int] | None = None


@dataclass(frozen=True)
class _ParsedCssRule:
    selectors: tuple[str, ...]
    declarations: dict[str, str]
    media: str | None


@dataclass(frozen=True)
class _CssFontRule:
    selector: str
    value: str
    specificity: tuple[int, int, int]
    order: int
    media: str | None


@dataclass(frozen=True)
class _SvgTextSample:
    element: ET.Element
    text: str
    rendered_font_px: float


class _FigureHtmlParser(HTMLParser):
    """Collect figure structure and accessible content without dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.captions: list[_Caption] = []
        self.figure_count = 0
        self.asset_references: list[tuple[int, str]] = []
        self.inline_svgs: list[_InlineSvg] = []
        self.security_issues: list[tuple[str, str]] = []
        self._stack: list[_HtmlStackEntry] = []
        self._active_captions: list[int] = []
        self._active_inline_svgs: list[int] = []
        self._active_svg_text: list[tuple[int, str]] = []
        self._active_svg_styles: list[tuple[int, int]] = []

    @staticmethod
    def _is_hidden(attributes: list[tuple[str, str | None]]) -> bool:
        attrs = {name.lower(): (value or "") for name, value in attributes}
        if "hidden" in attrs or attrs.get("aria-hidden", "").lower() == "true":
            return True

        classes = {item.lower() for item in attrs.get("class", "").split()}
        if classes & HIDDEN_CLASSES:
            return True

        style = re.sub(r"\s+", "", attrs.get("style", "").lower())
        return "display:none" in style or "visibility:hidden" in style

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        normalized_tag = tag.lower()
        inside_svg = any(entry.tag == "svg" for entry in self._stack)
        if normalized_tag == "svg" and any(
            entry.tag == "svg" for entry in self._stack
        ):
            self.security_issues.append(
                (
                    "html.nested-viewport",
                    (
                        "figure.html must not contain nested <svg> viewports; "
                        "their cumulative display scale is outside the audited subset"
                    ),
                )
            )
        if inside_svg and normalized_tag in UNSUPPORTED_SVG_CONTEXT_TAGS:
            self.security_issues.append(
                (
                    "html.svg-context",
                    (
                        f"figure.html inline SVG must not use <{normalized_tag}>; "
                        "instance and embedded coordinate contexts are outside the "
                        "audited figure subset"
                    ),
                )
            )
        seen_attributes: set[str] = set()
        for raw_name, _ in attrs:
            normalized_name = raw_name.lower()
            if normalized_name in seen_attributes:
                self.security_issues.append(
                    (
                        "html.duplicate-attribute",
                        (
                            "figure.html must not repeat attribute "
                            f"{normalized_name!r}; browsers and parsers can choose "
                            "different values"
                        ),
                    )
                )
            seen_attributes.add(normalized_name)
        inherited_hidden = self._stack[-1].hidden if self._stack else False
        hidden = inherited_hidden or self._is_hidden(attrs)
        parent_figure_index = next(
            (
                entry.figure_index
                for entry in reversed(self._stack)
                if entry.figure_index is not None
            ),
            None,
        )
        if normalized_tag == "figure":
            figure_index = self.figure_count
            self.figure_count += 1
        else:
            figure_index = parent_figure_index
        inside_figure = figure_index is not None

        attr_map = {name.lower(): (value or "") for name, value in attrs}
        if normalized_tag in ACTIVE_HTML_TAGS:
            self.security_issues.append(
                (
                    "html.active-content",
                    f"figure.html must not contain active <{normalized_tag}> content",
                )
            )
        for raw_name, raw_value in attr_map.items():
            if raw_name.startswith("on"):
                self.security_issues.append(
                    (
                        "html.event-handler",
                        f"figure.html must not contain event-handler attribute {raw_name!r}",
                    )
                )
            if raw_name == "srcset":
                self.security_issues.append(
                    (
                        "html.srcset",
                        "figure.html must not use srcset; it can override the audited canonical src",
                    )
                )
            if raw_name in URL_ATTRIBUTES and raw_name != "srcset" and raw_value:
                is_canonical_asset = (
                    (normalized_tag == "img" and raw_name == "src")
                    or (normalized_tag == "object" and raw_name == "data")
                )
                is_local_svg_reference = (
                    bool(self._active_inline_svgs)
                    and raw_name in {"href", "xlink:href"}
                    and raw_value.startswith("#")
                    and len(raw_value) > 1
                )
                if is_canonical_asset:
                    try:
                        parsed_asset = urlsplit(html.unescape(raw_value).strip())
                    except ValueError:
                        parsed_asset = None
                    safe_asset_path = (
                        parsed_asset.path.removeprefix("./")
                        if parsed_asset is not None
                        else ""
                    )
                    if (
                        parsed_asset is None
                        or parsed_asset.scheme
                        or parsed_asset.netloc
                        or parsed_asset.query
                        or safe_asset_path not in {"figure.svg", "figure.png"}
                        or "\\" in parsed_asset.path
                    ):
                        self.security_issues.append(
                            (
                                "html.asset-url",
                                f"figure.html canonical asset reference is unsafe: {raw_value!r}",
                            )
                        )
                elif is_local_svg_reference:
                    self.inline_svgs[self._active_inline_svgs[-1]].local_references.add(
                        raw_value[1:]
                    )
                elif not is_canonical_asset:
                    self.security_issues.append(
                        (
                            "html.external-reference",
                            (
                                f"figure.html attribute {raw_name!r} on <{normalized_tag}> "
                                "must not load or navigate to another resource"
                            ),
                        )
                    )

            if raw_value:
                if raw_name == "style":
                    try:
                        _parse_css_declarations(raw_value)
                    except _CssSyntaxError as error:
                        self.security_issues.append(
                            (
                                "html.style-syntax",
                                f"figure.html inline CSS cannot be audited safely: {error}",
                            )
                        )
                lowered_value = raw_value.lower()
                if "expression(" in lowered_value or any(
                    f"{name}:" in lowered_value for name in CSS_DANGEROUS_DECLARATIONS
                ):
                    self.security_issues.append(
                        (
                            "html.unsafe-style",
                            f"figure.html attribute {raw_name!r} contains active CSS",
                        )
                    )
                references, reference_error = _css_local_references(raw_value)
                if reference_error is not None:
                    self.security_issues.append(
                        (
                            "html.external-reference",
                            f"figure.html attribute {raw_name!r}: {reference_error}",
                        )
                    )
                elif references and self._active_inline_svgs:
                    self.inline_svgs[self._active_inline_svgs[-1]].local_references.update(
                        references
                    )

        if normalized_tag == "style" and not self._active_inline_svgs:
            self.security_issues.append(
                (
                    "html.page-style",
                    "figure.html must not contain a page-global <style> outside its inline SVG",
                )
            )

        if inside_figure and not hidden:
            if normalized_tag == "img" and attr_map.get("src"):
                assert figure_index is not None
                self.asset_references.append((figure_index, attr_map["src"]))
            elif normalized_tag == "object" and attr_map.get("data"):
                assert figure_index is not None
                self.asset_references.append((figure_index, attr_map["data"]))

        caption_index: int | None = None
        if normalized_tag == "figcaption":
            caption_index = len(self.captions)
            self.captions.append(
                _Caption(
                    visible=not hidden,
                    figure_index=figure_index if inside_figure else None,
                    text_parts=[],
                )
            )
            self._active_captions.append(caption_index)

        inline_svg_index: int | None = None
        if normalized_tag == "svg" and inside_figure and not hidden:
            assert figure_index is not None
            inline_svg_index = len(self.inline_svgs)
            self.inline_svgs.append(
                _InlineSvg(
                    figure_index=figure_index,
                    root_id=attr_map.get("id", "").strip(),
                    aria_labelledby=set(attr_map.get("aria-labelledby", "").split()),
                    ids=set(),
                    title_ids=set(),
                    description_ids=set(),
                    title_text=[],
                    description_text=[],
                    styles=[],
                    local_references=set(),
                )
            )
            self._active_inline_svgs.append(inline_svg_index)

        for svg_index in self._active_inline_svgs:
            element_id = attr_map.get("id")
            if element_id:
                self.inline_svgs[svg_index].ids.add(element_id)

        svg_text: tuple[int, str] | None = None
        if self._active_inline_svgs and normalized_tag in {"title", "desc"}:
            svg_index = self._active_inline_svgs[-1]
            svg_text = (svg_index, normalized_tag)
            self._active_svg_text.append(svg_text)
            element_id = attr_map.get("id")
            if element_id:
                if normalized_tag == "title":
                    self.inline_svgs[svg_index].title_ids.add(element_id)
                else:
                    self.inline_svgs[svg_index].description_ids.add(element_id)

        svg_style: tuple[int, int] | None = None
        if self._active_inline_svgs and normalized_tag == "style":
            svg_index = self._active_inline_svgs[-1]
            style_index = len(self.inline_svgs[svg_index].styles)
            self.inline_svgs[svg_index].styles.append([])
            svg_style = (svg_index, style_index)
            self._active_svg_styles.append(svg_style)

        if normalized_tag not in VOID_HTML_ELEMENTS:
            self._stack.append(
                _HtmlStackEntry(
                    tag=normalized_tag,
                    hidden=hidden,
                    figure_index=figure_index,
                    caption_index=caption_index,
                    inline_svg_index=inline_svg_index,
                    svg_text=svg_text,
                    svg_style=svg_style,
                )
            )

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_HTML_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        matching_index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index].tag == normalized_tag
            ),
            None,
        )
        if matching_index is None:
            return

        removed = self._stack[matching_index:]
        del self._stack[matching_index:]
        removed_caption_indexes = {
            entry.caption_index
            for entry in removed
            if entry.caption_index is not None
        }
        self._active_captions = [
            index
            for index in self._active_captions
            if index not in removed_caption_indexes
        ]
        removed_svg_indexes = {
            entry.inline_svg_index
            for entry in removed
            if entry.inline_svg_index is not None
        }
        self._active_inline_svgs = [
            index
            for index in self._active_inline_svgs
            if index not in removed_svg_indexes
        ]
        removed_svg_text = {
            entry.svg_text for entry in removed if entry.svg_text is not None
        }
        self._active_svg_text = [
            item for item in self._active_svg_text if item not in removed_svg_text
        ]
        removed_svg_styles = {
            entry.svg_style for entry in removed if entry.svg_style is not None
        }
        self._active_svg_styles = [
            item for item in self._active_svg_styles if item not in removed_svg_styles
        ]

    def handle_data(self, data: str) -> None:
        hidden = self._stack[-1].hidden if self._stack else False
        if hidden:
            return
        if data.strip():
            svg_start = next(
                (
                    index
                    for index in range(len(self._stack) - 1, -1, -1)
                    if self._stack[index].tag == "svg"
                ),
                None,
            )
            if svg_start is not None:
                svg_tags = [entry.tag for entry in self._stack[svg_start:]]
                is_rendered_text = (
                    bool({"text", "tspan"}.intersection(svg_tags))
                    and not SVG_NONRENDERED_TEXT_TAGS.intersection(svg_tags)
                )
                if is_rendered_text and SVG_DEFINITION_CONTEXT_TAGS.intersection(
                    svg_tags
                ):
                    self.security_issues.append(
                        (
                            "html.svg-definition-text",
                            (
                                "figure.html inline SVG must not place text inside "
                                "defs/marker/clipPath/mask/filter contexts"
                            ),
                        )
                    )
                unsupported_text_ancestors = (
                    set(svg_tags) - SVG_VISIBLE_TEXT_ANCESTRY
                )
                if is_rendered_text and unsupported_text_ancestors:
                    self.security_issues.append(
                        (
                            "html.svg-text-context",
                            (
                                "figure.html inline SVG visible text crosses unsupported "
                                f"ancestor <{sorted(unsupported_text_ancestors)[0]}>"
                            ),
                        )
                    )
        for caption_index in self._active_captions:
            self.captions[caption_index].text_parts.append(data)
        for svg_index, text_kind in self._active_svg_text:
            if text_kind == "title":
                self.inline_svgs[svg_index].title_text.append(data)
            else:
                self.inline_svgs[svg_index].description_text.append(data)
        for svg_index, style_index in self._active_svg_styles:
            self.inline_svgs[svg_index].styles[style_index].append(data)


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_declared_content(value: Any) -> bool:
    """Return whether a free-form ledger value records any concrete content."""

    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value) and any(
            _has_declared_content(item) for item in value.values()
        )
    if isinstance(value, list):
        return bool(value) and any(_has_declared_content(item) for item in value)
    return value is not None


def _contains_nonempty_text(value: Any) -> bool:
    """Return whether a free-form review response contains explanatory text."""

    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_contains_nonempty_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nonempty_text(item) for item in value)
    return False


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _style_declarations(value: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for item in value.split(";"):
        name, separator, raw_value = item.partition(":")
        if not separator:
            continue
        normalized_name = name.strip().lower()
        normalized_value = raw_value.strip()
        if normalized_name and normalized_value:
            declarations[normalized_name] = normalized_value
    return declarations


class _CssSyntaxError(ValueError):
    pass


def _split_css_top_level(value: str, separator: str) -> list[str]:
    """Split a small, deterministic CSS subset without hiding malformed syntax."""

    items: list[str] = []
    start = 0
    quote: str | None = None
    parentheses = 0
    for index, character in enumerate(value):
        if quote is not None:
            if character == "\\":
                raise _CssSyntaxError("CSS escapes are not supported by the figure gate")
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "\\":
            raise _CssSyntaxError("CSS escapes are not supported by the figure gate")
        elif character == "(":
            parentheses += 1
        elif character == ")":
            parentheses -= 1
            if parentheses < 0:
                raise _CssSyntaxError("CSS contains an unmatched ')'")
        elif character == separator and parentheses == 0:
            items.append(value[start:index])
            start = index + 1
    if quote is not None or parentheses != 0:
        raise _CssSyntaxError("CSS contains an unterminated string or function")
    items.append(value[start:])
    return items


def _parse_css_declarations(body: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for raw_item in _split_css_top_level(body, ";"):
        item = raw_item.strip()
        if not item:
            continue
        pieces = _split_css_top_level(item, ":")
        if len(pieces) < 2:
            raise _CssSyntaxError(f"CSS declaration lacks ':': {item!r}")
        name = pieces[0].strip().lower()
        raw_value = ":".join(pieces[1:]).strip()
        if not re.fullmatch(r"--[A-Za-z0-9_-]+|-?[A-Za-z][A-Za-z0-9_-]*", name):
            raise _CssSyntaxError(f"unsupported CSS property name {name!r}")
        if not raw_value:
            raise _CssSyntaxError(f"CSS property {name!r} has an empty value")
        if name in declarations:
            raise _CssSyntaxError(f"CSS property {name!r} is declared twice in one rule")
        if not name.startswith("--") and name not in ALLOWED_CSS_PROPERTIES:
            raise _CssSyntaxError(
                f"CSS property {name!r} is outside the figure-safe allowlist"
            )
        value_error = _validate_css_value(raw_value)
        if value_error is not None:
            raise _CssSyntaxError(value_error)
        declarations[name] = raw_value
    return declarations


def _find_css_block_end(css: str, opening_brace: int) -> int:
    depth = 1
    quote: str | None = None
    parentheses = 0
    index = opening_brace + 1
    while index < len(css):
        character = css[index]
        if quote is not None:
            if character == "\\":
                raise _CssSyntaxError("CSS escapes are not supported by the figure gate")
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == "\\":
            raise _CssSyntaxError("CSS escapes are not supported by the figure gate")
        elif character == "(":
            parentheses += 1
        elif character == ")":
            parentheses -= 1
            if parentheses < 0:
                raise _CssSyntaxError("CSS contains an unmatched ')'")
        elif parentheses == 0 and character == "{":
            depth += 1
        elif parentheses == 0 and character == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise _CssSyntaxError("CSS contains an unterminated block")


def _parse_css_stylesheet(
    css: str, *, media: str | None = None
) -> list[_ParsedCssRule]:
    """Parse the scoped subset used by figures; unknown constructs fail closed."""

    if _CSS_COMMENT.search(css) or "/*" in css or "*/" in css:
        raise _CssSyntaxError("CSS comments are not supported by the figure gate")
    if "\\" in css:
        raise _CssSyntaxError("CSS escapes are not supported by the figure gate")
    rules: list[_ParsedCssRule] = []
    index = 0
    while True:
        while index < len(css) and (css[index].isspace() or css[index] == ";"):
            index += 1
        if index >= len(css):
            return rules
        opening = css.find("{", index)
        if opening < 0:
            raise _CssSyntaxError(f"unconsumed CSS text {css[index:].strip()!r}")
        header = css[index:opening].strip()
        if not header:
            raise _CssSyntaxError("CSS rule has an empty selector")
        closing = _find_css_block_end(css, opening)
        body = css[opening + 1 : closing]
        if header.startswith("@"):
            media_match = re.fullmatch(
                r"@media\s*\(\s*prefers-color-scheme\s*:\s*(dark|light)\s*\)",
                header,
                re.IGNORECASE,
            )
            if media_match is None:
                raise _CssSyntaxError(f"unsupported CSS at-rule {header!r}")
            if media is not None:
                raise _CssSyntaxError("nested @media rules cannot be audited safely")
            rules.extend(
                _parse_css_stylesheet(
                    body,
                    media=media_match.group(1).lower(),
                )
            )
        else:
            if "{" in body or "}" in body:
                raise _CssSyntaxError("nested CSS blocks are allowed only inside @media")
            selectors = tuple(
                selector.strip()
                for selector in _split_css_top_level(header, ",")
                if selector.strip()
            )
            if not selectors:
                raise _CssSyntaxError("CSS rule has no selectors")
            rules.append(
                _ParsedCssRule(
                    selectors=selectors,
                    declarations=_parse_css_declarations(body),
                    media=media,
                )
            )
        index = closing + 1


def _css_local_references(value: str) -> tuple[set[str], str | None]:
    """Return local url(#id) references, rejecting every other CSS URL."""

    if _CSS_COMMENT.search(value) or "/*" in value or "*/" in value:
        return set(), "contains a CSS comment that cannot be audited safely"
    if "\\" in value:
        return set(), "contains a CSS escape that cannot be audited safely"
    if re.search(
        r"(?<![\w-])(?:-webkit-)?image-set\s*\(",
        value,
        re.IGNORECASE,
    ):
        return set(), "contains an unsupported CSS image-set() resource"
    matches = list(_CSS_URL.finditer(value))
    if len(matches) != len(list(_CSS_URL_OPEN.finditer(value))):
        return set(), "contains a malformed CSS url() reference"
    references: set[str] = set()
    for match in matches:
        target = html.unescape(match.group(2)).strip()
        if not re.fullmatch(r"#[A-Za-z_][\w.-]*", target):
            return set(), f"CSS url() target {target!r} is not a local SVG fragment"
        references.add(target[1:])
    return references, None


def _validate_css_value(value: str) -> str | None:
    """Validate one authored CSS value against the reviewed passive subset."""

    _, reference_error = _css_local_references(value)
    if reference_error is not None:
        return reference_error
    if "@" in value:
        return "contains an unsupported CSS @ token"
    functions = {
        match.group(1).lower()
        for match in re.finditer(r"(?<![\w-])(-?[A-Za-z][\w-]*)\s*\(", value)
    }
    unsupported_functions = sorted(functions - ALLOWED_CSS_FUNCTIONS)
    if unsupported_functions:
        return f"contains unsupported CSS function {unsupported_functions[0]!r}"
    return None


def _css_selector_specificity(selector: str) -> tuple[int, int, int] | None:
    """Return specificity for the simple selectors the structural lint trusts."""

    selector = selector.strip()
    if not selector or any(token in selector for token in (">", "+", "~", ":", "[")):
        return None
    compounds = selector.split()
    if not compounds:
        return None
    ids = 0
    classes = 0
    tag_count = 0
    for compound in compounds:
        if not re.fullmatch(
            r"(?:\*|[A-Za-z][\w-]*)?(?:#[\w-]+)?(?:\.[\w-]+)*", compound
        ):
            return None
        ids += compound.count("#")
        classes += compound.count(".")
        tag = re.match(r"^(\*|[A-Za-z][\w-]*)", compound)
        tag_count += int(bool(tag and tag.group(1) != "*"))
    return (ids, classes, tag_count)


def _css_font_rules(root: ET.Element) -> tuple[list[_CssFontRule], list[str]]:
    rules: list[_CssFontRule] = []
    issues: list[str] = []
    order = 0
    for element in root.iter():
        if _local_name(element.tag) != "style":
            continue
        css = "".join(element.itertext())
        try:
            parsed_rules = _parse_css_stylesheet(css)
        except _CssSyntaxError as error:
            issues.append(str(error))
            continue
        for parsed_rule in parsed_rules:
            declarations = parsed_rule.declarations
            if "font" in declarations:
                issues.append("CSS font shorthand cannot be measured safely")
            if "transform" in declarations:
                issues.append("CSS transform cannot be measured safely")
            font_size = declarations.get("font-size")
            if not font_size:
                continue
            normalized_font_size = font_size.strip().lower()
            if normalized_font_size != "inherit":
                length_match = _CSS_LENGTH.fullmatch(normalized_font_size)
                if length_match is None or length_match.group(2) is None:
                    issues.append(
                        f"font-size value {font_size!r} cannot be measured safely"
                    )
                    continue
            for selector in parsed_rule.selectors:
                specificity = _css_selector_specificity(selector)
                if specificity is None:
                    issues.append(
                        f"font-size selector {selector!r} cannot be matched safely"
                    )
                    continue
                rules.append(
                    _CssFontRule(
                        selector=selector,
                        value=font_size,
                        specificity=specificity,
                        order=order,
                        media=parsed_rule.media,
                    )
                )
                order += 1
    return rules, issues


def _compound_selector_matches(element: ET.Element, selector: str) -> bool:
    tag_match = re.match(r"^(\*|[A-Za-z][\w-]*)", selector)
    if tag_match and tag_match.group(1) != "*":
        if _local_name(element.tag).lower() != tag_match.group(1).lower():
            return False

    id_match = re.search(r"#([\w-]+)", selector)
    if id_match and element.get("id") != id_match.group(1):
        return False

    required_classes = set(re.findall(r"\.([\w-]+)", selector))
    actual_classes = set(element.get("class", "").split())
    return required_classes.issubset(actual_classes)


def _selector_matches(
    element: ET.Element,
    selector: str,
    parent_map: dict[ET.Element, ET.Element],
) -> bool:
    compounds = selector.split()
    if not compounds or not _compound_selector_matches(element, compounds[-1]):
        return False
    current = parent_map.get(element)
    for compound in reversed(compounds[:-1]):
        while current is not None and not _compound_selector_matches(current, compound):
            current = parent_map.get(current)
        if current is None:
            return False
        current = parent_map.get(current)
    return True


def _root_stylesheet_dimensions(
    root: ET.Element,
    *,
    color_scheme: str,
) -> tuple[dict[str, str], list[str]]:
    """Resolve the supported CSS box lengths that can resize the root SVG."""

    supported_properties = {"height", "width", "min-width", "max-width"}
    unsupported_properties = set(UNSUPPORTED_ROOT_SIZING_PROPERTIES)
    selected: dict[str, tuple[tuple[int, int, int], int, str]] = {}
    issues: list[str] = []
    order = 0
    for element in root.iter():
        if _local_name(element.tag) != "style":
            continue
        try:
            parsed_rules = _parse_css_stylesheet("".join(element.itertext()))
        except _CssSyntaxError as error:
            issues.append(str(error))
            continue
        for parsed_rule in parsed_rules:
            affected = supported_properties.intersection(parsed_rule.declarations)
            unsupported = unsupported_properties.intersection(
                parsed_rule.declarations
            )
            if not affected and not unsupported:
                order += len(parsed_rule.selectors)
                continue
            if parsed_rule.media is not None and parsed_rule.media != color_scheme:
                order += len(parsed_rule.selectors)
                continue
            for selector in parsed_rule.selectors:
                specificity = _css_selector_specificity(selector)
                if specificity is None:
                    issues.append(
                        f"root sizing selector {selector!r} cannot be matched safely"
                    )
                    order += 1
                    continue
                if not _selector_matches(root, selector, {}):
                    order += 1
                    continue
                for name in sorted(unsupported):
                    issues.append(
                        f"root CSS property {name!r} cannot be measured safely"
                    )
                for name in sorted(affected):
                    value = parsed_rule.declarations[name]
                    is_auto_height = (
                        name == "height" and value.strip().lower() == "auto"
                    )
                    if not is_auto_height and _CSS_LENGTH.fullmatch(value.strip()) is None:
                        issues.append(
                            f"root CSS {name} value {value!r} cannot be measured safely"
                        )
                        continue
                    candidate = (specificity, order, value)
                    previous = selected.get(name)
                    if previous is None or candidate[:2] >= previous[:2]:
                        selected[name] = candidate
                order += 1
    return {name: candidate[2] for name, candidate in selected.items()}, issues


def _css_length_px(value: str, inherited_px: float) -> float | None:
    match = _CSS_LENGTH.fullmatch(value.strip())
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    if not math.isfinite(number) or number <= 0:
        return None
    if unit == "pt":
        return number * 96.0 / 72.0
    if unit == "em":
        return number * inherited_px
    if unit == "rem":
        return number * 16.0
    if unit == "%":
        return number * inherited_px / 100.0
    return number


def _css_root_length_px(value: str, article_width_px: float) -> float | None:
    """Resolve a root box length without guessing font- or viewport-relative units."""

    match = _CSS_LENGTH.fullmatch(value.strip())
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    if not math.isfinite(number) or number <= 0:
        return None
    if unit == "pt":
        return number * 96.0 / 72.0
    if unit == "%":
        return number * article_width_px / 100.0
    if unit != "px":
        return None
    return number


def _computed_svg_font_sizes(
    root: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    *,
    color_scheme: str,
) -> tuple[dict[ET.Element, float], list[str]]:
    rules, issues = _css_font_rules(root)
    cache: dict[ET.Element, float] = {}
    issue_set = set(issues)

    def compute(element: ET.Element) -> float:
        if element in cache:
            return cache[element]
        parent = parent_map.get(element)
        inherited = compute(parent) if parent is not None else 16.0
        selected: tuple[tuple[int, int, int], int, str] | None = None
        for rule in rules:
            if rule.media is not None and rule.media != color_scheme:
                continue
            if not _selector_matches(element, rule.selector, parent_map):
                continue
            candidate = (rule.specificity, rule.order, rule.value)
            if selected is None or candidate[:2] >= selected[:2]:
                selected = candidate

        raw_value = selected[2] if selected is not None else None
        presentation = element.get("font-size")
        if raw_value is None and presentation:
            raw_value = presentation
        inline_css = element.get("style", "")
        try:
            inline_declarations = _parse_css_declarations(inline_css)
        except _CssSyntaxError as error:
            issue_set.add(f"inline CSS cannot be measured safely: {error}")
            inline_declarations = {}
        if "font" in inline_declarations:
            issue_set.add("inline CSS font shorthand cannot be measured safely")
        if "transform" in inline_declarations:
            issue_set.add("inline CSS transform cannot be measured safely")
        inline_value = inline_declarations.get("font-size")
        if inline_value:
            raw_value = inline_value
        if raw_value is None or raw_value.strip().lower() == "inherit":
            computed = inherited
        else:
            computed = _css_length_px(raw_value, inherited)
            if computed is None:
                issue_set.add(
                    f"font-size value {raw_value!r} cannot be measured safely"
                )
                computed = inherited
        cache[element] = computed
        return cache[element]

    for element in root.iter():
        compute(element)
    return cache, sorted(issue_set)


def _svg_element_is_hidden(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> bool:
    current: ET.Element | None = element
    while current is not None:
        style = _style_declarations(current.get("style", ""))
        if current.get("hidden") is not None:
            return True
        if current.get("aria-hidden", "").strip().lower() == "true":
            return True
        if current.get("display", "").strip().lower() == "none":
            return True
        if current.get("visibility", "").strip().lower() == "hidden":
            return True
        if style.get("display", "").strip().lower() == "none":
            return True
        if style.get("visibility", "").strip().lower() == "hidden":
            return True
        opacity = style.get("opacity", current.get("opacity", "")).strip()
        try:
            if opacity and float(opacity) == 0:
                return True
        except ValueError:
            pass
        current = parent_map.get(current)
    return False


def _transform_scale(value: str) -> float | None:
    """Return the smallest local scale for transforms we can measure safely."""

    if not value.strip():
        return 1.0
    scale = 1.0
    consumed: list[tuple[int, int]] = []
    for match in re.finditer(r"([A-Za-z]+)\s*\(([^)]*)\)", value):
        consumed.append(match.span())
        operation = match.group(1).lower()
        numbers = [float(item) for item in _SVG_NUMBER.findall(match.group(2))]
        if operation in {"translate", "rotate"}:
            continue
        if operation in {"skewx", "skewy"}:
            return None
        if operation == "scale" and numbers:
            x_scale = abs(numbers[0])
            y_scale = abs(numbers[1] if len(numbers) > 1 else numbers[0])
            scale *= min(x_scale, y_scale)
            continue
        if operation == "matrix" and len(numbers) == 6:
            a, b, c, d = numbers[:4]
            squared_sum = a * a + b * b + c * c + d * d
            determinant = a * d - b * c
            discriminant = max(0.0, squared_sum * squared_sum - 4.0 * determinant * determinant)
            smallest_squared = max(0.0, (squared_sum - math.sqrt(discriminant)) / 2.0)
            scale *= math.sqrt(smallest_squared)
            continue
        return None
    remainder = value
    for start, end in reversed(consumed):
        remainder = remainder[:start] + remainder[end:]
    if remainder.strip() or not math.isfinite(scale) or scale <= 0:
        return None
    return scale


def _svg_element_scale(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> float | None:
    scale = 1.0
    current: ET.Element | None = element
    while current is not None:
        local_scale = _transform_scale(current.get("transform", ""))
        if local_scale is None:
            return None
        scale *= local_scale
        current = parent_map.get(current)
    return scale


def _svg_fit_scale(
    root: ET.Element,
    article_width_px: float,
    *,
    color_scheme: str,
) -> tuple[float, float] | None:
    view_box_numbers = [float(item) for item in _SVG_NUMBER.findall(root.get("viewBox", ""))]
    if (
        len(view_box_numbers) == 4
        and view_box_numbers[2] > 0
        and view_box_numbers[3] > 0
    ):
        coordinate_width = view_box_numbers[2]
        coordinate_height = view_box_numbers[3]
    else:
        coordinate_width = None
        coordinate_height = None

    stylesheet_dimensions, sizing_issues = _root_stylesheet_dimensions(
        root,
        color_scheme=color_scheme,
    )
    if sizing_issues:
        return None
    try:
        root_style = _parse_css_declarations(root.get("style", ""))
    except _CssSyntaxError:
        return None
    if UNSUPPORTED_ROOT_SIZING_PROPERTIES.intersection(root_style):
        return None
    raw_width = root_style.get(
        "width",
        stylesheet_dimensions.get("width", root.get("width", "")),
    )
    if raw_width:
        parsed_width = _css_root_length_px(raw_width, article_width_px)
        if parsed_width is None:
            return None
    else:
        parsed_width = coordinate_width
    if parsed_width is None or parsed_width <= 0:
        return None

    display_width = min(parsed_width, article_width_px)
    for property_name, combine in (
        ("max-width", min),
        ("min-width", max),
    ):
        raw_limit = root_style.get(
            property_name,
            stylesheet_dimensions.get(property_name, ""),
        )
        if not raw_limit:
            continue
        parsed_limit = _css_root_length_px(raw_limit, article_width_px)
        if parsed_limit is None:
            return None
        display_width = combine(display_width, parsed_limit)
    horizontal_scale = (
        display_width / coordinate_width
        if coordinate_width is not None
        else min(1.0, display_width / parsed_width)
    )
    raw_height = root_style.get(
        "height",
        stylesheet_dimensions.get("height", root.get("height", "")),
    ).strip()
    if raw_height and raw_height.lower() != "auto":
        if coordinate_height is None or "%" in raw_height:
            return None
        parsed_height = _css_root_length_px(raw_height, article_width_px)
        if parsed_height is None:
            return None
        horizontal_scale = min(horizontal_scale, parsed_height / coordinate_height)
    if coordinate_width is None:
        return (horizontal_scale, display_width)
    return (horizontal_scale, display_width)


def _collect_svg_text_samples(
    root: ET.Element,
    article_width_px: float,
) -> tuple[list[_SvgTextSample], float, list[str]] | None:
    parent_map = {child: parent for parent in root.iter() for child in parent}
    text_runs: list[tuple[ET.Element, str]] = []
    non_rendering_text_nodes = {"desc", "metadata", "style", "title"}

    def is_inside_text(element: ET.Element) -> bool:
        current: ET.Element | None = element
        while current is not None:
            if _local_name(current.tag) in {"text", "tspan"}:
                return True
            current = parent_map.get(current)
        return False

    for element in root.iter():
        tag = _local_name(element.tag)
        if tag not in non_rendering_text_nodes and is_inside_text(element):
            text_value = " ".join((element.text or "").split())
            if text_value:
                text_runs.append((element, text_value))
        parent = parent_map.get(element)
        if parent is not None and is_inside_text(parent):
            tail_value = " ".join((element.tail or "").split())
            if tail_value:
                text_runs.append((parent, tail_value))

    samples: list[_SvgTextSample] = []
    issues: list[str] = []
    display_widths: list[float] = []
    for color_scheme in ("light", "dark"):
        fit = _svg_fit_scale(
            root,
            article_width_px,
            color_scheme=color_scheme,
        )
        if fit is None:
            return None
        fit_scale, display_width = fit
        display_widths.append(display_width)
        font_sizes, scheme_issues = _computed_svg_font_sizes(
            root,
            parent_map,
            color_scheme=color_scheme,
        )
        issues.extend(scheme_issues)
        for element, text_value in text_runs:
            if _svg_element_is_hidden(element, parent_map):
                continue
            local_scale = _svg_element_scale(element, parent_map)
            if local_scale is None:
                issues.append(
                    f"transform on visible text {text_value!r} cannot be measured safely"
                )
                continue
            rendered_font_px = font_sizes[element] * fit_scale * local_scale
            if not math.isfinite(rendered_font_px) or rendered_font_px <= 0:
                continue
            samples.append(
                _SvgTextSample(
                    element=element,
                    text=text_value,
                    rendered_font_px=rendered_font_px,
                )
            )
    return samples, min(display_widths), sorted(set(issues))


def _validate_css_style_scope(
    *,
    css: str,
    root_id: str,
    all_ids: set[str],
    bundle: Path,
    code_prefix: str,
    diagnostics: list[Diagnostic],
) -> None:
    if not css.strip():
        return
    raw_references, raw_reference_error = _css_local_references(css)
    if raw_reference_error is not None:
        _add(
            diagnostics,
            bundle,
            f"{code_prefix}.external-reference",
            raw_reference_error,
        )
    else:
        missing = sorted(raw_references - all_ids)
        if missing:
            _add(
                diagnostics,
                bundle,
                f"{code_prefix}.url-reference",
                f"figure CSS refers to missing local SVG id {missing[0]!r}",
            )
    if re.search(r"(?<![\w-]):root\b", css, re.IGNORECASE):
        _add(
            diagnostics,
            bundle,
            f"{code_prefix}.style-root",
            (
                "figure CSS must not use :root because the documentation "
                "renderer can inline the SVG and leak those declarations to the page"
            ),
        )

    if not root_id:
        _add(
            diagnostics,
            bundle,
            f"{code_prefix}.style-scope-root",
            "an SVG with a <style> block must give its root <svg> a stable id",
        )
        return

    try:
        rules = _parse_css_stylesheet(css)
    except _CssSyntaxError as error:
        _add(
            diagnostics,
            bundle,
            f"{code_prefix}.style-syntax",
            f"figure CSS cannot be audited safely: {error}",
        )
        return

    scoped_selector = re.compile(
        rf"^(?:svg)?#{re.escape(root_id)}(?:$|[.#:\[\s>+~])"
    )
    unscoped: list[str] = []
    for rule in rules:
        for selector in rule.selectors:
            if not scoped_selector.match(selector):
                unscoped.append(selector)
        for name, value in rule.declarations.items():
            if name in CSS_DANGEROUS_DECLARATIONS or "expression(" in value.lower():
                _add(
                    diagnostics,
                    bundle,
                    f"{code_prefix}.unsafe-style",
                    f"figure CSS declaration {name!r} is active or browser-specific",
                )
    if unscoped:
        _add(
            diagnostics,
            bundle,
            f"{code_prefix}.style-unscoped",
            (
                f"figure CSS selector {unscoped[0]!r} is not scoped under "
                f"#{root_id}; inline figures share the article DOM, so prefix every "
                "selector with the bundle root id"
            ),
        )


def _validate_svg_style_scope(
    *,
    root: ET.Element,
    bundle: Path,
    diagnostics: list[Diagnostic],
) -> None:
    """Keep CSS from an inlined figure inside the figure's own root SVG."""

    styles = [
        "".join(element.itertext())
        for element in root.iter()
        if _local_name(element.tag) == "style"
    ]
    if not styles:
        return
    all_ids = {element.get("id") for element in root.iter() if element.get("id")}
    _validate_css_style_scope(
        css="\n".join(styles),
        root_id=root.get("id", "").strip(),
        all_ids=all_ids,
        bundle=bundle,
        code_prefix="svg",
        diagnostics=diagnostics,
    )


def _add(
    diagnostics: list[Diagnostic], bundle: Path, code: str, message: str
) -> None:
    diagnostics.append(Diagnostic(bundle=bundle, code=code, message=message))


def _is_reparse_point(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _first_reparse_below(root: Path, path: Path) -> Path | None:
    """Return the first untrusted symlink/reparse component below a trusted root."""

    root = root.resolve()
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(root)
    except ValueError:
        return None
    current = root
    for part in relative.parts:
        current = current / part
        if _is_reparse_point(current):
            return current
        if not current.exists():
            break
    return None


def _bundle_file(
    *,
    path: Path,
    repo_root: Path,
    bundle: Path,
    label: str,
    required: bool,
    diagnostics: list[Diagnostic],
) -> Path | None:
    """Resolve one regular bundle child without following reparse points."""

    if not path.exists() and not _is_reparse_point(path):
        if required:
            _add(diagnostics, bundle, f"{label}.missing", f"missing required {path.name}")
        return None
    reparse = _first_reparse_below(bundle, path)
    if reparse is not None:
        _add(
            diagnostics,
            bundle,
            f"{label}.reparse",
            f"{path.name} must be a regular bundle file, not symlink/reparse point {reparse}",
        )
        return None
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        _add(
            diagnostics,
            bundle,
            f"{label}.resolve",
            f"cannot resolve {path.name}: {error}",
        )
        return None
    if not _is_within(resolved, repo_root) or not _is_within(resolved, bundle):
        _add(
            diagnostics,
            bundle,
            f"{label}.outside-root",
            f"{path.name} resolves outside its audited bundle",
        )
        return None
    try:
        mode = resolved.stat().st_mode
    except OSError as error:
        _add(diagnostics, bundle, f"{label}.read", f"cannot stat {path.name}: {error}")
        return None
    if not stat.S_ISREG(mode):
        _add(
            diagnostics,
            bundle,
            f"{label}.not-file",
            f"{path.name} must be a regular file",
        )
        return None
    return resolved


def _mask_markdown_inline_code(content: str) -> str:
    """Mask matched CommonMark backtick spans while preserving line structure."""

    masked = list(content)
    index = 0
    while index < len(content):
        if content[index] != "`":
            index += 1
            continue
        preceding_slashes = 0
        cursor = index - 1
        while cursor >= 0 and content[cursor] == "\\":
            preceding_slashes += 1
            cursor -= 1
        opening = index
        while index < len(content) and content[index] == "`":
            index += 1
        delimiter_length = index - opening
        if preceding_slashes % 2:
            continue
        search = index
        closing_end: int | None = None
        while search < len(content):
            if content[search] != "`":
                search += 1
                continue
            closing = search
            while search < len(content) and content[search] == "`":
                search += 1
            if search - closing == delimiter_length:
                closing_end = search
                break
        if closing_end is None:
            continue
        for position in range(opening, closing_end):
            if masked[position] not in {"\r", "\n"}:
                masked[position] = " "
        index = closing_end
    return "".join(masked)


class _MarkdownHtmlAnchorParser(HTMLParser):
    """Collect actual raw-HTML fragment targets from visible Markdown source."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        normalized_tag = tag.lower()
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if raw_value is None:
                continue
            if name == "id" or (name == "name" and normalized_tag == "a"):
                self.targets.add(raw_value)


def _markdown_visible_source(content: str) -> str:
    """Remove Markdown regions that cannot contribute browser fragment targets."""

    content = re.sub(r"<!--.*?(?:-->|$)", "", content, flags=re.DOTALL)
    visible_lines: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in content.splitlines():
        if fence_character is not None:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*",
                line,
            ):
                fence_character = None
                fence_length = 0
            visible_lines.append("")
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening:
            marker = opening.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            visible_lines.append("")
            continue
        if line.startswith("    ") or line.startswith("\t"):
            visible_lines.append("")
            continue
        visible_lines.append(line)
    return _mask_markdown_inline_code("\n".join(visible_lines))


def _markdown_heading_ids(content: str) -> set[str]:
    ids: set[str] = set()
    counts: dict[str, int] = {}
    lines = content.splitlines()
    headings: list[str] = []
    for index, line in enumerate(lines):
        match = _MARKDOWN_ATX_HEADING.match(line)
        if match:
            headings.append(match.group(1).strip())
            continue
        if index > 0 and re.fullmatch(r" {0,3}(?:=+|-+)\s*", line):
            prior = lines[index - 1].strip()
            if prior:
                headings.append(prior)
    for heading in headings:
        explicit = _MARKDOWN_EXPLICIT_ID.search(heading)
        if explicit:
            basis = explicit.group(1)
        else:
            plain = re.sub(r"<[^>]+>", "", heading)
            plain = html.unescape(plain)
            basis = re.sub(r"[^\w\s-]", "", plain.lower()).strip()
            basis = re.sub(r"[\s_]+", "-", basis) or "section"
        duplicate = counts.get(basis, 0)
        counts[basis] = duplicate + 1
        ids.add(basis if duplicate == 0 else f"{basis}-{duplicate}")
    return ids


def _evidence_fragment_exists(path: Path, fragment: str) -> tuple[bool, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return False, f"cannot read locator source as UTF-8: {error}"

    line_locator = _LINE_LOCATOR.fullmatch(fragment)
    if line_locator:
        first = int(line_locator.group(1))
        last = int(line_locator.group(2) or first)
        line_count = len(content.splitlines())
        if 1 <= first <= last <= line_count:
            return True, ""
        return False, f"line locator {fragment!r} exceeds the file's {line_count} lines"

    suffix = path.suffix.lower()
    searchable_content = (
        _markdown_visible_source(content)
        if suffix in {".md", ".markdown"}
        else content
    )
    if re.search(_SOURCE_MARKER.format(re.escape(fragment)), searchable_content):
        return True, ""
    if suffix in {".md", ".markdown"}:
        if fragment in _markdown_heading_ids(searchable_content):
            return True, ""
        anchor_parser = _MarkdownHtmlAnchorParser()
        try:
            anchor_parser.feed(searchable_content)
            anchor_parser.close()
        except Exception:
            anchor_parser.targets.clear()
        if fragment in anchor_parser.targets:
            return True, ""
        return False, (
            f"locator {fragment!r} is not a Markdown heading, explicit id, "
            "line locator, or docs marker"
        )

    if suffix in STRUCTURED_EVIDENCE_SUFFIXES:
        if suffix == ".json":
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return False, "cannot resolve a fragment in malformed JSON evidence"

            def contains_key(value: Any) -> bool:
                if isinstance(value, dict):
                    return fragment in value or any(
                        contains_key(child) for child in value.values()
                    )
                if isinstance(value, list):
                    return any(contains_key(child) for child in value)
                return False

            if contains_key(parsed):
                return True, ""
        elif re.search(
            rf"(?m)^\s*(?:\[+\s*)?{re.escape(fragment)}(?:\s*\]+)?\s*[:=]",
            content,
        ):
            return True, ""
        return False, f"locator {fragment!r} is not a structured-data key"

    source_like = suffix in SOURCE_EVIDENCE_SUFFIXES or path.name.lower() in {
        "cmakelists.txt",
        "makefile",
    }
    if source_like:
        if re.search(rf"(?<![\w-]){re.escape(fragment)}(?![\w-])", content):
            return True, ""
        if re.fullmatch(r"[A-Za-z_]\w*(?:-[A-Za-z_]\w*)+", fragment):
            parts = fragment.split("-")
            for split in range(1, len(parts)):
                scoped = "-".join(parts[:split]) + "::" + "-".join(parts[split:])
                if re.search(
                    rf"(?<![\w:]){re.escape(scoped)}(?![\w:])",
                    content,
                ):
                    return True, ""
    return False, f"locator {fragment!r} does not name a line, heading, marker, or symbol"


def _load_intent(
    bundle: Path, repo_root: Path, diagnostics: list[Diagnostic]
) -> dict[str, Any] | None:
    intent_path = _bundle_file(
        path=bundle / INTENT_FILENAME,
        repo_root=repo_root,
        bundle=bundle,
        label="intent",
        required=True,
        diagnostics=diagnostics,
    )
    if intent_path is None:
        return None

    try:
        content = intent_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        _add(
            diagnostics,
            bundle,
            "intent.read",
            f"cannot read {INTENT_FILENAME} as UTF-8: {error}",
        )
        return None

    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        _add(
            diagnostics,
            bundle,
            "intent.json",
            (
                f"malformed {INTENT_FILENAME} at line {error.lineno}, "
                f"column {error.colno}: {error.msg}"
            ),
        )
        return None
    except (ValueError, MemoryError) as error:
        _add(
            diagnostics,
            bundle,
            "intent.json",
            f"malformed {INTENT_FILENAME}: {type(error).__name__}: {error}",
        )
        return None

    if not isinstance(value, dict):
        _add(
            diagnostics,
            bundle,
            "intent.type",
            f"{INTENT_FILENAME} must contain a JSON object",
        )
        return None
    return value


def _public_https_url_issue(parsed: Any, raw_value: str) -> str | None:
    """Return why a URL is unsafe to publish, or ``None`` when public-safe."""

    if parsed.scheme.lower() != "https":
        return "must use HTTPS"
    if any(character.isspace() or ord(character) < 0x20 for character in raw_value):
        return "must not contain whitespace or control characters"
    try:
        hostname = parsed.hostname
        port = parsed.port
        username = parsed.username
        password = parsed.password
    except ValueError:
        return "has malformed authority or port syntax"
    if username is not None or password is not None:
        return "must not contain URL user information"
    if parsed.query:
        return "must not contain a query string or signed-URL parameters"
    if port not in {None, 443}:
        return "must not use a non-default network port"
    if not hostname:
        return "must name a public host"

    normalized_host = hostname.casefold().rstrip(".")
    if not normalized_host or normalized_host == "localhost":
        return "must not name localhost or a private host"
    if normalized_host.endswith(_PRIVATE_HOST_SUFFIXES):
        return "must not name localhost or a private host"

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        labels = normalized_host.split(".")
        if len(labels) < 2 or any(label in _PRIVATE_HOST_LABELS for label in labels):
            return "must name a public DNS host"
    else:
        if not address.is_global:
            return "must not name a private, loopback, link-local, or reserved address"
    return None


def _validate_evidence(
    *,
    evidence: Any,
    element_label: str,
    bundle: Path,
    repo_root: Path,
    diagnostics: list[Diagnostic],
) -> None:
    if not isinstance(evidence, list) or not evidence:
        _add(
            diagnostics,
            bundle,
            "element.evidence",
            f"{element_label}.evidence must be a non-empty array of paths or public HTTPS URLs",
        )
        return

    for evidence_index, item in enumerate(evidence):
        item_label = f"{element_label}.evidence[{evidence_index}]"
        if not _is_nonempty_string(item):
            _add(
                diagnostics,
                bundle,
                "element.evidence",
                f"{item_label} must be a non-empty string",
            )
            continue

        evidence_value = item.strip()
        if "\x00" in evidence_value:
            _add(
                diagnostics,
                bundle,
                "evidence.path",
                f"{item_label} contains a null byte",
            )
            continue
        try:
            parsed = urlsplit(evidence_value)
        except ValueError as error:
            _add(
                diagnostics,
                bundle,
                "evidence.url",
                f"{item_label} is not a valid path or URL: {error}",
            )
            continue
        if parsed.scheme.lower() in {"http", "https"}:
            if not parsed.netloc:
                _add(
                    diagnostics,
                    bundle,
                    "evidence.url",
                    f"{item_label} is not a valid HTTPS URL: {evidence_value!r}",
                )
                continue
            public_url_issue = _public_https_url_issue(parsed, evidence_value)
            if public_url_issue is not None:
                _add(
                    diagnostics,
                    bundle,
                    "evidence.url-policy",
                    f"{item_label} {public_url_issue}",
                )
            continue

        local_value, fragment_separator, fragment = evidence_value.partition("#")
        if fragment_separator and not fragment:
            _add(
                diagnostics,
                bundle,
                "evidence.fragment",
                f"{item_label} has an empty source locator after '#': {evidence_value!r}",
            )
            continue

        local_path = Path(local_value)
        if local_path.is_absolute() or PureWindowsPath(local_value).is_absolute():
            _add(
                diagnostics,
                bundle,
                "evidence.absolute",
                (
                    f"{item_label} must be a repository-relative file path, "
                    f"not an absolute path: {evidence_value!r}"
                ),
            )
            continue
        # A URI-like value is neither reproducible local evidence nor an allowed URL.
        if parsed.scheme:
            _add(
                diagnostics,
                bundle,
                "evidence.scheme",
                (
                    f"{item_label} uses unsupported URI scheme {parsed.scheme!r}; "
                    "use a repository path or public HTTPS URL"
                ),
            )
            continue

        try:
            lexical_path = repo_root / local_path
            reparse = _first_reparse_below(repo_root, lexical_path)
            if reparse is not None:
                _add(
                    diagnostics,
                    bundle,
                    "evidence.reparse",
                    f"{item_label} crosses symlink/reparse point {reparse}",
                )
                continue
            resolved = lexical_path.resolve()
        except (OSError, RuntimeError, ValueError) as error:
            _add(
                diagnostics,
                bundle,
                "evidence.path",
                f"cannot resolve {item_label} {evidence_value!r}: {error}",
            )
            continue

        if not _is_within(resolved, repo_root):
            _add(
                diagnostics,
                bundle,
                "evidence.outside-root",
                (
                    f"{item_label} resolves outside --repo-root: "
                    f"{evidence_value!r}"
                ),
            )
        elif not resolved.exists():
            _add(
                diagnostics,
                bundle,
                "evidence.missing",
                f"{item_label} does not exist under --repo-root: {evidence_value!r}",
            )
        elif not resolved.is_file():
            _add(
                diagnostics,
                bundle,
                "evidence.not-file",
                f"{item_label} must identify a file, not a directory: {evidence_value!r}",
            )
        elif fragment_separator:
            exists, reason = _evidence_fragment_exists(resolved, fragment)
            if not exists:
                _add(
                    diagnostics,
                    bundle,
                    "evidence.fragment-missing",
                    f"{item_label} has no resolvable source locator: {reason}",
                )


def _validate_decomposition(
    intent: dict[str, Any], bundle: Path, diagnostics: list[Diagnostic]
) -> None:
    decomposition = intent.get("decomposition")
    if not isinstance(decomposition, (dict, list)) or not _has_declared_content(
        decomposition
    ):
        _add(
            diagnostics,
            bundle,
            "intent.decomposition",
            (
                "decomposition must be a non-empty object or array containing "
                "only the semantic facts that apply"
            ),
        )


def _validate_compositions(
    intent: dict[str, Any], bundle: Path, diagnostics: list[Diagnostic]
) -> None:
    composition_field = (
        "compositions" if "compositions" in intent else "labelFreeCompositions"
    )
    raw_compositions = intent.get(composition_field)
    candidate_ids: set[str] = set()
    if not isinstance(raw_compositions, list) or not raw_compositions:
        _add(
            diagnostics,
            bundle,
            "composition.candidates",
            (
                "compositions must contain at least the selected composition; "
                "record alternatives only when they informed the decision"
            ),
        )
        raw_compositions = (
            raw_compositions if isinstance(raw_compositions, list) else []
        )

    for index, composition in enumerate(raw_compositions):
        label = f"{composition_field}[{index}]"
        if not isinstance(composition, dict):
            _add(
                diagnostics,
                bundle,
                "composition.type",
                f"{label} must be an object",
            )
            continue
        composition_id = composition.get("id")
        if not _is_nonempty_string(composition_id):
            _add(
                diagnostics,
                bundle,
                "composition.id",
                f"{label}.id must be a stable kebab-case identifier",
            )
        else:
            composition_id = composition_id.strip()
            if not STABLE_ID.fullmatch(composition_id):
                _add(
                    diagnostics,
                    bundle,
                    "composition.id-format",
                    f"{label}.id is not stable kebab-case: {composition_id!r}",
                )
            if composition_id in candidate_ids:
                _add(
                    diagnostics,
                    bundle,
                    "composition.id-duplicate",
                    f"duplicate composition id {composition_id!r}",
                )
            else:
                candidate_ids.add(composition_id)
        if not _is_nonempty_string(composition.get("model")):
            _add(
                diagnostics,
                bundle,
                "composition.model",
                f"{label}.model must be a non-empty string",
            )

    selected = intent.get("selectedComposition")
    if not isinstance(selected, dict):
        _add(
            diagnostics,
            bundle,
            "composition.selected",
            "selectedComposition must be an object",
        )
        return
    selected_id = selected.get("id")
    if not _is_nonempty_string(selected_id):
        _add(
            diagnostics,
            bundle,
            "composition.selected-id",
            "selectedComposition.id must be a non-empty string",
        )
    elif selected_id.strip() not in candidate_ids:
        _add(
            diagnostics,
            bundle,
            "composition.selected-unknown",
            (
                "selectedComposition.id must reference a declared composition "
                f"candidate: {selected_id.strip()!r}"
            ),
        )
    if not _is_nonempty_string(selected.get("reason")):
        _add(
            diagnostics,
            bundle,
            "composition.selected-reason",
            "selectedComposition.reason must be a non-empty string",
        )


def _validate_representative_trace(
    intent: dict[str, Any],
    element_ids: set[str],
    bundle: Path,
    diagnostics: list[Diagnostic],
) -> None:
    trace = intent.get("representativeTrace")
    if not isinstance(trace, dict):
        _add(
            diagnostics,
            bundle,
            "trace.type",
            "representativeTrace must be an object",
        )
        return

    status = trace.get("status")
    if status == "pass":
        if not _is_nonempty_string(trace.get("entity")):
            _add(
                diagnostics,
                bundle,
                "trace.entity",
                "representativeTrace.entity must be non-empty when status is pass",
            )
        steps = trace.get("steps")
        if not isinstance(steps, list) or not steps:
            _add(
                diagnostics,
                bundle,
                "trace.steps",
                "representativeTrace.steps must be a non-empty element-ID array",
            )
            return
        for index, step in enumerate(steps):
            if not _is_nonempty_string(step):
                _add(
                    diagnostics,
                    bundle,
                    "trace.step",
                    f"representativeTrace.steps[{index}] must be an element ID",
                )
            elif step.strip() not in element_ids:
                _add(
                    diagnostics,
                    bundle,
                    "trace.step-unknown",
                    (
                        f"representativeTrace.steps[{index}] refers to unknown "
                        f"element ID {step.strip()!r}"
                    ),
                )
    elif status == "not-applicable":
        if not _is_nonempty_string(trace.get("reason")):
            _add(
                diagnostics,
                bundle,
                "trace.reason",
                (
                    "representativeTrace.reason must be non-empty when status "
                    "is not-applicable"
                ),
            )
    else:
        _add(
            diagnostics,
            bundle,
            "trace.status",
            "representativeTrace.status must be 'pass' or 'not-applicable'",
        )


def _validate_review_entry(
    *,
    name: str,
    value: Any,
    conditional: bool,
    bundle: Path,
    diagnostics: list[Diagnostic],
) -> None:
    label = f"review.{name}"
    if not isinstance(value, dict):
        _add(
            diagnostics,
            bundle,
            "review.entry",
            f"{label} must be an object",
        )
        return
    status = value.get("status")
    if status == "pass":
        if not _is_nonempty_string(value.get("observation")):
            _add(
                diagnostics,
                bundle,
                "review.observation",
                f"{label}.observation must be non-empty when status is pass",
            )
    elif conditional and status == "not-applicable":
        if not _is_nonempty_string(value.get("reason")):
            _add(
                diagnostics,
                bundle,
                "review.reason",
                f"{label}.reason must be non-empty when status is not-applicable",
            )
    else:
        allowed = "'pass' or 'not-applicable'" if conditional else "'pass'"
        _add(
            diagnostics,
            bundle,
            "review.status",
            f"{label}.status must be {allowed}",
        )


def _validate_review(
    intent: dict[str, Any], bundle: Path, diagnostics: list[Diagnostic]
) -> None:
    review = intent.get("review")
    if not isinstance(review, dict):
        _add(
            diagnostics,
            bundle,
            "review.type",
            "review must be an object",
        )
        return
    for name in CORE_REVIEW_CHECKS:
        _validate_review_entry(
            name=name,
            value=review.get(name),
            conditional=False,
            bundle=bundle,
            diagnostics=diagnostics,
        )
    for name, aliases in REVIEW_ALIASES.items():
        value = next((review.get(alias) for alias in aliases if alias in review), None)
        _validate_review_entry(
            name=name,
            value=value,
            conditional=False,
            bundle=bundle,
            diagnostics=diagnostics,
        )
    for name in CONDITIONAL_REVIEW_CHECKS:
        _validate_review_entry(
            name=name,
            value=review.get(name),
            conditional=True,
            bundle=bundle,
            diagnostics=diagnostics,
        )

    representative_trace = intent.get("representativeTrace")
    trace_review = review.get("trace")
    if isinstance(representative_trace, dict) and isinstance(trace_review, dict):
        representative_status = representative_trace.get("status")
        review_status = trace_review.get("status")
        if (
            representative_status in {"pass", "not-applicable"}
            and review_status in {"pass", "not-applicable"}
            and representative_status != review_status
        ):
            _add(
                diagnostics,
                bundle,
                "review.trace-consistency",
                (
                    "review.trace.status must match "
                    "representativeTrace.status"
                ),
            )

    blind_review = review.get("blindReview")
    if not isinstance(blind_review, dict):
        _add(
            diagnostics,
            bundle,
            "blind-review.type",
            "review.blindReview must be an object",
        )
        return
    if blind_review.get("status") != "pass":
        _add(
            diagnostics,
            bundle,
            "blind-review.status",
            "review.blindReview.status must be 'pass'",
        )
    reviewer_label = blind_review.get("reviewerLabel")
    if not _is_nonempty_string(reviewer_label) or not (
        NON_IDENTIFYING_REVIEWER_LABEL.fullmatch(reviewer_label.strip())
    ):
        _add(
            diagnostics,
            bundle,
            "blind-review.reviewer-label",
            (
                "review.blindReview.reviewerLabel must be a non-identifying "
                "stable label beginning with anonymous-, blind-, independent-, "
                "or review-session-"
            ),
        )
    for field in ("rendering", "prompt"):
        value = blind_review.get(field)
        if field == "rendering" and field not in blind_review:
            value = blind_review.get("artifact")  # Existing public bundles.
        if not _is_nonempty_string(value):
            requirement = (
                "the exact non-leading prompt"
                if field == "prompt"
                else f"the {field} provenance"
            )
            _add(
                diagnostics,
                bundle,
                f"blind-review.{field}",
                (
                    f"review.blindReview.{field} must record {requirement} "
                    "as a non-empty string"
                ),
            )
    recovered = blind_review.get("recovered")
    if not _contains_nonempty_text(recovered):
        _add(
            diagnostics,
            bundle,
            "blind-review.recovered",
            (
                "review.blindReview.recovered must contain the reviewer's free "
                "reading as text; no preset semantic fields are required"
            ),
        )
    if not _is_nonempty_string(blind_review.get("comparison")):
        _add(
            diagnostics,
            bundle,
            "blind-review.comparison",
            "review.blindReview.comparison must be a non-empty string",
        )


def _validate_intent(
    *,
    intent: dict[str, Any],
    bundle: Path,
    repo_root: Path,
    diagnostics: list[Diagnostic],
) -> dict[str, str]:
    """Validate the declared ledger structure and return mapped SVG ids."""

    if type(intent.get("version")) is not int or intent.get("version") != 1:
        _add(
            diagnostics,
            bundle,
            "intent.version",
            "version must be the integer 1",
        )
    intent_id = intent.get("id")
    if not _is_nonempty_string(intent_id) or not STABLE_ID.fullmatch(intent_id.strip()):
        _add(
            diagnostics,
            bundle,
            "intent.id",
            "id must be a stable kebab-case identifier",
        )
    for field in REQUIRED_INTENT_STRINGS:
        if not _is_nonempty_string(intent.get(field)):
            _add(
                diagnostics,
                bundle,
                "intent.field",
                f"{field} must be a non-empty string",
            )
    if not any(_is_nonempty_string(intent.get(field)) for field in TAKEAWAY_FIELDS):
        _add(
            diagnostics,
            bundle,
            "intent.takeaway",
            (
                "immediateTakeaway must be a non-empty string; "
                "threeSecondTakeaway remains accepted for existing bundles"
            ),
        )
    if "kind" in intent:
        kind = intent.get("kind")
        if not _is_nonempty_string(kind) or kind.strip() not in FIGURE_KINDS:
            _add(
                diagnostics,
                bundle,
                "intent.kind",
                (
                    "kind is optional; when present it must be one of "
                    + ", ".join(FIGURE_KINDS)
                ),
            )

    _validate_decomposition(intent, bundle, diagnostics)
    _validate_compositions(intent, bundle, diagnostics)

    raw_elements = intent.get("elements")
    element_ids: set[str] = set()
    svg_ids: dict[str, str] = {}
    svg_id_owners: dict[str, str] = {}
    if not isinstance(raw_elements, list) or not raw_elements:
        _add(
            diagnostics,
            bundle,
            "intent.elements",
            "elements must be a non-empty array",
        )
        raw_elements = []

    for index, element in enumerate(raw_elements):
        element_label = f"elements[{index}]"
        if not isinstance(element, dict):
            _add(
                diagnostics,
                bundle,
                "element.type",
                f"{element_label} must be an object",
            )
            continue

        for field in REQUIRED_ELEMENT_STRINGS:
            if not _is_nonempty_string(element.get(field)):
                _add(
                    diagnostics,
                    bundle,
                    "element.field",
                    f"{element_label}.{field} must be a non-empty string",
                )

        element_id = element.get("id")
        if _is_nonempty_string(element_id):
            element_id = element_id.strip()
            if not STABLE_ID.fullmatch(element_id):
                _add(
                    diagnostics,
                    bundle,
                    "element.id-format",
                    (
                        f"{element_label}.id must be a stable kebab-case identifier: "
                        f"{element_id!r}"
                    ),
                )
            if element_id in element_ids:
                _add(
                    diagnostics,
                    bundle,
                    "element.id-duplicate",
                    f"duplicate element id {element_id!r}",
                )
            else:
                element_ids.add(element_id)

        if "verb" in element and not _is_nonempty_string(element.get("verb")):
            _add(
                diagnostics,
                bundle,
                "element.verb",
                f"{element_label}.verb must be non-empty when present",
            )

        _validate_evidence(
            evidence=element.get("evidence"),
            element_label=element_label,
            bundle=bundle,
            repo_root=repo_root,
            diagnostics=diagnostics,
        )

        if "svgId" in element:
            svg_id = element["svgId"]
            if not _is_nonempty_string(svg_id):
                _add(
                    diagnostics,
                    bundle,
                    "element.svg-id",
                    f"{element_label}.svgId must be a non-empty string when present",
                )
            else:
                normalized_svg_id = svg_id.strip()
                owner = svg_id_owners.get(normalized_svg_id)
                if owner is not None:
                    _add(
                        diagnostics,
                        bundle,
                        "element.svg-id-duplicate",
                        (
                            f"{element_label}.svgId {normalized_svg_id!r} is already "
                            f"used by element {owner!r}"
                        ),
                    )
                else:
                    normalized_element_id = (
                        element_id.strip()
                        if _is_nonempty_string(element_id)
                        else element_label
                    )
                    svg_id_owners[normalized_svg_id] = normalized_element_id
                    if _is_nonempty_string(element_id):
                        svg_ids[normalized_element_id] = normalized_svg_id

    raw_order = intent.get("readingOrder")
    if not isinstance(raw_order, list) or not raw_order:
        _add(
            diagnostics,
            bundle,
            "intent.reading-order",
            "readingOrder must be a non-empty array of element IDs",
        )
    else:
        seen_order_ids: set[str] = set()
        for index, item in enumerate(raw_order):
            item_label = f"readingOrder[{index}]"
            if not _is_nonempty_string(item):
                _add(
                    diagnostics,
                    bundle,
                    "reading-order.id",
                    f"{item_label} must be a non-empty element ID",
                )
                continue
            order_id = item.strip()
            if order_id in seen_order_ids:
                _add(
                    diagnostics,
                    bundle,
                    "reading-order.duplicate",
                    f"readingOrder repeats element ID {order_id!r}",
                )
            else:
                seen_order_ids.add(order_id)
            if order_id not in element_ids:
                _add(
                    diagnostics,
                    bundle,
                    "reading-order.unknown",
                    f"{item_label} refers to unknown element ID {order_id!r}",
                )

    _validate_representative_trace(intent, element_ids, bundle, diagnostics)
    _validate_review(intent, bundle, diagnostics)

    return svg_ids


def _validate_html(
    bundle: Path,
    repo_root: Path,
    diagnostics: list[Diagnostic],
    intent_caption: str | None = None,
) -> None:
    html_path = _bundle_file(
        path=bundle / "figure.html",
        repo_root=repo_root,
        bundle=bundle,
        label="html",
        required=True,
        diagnostics=diagnostics,
    )
    if html_path is None:
        return

    try:
        content = html_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        _add(
            diagnostics,
            bundle,
            "html.read",
            f"cannot read figure.html as UTF-8: {error}",
        )
        return

    parser = _FigureHtmlParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception as error:  # HTMLParser subclasses may surface malformed entities.
        _add(
            diagnostics,
            bundle,
            "html.parse",
            f"cannot parse figure.html: {error}",
        )
        return

    if re.search(r"<!\s*(?:doctype|entity)|<\?xml", content, re.IGNORECASE):
        _add(
            diagnostics,
            bundle,
            "html.declaration",
            "figure.html must be a passive fragment without declarations or entities",
        )
    for code, message in parser.security_issues:
        _add(diagnostics, bundle, code, message)
    for inline_svg in parser.inline_svgs:
        for style_parts in inline_svg.styles:
            _validate_css_style_scope(
                css="".join(style_parts),
                root_id=inline_svg.root_id,
                all_ids=inline_svg.ids,
                bundle=bundle,
                code_prefix="html.inline-svg",
                diagnostics=diagnostics,
            )
        for missing_reference in sorted(
            inline_svg.local_references - inline_svg.ids
        ):
            _add(
                diagnostics,
                bundle,
                "html.inline-svg.url-reference",
                f"inline SVG refers to missing local id {missing_reference!r}",
            )

    captions_in_figures = [
        caption for caption in parser.captions if caption.figure_index is not None
    ]
    visible_captions = [
        caption for caption in captions_in_figures if caption.visible
    ]
    if parser.figure_count == 0:
        _add(
            diagnostics,
            bundle,
            "html.figure",
            "figure.html must contain a <figure> element",
        )
    if not captions_in_figures:
        _add(
            diagnostics,
            bundle,
            "caption.missing",
            "a <figure> must contain a visible <figcaption> that states the conclusion",
        )
    elif not visible_captions:
        _add(
            diagnostics,
            bundle,
            "caption.hidden",
            "figure.html contains figcaption only in hidden content",
        )
    else:
        visible_caption_text = [
            _normalized_text(" ".join(caption.text_parts))
            for caption in visible_captions
            if _normalized_text(" ".join(caption.text_parts))
        ]
        if not visible_caption_text:
            _add(
                diagnostics,
                bundle,
                "caption.empty",
                "the visible figcaption in figure.html must contain text",
            )
        elif intent_caption is not None and intent_caption not in visible_caption_text:
            _add(
                diagnostics,
                bundle,
                "caption.intent-mismatch",
                "the visible figcaption must match figure-intent.json caption",
            )

    referenced_output_figures: set[int] = set()
    for figure_index, reference in parser.asset_references:
        try:
            parsed = urlsplit(reference)
        except ValueError as error:
            _add(
                diagnostics,
                bundle,
                "html.asset-url",
                f"figure.html has an invalid canonical asset reference {reference!r}: {error}",
            )
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            _add(
                diagnostics,
                bundle,
                "html.asset-url",
                f"figure.html asset reference must be local: {reference!r}",
            )
            continue
        reference_path = Path(parsed.path)
        if (
            reference_path.is_absolute()
            or PureWindowsPath(parsed.path).is_absolute()
            or "\\" in parsed.path
        ):
            _add(
                diagnostics,
                bundle,
                "html.asset-url",
                f"figure.html asset reference must use a relative POSIX path: {reference!r}",
            )
            continue
        try:
            resolved_reference = (bundle / reference_path).resolve()
        except (OSError, RuntimeError, ValueError):
            _add(
                diagnostics,
                bundle,
                "html.asset-url",
                f"figure.html asset reference cannot be resolved: {reference!r}",
            )
            continue
        matched_output = False
        for output_name in ("figure.svg", "figure.png"):
            expected_output = (bundle / output_name).resolve()
            if resolved_reference == expected_output:
                matched_output = True
                safe_output = _bundle_file(
                    path=bundle / output_name,
                    repo_root=repo_root,
                    bundle=bundle,
                    label="svg" if output_name.endswith(".svg") else "png",
                    required=False,
                    diagnostics=diagnostics,
                )
                if safe_output is not None:
                    referenced_output_figures.add(figure_index)
                else:
                    _add(
                        diagnostics,
                        bundle,
                        "html.asset-missing",
                        f"figure.html references missing {output_name}",
                    )
        if not matched_output:
            _add(
                diagnostics,
                bundle,
                "html.asset-url",
                (
                    "figure.html may reference only its canonical figure.svg or "
                    f"figure.png, not {reference!r}"
                ),
            )

    accessible_inline_figures = {
        svg.figure_index
        for svg in parser.inline_svgs
        if bool(" ".join(svg.title_text).strip())
        and bool(" ".join(svg.description_text).strip())
        and bool(svg.title_ids.intersection(svg.aria_labelledby))
        and bool(svg.description_ids.intersection(svg.aria_labelledby))
    }
    content_figures = referenced_output_figures | accessible_inline_figures
    caption_figures = {
        caption.figure_index
        for caption in visible_captions
        if " ".join(caption.text_parts).strip()
        and caption.figure_index is not None
    }
    if not content_figures:
        detail = (
            "inline SVG lacks a titled and described aria-labelledby association"
            if parser.inline_svgs
            else "no canonical figure.svg or figure.png reference was found"
        )
        _add(
            diagnostics,
            bundle,
            "html.figure-content",
            (
                "a visible <figure> must contain an <img>/<object> referencing "
                "figure.svg or figure.png, or an accessible inline <svg>; "
                + detail
            ),
        )
    elif not content_figures.intersection(caption_figures):
        _add(
            diagnostics,
            bundle,
            "html.figure-association",
            (
                "the visible figcaption and canonical or inline figure content "
                "must belong to the same <figure> element"
            ),
        )


def _validate_png(
    png_path: Path, bundle: Path, diagnostics: list[Diagnostic]
) -> None:
    """Validate the complete PNG container and its decompressed scanline shape."""

    try:
        file_size = png_path.stat().st_size
        if file_size > MAX_PNG_FILE_BYTES:
            _add(
                diagnostics,
                bundle,
                "png.resource-limit",
                f"figure.png exceeds the {MAX_PNG_FILE_BYTES}-byte audit limit",
            )
            return
        data = png_path.read_bytes()
    except OSError as error:
        _add(diagnostics, bundle, "png.read", f"cannot read figure.png: {error}")
        return
    if len(data) < len(PNG_SIGNATURE) or data[:8] != PNG_SIGNATURE:
        _add(
            diagnostics,
            bundle,
            "png.signature",
            "figure.png must have the exact PNG signature",
        )
        return

    offset = 8
    chunk_count = 0
    ihdr: bytes | None = None
    palette: bytes | None = None
    idat_parts: list[bytes] = []
    seen_idat = False
    idat_closed = False
    seen_iend = False
    while offset < len(data):
        chunk_count += 1
        if chunk_count > MAX_PNG_CHUNKS:
            _add(
                diagnostics,
                bundle,
                "png.resource-limit",
                f"figure.png exceeds the {MAX_PNG_CHUNKS}-chunk audit limit",
            )
            return
        if len(data) - offset < 12:
            _add(
                diagnostics,
                bundle,
                "png.chunk-truncated",
                "figure.png ends inside a chunk header or CRC",
            )
            return
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if length > MAX_PNG_FILE_BYTES or chunk_end > len(data):
            _add(
                diagnostics,
                bundle,
                "png.chunk-length",
                f"PNG chunk {chunk_type!r} declares data beyond the file",
            )
            return
        if (
            len(chunk_type) != 4
            or any(not (65 <= byte <= 90 or 97 <= byte <= 122) for byte in chunk_type)
            or not (65 <= chunk_type[2] <= 90)
        ):
            _add(
                diagnostics,
                bundle,
                "png.chunk-type",
                f"PNG chunk type {chunk_type!r} is not structurally valid",
            )
            return
        payload = data[offset + 8 : offset + 8 + length]
        recorded_crc = int.from_bytes(data[offset + 8 + length : chunk_end], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if actual_crc != recorded_crc:
            _add(
                diagnostics,
                bundle,
                "png.chunk-crc",
                f"PNG chunk {chunk_type.decode('ascii')} has an invalid CRC",
            )
            return

        if chunk_count == 1 and chunk_type != b"IHDR":
            _add(
                diagnostics,
                bundle,
                "png.ihdr",
                "figure.png must begin with one 13-byte IHDR chunk",
            )
            return
        if chunk_type == b"IHDR":
            if ihdr is not None or chunk_count != 1 or length != 13:
                _add(
                    diagnostics,
                    bundle,
                    "png.ihdr",
                    "figure.png must contain exactly one 13-byte IHDR first",
                )
                return
            ihdr = payload
        elif chunk_type == b"PLTE":
            if palette is not None or seen_idat:
                _add(
                    diagnostics,
                    bundle,
                    "png.order",
                    "PNG PLTE must occur at most once and before IDAT",
                )
                return
            palette = payload
        elif chunk_type == b"IDAT":
            if idat_closed:
                _add(
                    diagnostics,
                    bundle,
                    "png.order",
                    "PNG IDAT chunks must be consecutive",
                )
                return
            seen_idat = True
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            if length != 0:
                _add(
                    diagnostics,
                    bundle,
                    "png.iend",
                    "PNG IEND must have zero-length data",
                )
                return
            seen_iend = True
            offset = chunk_end
            if offset != len(data):
                _add(
                    diagnostics,
                    bundle,
                    "png.trailing-data",
                    "figure.png contains bytes or chunks after IEND",
                )
            break
        else:
            if chunk_type[0] <= ord("Z"):
                _add(
                    diagnostics,
                    bundle,
                    "png.unknown-critical",
                    f"figure.png contains unknown critical chunk {chunk_type!r}",
                )
                return
            if seen_idat:
                idat_closed = True
        offset = chunk_end

    if ihdr is None:
        _add(diagnostics, bundle, "png.ihdr", "figure.png is missing IHDR")
        return
    if not seen_iend:
        _add(diagnostics, bundle, "png.iend", "figure.png is missing IEND")
        return
    if not seen_idat:
        _add(diagnostics, bundle, "png.order", "figure.png is missing IDAT")
        return

    width = int.from_bytes(ihdr[0:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
    bit_depth, color_type, compression, filter_method, interlace = ihdr[8:13]
    if not (1 <= width <= 0x7FFFFFFF and 1 <= height <= 0x7FFFFFFF):
        _add(
            diagnostics,
            bundle,
            "png.dimensions",
            f"figure.png dimensions must be 1..2147483647; got {width}x{height}",
        )
        return
    if bit_depth not in PNG_COLOR_DEPTHS.get(color_type, frozenset()):
        _add(
            diagnostics,
            bundle,
            "png.color-format",
            f"PNG color type {color_type} does not permit bit depth {bit_depth}",
        )
        return
    if compression != 0 or filter_method != 0 or interlace not in {0, 1}:
        _add(
            diagnostics,
            bundle,
            "png.color-format",
            "PNG uses an unsupported compression, filter, or interlace method",
        )
        return

    if palette is not None:
        if len(palette) < 3 or len(palette) > 768 or len(palette) % 3:
            _add(
                diagnostics,
                bundle,
                "png.palette",
                "PNG PLTE must contain 1..256 complete RGB entries",
            )
            return
        if color_type in {0, 4}:
            _add(
                diagnostics,
                bundle,
                "png.palette",
                "grayscale PNG color types must not contain PLTE",
            )
            return
        if color_type == 3 and len(palette) // 3 > 2**bit_depth:
            _add(
                diagnostics,
                bundle,
                "png.palette",
                "indexed PNG PLTE has more entries than its bit depth permits",
            )
            return
    elif color_type == 3:
        _add(
            diagnostics,
            bundle,
            "png.palette",
            "indexed PNG color type requires PLTE before IDAT",
        )
        return

    channels = PNG_CHANNELS[color_type]
    passes = ADAM7_PASSES if interlace else ((0, 0, 1, 1),)
    row_shapes: list[tuple[int, int]] = []
    expected_bytes = 0
    scanlines = 0
    for x_start, y_start, x_step, y_step in passes:
        pass_width = (
            0 if width <= x_start else (width - x_start + x_step - 1) // x_step
        )
        pass_height = (
            0 if height <= y_start else (height - y_start + y_step - 1) // y_step
        )
        if pass_width == 0 or pass_height == 0:
            continue
        row_bytes = (pass_width * channels * bit_depth + 7) // 8
        expected_bytes += pass_height * (row_bytes + 1)
        scanlines += pass_height
        row_shapes.append((pass_height, row_bytes))
    if (
        expected_bytes > MAX_PNG_DECOMPRESSED_BYTES
        or scanlines > MAX_PNG_SCANLINES
    ):
        _add(
            diagnostics,
            bundle,
            "png.resource-limit",
            "PNG decompressed scanlines exceed the figure audit resource limit",
        )
        return

    compressed = b"".join(idat_parts)
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, expected_bytes + 1)
        if decompressor.unconsumed_tail:
            _add(
                diagnostics,
                bundle,
                "png.scanline-length",
                "PNG decompresses to more bytes than its IHDR permits",
            )
            return
        raw += decompressor.flush()
    except zlib.error as error:
        _add(diagnostics, bundle, "png.zlib", f"PNG IDAT zlib stream is invalid: {error}")
        return
    if not decompressor.eof or decompressor.unused_data:
        _add(
            diagnostics,
            bundle,
            "png.zlib",
            "PNG IDAT must contain exactly one complete zlib stream",
        )
        return
    if len(raw) != expected_bytes:
        _add(
            diagnostics,
            bundle,
            "png.scanline-length",
            f"PNG scanlines contain {len(raw)} bytes; IHDR requires {expected_bytes}",
        )
        return

    cursor = 0
    for pass_height, row_bytes in row_shapes:
        for _ in range(pass_height):
            filter_byte = raw[cursor]
            if filter_byte > 4:
                _add(
                    diagnostics,
                    bundle,
                    "png.filter-byte",
                    f"PNG scanline has invalid filter byte {filter_byte}",
                )
                return
            cursor += row_bytes + 1


def _validate_svg_typography(
    *,
    root: ET.Element,
    bundle: Path,
    article_width_px: float,
    diagnostics: list[Diagnostic],
) -> None:
    """Require a structurally measurable SVG text layout without judging it."""

    collected = _collect_svg_text_samples(root, article_width_px)
    if collected is None:
        _add(
            diagnostics,
            bundle,
            "svg.typography-unverifiable",
            "SVG display scale cannot be derived from its width/viewBox",
        )
        return
    _, _, typography_issues = collected
    for issue in typography_issues:
        _add(
            diagnostics,
            bundle,
            "svg.typography-unverifiable",
            issue,
        )

def _validate_svg_active_content(
    *,
    root: ET.Element,
    raw_svg: str,
    bundle: Path,
    diagnostics: list[Diagnostic],
) -> None:
    if re.search(r"<!\s*(?:doctype|entity)", raw_svg, re.IGNORECASE):
        _add(
            diagnostics,
            bundle,
            "svg.declaration",
            "figure.svg must not contain a document type or entity declaration",
        )
    processing_instructions = re.findall(
        r"<\?\s*([A-Za-z_:][\w:.-]*)",
        raw_svg,
    )
    if any(target.lower() != "xml" for target in processing_instructions):
        _add(
            diagnostics,
            bundle,
            "svg.declaration",
            "figure.svg must not contain processing instructions such as xml-stylesheet",
        )

    all_ids = {element.get("id") for element in root.iter() if element.get("id")}
    forbidden_svg_tags = {
        "audio",
        "animate",
        "animatemotion",
        "animatetransform",
        "discard",
        "embed",
        "foreignobject",
        "iframe",
        "math",
        "object",
        "script",
        "set",
        "video",
    }
    for element in root.iter():
        tag = _local_name(element.tag).lower()
        if tag == "svg" and element is not root:
            _add(
                diagnostics,
                bundle,
                "svg.nested-viewport",
                (
                    "figure.svg must not contain nested <svg> viewports; flatten the "
                    "drawing so typography has one auditable coordinate mapping"
                ),
            )
        if tag in UNSUPPORTED_SVG_CONTEXT_TAGS:
            _add(
                diagnostics,
                bundle,
                "svg.unsupported-context",
                (
                    f"figure.svg must not use <{tag}>; instance, embedded, and "
                    "secondary viewport contexts are outside the audited subset"
                ),
            )
        if tag in forbidden_svg_tags:
            _add(
                diagnostics,
                bundle,
                "svg.active-content",
                f"figure.svg must not contain active <{tag}> content",
            )
        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name).lower()
            if name.startswith("on"):
                _add(
                    diagnostics,
                    bundle,
                    "svg.event-handler",
                    f"figure.svg must not contain event-handler attribute {name!r}",
                )
            if name == "base":
                _add(
                    diagnostics,
                    bundle,
                    "svg.external-reference",
                    "figure.svg must not alter URL resolution with xml:base",
                )
            if name == "style":
                try:
                    _parse_css_declarations(raw_value)
                except _CssSyntaxError as error:
                    _add(
                        diagnostics,
                        bundle,
                        "svg.style-syntax",
                        f"figure.svg inline CSS cannot be audited safely: {error}",
                    )
            if name == "href":
                target = html.unescape(raw_value).strip()
                if not re.fullmatch(r"#[A-Za-z_][\w.-]*", target):
                    _add(
                        diagnostics,
                        bundle,
                        "svg.external-reference",
                        f"figure.svg href {target!r} is not a local fragment",
                    )
                elif target[1:] not in all_ids:
                    _add(
                        diagnostics,
                        bundle,
                        "svg.url-reference",
                        f"figure.svg href refers to missing local id {target[1:]!r}",
                    )
            references, reference_error = _css_local_references(raw_value)
            if reference_error is not None:
                _add(
                    diagnostics,
                    bundle,
                    "svg.external-reference",
                    f"figure.svg attribute {name!r}: {reference_error}",
                )
            else:
                missing = sorted(references - all_ids)
                if missing:
                    _add(
                        diagnostics,
                        bundle,
                        "svg.url-reference",
                        f"figure.svg refers to missing local id {missing[0]!r}",
                    )

    parent_map = {child: parent for parent in root.iter() for child in parent}

    def is_inside_text(element: ET.Element) -> bool:
        current: ET.Element | None = element
        while current is not None:
            if _local_name(current.tag).lower() in {"text", "tspan"}:
                return True
            current = parent_map.get(current)
        return False

    definition_text_reported = False
    unsupported_text_reported = False
    for element in root.iter():
        candidates: list[ET.Element] = []
        tag = _local_name(element.tag).lower()
        if (
            tag not in SVG_NONRENDERED_TEXT_TAGS
            and is_inside_text(element)
            and (element.text or "").strip()
        ):
            candidates.append(element)
        parent = parent_map.get(element)
        if (
            parent is not None
            and is_inside_text(parent)
            and (element.tail or "").strip()
        ):
            candidates.append(parent)
        for owner in candidates:
            ancestry: list[str] = []
            current: ET.Element | None = owner
            while current is not None:
                ancestry.append(_local_name(current.tag).lower())
                current = parent_map.get(current)
            if (
                not definition_text_reported
                and SVG_DEFINITION_CONTEXT_TAGS.intersection(ancestry)
            ):
                _add(
                    diagnostics,
                    bundle,
                    "svg.definition-text",
                    (
                        "figure.svg must not place text inside "
                        "defs/marker/clipPath/mask/filter contexts"
                    ),
                )
                definition_text_reported = True
            unsupported_ancestors = set(ancestry) - SVG_VISIBLE_TEXT_ANCESTRY
            if unsupported_ancestors and not unsupported_text_reported:
                _add(
                    diagnostics,
                    bundle,
                    "svg.text-context",
                    (
                        "visible SVG text crosses unsupported ancestor "
                        f"<{sorted(unsupported_ancestors)[0]}>"
                    ),
                )
                unsupported_text_reported = True


def _validate_svg(
    *,
    bundle: Path,
    repo_root: Path,
    svg_ids_from_intent: dict[str, str],
    article_width_px: float,
    diagnostics: list[Diagnostic],
) -> None:
    svg_path = _bundle_file(
        path=bundle / "figure.svg",
        repo_root=repo_root,
        bundle=bundle,
        label="svg",
        required=False,
        diagnostics=diagnostics,
    )
    png_path = _bundle_file(
        path=bundle / "figure.png",
        repo_root=repo_root,
        bundle=bundle,
        label="png",
        required=False,
        diagnostics=diagnostics,
    )
    has_svg = svg_path is not None
    has_png = png_path is not None
    if not has_svg and not has_png:
        _add(
            diagnostics,
            bundle,
            "output.missing",
            "bundle must contain at least one generated output: figure.svg or figure.png",
        )
        return

    if png_path is not None:
        _validate_png(png_path, bundle, diagnostics)

    if not has_svg:
        for element_id, svg_id in sorted(svg_ids_from_intent.items()):
            _add(
                diagnostics,
                bundle,
                "element.svg-id-no-svg",
                (
                    f"element {element_id!r} declares svgId {svg_id!r}, "
                    "but the bundle has no figure.svg"
                ),
            )
        return

    try:
        raw_svg = svg_path.read_text(encoding="utf-8")
        root = ET.fromstring(raw_svg)
    except (ET.ParseError, OSError, UnicodeError) as error:
        _add(
            diagnostics,
            bundle,
            "svg.parse",
            f"cannot parse figure.svg: {error}",
        )
        return

    if _local_name(root.tag) != "svg":
        _add(
            diagnostics,
            bundle,
            "svg.root",
            "figure.svg root element must be <svg>",
        )

    _validate_svg_style_scope(
        root=root,
        bundle=bundle,
        diagnostics=diagnostics,
    )
    _validate_svg_active_content(
        root=root,
        raw_svg=raw_svg,
        bundle=bundle,
        diagnostics=diagnostics,
    )
    _validate_svg_typography(
        root=root,
        bundle=bundle,
        article_width_px=article_width_px,
        diagnostics=diagnostics,
    )

    direct_titles = [child for child in root if _local_name(child.tag) == "title"]
    direct_descriptions = [
        child for child in root if _local_name(child.tag) == "desc"
    ]
    valid_titles = [
        item for item in direct_titles if "".join(item.itertext()).strip()
    ]
    valid_descriptions = [
        item for item in direct_descriptions if "".join(item.itertext()).strip()
    ]
    if not valid_titles:
        _add(
            diagnostics,
            bundle,
            "svg.title",
            "figure.svg must have a non-empty top-level <title>",
        )
    if not valid_descriptions:
        _add(
            diagnostics,
            bundle,
            "svg.desc",
            "figure.svg must have a non-empty top-level <desc>",
        )

    all_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for element in root.iter():
        element_id = element.get("id")
        if not element_id:
            continue
        if element_id in all_ids:
            duplicate_ids.add(element_id)
        all_ids.add(element_id)
    for duplicate_id in sorted(duplicate_ids):
        _add(
            diagnostics,
            bundle,
            "svg.id-duplicate",
            f"figure.svg contains duplicate id {duplicate_id!r}",
        )

    labelled_by = root.get("aria-labelledby", "").split()
    if not labelled_by:
        _add(
            diagnostics,
            bundle,
            "svg.aria-labelledby",
            "figure.svg root must declare aria-labelledby for its title and description",
        )
    else:
        for referenced_id in labelled_by:
            if referenced_id not in all_ids:
                _add(
                    diagnostics,
                    bundle,
                    "svg.aria-reference",
                    f"aria-labelledby refers to missing id {referenced_id!r}",
                )

        title_ids = {item.get("id") for item in valid_titles if item.get("id")}
        desc_ids = {
            item.get("id") for item in valid_descriptions if item.get("id")
        }
        if not title_ids.intersection(labelled_by):
            _add(
                diagnostics,
                bundle,
                "svg.aria-title",
                "aria-labelledby must reference the top-level title id",
            )
        if not desc_ids.intersection(labelled_by):
            _add(
                diagnostics,
                bundle,
                "svg.aria-desc",
                "aria-labelledby must reference the top-level desc id",
            )

    for element_id, svg_id in sorted(svg_ids_from_intent.items()):
        if svg_id not in all_ids:
            _add(
                diagnostics,
                bundle,
                "element.svg-id-missing",
                (
                    f"element {element_id!r} declares svgId {svg_id!r}, "
                    "which is not an id in figure.svg"
                ),
            )


def audit_bundle(
    bundle: Path,
    repo_root: Path,
    article_width_px: float = DEFAULT_ARTICLE_WIDTH_PX,
) -> list[Diagnostic]:
    """Audit one bundle and return all errors without stopping at the first one."""

    repo_root = repo_root.resolve()
    lexical_bundle = Path(os.path.abspath(bundle))
    diagnostics: list[Diagnostic] = []

    reparse = _first_reparse_below(repo_root, lexical_bundle)
    if reparse is not None:
        _add(
            diagnostics,
            lexical_bundle,
            "bundle.reparse",
            f"bundle path crosses symlink/reparse point {reparse}",
        )
        return diagnostics
    try:
        bundle = lexical_bundle.resolve()
    except (OSError, RuntimeError, ValueError) as error:
        _add(
            diagnostics,
            lexical_bundle,
            "bundle.resolve",
            f"cannot resolve bundle path: {error}",
        )
        return diagnostics

    if not _is_within(bundle, repo_root):
        _add(
            diagnostics,
            bundle,
            "bundle.outside-root",
            f"bundle resolves outside --repo-root {str(repo_root)!r}",
        )
        return diagnostics
    if not bundle.is_dir():
        _add(
            diagnostics,
            bundle,
            "bundle.missing",
            "bundle path does not exist or is not a directory",
        )
        return diagnostics

    _bundle_file(
        path=bundle / "build.py",
        repo_root=repo_root,
        bundle=bundle,
        label="build",
        required=True,
        diagnostics=diagnostics,
    )

    intent = _load_intent(bundle, repo_root, diagnostics)
    svg_ids: dict[str, str] = {}
    intent_caption: str | None = None
    if intent is not None:
        svg_ids = _validate_intent(
            intent=intent,
            bundle=bundle,
            repo_root=repo_root,
            diagnostics=diagnostics,
        )
        raw_caption = intent.get("caption")
        if _is_nonempty_string(raw_caption):
            intent_caption = _normalized_text(raw_caption)

    _validate_html(
        bundle,
        repo_root,
        diagnostics,
        intent_caption=intent_caption,
    )
    _validate_svg(
        bundle=bundle,
        repo_root=repo_root,
        svg_ids_from_intent=svg_ids,
        article_width_px=article_width_px,
        diagnostics=diagnostics,
    )
    return diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="repository root for bundle containment and evidence paths (default: cwd)",
    )
    parser.add_argument(
        "--bundle",
        action="append",
        required=True,
        type=Path,
        help="figure bundle to audit; repeat for each opt-in bundle",
    )
    parser.add_argument(
        "--article-width-px",
        type=float,
        default=DEFAULT_ARTICLE_WIDTH_PX,
        help=(
            "normal shrink-to-fit article slot used to resolve SVG sizing "
            f"declarations (default: {DEFAULT_ARTICLE_WIDTH_PX:g})"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    if not repo_root.is_dir():
        print(
            f"ERROR [--repo-root] repo.missing: not a directory: {repo_root}",
            file=sys.stderr,
        )
        return 2
    if not math.isfinite(arguments.article_width_px) or arguments.article_width_px <= 0:
        print(
            "ERROR [--article-width-px] value must be a positive finite number",
            file=sys.stderr,
        )
        return 2

    bundles: list[Path] = []
    seen_bundles: set[Path] = set()
    for raw_bundle in arguments.bundle:
        bundle = raw_bundle if raw_bundle.is_absolute() else repo_root / raw_bundle
        if bundle not in seen_bundles:
            seen_bundles.add(bundle)
            bundles.append(bundle)

    diagnostics: list[Diagnostic] = []
    for bundle in bundles:
        diagnostics.extend(
            audit_bundle(
                bundle=bundle,
                repo_root=repo_root,
                article_width_px=arguments.article_width_px,
            )
        )

    if diagnostics:
        for diagnostic in diagnostics:
            print(diagnostic.format(repo_root), file=sys.stderr)
        print(
            f"Figure structural gate failed: {len(diagnostics)} error(s) across "
            f"{len(bundles)} explicitly selected bundle(s).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Figure structural gate passed: {len(bundles)} "
        "explicitly selected bundle(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
