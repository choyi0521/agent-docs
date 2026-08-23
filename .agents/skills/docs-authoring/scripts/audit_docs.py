#!/usr/bin/env python3
"""Audit a configured public documentation tree without repository assumptions."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any


DISCOURAGED = re.compile(
    r"\b(obviously|simply|seamlessly|robust|powerful)\b", re.IGNORECASE
)
WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)
H1 = re.compile(r"^[ \t]{0,3}#[ \t]+(.+?)[ \t]*$", re.MULTILINE)
HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+", re.MULTILINE)
H2 = re.compile(r"^[ \t]{0,3}##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
H3 = re.compile(r"^[ \t]{0,3}###[ \t]+(.+?)[ \t]*$", re.MULTILINE)
PLAN_OPEN = re.compile(
    r"^[ \t]{0,3}:::plan(?:[ \t]+(?P<title>.*\S))?[ \t]*$", re.MULTILINE
)
PLAN_CLOSE = re.compile(r"^[ \t]{0,3}:::[ \t]*$", re.MULTILINE)
PLAN_GOAL = re.compile(
    r"^[ \t]{0,3}###[ \t]+(?P<title>.+?)[ \t]+"
    r"\{#(?P<anchor>[a-z0-9]+(?:-[a-z0-9]+)*)\}"
    r"(?:[ \t]+#+)?[ \t]*$"
)
PLAN_FIELD = re.compile(
    r"^[ \t]{0,3}\*\*(?P<name>[^*]+):\*\*[ \t]*(?P<value>.*?)[ \t]*$",
    re.MULTILINE,
)
PLAN_BULLET_FIELD = re.compile(
    r"^[ \t]{0,3}[-+*][ \t]+\*\*(?P<name>[^*\n]+):\*\*", re.MULTILINE
)
PLAN_STEP = re.compile(
    r"^[ \t]{0,3}-[ \t]+\[ \][ \t]+(?P<value>\S.*)$", re.MULTILINE
)
PLAN_DONE_STEP = re.compile(
    r"^[ \t]{0,3}[-+*][ \t]+\[[xX]\](?:[ \t]+|$)", re.MULTILINE
)
MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]]+\]\((?P<target>[^)\s]+)(?:\s+[^)]*)?\)"
)
VISIBLE_IMAGE = re.compile(r"!\[[^\]]+\]\([^)]+\)|<img\s", re.IGNORECASE)
SOURCE_MARKER = re.compile(
    r"^[ \t]*[^A-Za-z0-9\r\n]*docs:(?P<kind>begin|end)[ \t]+"
    r"(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)[^A-Za-z0-9_\r\n]*$"
)
REFERENCE_ITEM = re.compile(
    r"^[ \t]{0,3}-[ \t]+\*\*(?P<label>Source|Tests|Build|"
    r"Project authorities|External sources):\*\*[ \t]+(?P<body>.*?)(?="
    r"^[ \t]{0,3}-[ \t]+\*\*|\Z)",
    re.MULTILINE | re.DOTALL,
)
REFERENCE_BULLET_LABEL = re.compile(
    r"^[ \t]{0,3}-[ \t]+\*\*(?P<label>[^*\n]+):\*\*", re.MULTILINE
)
REFERENCE_LABELS = frozenset(
    {"Source", "Tests", "Build", "Project authorities", "External sources"}
)
EVIDENCE_LABELS = frozenset({"Source", "Tests", "Build"})
PLAN_REQUIRED_FIELDS = ("Current", "Done when")
PLAN_OPTIONAL_FIELDS = ("Source", "Depends on", "Decision", "Out of scope")
PLAN_FIELDS = frozenset(PLAN_REQUIRED_FIELDS + PLAN_OPTIONAL_FIELDS)
SNIPPET_FOLD_VALUES = frozenset({"true", "false", "1", "0", "yes", "no"})
SNIPPET_FOLDED_VALUES = frozenset({"true", "1", "yes"})
GENERIC_SNIPPET_TITLES = frozenset(
    {"code", "implementation", "snippet", "source", "source code", "source snippet"}
)
VISIBLE_SNIPPET_REVIEW_LINES = 24
VISIBLE_SNIPPET_MAX_LINES = 40
FOLDED_SNIPPET_REVIEW_LINES = 120
CODE_HEAVY_SECTION_LINES = 60
MANY_SNIPPETS = 8
SUBSTANTIAL_CONCEPT_WORDS = 500


class ConfigurationError(ValueError):
    """Raised when the JSON audit configuration is invalid."""


@dataclass(frozen=True)
class SectionConfig:
    path: str
    role: str
    allow_plans: bool
    require_references: bool


@dataclass(frozen=True)
class SourceRootConfig:
    id: str
    path: str
    resolved: pathlib.Path
    code_route: str | None


@dataclass(frozen=True)
class EvidenceRule:
    role: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class BuildCommand:
    name: str
    cwd: str
    resolved_cwd: pathlib.Path
    argv: tuple[str, ...]


@dataclass(frozen=True)
class AuditConfig:
    repository: pathlib.Path
    docs_path: str
    docs: pathlib.Path
    index_file: str
    nav_key: str
    sections: tuple[SectionConfig, ...]
    asset_roots: tuple[str, ...]
    retired_roots: tuple[str, ...]
    plan_anchor_prefix: str
    source_roots: tuple[SourceRootConfig, ...]
    evidence_rules: tuple[EvidenceRule, ...]
    build_commands: tuple[BuildCommand, ...]

    @property
    def sections_by_path(self) -> dict[str, SectionConfig]:
        return {section.path: section for section in self.sections}

    @property
    def source_roots_by_id(self) -> dict[str, SourceRootConfig]:
        return {source.id: source for source in self.source_roots}


@dataclass(frozen=True)
class FenceBlock:
    start: int
    end: int
    info: str
    body: str


@dataclass(frozen=True)
class PlanBlock:
    start: int
    content_start: int
    content_end: int
    end: int
    title: str


@dataclass(frozen=True)
class SnippetTarget:
    source: SourceRootConfig
    relative_path: str
    snippet_id: str
    resolved: pathlib.Path


@dataclass(frozen=True)
class CodeEvidence:
    start: int
    end: int
    label: str
    line_count: int | None
    source_snippet: bool
    folded: bool
    target: SnippetTarget | None = None
    target_error: str | None = None


def require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{field} must be an object")
    return value


def require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigurationError(f"{field} must be an array")
    return value


def reject_unknown(mapping: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ConfigurationError(f"{field} has unknown field(s): {', '.join(unknown)}")


def relative_posix_path(
    value: Any,
    field: str,
    *,
    allow_dot: bool = False,
    single_segment: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a nonempty string")
    if value != value.strip() or "\\" in value or "\x00" in value:
        raise ConfigurationError(f"{field} must use a clean forward-slash path")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        raise ConfigurationError(f"{field} must be repository-relative")
    pure = pathlib.PurePosixPath(value)
    raw_parts = value.split("/")
    if pure.is_absolute() or any(part in {"", ".."} for part in raw_parts):
        raise ConfigurationError(f"{field} must not be absolute or contain '..'")
    normalized = pure.as_posix()
    if normalized == "." and not allow_dot:
        raise ConfigurationError(f"{field} must name a path")
    if single_segment and (normalized == "." or len(pure.parts) != 1):
        raise ConfigurationError(f"{field} must be one top-level directory name")
    return normalized


def resolve_inside(
    root: pathlib.Path, relative: str, field: str, *, strict: bool = False
) -> pathlib.Path:
    pure = pathlib.PurePosixPath(relative)
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=strict)
        resolved.relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as error:
        raise ConfigurationError(f"{field} resolves outside the repository ({error})")
    return resolved


def load_config(
    config_path: pathlib.Path, repository_override: pathlib.Path | None = None
) -> AuditConfig:
    try:
        resolved_config = config_path.resolve(strict=True)
        raw = json.loads(resolved_config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"cannot read configuration: {error}") from error

    data = require_mapping(raw, "configuration")
    reject_unknown(
        data,
        {
            "repo_root",
            "docs_root",
            "index_file",
            "nav_key",
            "sections",
            "asset_roots",
            "retired_roots",
            "plan_anchor_prefix",
            "source_roots",
            "evidence_rules",
            "build_commands",
        },
        "configuration",
    )

    if repository_override is not None:
        repository = repository_override.resolve()
    else:
        repo_value = data.get("repo_root", ".")
        repo_relative = relative_posix_path(
            repo_value, "repo_root", allow_dot=True
        )
        repository = resolved_config.parent.joinpath(
            *pathlib.PurePosixPath(repo_relative).parts
        ).resolve()
    if not repository.is_dir():
        raise ConfigurationError(f"repository root is not a directory: {repository}")

    docs_path = relative_posix_path(
        data.get("docs_root"), "docs_root", allow_dot=True
    )
    docs = resolve_inside(repository, docs_path, "docs_root")

    index_file = data.get("index_file", "_index.md")
    if (
        not isinstance(index_file, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]+\.md", index_file)
    ):
        raise ConfigurationError("index_file must be a Markdown filename")
    nav_key = data.get("nav_key", "nav")
    if not isinstance(nav_key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", nav_key):
        raise ConfigurationError("nav_key must be a simple frontmatter key")

    sections_raw = require_list(data.get("sections"), "sections")
    if not sections_raw:
        raise ConfigurationError("sections must contain at least one section")
    sections: list[SectionConfig] = []
    seen_sections: set[str] = set()
    for index, item in enumerate(sections_raw):
        name = f"sections[{index}]"
        entry = require_mapping(item, name)
        reject_unknown(
            entry,
            {"path", "role", "allow_plans", "require_references"},
            name,
        )
        path = relative_posix_path(
            entry.get("path"), f"{name}.path", single_segment=True
        )
        if path in seen_sections:
            raise ConfigurationError(f"duplicate section path: {path}")
        seen_sections.add(path)
        role = entry.get("role")
        if not isinstance(role, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]*", role
        ):
            raise ConfigurationError(f"{name}.role must be a lowercase id")
        allow_plans = entry.get("allow_plans", False)
        require_references = entry.get("require_references", False)
        if not isinstance(allow_plans, bool) or not isinstance(require_references, bool):
            raise ConfigurationError(
                f"{name} allow_plans and require_references must be booleans"
            )
        sections.append(
            SectionConfig(path, role, allow_plans, require_references)
        )

    def top_level_names(key: str) -> tuple[str, ...]:
        values = require_list(data.get(key, []), key)
        names = tuple(
            relative_posix_path(value, f"{key}[{index}]", single_segment=True)
            for index, value in enumerate(values)
        )
        if len(set(names)) != len(names):
            raise ConfigurationError(f"{key} contains duplicate names")
        return names

    asset_roots = top_level_names("asset_roots")
    retired_roots = top_level_names("retired_roots")
    occupied = set(seen_sections)
    for group_name, values in (
        ("asset_roots", asset_roots),
        ("retired_roots", retired_roots),
    ):
        overlap = occupied.intersection(values)
        if overlap:
            raise ConfigurationError(
                f"{group_name} overlaps a section: {', '.join(sorted(overlap))}"
            )
        occupied.update(values)

    prefix = data.get("plan_anchor_prefix")
    if not isinstance(prefix, str) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*-", prefix
    ):
        raise ConfigurationError(
            "plan_anchor_prefix must be a lowercase hyphenated prefix ending in '-'"
        )

    source_items = require_list(data.get("source_roots", []), "source_roots")
    source_roots: list[SourceRootConfig] = []
    seen_source_ids: set[str] = set()
    seen_source_paths: set[str] = set()
    routes: list[str] = []
    for index, item in enumerate(source_items):
        name = f"source_roots[{index}]"
        entry = require_mapping(item, name)
        reject_unknown(entry, {"id", "path", "code_route"}, name)
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]*", source_id
        ):
            raise ConfigurationError(f"{name}.id must be a lowercase id")
        if source_id in seen_source_ids:
            raise ConfigurationError(f"duplicate source root id: {source_id}")
        seen_source_ids.add(source_id)
        path = relative_posix_path(
            entry.get("path"), f"{name}.path", allow_dot=True
        )
        if path in seen_source_paths:
            raise ConfigurationError(f"duplicate source root path: {path}")
        seen_source_paths.add(path)
        resolved = resolve_inside(repository, path, f"{name}.path")
        for existing in source_roots:
            try:
                resolved.relative_to(existing.resolved)
                overlaps = True
            except ValueError:
                try:
                    existing.resolved.relative_to(resolved)
                    overlaps = True
                except ValueError:
                    overlaps = False
            if overlaps:
                raise ConfigurationError(
                    f"overlapping source root paths: {existing.path} and {path}"
                )
        route = entry.get("code_route")
        if route is not None:
            if (
                not isinstance(route, str)
                or not re.fullmatch(r"/(?:[A-Za-z0-9._~-]+/)+", route)
            ):
                raise ConfigurationError(
                    f"{name}.code_route must be an absolute site route ending in '/'"
                )
            if any(route.startswith(other) or other.startswith(route) for other in routes):
                raise ConfigurationError(f"overlapping code route: {route}")
            routes.append(route)
        source_roots.append(SourceRootConfig(source_id, path, resolved, route))

    rule_items = require_list(data.get("evidence_rules", []), "evidence_rules")
    rules: list[EvidenceRule] = []
    for index, item in enumerate(rule_items):
        name = f"evidence_rules[{index}]"
        entry = require_mapping(item, name)
        reject_unknown(entry, {"role", "patterns"}, name)
        role = entry.get("role")
        if role not in EVIDENCE_LABELS:
            raise ConfigurationError(
                f"{name}.role must be one of {', '.join(sorted(EVIDENCE_LABELS))}"
            )
        patterns_raw = require_list(entry.get("patterns"), f"{name}.patterns")
        if not patterns_raw:
            raise ConfigurationError(f"{name}.patterns must not be empty")
        patterns: list[str] = []
        for pattern_index, pattern in enumerate(patterns_raw):
            if (
                not isinstance(pattern, str)
                or not pattern
                or "\\" in pattern
                or "\x00" in pattern
                or any(part == ".." for part in pattern.split("/"))
            ):
                raise ConfigurationError(
                    f"{name}.patterns[{pattern_index}] is not a safe glob"
                )
            patterns.append(pattern)
        rules.append(EvidenceRule(role, tuple(patterns)))

    command_items = require_list(data.get("build_commands", []), "build_commands")
    commands: list[BuildCommand] = []
    seen_commands: set[str] = set()
    for index, item in enumerate(command_items):
        name = f"build_commands[{index}]"
        entry = require_mapping(item, name)
        reject_unknown(entry, {"name", "cwd", "argv"}, name)
        command_name = entry.get("name")
        if not isinstance(command_name, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]*", command_name
        ):
            raise ConfigurationError(f"{name}.name must be a lowercase id")
        if command_name in seen_commands:
            raise ConfigurationError(f"duplicate build command: {command_name}")
        seen_commands.add(command_name)
        cwd = relative_posix_path(
            entry.get("cwd", "."), f"{name}.cwd", allow_dot=True
        )
        resolved_cwd = resolve_inside(repository, cwd, f"{name}.cwd")
        argv_raw = require_list(entry.get("argv"), f"{name}.argv")
        if not argv_raw or any(
            not isinstance(argument, str) or not argument or "\x00" in argument
            for argument in argv_raw
        ):
            raise ConfigurationError(f"{name}.argv must contain nonempty strings")
        commands.append(
            BuildCommand(command_name, cwd, resolved_cwd, tuple(argv_raw))
        )

    return AuditConfig(
        repository=repository,
        docs_path=docs_path,
        docs=docs,
        index_file=index_file,
        nav_key=nav_key,
        sections=tuple(sections),
        asset_roots=asset_roots,
        retired_roots=retired_roots,
        plan_anchor_prefix=prefix,
        source_roots=tuple(source_roots),
        evidence_rules=tuple(rules),
        build_commands=tuple(commands),
    )


def display_path(config: AuditConfig, path: pathlib.Path) -> str:
    try:
        return path.relative_to(config.repository).as_posix()
    except ValueError:
        return str(path)


def heading_title(match: re.Match[str]) -> str:
    return re.sub(r"[ \t]+#+[ \t]*$", "", match.group(1)).strip()


def mask_html_comments(text: str) -> str:
    result = list(text)
    fence_character = ""
    fence_length = 0
    in_comment = False
    offset = 0

    def hide(start: int, end: int) -> None:
        for index in range(start, end):
            if result[index] not in "\r\n":
                result[index] = " "

    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        content_end = offset + len(content)
        if fence_character:
            closing = re.match(
                rf"^[ \t]{{0,3}}{re.escape(fence_character)}"
                rf"{{{fence_length},}}[ \t]*$",
                content,
            )
            if closing:
                fence_character = ""
                fence_length = 0
            offset += len(line)
            continue

        opening = None if in_comment else re.match(
            r"^[ \t]{0,3}(`{3,}|~{3,})", content
        )
        if opening:
            token = opening.group(1)
            fence_character = token[0]
            fence_length = len(token)
            offset += len(line)
            continue

        cursor = 0
        while cursor < len(content):
            if in_comment:
                comment_end = content.find("-->", cursor)
                if comment_end < 0:
                    hide(offset + cursor, content_end)
                    break
                hide(offset + cursor, offset + comment_end + 3)
                cursor = comment_end + 3
                in_comment = False
                continue
            comment_start = content.find("<!--", cursor)
            if comment_start < 0:
                break
            comment_end = content.find("-->", comment_start + 4)
            if comment_end < 0:
                hide(offset + comment_start, content_end)
                in_comment = True
                break
            hide(offset + comment_start, offset + comment_end + 3)
            cursor = comment_end + 3
        offset += len(line)
    return "".join(result)


def mask_fenced_blocks(text: str) -> str:
    masked = mask_html_comments(text)
    result = list(masked)
    fence_character = ""
    fence_length = 0
    offset = 0
    for line in masked.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        opening = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", content)
        inside = bool(fence_character)
        if inside:
            closing = re.match(
                rf"^[ \t]{{0,3}}{re.escape(fence_character)}"
                rf"{{{fence_length},}}[ \t]*$",
                content,
            )
            if closing:
                fence_character = ""
                fence_length = 0
        elif opening:
            token = opening.group(1)
            fence_character = token[0]
            fence_length = len(token)
        if inside or opening:
            for index in range(offset, offset + len(content)):
                result[index] = " "
        offset += len(line)
    return "".join(result)


def fenced_blocks(text: str) -> list[FenceBlock]:
    blocks: list[FenceBlock] = []
    lines = mask_html_comments(text).splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    index = 0
    while index < len(lines):
        content = lines[index].rstrip("\r\n")
        opening = re.match(
            r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)$",
            content,
        )
        if not opening:
            index += 1
            continue
        token = opening.group("fence")
        closing = re.compile(
            rf"^[ \t]{{0,3}}{re.escape(token[0])}{{{len(token)},}}[ \t]*$"
        )
        end_index = index + 1
        while end_index < len(lines):
            if closing.match(lines[end_index].rstrip("\r\n")):
                body_start = offsets[index] + len(lines[index])
                body_end = offsets[end_index]
                blocks.append(
                    FenceBlock(
                        offsets[index],
                        offsets[end_index] + len(lines[end_index]),
                        opening.group("info").strip(),
                        text[body_start:body_end],
                    )
                )
                index = end_index + 1
                break
            end_index += 1
        else:
            index += 1
    return blocks


def prose_lines(text: str) -> list[str]:
    return [
        re.sub(r"`[^`]*`", "", line)
        for line in mask_fenced_blocks(text).splitlines()
    ]


def paragraphs(lines: list[str]) -> list[str]:
    found: list[str] = []
    pending: list[str] = []
    for line in lines + [""]:
        stripped = line.strip()
        structural = (
            not stripped
            or stripped.startswith(("#", "|", "- ", "* ", ">", "---"))
            or bool(re.match(r"^\d+\.\s", stripped))
        )
        if structural:
            if pending:
                found.append(" ".join(pending))
                pending = []
            continue
        pending.append(stripped)
    return found


def markdown_links(text: str) -> list[str]:
    return [
        match.group("target")
        for match in MARKDOWN_LINK.finditer(mask_fenced_blocks(text))
    ]


def frontmatter_nav(text: str, nav_key: str) -> tuple[str, ...] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    lines = text[4:end].splitlines()
    for index, line in enumerate(lines):
        if line.strip() != f"{nav_key}:":
            continue
        items: list[str] = []
        for child in lines[index + 1 :]:
            match = re.match(r"^\s+-\s+(.+?)\s*$", child)
            if not match:
                break
            items.append(match.group(1))
        return tuple(items)
    return None


def has_visible_figure(text: str) -> bool:
    if any(
        block.info.split()
        and block.info.split()[0].casefold() in {"figure", "mermaid"}
        for block in fenced_blocks(text)
    ):
        return True
    return VISIBLE_IMAGE.search(mask_fenced_blocks(text)) is not None


def snippet_metadata(body: str, key: str) -> list[str]:
    expected = key.casefold()
    values: list[str] = []
    for line in body.splitlines():
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name.strip().casefold() == expected:
            values.append(value.strip())
    return values


def parse_snippet_target(label: str, config: AuditConfig) -> SnippetTarget:
    if "#" not in label:
        raise ValueError("target must include '#<region-id>'")
    file_part, snippet_id = label.rsplit("#", 1)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", snippet_id):
        raise ValueError("region id must contain only letters, digits, '_' or '-'")
    if ":" in file_part:
        source_id, relative = file_part.split(":", 1)
    elif len(config.source_roots) == 1:
        source_id = config.source_roots[0].id
        relative = file_part
    else:
        raise ValueError("target must start with a configured source id and ':'")
    source = config.source_roots_by_id.get(source_id)
    if source is None:
        raise ValueError(f"unknown source id '{source_id}'")
    try:
        relative_path = relative_posix_path(relative, "snippet path")
        candidate = resolve_inside(source.resolved, relative_path, "snippet path", strict=True)
    except ConfigurationError as error:
        raise ValueError(str(error)) from error
    if not candidate.is_file():
        raise ValueError("snippet path is not a file")
    return SnippetTarget(source, relative_path, snippet_id, candidate)


def snippet_line_count(target: SnippetTarget) -> tuple[int | None, str | None]:
    try:
        lines = target.resolved.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        return None, f"cannot read source file ({error})"
    markers = [
        (index, match.group("kind"), match.group("id"))
        for index, line in enumerate(lines)
        if (match := SOURCE_MARKER.match(line)) is not None
    ]
    begins = [index for index, kind, item_id in markers if kind == "begin" and item_id == target.snippet_id]
    ends = [index for index, kind, item_id in markers if kind == "end" and item_id == target.snippet_id]
    if len(begins) != 1 or len(ends) != 1:
        return None, "region requires exactly one begin marker and one end marker"
    if begins[0] >= ends[0]:
        return None, "region end marker must follow its begin marker"
    marker_lines = {index for index, _, _ in markers}
    count = sum(
        1
        for index, line in enumerate(lines[begins[0] + 1 : ends[0]], begins[0] + 1)
        if line.strip() and index not in marker_lines
    )
    return count, None


def code_evidence(
    path: pathlib.Path, text: str, config: AuditConfig
) -> list[CodeEvidence]:
    del path
    evidence: list[CodeEvidence] = []
    for block in fenced_blocks(text):
        parts = block.info.split()
        kind = parts[0].casefold() if parts else ""
        if kind in {"figure", "mermaid"}:
            continue
        source_snippet = kind == "snippet"
        fold_values = snippet_metadata(block.body, "fold") if source_snippet else []
        folded = bool(
            fold_values and fold_values[-1].casefold() in SNIPPET_FOLDED_VALUES
        )
        target: SnippetTarget | None = None
        target_error: str | None = None
        if source_snippet:
            label = parts[1] if len(parts) >= 2 else "snippet"
            if len(parts) < 2:
                target_error = "snippet fence requires a source target"
                line_count = None
            else:
                try:
                    target = parse_snippet_target(label, config)
                    line_count, target_error = snippet_line_count(target)
                except ValueError as error:
                    line_count = None
                    target_error = str(error)
        else:
            label = kind or "code"
            line_count = sum(1 for line in block.body.splitlines() if line.strip())
        evidence.append(
            CodeEvidence(
                block.start,
                block.end,
                label,
                line_count,
                source_snippet,
                folded,
                target,
                target_error,
            )
        )
    return evidence


def source_snippet_errors(
    path: pathlib.Path, text: str, config: AuditConfig
) -> list[str]:
    rel = display_path(config, path)
    errors: list[str] = []
    evidence_by_start = {
        block.start: block for block in code_evidence(path, text, config)
    }
    for fence in fenced_blocks(text):
        parts = fence.info.split()
        if not parts or parts[0].casefold() != "snippet":
            continue
        line = text.count("\n", 0, fence.start) + 1
        label = parts[1] if len(parts) >= 2 else "snippet"
        evidence = evidence_by_start[fence.start]
        if evidence.target_error:
            errors.append(f"{rel}:{line}: source snippet '{label}' {evidence.target_error}")
        titles = snippet_metadata(fence.body, "title")
        if (
            len(titles) != 1
            or not titles[0]
            or titles[0].casefold() in GENERIC_SNIPPET_TITLES
        ):
            errors.append(
                f"{rel}:{line}: source snippet '{label}' requires one meaningful title"
            )
        fold_values = snippet_metadata(fence.body, "fold")
        if len(fold_values) > 1:
            errors.append(f"{rel}:{line}: source snippet '{label}' repeats fold")
        for value in fold_values:
            if value.casefold() not in SNIPPET_FOLD_VALUES:
                errors.append(
                    f"{rel}:{line}: source snippet '{label}' has invalid fold value '{value}'"
                )
        if (
            not evidence.folded
            and evidence.line_count is not None
            and evidence.line_count > VISIBLE_SNIPPET_MAX_LINES
        ):
            errors.append(
                f"{rel}:{line}: visible source snippet '{label}' renders "
                f"{evidence.line_count} nonblank lines; narrow or fold it"
            )
    return errors


def evidence_role(config: AuditConfig, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    for rule in config.evidence_rules:
        if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in rule.patterns):
            return rule.role
    return "Source"


def is_under(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_repo_file_link(
    page: pathlib.Path, target: str, config: AuditConfig
) -> pathlib.Path | None:
    clean = target.split("#", 1)[0].split("?", 1)[0]
    if (
        not clean
        or clean.startswith(("/", "http://", "https://", "mailto:"))
        or pathlib.PurePosixPath(clean).is_absolute()
    ):
        return None
    try:
        candidate = page.parent.joinpath(*pathlib.PurePosixPath(clean).parts).resolve()
        candidate.relative_to(config.repository)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def source_location(
    path: pathlib.Path, config: AuditConfig
) -> tuple[SourceRootConfig, str] | None:
    for source in config.source_roots:
        try:
            relative = path.resolve().relative_to(source.resolved.resolve()).as_posix()
        except (OSError, ValueError):
            continue
        return source, relative
    return None


def expected_source_link(page: pathlib.Path, target: SnippetTarget) -> str:
    if target.source.code_route:
        return target.source.code_route + target.relative_path
    relative = os.path.relpath(target.resolved, page.parent).replace(os.sep, "/")
    return relative


def route_location(
    target: str, config: AuditConfig
) -> tuple[SourceRootConfig, str, pathlib.Path] | None:
    clean = target.split("#", 1)[0].split("?", 1)[0]
    for source in config.source_roots:
        if not source.code_route or not clean.startswith(source.code_route):
            continue
        relative = clean[len(source.code_route) :]
        try:
            safe = relative_posix_path(relative, "code route path")
            resolved = resolve_inside(source.resolved, safe, "code route path", strict=True)
        except ConfigurationError:
            return None
        return source, safe, resolved
    return None


def reference_section_checks(
    path: pathlib.Path, text: str, config: AuditConfig
) -> list[str]:
    rel = display_path(config, path)
    section = section_for_page(path, config)
    requires_references = bool(section and section.require_references and path.name != config.index_file)
    snippets = [
        item
        for item in code_evidence(path, text, config)
        if item.source_snippet and item.target is not None and item.target_error is None
    ]
    masked = mask_fenced_blocks(text)
    headings = [
        match for match in H2.finditer(masked) if heading_title(match) == "References"
    ]
    section_start = headings[0].start() if headings else len(text)
    links_before = markdown_links(text[:section_start])
    has_external = any(target.startswith(("https://", "http://")) for target in links_before)
    has_route = any(route_location(target, config) is not None for target in links_before)
    has_source_file = any(
        (resolved := resolve_repo_file_link(path, target, config)) is not None
        and source_location(resolved, config) is not None
        for target in links_before
    )
    needs_references = requires_references or bool(snippets) or has_external or has_route or has_source_file
    if not needs_references and not headings:
        return []
    errors: list[str] = []
    if len(headings) != 1:
        errors.append(
            f"{rel}: expected exactly one final H2 References section, found {len(headings)}"
        )
        return errors
    h2s = list(H2.finditer(masked))
    if not h2s or h2s[-1].start() != headings[0].start():
        errors.append(f"{rel}: References must be the final H2 section")
    reference_body = text[headings[0].end() :]
    labels = [
        match.group("label").strip()
        for match in REFERENCE_BULLET_LABEL.finditer(reference_body)
    ]
    for label in labels:
        if label not in REFERENCE_LABELS:
            errors.append(f"{rel}: unknown References role: {label}")
    rows = [
        (match.group("label"), match.group("body").strip())
        for match in REFERENCE_ITEM.finditer(reference_body)
    ]
    if not rows:
        errors.append(f"{rel}: References must contain at least one labeled link")
        return errors
    row_targets: list[tuple[str, str]] = []
    for label, body in rows:
        targets = [match.group("target") for match in MARKDOWN_LINK.finditer(body)]
        if not targets:
            errors.append(f"{rel}: References {label} row must contain a link")
            continue
        row_targets.extend((label, target) for target in targets)
        if label == "External sources":
            for target in targets:
                if not target.startswith(("https://", "http://")):
                    errors.append(f"{rel}: External sources must use HTTP(S): {target}")

    for label, target in row_targets:
        if label not in EVIDENCE_LABELS:
            continue
        if "#" in target:
            errors.append(
                f"{rel}: References {label} must link the complete file without a fragment"
            )
        route = route_location(target, config)
        if route is not None:
            _, relative, _ = route
            expected = evidence_role(config, relative)
            if label != expected:
                errors.append(
                    f"{rel}: {relative} is classified as {label}; expected {expected}"
                )
            continue
        repo_file = resolve_repo_file_link(path, target, config)
        location = source_location(repo_file, config) if repo_file is not None else None
        if location is None:
            errors.append(
                f"{rel}: References {label} must link a configured public source file"
            )
            continue
        source, relative = location
        if source.code_route:
            errors.append(
                f"{rel}: source file must use configured code route: "
                f"{source.code_route}{relative}"
            )
        expected = evidence_role(config, relative)
        if label != expected:
            errors.append(
                f"{rel}: {relative} is classified as {label}; expected {expected}"
            )

    for snippet in snippets:
        assert snippet.target is not None
        expected_target = expected_source_link(path, snippet.target)
        expected_label = evidence_role(config, snippet.target.relative_path)
        if (expected_label, expected_target) not in row_targets:
            errors.append(
                f"{rel}: snippet file must appear as a complete-file References "
                f"{expected_label} link: {expected_target}"
            )

    for target in links_before:
        if target.startswith(("https://", "http://")) and (
            "External sources", target
        ) not in row_targets:
            errors.append(
                f"{rel}: external source must also appear under References "
                f"External sources: {target}"
            )
        route = route_location(target, config)
        if route is not None:
            _, relative, _ = route
            complete = target.split("#", 1)[0]
            expected_label = evidence_role(config, relative)
            if (expected_label, complete) not in row_targets:
                errors.append(
                    f"{rel}: inline source must also appear as a complete-file "
                    f"References {expected_label} link: {complete}"
                )
    for label, target in row_targets:
        if label == "External sources" and target not in links_before:
            errors.append(
                f"{rel}: References external source must also be cited inline: {target}"
            )
    return errors


def code_wall_warnings(
    path: pathlib.Path, text: str, config: AuditConfig
) -> list[str]:
    rel = display_path(config, path)
    warnings: list[str] = []
    snippets = [
        item for item in code_evidence(path, text, config) if item.source_snippet
    ]
    for block in snippets:
        if block.line_count is None:
            continue
        line = text.count("\n", 0, block.start) + 1
        if (
            not block.folded
            and VISIBLE_SNIPPET_REVIEW_LINES < block.line_count <= VISIBLE_SNIPPET_MAX_LINES
        ):
            warnings.append(
                f"{rel}:{line}: visible source snippet '{block.label}' renders "
                f"{block.line_count} nonblank lines; review whether a smaller shape suffices"
            )
        elif block.folded and block.line_count > FOLDED_SNIPPET_REVIEW_LINES:
            warnings.append(
                f"{rel}:{line}: folded source snippet '{block.label}' renders "
                f"{block.line_count} nonblank lines; narrow it or link to source"
            )
    adjacent = sum(
        1
        for previous, current in zip(snippets, snippets[1:])
        if not text[previous.end : current.start].strip()
    )
    if adjacent:
        warnings.append(
            f"{rel}: {adjacent} adjacent source-snippet pair(s) lack local interpretation"
        )
    visible = [
        item for item in snippets if not item.folded and item.line_count is not None
    ]
    if len(visible) >= MANY_SNIPPETS:
        warnings.append(
            f"{rel}: {len(visible)} visible source snippets; review the lookup hierarchy"
        )
    masked = mask_fenced_blocks(text)
    headings = list(re.finditer(r"^(#{2,3})[ \t]+(.+?)[ \t]*$", masked, re.MULTILINE))
    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section_blocks = [item for item in visible if start <= item.start < end]
        if len(section_blocks) < 2:
            continue
        code_lines = sum(item.line_count or 0 for item in section_blocks)
        prose_words = len(WORD.findall("\n".join(prose_lines(masked[start:end]))))
        if code_lines >= CODE_HEAVY_SECTION_LINES and prose_words < code_lines * 2:
            warnings.append(
                f"{rel}: section '{heading.group(2).strip()}' has {code_lines} "
                f"visible source lines and {prose_words} explanatory words"
            )
    return warnings


def scan_plan_blocks(text: str) -> tuple[list[PlanBlock], list[int]]:
    masked = mask_fenced_blocks(text)
    openings = list(PLAN_OPEN.finditer(masked))
    blocks: list[PlanBlock] = []
    unclosed: list[int] = []
    consumed_until = 0
    for index, opening in enumerate(openings):
        if opening.start() < consumed_until:
            continue
        closing = PLAN_CLOSE.search(masked, opening.end())
        next_opening = openings[index + 1] if index + 1 < len(openings) else None
        if closing is None or (
            next_opening is not None and next_opening.start() < closing.start()
        ):
            unclosed.append(opening.start())
            continue
        blocks.append(
            PlanBlock(
                opening.start(),
                opening.end(),
                closing.start(),
                closing.end(),
                (opening.group("title") or "").strip(),
            )
        )
        consumed_until = closing.end()
    return blocks, unclosed


def mask_plan_blocks(text: str, blocks: list[PlanBlock], unclosed: list[int]) -> str:
    result = list(text)
    ranges = [(block.start, block.end) for block in blocks]
    ranges.extend((start, len(text)) for start in unclosed)
    for start, end in ranges:
        for index in range(start, end):
            if result[index] not in "\r\n":
                result[index] = " "
    return "".join(result)


def normalized_plan_statement(value: str) -> str:
    value = re.sub(r"[`*_]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n.!?:;-").casefold()


def section_for_page(path: pathlib.Path, config: AuditConfig) -> SectionConfig | None:
    try:
        parts = path.relative_to(config.docs).parts
    except ValueError:
        return None
    return config.sections_by_path.get(parts[0]) if parts else None


def plan_checks(path: pathlib.Path, text: str, config: AuditConfig) -> list[str]:
    rel = display_path(config, path)
    masked = mask_fenced_blocks(text)
    openings = list(PLAN_OPEN.finditer(masked))
    if not openings:
        return []
    errors: list[str] = []
    section_config = section_for_page(path, config)
    if path.name == config.index_file:
        errors.append(f"{rel}: an index must not own a Plan container")
    if section_config is None or not section_config.allow_plans:
        errors.append(f"{rel}: the configured section does not allow Plans")
    blocks, unclosed = scan_plan_blocks(text)
    for start in unclosed:
        line = text.count("\n", 0, start) + 1
        errors.append(f"{rel}:{line}: Plan container is missing its closing :::")
    seen_titles: set[str] = set()
    for block in blocks:
        line = text.count("\n", 0, block.start) + 1
        label = f"{rel}:{line}: Plan container"
        normalized_title = re.sub(r"\s+", " ", block.title).strip().casefold()
        if not block.title:
            errors.append(f"{label} requires a meaningful title after :::plan")
        else:
            if re.search(r"[\[\]*_<>`]", block.title):
                errors.append(f"{label} title must be plain text without Markdown")
            if normalized_title in {
                "plan", "plans", "planned work", "future work", "implementation status"
            }:
                errors.append(f"{label} title must name its outcome")
            if normalized_title in seen_titles:
                errors.append(f"{label} repeats the title '{block.title}'")
            seen_titles.add(normalized_title)
        section = text[block.content_start : block.content_end]
        section_masked = masked[block.content_start : block.content_end]
        goals = list(H3.finditer(section_masked))
        if not goals:
            errors.append(f"{label} must contain at least one H3 goal")
            continue
        if section_masked[: goals[0].start()].strip():
            errors.append(f"{label} must begin with an H3 goal")
        other_headings = [
            item for item in HEADING.finditer(section_masked) if len(item.group(1)) != 3
        ]
        if other_headings:
            errors.append(f"{label} may contain only H3 goal headings")
        if any(
            fence.info.split()
            and fence.info.split()[0].casefold() == "snippet"
            for fence in fenced_blocks(section)
        ):
            errors.append(f"{label} must not contain source snippet fences")
        if re.search(r"^[ \t]{0,3}\d+[.)][ \t]+", section_masked, re.MULTILINE):
            errors.append(f"{label} must not contain numbered procedures")
        if re.search(
            r"^[ \t]{0,3}\|?.+\|.+\n[ \t]{0,3}\|?[ \t]*:?-{3,}",
            section_masked,
            re.MULTILINE,
        ):
            errors.append(f"{label} must not contain current lookup tables")
        for index, goal in enumerate(goals):
            title = heading_title(goal)
            parsed = PLAN_GOAL.fullmatch(goal.group(0))
            if not parsed:
                errors.append(
                    f"{rel}: Plan goal '{title}' must end with "
                    f"{{#{config.plan_anchor_prefix}<id>}}"
                )
            elif not parsed.group("anchor").startswith(config.plan_anchor_prefix):
                errors.append(
                    f"{rel}: Plan goal '{title}' must use prefix "
                    f"'{config.plan_anchor_prefix}'"
                )
            end = goals[index + 1].start() if index + 1 < len(goals) else len(section)
            body = section_masked[goal.end() : end]
            found: dict[str, list[str]] = {}
            for field in PLAN_FIELD.finditer(body):
                found.setdefault(field.group("name"), []).append(
                    field.group("value").strip()
                )
            for field in PLAN_REQUIRED_FIELDS:
                values = found.get(field, [])
                if not values:
                    errors.append(f"{rel}: Plan goal '{title}' is missing {field}")
                elif len(values) > 1:
                    errors.append(f"{rel}: Plan goal '{title}' repeats {field}")
                elif not values[0]:
                    errors.append(f"{rel}: Plan goal '{title}' has an empty {field}")
            if found.get("Current") and normalized_plan_statement(found["Current"][0]) == "tbd":
                errors.append(f"{rel}: Plan goal '{title}' Current must not be 'TBD'")
            if found.get("Done when") and normalized_plan_statement(found["Done when"][0]) == "it works":
                errors.append(f"{rel}: Plan goal '{title}' Done when must be observable")
            for field in PLAN_OPTIONAL_FIELDS:
                values = found.get(field, [])
                if len(values) > 1:
                    errors.append(f"{rel}: Plan goal '{title}' repeats {field}")
                elif values and not values[0]:
                    errors.append(f"{rel}: Plan goal '{title}' has an empty {field}")
            for field in sorted(set(found) - PLAN_FIELDS):
                errors.append(f"{rel}: Plan goal '{title}' uses unsupported field {field}")
            for bullet_field in PLAN_BULLET_FIELD.finditer(body):
                errors.append(
                    f"{rel}: Plan goal '{title}' must write "
                    f"{bullet_field.group('name')} as a plain field"
                )
            if not PLAN_STEP.search(body):
                errors.append(f"{rel}: Plan goal '{title}' requires an unchecked step")
            for step in PLAN_STEP.finditer(body):
                if normalized_plan_statement(step.group("value")) == "do it":
                    errors.append(f"{rel}: Plan goal '{title}' step must be concrete")
            if PLAN_DONE_STEP.search(body):
                errors.append(f"{rel}: Plan goal '{title}' must not retain [x] steps")
            source = found.get("Source", [])
            if len(source) == 1 and not re.search(r"\[[^\]]+\]\([^)]+\)", source[0]):
                errors.append(f"{rel}: Plan goal '{title}' Source must contain a link")
    return errors


def duplicate_plan_anchor_checks(config: AuditConfig) -> list[str]:
    owners: dict[str, list[str]] = {}
    pages, _ = discover_pages(config)
    for path in pages:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        masked = mask_fenced_blocks(text)
        blocks, _ = scan_plan_blocks(text)
        for block in blocks:
            section = masked[block.content_start : block.content_end]
            for goal in H3.finditer(section):
                parsed = PLAN_GOAL.fullmatch(goal.group(0))
                if parsed:
                    owners.setdefault(parsed.group("anchor"), []).append(
                        display_path(config, path)
                    )
    return [
        f"duplicate Plan anchor '{anchor}': {', '.join(paths)}"
        for anchor, paths in sorted(owners.items())
        if len(paths) > 1
    ]


def page_checks(
    path: pathlib.Path, config: AuditConfig
) -> tuple[list[str], list[str]]:
    rel = display_path(config, path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [f"{rel}: cannot read UTF-8 Markdown ({error})"], []
    masked = mask_fenced_blocks(text)
    errors = plan_checks(path, text, config)
    errors.extend(source_snippet_errors(path, text, config))
    errors.extend(reference_section_checks(path, text, config))
    warnings = code_wall_warnings(path, text, config)
    titles = H1.findall(masked)
    if len(titles) != 1:
        errors.append(f"{rel}: expected exactly one H1, found {len(titles)}")
    levels = [len(match.group(1)) for match in HEADING.finditer(masked)]
    for previous, current in zip(levels, levels[1:]):
        if current > previous + 1:
            errors.append(f"{rel}: heading level jumps from H{previous} to H{current}")
            break
    prose = "\n".join(prose_lines(text))
    if "—" in prose:
        errors.append(f"{rel}: prose contains an em dash")
    filler = DISCOURAGED.search(prose)
    if filler:
        errors.append(f"{rel}: prose contains discouraged filler '{filler.group(0)}'")
    for paragraph in paragraphs(prose.splitlines()):
        count = len(WORD.findall(paragraph))
        if count > 120:
            warnings.append(f"{rel}: paragraph has {count} words; review for a split")
    h2_count = len(list(H2.finditer(masked)))
    if h2_count > 12:
        warnings.append(f"{rel}: {h2_count} H2 sections; review the page boundary")
    blocks, unclosed = scan_plan_blocks(text)
    current_text = mask_plan_blocks(text, blocks, unclosed)
    section = section_for_page(path, config)
    word_count = len(WORD.findall("\n".join(prose_lines(current_text))))
    if (
        section is not None
        and section.role == "concept"
        and path.name != config.index_file
        and word_count >= SUBSTANTIAL_CONCEPT_WORDS
        and not has_visible_figure(current_text)
    ):
        warnings.append(
            f"{rel}: substantial Concept has no figure; review context, flow, and failure lenses"
        )
    return errors, warnings


def resolve_markdown_file(
    candidate: pathlib.Path, config: AuditConfig
) -> tuple[pathlib.Path | None, str | None]:
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        return None, f"cannot be resolved ({error})"
    try:
        resolved.relative_to(config.docs)
    except ValueError:
        return None, "resolves outside the documentation root"
    if not resolved.is_file() or resolved.suffix.casefold() != ".md":
        return None, "is not a Markdown file"
    return resolved, None


def discover_pages(config: AuditConfig) -> tuple[list[pathlib.Path], list[str]]:
    pages: list[pathlib.Path] = []
    errors: list[str] = []
    if not config.docs.is_dir():
        return pages, [f"documentation root is missing: {config.docs_path}"]
    for candidate in sorted(config.docs.rglob("*.md")):
        resolved, error = resolve_markdown_file(candidate, config)
        if error:
            errors.append(f"documentation page {error}: {display_path(config, candidate)}")
        elif resolved is not None and resolved not in pages:
            pages.append(resolved)
    return pages, errors


def section_has_pages(config: AuditConfig, section: SectionConfig) -> bool:
    root = config.docs / section.path
    return root.is_dir() and any(
        page.name != config.index_file for page in root.rglob("*.md")
    )


def directory_has_files(path: pathlib.Path) -> bool:
    return path.is_dir() and any(candidate.is_file() for candidate in path.rglob("*"))


def nested_index_checks(config: AuditConfig) -> list[str]:
    pages, errors = discover_pages(config)
    content_pages = [page for page in pages if page.name != config.index_file]
    required: set[pathlib.Path] = set()
    for page in content_pages:
        parent = page.parent
        while parent != config.docs:
            if len(parent.relative_to(config.docs).parts) >= 2:
                required.add(parent)
            parent = parent.parent
    for directory in sorted(required):
        index = directory / config.index_file
        if not index.is_file():
            errors.append(
                f"{display_path(config, directory)}/{config.index_file} is missing"
            )
            continue
        resolved, error = resolve_markdown_file(index, config)
        if error:
            errors.append(f"{display_path(config, index)} {error}")
        elif resolved is not None:
            try:
                text = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as read_error:
                errors.append(f"{display_path(config, index)} cannot be read ({read_error})")
            else:
                if frontmatter_nav(text, config.nav_key) is None:
                    errors.append(f"{display_path(config, index)} has no explicit navigation")
    for index in (page for page in pages if page.name == config.index_file):
        relative = index.parent.relative_to(config.docs)
        if len(relative.parts) >= 2 and index.parent not in required:
            errors.append(f"{display_path(config, index.parent)}/ is an empty hierarchy")
    return errors


def tree_checks(config: AuditConfig) -> list[str]:
    errors: list[str] = []
    if not config.docs.is_dir():
        return [f"documentation root is missing: {config.docs_path}"]
    for source in config.source_roots:
        if not source.resolved.is_dir():
            errors.append(
                f"configured source root is missing or is not a directory: {source.path}"
            )
    for name in config.retired_roots:
        if directory_has_files(config.docs / name):
            errors.append(f"retired documentation root contains files: {name}")
    root_index = config.docs / config.index_file
    if not root_index.is_file():
        errors.append(f"{config.docs_path}/{config.index_file} is missing")
    else:
        resolved, error = resolve_markdown_file(root_index, config)
        if error:
            errors.append(f"{display_path(config, root_index)} {error}")
        elif resolved is not None:
            try:
                nav = frontmatter_nav(
                    resolved.read_text(encoding="utf-8"), config.nav_key
                )
            except (OSError, UnicodeError) as read_error:
                errors.append(f"{display_path(config, root_index)} cannot be read ({read_error})")
            else:
                expected = tuple(
                    f"{section.path}/"
                    for section in config.sections
                    if section_has_pages(config, section)
                )
                if nav != expected:
                    errors.append(
                        f"{config.docs_path}/{config.index_file} navigation must list "
                        f"populated sections in this order: {', '.join(expected)}"
                    )
    for section in config.sections:
        root = config.docs / section.path
        index = root / config.index_file
        has_pages = section_has_pages(config, section)
        if index.is_file() and not has_pages:
            errors.append(f"{config.docs_path}/{section.path}/ is an empty section")
        elif has_pages and not index.is_file():
            errors.append(
                f"{config.docs_path}/{section.path}/{config.index_file} is missing"
            )
        elif index.is_file():
            try:
                nav = frontmatter_nav(index.read_text(encoding="utf-8"), config.nav_key)
            except (OSError, UnicodeError) as read_error:
                errors.append(f"{display_path(config, index)} cannot be read ({read_error})")
            else:
                if nav is None:
                    errors.append(f"{display_path(config, index)} has no explicit navigation")
    allowed = set(config.sections_by_path) | set(config.asset_roots) | set(config.retired_roots)
    for child in config.docs.iterdir():
        try:
            resolved = child.resolve(strict=True)
            resolved.relative_to(config.docs)
        except (OSError, RuntimeError, ValueError):
            errors.append(
                f"documentation root entry escapes the root or is unreadable: "
                f"{display_path(config, child)}"
            )
            continue
        if child.is_dir() and child.name not in allowed and directory_has_files(child):
            errors.append(f"unexpected documentation root: {child.name}/")
        if child.is_file() and child.name != config.index_file:
            errors.append(f"unexpected root page: {child.name}")
    errors.extend(nested_index_checks(config))
    return errors


def resolve_review_page(
    supplied: str, config: AuditConfig
) -> tuple[pathlib.Path | None, str | None]:
    raw = pathlib.Path(supplied)
    if ".." in raw.parts:
        return None, f"review path must not contain '..': {supplied}"
    candidate = raw if raw.is_absolute() else config.repository / raw
    page, error = resolve_markdown_file(candidate, config)
    if error:
        return None, f"review path {error}: {supplied}"
    return page, None


def run_build_commands(
    config: AuditConfig, selected: tuple[str, ...], timeout_seconds: int = 300
) -> list[str]:
    by_name = {command.name: command for command in config.build_commands}
    if len(set(selected)) != len(selected):
        return ["a build command may be selected only once"]
    unknown = sorted(set(selected) - set(by_name))
    if unknown:
        return [f"unknown build command(s): {', '.join(unknown)}"]
    commands = (
        [by_name[name] for name in selected]
        if selected
        else list(config.build_commands)
    )
    if not commands:
        return ["no build commands are configured"]
    errors: list[str] = []
    for command in commands:
        if not command.resolved_cwd.is_dir():
            errors.append(
                f"build command '{command.name}' working directory is missing: {command.cwd}"
            )
            continue
        try:
            result = subprocess.run(
                command.argv,
                cwd=command.resolved_cwd,
                shell=False,
                check=False,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            errors.append(
                f"build command '{command.name}' exceeded {timeout_seconds} second(s)"
            )
            continue
        except OSError as error:
            errors.append(f"build command '{command.name}' could not start: {error}")
            continue
        if result.returncode:
            errors.append(
                f"build command '{command.name}' exited with {result.returncode}"
            )
    return errors


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="path to the JSON audit configuration")
    parser.add_argument("--repo-root", help="override the repository root")
    parser.add_argument("--check", action="store_true", help="return nonzero for hard errors")
    parser.add_argument(
        "--review",
        action="store_true",
        help="emit qualitative warnings and return nonzero for hard errors",
    )
    parser.add_argument(
        "--run-build",
        action="store_true",
        help="run trusted build commands declared in the configuration",
    )
    parser.add_argument(
        "--build-command",
        action="append",
        default=[],
        help="select one configured build command; repeat to select several",
    )
    parser.add_argument(
        "--build-timeout-seconds",
        type=positive_integer,
        default=300,
        help="maximum seconds for each configured build command (default: 300)",
    )
    parser.add_argument("paths", nargs="*", help="limit page checks to these Markdown files")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.build_command and not args.run_build:
        parser.error("--build-command requires --run-build")
    try:
        config = load_config(
            pathlib.Path(args.config),
            pathlib.Path(args.repo_root) if args.repo_root else None,
        )
    except ConfigurationError as error:
        print(f"CONFIG ERROR: {error}")
        return 2
    errors = tree_checks(config)
    warnings: list[str] = []
    pages: list[pathlib.Path] = []
    if config.docs.is_dir():
        if args.paths:
            for supplied in args.paths:
                page, error = resolve_review_page(supplied, config)
                if error:
                    errors.append(error)
                elif page is not None and page not in pages:
                    pages.append(page)
        else:
            pages, discovery_errors = discover_pages(config)
            errors.extend(discovery_errors)
        for page in pages:
            page_errors, page_warnings = page_checks(page, config)
            errors.extend(page_errors)
            warnings.extend(page_warnings)
        errors.extend(duplicate_plan_anchor_checks(config))
    if args.run_build:
        errors.extend(
            run_build_commands(
                config,
                tuple(args.build_command),
                timeout_seconds=args.build_timeout_seconds,
            )
        )
    for error in errors:
        print(f"ERROR: {error}")
    if args.review:
        for warning in warnings:
            print(f"WARN:  {warning}")
    summary = f"docs: {len(pages)} page(s), {len(errors)} error(s)"
    if args.review:
        summary += f", {len(warnings)} review warning(s)"
    print(summary)
    return 1 if errors and (args.check or args.review or args.run_build) else 0


if __name__ == "__main__":
    sys.exit(main())
