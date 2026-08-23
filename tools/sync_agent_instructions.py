#!/usr/bin/env python3
"""Generate deterministic Codex and Claude discovery surfaces.

Canonical instructions and skill packages live under ``_agents/``. The v2
generation manifest names every source package and output explicitly; directory
auto-discovery is intentionally unsupported.

    python -B tools/sync_agent_instructions.py --write
    python -B tools/sync_agent_instructions.py --check
    python -B tools/sync_agent_instructions.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import stat
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, Iterator


ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_GENERATION_MANIFEST = pathlib.PurePosixPath("_agents/generation.json")
DEFAULT_PUBLICATION_MANIFEST = pathlib.PurePosixPath("_agents/publication.json")
GENERATION_SCHEMA = "../schemas/agent-generation.schema.json"
PUBLICATION_SCHEMA = "../schemas/agent-publication.schema.json"
GENERATED_BY = "tools/sync_agent_instructions.py"

ALLOWED_MANAGED_FILES = frozenset(
    {pathlib.PurePosixPath("AGENTS.md"), pathlib.PurePosixPath("CLAUDE.md")}
)
ALLOWED_MANAGED_ROOTS = frozenset(
    {
        pathlib.PurePosixPath(".agents/skills"),
        pathlib.PurePosixPath(".claude/skills"),
    }
)
PROTECTED_TOP_LEVEL = frozenset(
    {".git", ".github", "_agents", "docs", "schemas", "src", "tools"}
)

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
MARKDOWN_LINK = re.compile(r"(?P<prefix>\]\()(?P<target>[^)\s]+)(?P<suffix>\))")
INLINE_PATH = re.compile(
    r"`(?P<target>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+"
    r"\.(?:md|py|json|txt|sh|ps1|yaml|yml))`"
)
SKIP_LINK_PREFIXES = ("#", "http://", "https://", "mailto:", "data:")

PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----", re.IGNORECASE
)
TOKEN_SIGNATURE = re.compile(
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9_]{20,}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
    r"|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
    r"|\bAIza[0-9A-Za-z_-]{25,}\b"
)
SECRET_ASSIGNMENT = re.compile(
    r"\b(?:password|passwd|pwd|api[_ -]?key|secret(?:[_ -]?(?:key|token))?|"
    r"private[_ -]?key|client[_ -]?secret|dsn|"
    r"access[_ -]?token|auth[_ -]?token|bearer[_ -]?token|"
    r"connection[_ -]?string|webhook[_ -]?(?:secret|url))\b"
    r"\s*[:=]\s*"
    r"(?P<value>`[^`\r\n]+`|\"[^\"\r\n]+\"|'[^'\r\n]+'|[^\s,;]+)",
    re.IGNORECASE,
)
_USER_DIRECTORY = "Us" + "ers"
_HOME_DIRECTORY = "ho" + "me"
_ADMIN_DIRECTORY = "ro" + "ot"
_SERVICE_DIRECTORY = "s" + "rv"
_MOUNT_DIRECTORY = "m" + "nt"
MACHINE_LOCAL_PATH = re.compile(
    rf"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/]){_USER_DIRECTORY}[\\/][^\\/\r\n`\"']+"
    r"|(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])"
    r"(?!(?:Program Files|Windows)(?:[\\/\r\n`\"']|$))[^\r\n`\"']+"
    rf"|/{_MOUNT_DIRECTORY}/[A-Za-z]/{_USER_DIRECTORY}/[^/\r\n`\"']+"
    rf"|/(?:{_USER_DIRECTORY}|{_HOME_DIRECTORY})/[^/\r\n`\"']+"
    rf"|(?<![A-Za-z0-9_<])/(?:{_ADMIN_DIRECTORY}|{_SERVICE_DIRECTORY})/[^\r\n`\"']+"
    r"|\\\\[^\\\s]+\\[^\\\s]+)",
    re.IGNORECASE,
)
PRIVATE_HOST_URL = re.compile(
    r"https?://(?P<host>[A-Za-z0-9.-]+\.(?:internal|intranet|corp|lan|local))"
    r"(?::\d+)?(?:/[^\s`\"']*)?",
    re.IGNORECASE,
)
URI_CREDENTIAL = re.compile(
    r"\b[a-z][a-z0-9+.-]*://(?P<user>[^/\s:@]+):(?P<password>[^/\s@]+)@"
    r"(?P<host>[^/\s:]+)",
    re.IGNORECASE,
)
AUTHORIZATION_CREDENTIAL = re.compile(
    r"\bAuthorization\s*:\s*(?:Bearer|Basic)\s+(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
RESTRICTED_MARKER = re.compile(
    r"(?im)^\s*(?:confidential|proprietary|internal[ -]only|do not distribute)\b"
)

UNSAFE_SUFFIXES = frozenset(
    {
        ".cer",
        ".crt",
        ".der",
        ".env",
        ".jks",
        ".key",
        ".keystore",
        ".p12",
        ".pem",
        ".pfx",
        ".pub",
        ".pyc",
        ".pyo",
    }
)
SAFE_PACKAGE_SUFFIXES = frozenset(
    {
        ".blend",
        ".css",
        ".dot",
        ".drawio",
        ".gif",
        ".html",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".pdf",
        ".png",
        ".ps1",
        ".py",
        ".sh",
        ".svg",
        ".toml",
        ".txt",
        ".webp",
        ".xml",
        ".yaml",
        ".yml",
    }
)
TEXT_SUFFIXES = frozenset(
    {
        ".css",
        ".dot",
        ".drawio",
        ".html",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".ps1",
        ".py",
        ".sh",
        ".svg",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
UNSAFE_DIRECTORY_NAMES = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", "__pycache__", "node_modules"}
)
UNSAFE_FILE_NAMES = frozenset(
    {
        ".env",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }
)


class GenerationError(ValueError):
    """The manifests or canonical sources cannot produce a safe output."""


@dataclass(frozen=True)
class Target:
    path: pathlib.PurePosixPath
    vendor: str


@dataclass(frozen=True)
class Instruction:
    id: str
    source: pathlib.PurePosixPath
    targets: tuple[Target, ...]


@dataclass(frozen=True)
class Skill:
    id: str
    source: pathlib.PurePosixPath
    targets: tuple[Target, ...]


@dataclass(frozen=True)
class GenerationManifest:
    instructions: tuple[Instruction, ...]
    skills: tuple[Skill, ...]
    managed_files: tuple[pathlib.PurePosixPath, ...]
    managed_roots: tuple[pathlib.PurePosixPath, ...]


@dataclass(frozen=True)
class PublicationManifest:
    instructions: tuple[str, ...]
    skills: tuple[str, ...]


@dataclass(frozen=True)
class BuildResult:
    outputs: dict[pathlib.PurePosixPath, bytes]
    origins: dict[pathlib.PurePosixPath, str]
    managed_files: tuple[pathlib.PurePosixPath, ...]
    managed_roots: tuple[pathlib.PurePosixPath, ...]
    canonical_markdown: tuple[pathlib.PurePosixPath, ...]


def _normalise_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def _relative(repo: pathlib.Path, path: pathlib.Path) -> pathlib.PurePosixPath:
    try:
        relative = path.absolute().relative_to(repo.absolute())
    except ValueError as error:
        raise GenerationError(f"path escapes the repository: {path}") from error
    return pathlib.PurePosixPath(relative.as_posix())


def _manifest_path(value: object, *, label: str) -> pathlib.PurePosixPath:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GenerationError(f"{label} must be a nonempty repository-relative path")
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise GenerationError(f"{label} must be a normalized repository-relative path: {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") or not PATH_SEGMENT.fullmatch(part) for part in parts):
        raise GenerationError(f"{label} must be a normalized repository-relative path: {value!r}")
    return pathlib.PurePosixPath(*parts)


def _id(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise GenerationError(f"{label} must be a stable lowercase ID")
    return value


def _expect_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GenerationError(f"{label} must be an object")
    return value


def _expect_keys(value: dict[str, object], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        unknown = sorted(actual - expected)
        missing = sorted(expected - actual)
        details: list[str] = []
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        if missing:
            details.append("missing " + ", ".join(missing))
        raise GenerationError(f"{label} has invalid fields ({'; '.join(details)})")


def _expect_array(value: object, *, label: str, nonempty: bool = True) -> list[object]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " a nonempty array" if nonempty else " an array"
        raise GenerationError(f"{label} must be{suffix}")
    return value


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GenerationError(f"JSON object contains duplicate key {key!r}")
        result[key] = value
    return result


def _read_json_file(path: pathlib.Path, *, label: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text, object_pairs_hook=_json_object)
    except GenerationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GenerationError(f"cannot read {label}: {error}") from error


def _is_reparse(path: pathlib.Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise GenerationError(f"cannot inspect {path}: {error}") from error
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _reject_reparse(path: pathlib.Path, *, label: str) -> None:
    if _is_reparse(path):
        raise GenerationError(f"{label} is a symlink or reparse point: {path}")


def _directory_entries(directory: pathlib.Path, *, label: str) -> list[pathlib.Path]:
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError as error:
        raise GenerationError(f"cannot enumerate {label}: {error}") from error
    folded: dict[str, str] = {}
    for entry in entries:
        key = entry.name.casefold()
        previous = folded.get(key)
        if previous is not None and previous != entry.name:
            raise GenerationError(
                f"case-insensitive name collision in {label}: {previous!r} and {entry.name!r}"
            )
        folded[key] = entry.name
    return entries


def _resolve_existing_exact(
    repo: pathlib.Path,
    relative: pathlib.PurePosixPath,
    *,
    label: str,
    expect_directory: bool,
) -> pathlib.Path:
    current = repo.absolute()
    for part in relative.parts:
        if not current.is_dir():
            raise GenerationError(f"{label} does not exist: {relative.as_posix()}")
        entries = _directory_entries(current, label=_relative(repo, current).as_posix() or ".")
        exact = next((entry for entry in entries if entry.name == part), None)
        if exact is None:
            folded = [entry for entry in entries if entry.name.casefold() == part.casefold()]
            if folded:
                raise GenerationError(
                    f"{label} has stale path casing: {relative.as_posix()} "
                    f"(found {folded[0].name!r})"
                )
            raise GenerationError(f"{label} does not exist: {relative.as_posix()}")
        _reject_reparse(exact, label=label)
        current = exact
    if expect_directory and not current.is_dir():
        raise GenerationError(f"{label} must be a directory: {relative.as_posix()}")
    if not expect_directory and not current.is_file():
        raise GenerationError(f"{label} must be a file: {relative.as_posix()}")
    return current.absolute()


def _inspect_target_chain(
    repo: pathlib.Path, relative: pathlib.PurePosixPath, *, label: str
) -> None:
    current = repo.absolute()
    for part in relative.parts:
        if not current.exists():
            return
        if not current.is_dir():
            raise GenerationError(f"{label} has a non-directory parent: {relative.as_posix()}")
        entries = _directory_entries(current, label=_relative(repo, current).as_posix() or ".")
        exact = next((entry for entry in entries if entry.name == part), None)
        if exact is None:
            folded = [entry for entry in entries if entry.name.casefold() == part.casefold()]
            if folded:
                raise GenerationError(
                    f"{label} has stale path casing: {relative.as_posix()} "
                    f"(found {folded[0].name!r})"
                )
            return
        _reject_reparse(exact, label=label)
        current = exact


def _parse_targets(value: object, *, label: str) -> tuple[Target, ...]:
    raw = _expect_array(value, label=label)
    if len(raw) != 2:
        raise GenerationError(f"{label} must contain exactly one Codex and one Claude target")
    targets: list[Target] = []
    seen_vendors: set[str] = set()
    seen_paths: dict[str, str] = {}
    for index, item in enumerate(raw):
        entry = _expect_object(item, label=f"{label}[{index}]")
        _expect_keys(entry, {"path", "vendor"}, label=f"{label}[{index}]")
        path = _manifest_path(entry["path"], label=f"{label}[{index}].path")
        vendor = entry["vendor"]
        if vendor not in ("codex", "claude"):
            raise GenerationError(f"{label}[{index}].vendor is unsupported: {vendor!r}")
        if vendor in seen_vendors:
            raise GenerationError(f"{label} contains duplicate vendor {vendor!r}")
        folded = path.as_posix().casefold()
        if folded in seen_paths:
            raise GenerationError(
                f"{label} contains a case-insensitive target collision: "
                f"{seen_paths[folded]!r} and {path.as_posix()!r}"
            )
        seen_vendors.add(vendor)
        seen_paths[folded] = path.as_posix()
        targets.append(Target(path, vendor))
    if seen_vendors != {"codex", "claude"}:
        raise GenerationError(f"{label} must contain Codex and Claude targets")
    return tuple(targets)


def _unique_ids(values: Iterable[str], *, label: str) -> None:
    seen: dict[str, str] = {}
    for value in values:
        folded = value.casefold()
        previous = seen.get(folded)
        if previous is not None:
            raise GenerationError(f"duplicate or case-colliding {label}: {previous!r} and {value!r}")
        seen[folded] = value


def load_generation_manifest(
    repo: pathlib.Path = ROOT,
    manifest: pathlib.PurePosixPath = DEFAULT_GENERATION_MANIFEST,
) -> GenerationManifest:
    repo = repo.absolute()
    manifest_path = _resolve_existing_exact(
        repo, manifest, label="generation manifest", expect_directory=False
    )
    raw = _expect_object(
        _read_json_file(manifest_path, label=manifest.as_posix()),
        label="generation manifest",
    )
    _expect_keys(
        raw,
        {"$schema", "version", "instructions", "skills", "managed"},
        label="generation manifest",
    )
    if raw["$schema"] != GENERATION_SCHEMA or type(raw["version"]) is not int or raw["version"] != 2:
        raise GenerationError("generation manifest must declare the v2 schema and version 2")

    instructions: list[Instruction] = []
    for index, item in enumerate(_expect_array(raw["instructions"], label="manifest.instructions")):
        entry = _expect_object(item, label=f"manifest.instructions[{index}]")
        _expect_keys(entry, {"id", "source", "targets"}, label=f"manifest.instructions[{index}]")
        identifier = _id(entry["id"], label=f"manifest.instructions[{index}].id")
        source = _manifest_path(entry["source"], label=f"manifest.instructions[{index}].source")
        if len(source.parts) < 3 or source.parts[:2] != ("_agents", "instructions") or source.suffix != ".md":
            raise GenerationError(
                f"instruction source must be lowercase Markdown under _agents/instructions: {source}"
            )
        targets = _parse_targets(entry["targets"], label=f"manifest.instructions[{index}].targets")
        for target in targets:
            expected = pathlib.PurePosixPath("AGENTS.md" if target.vendor == "codex" else "CLAUDE.md")
            if target.path != expected:
                raise GenerationError(
                    f"{target.vendor} instruction target must be {expected.as_posix()}: "
                    f"{target.path.as_posix()}"
                )
        instructions.append(Instruction(identifier, source, targets))

    skills: list[Skill] = []
    for index, item in enumerate(_expect_array(raw["skills"], label="manifest.skills")):
        entry = _expect_object(item, label=f"manifest.skills[{index}]")
        _expect_keys(entry, {"id", "source", "targets"}, label=f"manifest.skills[{index}]")
        identifier = _id(entry["id"], label=f"manifest.skills[{index}].id")
        source = _manifest_path(entry["source"], label=f"manifest.skills[{index}].source")
        expected_source = pathlib.PurePosixPath("_agents", "skills", identifier)
        if source != expected_source:
            raise GenerationError(
                f"skill {identifier!r} source must be {expected_source.as_posix()}: {source.as_posix()}"
            )
        targets = _parse_targets(entry["targets"], label=f"manifest.skills[{index}].targets")
        for target in targets:
            root = ".agents/skills" if target.vendor == "codex" else ".claude/skills"
            expected = pathlib.PurePosixPath(root, identifier)
            if target.path != expected:
                raise GenerationError(
                    f"{target.vendor} skill target for {identifier!r} must be "
                    f"{expected.as_posix()}: {target.path.as_posix()}"
                )
        skills.append(Skill(identifier, source, targets))

    _unique_ids((entry.id for entry in instructions), label="instruction ID")
    _unique_ids((entry.id for entry in skills), label="skill ID")
    _unique_ids(
        [entry.id for entry in instructions] + [entry.id for entry in skills],
        label="agent surface ID",
    )

    managed = _expect_object(raw["managed"], label="manifest.managed")
    _expect_keys(managed, {"files", "roots"}, label="manifest.managed")
    managed_files = tuple(
        _manifest_path(value, label=f"manifest.managed.files[{index}]")
        for index, value in enumerate(_expect_array(managed["files"], label="manifest.managed.files"))
    )
    managed_roots = tuple(
        _manifest_path(value, label=f"manifest.managed.roots[{index}]")
        for index, value in enumerate(_expect_array(managed["roots"], label="manifest.managed.roots"))
    )
    _unique_ids((path.as_posix() for path in managed_files), label="managed file")
    _unique_ids((path.as_posix() for path in managed_roots), label="managed root")
    if frozenset(managed_files) != ALLOWED_MANAGED_FILES:
        raise GenerationError(
            "managed files must be exactly AGENTS.md and CLAUDE.md; cleanup authority cannot be expanded"
        )
    if frozenset(managed_roots) != ALLOWED_MANAGED_ROOTS:
        raise GenerationError(
            "managed roots must be exactly .agents/skills and .claude/skills; "
            "cleanup authority cannot be expanded"
        )
    for root in managed_roots:
        if root.parts[0] in PROTECTED_TOP_LEVEL:
            raise GenerationError(f"protected path cannot be a managed root: {root.as_posix()}")
        _inspect_target_chain(repo, root, label="managed root")

    return GenerationManifest(
        tuple(instructions),
        tuple(skills),
        tuple(sorted(managed_files)),
        tuple(sorted(managed_roots)),
    )


def load_publication_manifest(
    repo: pathlib.Path = ROOT,
    manifest: pathlib.PurePosixPath = DEFAULT_PUBLICATION_MANIFEST,
) -> PublicationManifest:
    repo = repo.absolute()
    manifest_path = _resolve_existing_exact(
        repo, manifest, label="publication manifest", expect_directory=False
    )
    raw = _expect_object(
        _read_json_file(manifest_path, label=manifest.as_posix()),
        label="publication manifest",
    )
    _expect_keys(
        raw,
        {"$schema", "version", "instructions", "skills"},
        label="publication manifest",
    )
    if raw["$schema"] != PUBLICATION_SCHEMA or type(raw["version"]) is not int or raw["version"] != 2:
        raise GenerationError("publication manifest must declare the v2 schema and version 2")
    instructions = tuple(
        _id(value, label=f"publication.instructions[{index}]")
        for index, value in enumerate(
            _expect_array(raw["instructions"], label="publication.instructions")
        )
    )
    skills = tuple(
        _id(value, label=f"publication.skills[{index}]")
        for index, value in enumerate(_expect_array(raw["skills"], label="publication.skills"))
    )
    _unique_ids(instructions, label="published instruction ID")
    _unique_ids(skills, label="published skill ID")
    _unique_ids(list(instructions) + list(skills), label="published agent surface ID")
    return PublicationManifest(instructions, skills)


def validate_publication_intersection(
    generation: GenerationManifest, publication: PublicationManifest
) -> None:
    instruction_ids = {entry.id for entry in generation.instructions}
    skill_ids = {entry.id for entry in generation.skills}
    unknown_instructions = sorted(set(publication.instructions) - instruction_ids)
    unknown_skills = sorted(set(publication.skills) - skill_ids)
    wrong_instruction_kind = sorted(set(publication.instructions) & skill_ids)
    wrong_skill_kind = sorted(set(publication.skills) & instruction_ids)
    if unknown_instructions or unknown_skills or wrong_instruction_kind or wrong_skill_kind:
        details: list[str] = []
        if unknown_instructions:
            details.append("unknown instruction IDs: " + ", ".join(unknown_instructions))
        if unknown_skills:
            details.append("unknown skill IDs: " + ", ".join(unknown_skills))
        if wrong_instruction_kind:
            details.append("skills listed as instructions: " + ", ".join(wrong_instruction_kind))
        if wrong_skill_kind:
            details.append("instructions listed as skills: " + ", ".join(wrong_skill_kind))
        raise GenerationError("publication manifest is outside the generation manifest (" + "; ".join(details) + ")")


def load_manifests(repo: pathlib.Path = ROOT) -> tuple[GenerationManifest, PublicationManifest]:
    generation = load_generation_manifest(repo)
    publication = load_publication_manifest(repo)
    validate_publication_intersection(generation, publication)
    return generation, publication


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip("`'\"")
    lowered = normalized.casefold()
    return (
        not normalized
        or normalized.startswith(("<", "$", "%", "{"))
        or any(
            token in lowered
            for token in ("example", "placeholder", "redacted", "your-", "dummy", "fake", "test-only")
        )
    )


def validate_public_text(text: str, *, label: str) -> None:
    """Reject content that is unsafe to copy into an unrestricted repository."""
    if "\x00" in text:
        raise GenerationError(f"{label} contains a NUL byte")
    if PRIVATE_KEY_HEADER.search(text):
        raise GenerationError(f"{label} contains a private-key header")
    if TOKEN_SIGNATURE.search(text):
        raise GenerationError(f"{label} contains a credential-shaped token")
    if MACHINE_LOCAL_PATH.search(text):
        raise GenerationError(f"{label} contains a machine-local or private filesystem path")
    if RESTRICTED_MARKER.search(text):
        raise GenerationError(f"{label} contains a restricted-publication marker")
    for match in PRIVATE_HOST_URL.finditer(text):
        if not match.group("host").casefold().endswith(".example.com"):
            raise GenerationError(f"{label} contains a private service address")
    for match in URI_CREDENTIAL.finditer(text):
        if not match.group("host").casefold().endswith("example.com"):
            raise GenerationError(f"{label} contains credentials embedded in a URI")
    for match in AUTHORIZATION_CREDENTIAL.finditer(text):
        if not _looks_like_placeholder(match.group("value")):
            raise GenerationError(f"{label} contains an authorization credential")
    for match in SECRET_ASSIGNMENT.finditer(text):
        value = match.group("value").strip("`'\"")
        if "." in value and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value):
            continue
        if not _looks_like_placeholder(value):
            raise GenerationError(f"{label} contains a literal secret or credential")


def _validate_package_path(relative: pathlib.PurePosixPath, *, package: str) -> None:
    lowered_parts = {part.casefold() for part in relative.parts}
    unsafe_directories = lowered_parts & UNSAFE_DIRECTORY_NAMES
    if unsafe_directories:
        raise GenerationError(
            f"skill {package!r} contains an unsafe generated/dependency directory: "
            f"{relative.as_posix()}"
        )
    lowered_name = relative.name.casefold()
    suffix = relative.suffix.casefold()
    if (
        lowered_name in UNSAFE_FILE_NAMES
        or lowered_name.startswith(".env.")
        or suffix in UNSAFE_SUFFIXES
    ):
        raise GenerationError(f"skill {package!r} contains an unsafe credential/key file: {relative}")
    if suffix not in SAFE_PACKAGE_SUFFIXES:
        raise GenerationError(
            f"skill {package!r} contains an unsupported file type {suffix or '<none>'}: "
            f"{relative.as_posix()}"
        )
    if relative.as_posix() == "agents/openai.yaml":
        raise GenerationError(
            f"skill {package!r} authors agents/openai.yaml; use interface.json instead"
        )


def _walk_package_files(
    repo: pathlib.Path, package_path: pathlib.Path, *, package: str
) -> list[pathlib.Path]:
    result: list[pathlib.Path] = []
    pending = [package_path]
    while pending:
        directory = pending.pop()
        directory_label = _relative(repo, directory).as_posix()
        for entry in reversed(_directory_entries(directory, label=directory_label)):
            _reject_reparse(entry, label=f"skill {package!r} entry")
            relative = pathlib.PurePosixPath(entry.relative_to(package_path).as_posix())
            if entry.is_dir():
                if entry.name.casefold() in UNSAFE_DIRECTORY_NAMES:
                    raise GenerationError(
                        f"skill {package!r} contains an unsafe generated/dependency directory: "
                        f"{relative.as_posix()}"
                    )
                pending.append(entry)
            elif entry.is_file():
                _validate_package_path(relative, package=package)
                result.append(entry)
            else:
                raise GenerationError(
                    f"skill {package!r} contains an unsupported filesystem entry: "
                    f"{relative.as_posix()}"
                )
    return sorted(result, key=lambda path: path.relative_to(package_path).as_posix())


def _read_text(path: pathlib.Path, *, label: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise GenerationError(f"cannot read UTF-8 text {label}: {error}") from error
    normalized = _normalise_text(text)
    validate_public_text(normalized, label=label)
    return normalized


def _interface(path: pathlib.Path, *, label: str) -> dict[str, str]:
    raw = _expect_object(_read_json_file(path, label=label), label=label)
    keys = {"display_name", "short_description", "default_prompt"}
    _expect_keys(raw, keys, label=label)
    result: dict[str, str] = {}
    for key in sorted(keys):
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise GenerationError(f"{label}.{key} must be a nonempty string")
        result[key] = value.strip()
    if len(result["display_name"]) > 64 or len(result["short_description"]) > 64:
        raise GenerationError(f"{label} display_name and short_description must be <= 64 characters")
    if len(result["default_prompt"]) > 1024:
        raise GenerationError(f"{label}.default_prompt must be <= 1024 characters")
    validate_public_text("\n".join(result.values()), label=label)
    return result


def _validate_skill_frontmatter(text: str, *, skill: str, label: str) -> None:
    if not text.startswith("---\n"):
        raise GenerationError(f"{label} must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise GenerationError(f"{label} has unterminated YAML frontmatter")
    frontmatter = text[4:end]
    name_match = re.search(r"(?m)^name:\s*([^\s]+)\s*$", frontmatter)
    description_match = re.search(r"(?m)^description:\s*(\S.*)\s*$", frontmatter)
    if not name_match or name_match.group(1) != skill:
        raise GenerationError(f"{label} frontmatter name must match package ID {skill!r}")
    if not description_match:
        raise GenerationError(f"{label} frontmatter needs a nonempty description")


def _generated_notice(source: pathlib.PurePosixPath) -> str:
    return (
        f"<!-- Generated from {source.as_posix()} by {GENERATED_BY}. "
        "Do not edit this copy directly. -->\n"
    )


def _insert_notice(text: str, source: pathlib.PurePosixPath) -> str:
    notice = _generated_notice(source)
    if not text.startswith("---\n"):
        return notice + text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise GenerationError(f"unterminated YAML frontmatter in {source.as_posix()}")
    boundary = end + len("\n---\n")
    return text[:boundary] + notice + text[boundary:]


def _local_link_parts(raw_target: str) -> tuple[str, str, str]:
    path_and_query, separator, fragment = raw_target.partition("#")
    path_part, query_separator, query = path_and_query.partition("?")
    tail = ("?" + query if query_separator else "") + ("#" + fragment if separator else "")
    return path_part, tail, urllib.parse.unquote(path_part)


def _map_link(
    raw_target: str,
    *,
    repo: pathlib.Path,
    source_file: pathlib.Path,
    output_file: pathlib.Path,
    source_package: pathlib.Path | None,
    output_package: pathlib.Path | None,
) -> str:
    if raw_target.startswith(SKIP_LINK_PREFIXES):
        return raw_target
    path_part, tail, decoded_path = _local_link_parts(raw_target)
    if not path_part:
        return raw_target
    if (
        "\\" in decoded_path
        or decoded_path.startswith("/")
        or re.match(r"^[A-Za-z]:", decoded_path)
    ):
        raise GenerationError(
            f"local Markdown target must be repository-contained: {raw_target!r} in "
            f"{_relative(repo, source_file).as_posix()}"
        )
    candidate = pathlib.Path(os.path.abspath(source_file.parent / pathlib.Path(decoded_path)))
    try:
        candidate.relative_to(repo.absolute())
    except ValueError as error:
        raise GenerationError(
            f"Markdown target escapes the repository: {raw_target!r} in "
            f"{_relative(repo, source_file).as_posix()}"
        ) from error
    if not candidate.exists():
        return raw_target
    relative_candidate = _relative(repo, candidate)
    source_target = _resolve_existing_exact(
        repo,
        relative_candidate,
        label=f"Markdown target in {_relative(repo, source_file).as_posix()}",
        expect_directory=candidate.is_dir(),
    )

    mapped_target = source_target
    if source_package is not None and output_package is not None:
        try:
            package_relative = source_target.relative_to(source_package)
        except ValueError:
            pass
        else:
            mapped_target = output_package / package_relative
    rebased = os.path.relpath(mapped_target, output_file.parent).replace("\\", "/")
    if rebased == ".":
        rebased = "./"
    return pathlib.PurePosixPath(rebased).as_posix() + tail


def _render_markdown(
    text: str,
    *,
    repo: pathlib.Path,
    source_file: pathlib.Path,
    output_file: pathlib.Path,
    source_package: pathlib.Path | None = None,
    output_package: pathlib.Path | None = None,
) -> bytes:
    text = _normalise_text(text)

    def replace_link(match: re.Match[str]) -> str:
        target = _map_link(
            match.group("target"),
            repo=repo,
            source_file=source_file,
            output_file=output_file,
            source_package=source_package,
            output_package=output_package,
        )
        return match.group("prefix") + target + match.group("suffix")

    rendered = MARKDOWN_LINK.sub(replace_link, text)

    def replace_inline(match: re.Match[str]) -> str:
        target = _map_link(
            match.group("target"),
            repo=repo,
            source_file=source_file,
            output_file=output_file,
            source_package=source_package,
            output_package=output_package,
        )
        return "`" + target + "`"

    rendered = INLINE_PATH.sub(replace_inline, rendered)
    return _insert_notice(rendered, _relative(repo, source_file)).encode("utf-8")


def _render_openai_yaml(interface: dict[str, str]) -> bytes:
    quote = lambda value: json.dumps(value, ensure_ascii=False)  # noqa: E731
    return (
        "interface:\n"
        f"  display_name: {quote(interface['display_name'])}\n"
        f"  short_description: {quote(interface['short_description'])}\n"
        f"  default_prompt: {quote(interface['default_prompt'])}\n"
    ).encode("utf-8")


def _is_output_owned(path: pathlib.PurePosixPath, manifest: GenerationManifest) -> bool:
    if path in manifest.managed_files:
        return True
    return any(path != root and path.is_relative_to(root) for root in manifest.managed_roots)


def _paths_overlap(left: pathlib.PurePosixPath, right: pathlib.PurePosixPath) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def build_outputs(repo: pathlib.Path = ROOT) -> BuildResult:
    repo = repo.absolute()
    generation, _publication = load_manifests(repo)
    outputs: dict[pathlib.PurePosixPath, bytes] = {}
    origins: dict[pathlib.PurePosixPath, str] = {}
    folded_outputs: dict[str, pathlib.PurePosixPath] = {}
    canonical_paths: set[pathlib.PurePosixPath] = {
        DEFAULT_GENERATION_MANIFEST,
        DEFAULT_PUBLICATION_MANIFEST,
    }
    canonical_markdown: set[pathlib.PurePosixPath] = set()

    def add_output(target: pathlib.PurePosixPath, content: bytes, *, origin: str) -> None:
        if not _is_output_owned(target, generation):
            raise GenerationError(f"generated target is outside exact managed outputs: {target}")
        if target.parts[0] in PROTECTED_TOP_LEVEL:
            raise GenerationError(f"generated target overlaps protected path: {target}")
        folded = target.as_posix().casefold()
        previous = folded_outputs.get(folded)
        if previous is not None:
            raise GenerationError(
                f"duplicate or case-colliding generated target: {previous.as_posix()} and "
                f"{target.as_posix()}"
            )
        _inspect_target_chain(repo, target, label="generated target")
        folded_outputs[folded] = target
        outputs[target] = content
        origins[target] = origin

    for instruction in generation.instructions:
        source_file = _resolve_existing_exact(
            repo,
            instruction.source,
            label=f"instruction {instruction.id!r}",
            expect_directory=False,
        )
        source_text = _read_text(source_file, label=instruction.source.as_posix())
        canonical_paths.add(instruction.source)
        canonical_markdown.add(instruction.source)
        for target in instruction.targets:
            output_file = repo.joinpath(*target.path.parts)
            add_output(
                target.path,
                _render_markdown(
                    source_text,
                    repo=repo,
                    source_file=source_file,
                    output_file=output_file,
                ),
                origin=instruction.source.as_posix(),
            )

    for skill in generation.skills:
        package_path = _resolve_existing_exact(
            repo, skill.source, label=f"skill {skill.id!r}", expect_directory=True
        )
        package_files = _walk_package_files(repo, package_path, package=skill.id)
        package_relative_files = {
            pathlib.PurePosixPath(path.relative_to(package_path).as_posix()): path
            for path in package_files
        }
        required = {pathlib.PurePosixPath("SKILL.md"), pathlib.PurePosixPath("interface.json")}
        missing = required - set(package_relative_files)
        if missing:
            raise GenerationError(
                f"skill {skill.id!r} is missing required files: "
                + ", ".join(path.as_posix() for path in sorted(missing))
            )
        skill_text = _read_text(
            package_relative_files[pathlib.PurePosixPath("SKILL.md")],
            label=f"{skill.source.as_posix()}/SKILL.md",
        )
        _validate_skill_frontmatter(
            skill_text,
            skill=skill.id,
            label=f"{skill.source.as_posix()}/SKILL.md",
        )
        interface = _interface(
            package_relative_files[pathlib.PurePosixPath("interface.json")],
            label=f"{skill.source.as_posix()}/interface.json",
        )
        canonical_paths.add(skill.source)
        for relative, source_file in package_relative_files.items():
            canonical = skill.source / relative
            canonical_paths.add(canonical)
            if relative.suffix.casefold() in TEXT_SUFFIXES:
                source_text = _read_text(source_file, label=canonical.as_posix())
                if relative.suffix.casefold() == ".md":
                    canonical_markdown.add(canonical)
            else:
                source_text = ""

            if relative == pathlib.PurePosixPath("interface.json"):
                continue
            for target in skill.targets:
                target_file_relative = target.path / relative
                target_package = repo.joinpath(*target.path.parts)
                target_file = repo.joinpath(*target_file_relative.parts)
                if relative.suffix.casefold() == ".md":
                    content = _render_markdown(
                        source_text,
                        repo=repo,
                        source_file=source_file,
                        output_file=target_file,
                        source_package=package_path,
                        output_package=target_package,
                    )
                elif relative.suffix.casefold() in TEXT_SUFFIXES:
                    content = source_text.encode("utf-8")
                else:
                    try:
                        content = source_file.read_bytes()
                    except OSError as error:
                        raise GenerationError(f"cannot read {canonical.as_posix()}: {error}") from error
                add_output(target_file_relative, content, origin=canonical.as_posix())
        for target in skill.targets:
            if target.vendor == "codex":
                add_output(
                    target.path / "agents" / "openai.yaml",
                    _render_openai_yaml(interface),
                    origin=f"{skill.source.as_posix()}/interface.json",
                )

    for output in outputs:
        for source in canonical_paths:
            if _paths_overlap(output, source):
                raise GenerationError(
                    f"generated target overlaps canonical source: {output.as_posix()} and "
                    f"{source.as_posix()}"
                )
    return BuildResult(
        outputs,
        origins,
        generation.managed_files,
        generation.managed_roots,
        tuple(sorted(canonical_markdown)),
    )


def _actual_managed_files(
    repo: pathlib.Path, roots: Iterable[pathlib.PurePosixPath]
) -> set[pathlib.PurePosixPath]:
    actual: set[pathlib.PurePosixPath] = set()
    for root in roots:
        root_path = repo.joinpath(*root.parts)
        _inspect_target_chain(repo, root, label="managed root")
        if not root_path.exists():
            continue
        resolved_root = _resolve_existing_exact(
            repo, root, label="managed root", expect_directory=True
        )
        pending = [resolved_root]
        while pending:
            directory = pending.pop()
            for entry in _directory_entries(directory, label=_relative(repo, directory).as_posix()):
                _reject_reparse(entry, label="managed output")
                if entry.is_dir():
                    pending.append(entry)
                elif entry.is_file():
                    actual.add(_relative(repo, entry))
                else:
                    raise GenerationError(f"managed output has unsupported entry: {entry}")
    return actual


def check_outputs(repo: pathlib.Path, result: BuildResult) -> list[str]:
    repo = repo.absolute()
    problems: list[str] = []
    for relative, expected in sorted(result.outputs.items()):
        path = repo.joinpath(*relative.parts)
        if not path.is_file():
            problems.append(f"missing: {relative.as_posix()}")
            continue
        try:
            exact = _resolve_existing_exact(
                repo, relative, label="generated output", expect_directory=False
            )
            actual = exact.read_bytes()
        except (GenerationError, OSError) as error:
            problems.append(f"unsafe: {relative.as_posix()}: {error}")
            continue
        if actual != expected:
            problems.append(f"stale: {relative.as_posix()}")
    unexpected = _actual_managed_files(repo, result.managed_roots) - set(result.outputs)
    problems.extend(f"unexpected: {path.as_posix()}" for path in sorted(unexpected))
    return problems


def _atomic_write(path: pathlib.Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".agent-sync-", delete=False
    ) as handle:
        temporary = pathlib.Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _assert_cleanup_target(
    relative: pathlib.PurePosixPath, roots: Iterable[pathlib.PurePosixPath]
) -> None:
    if not any(relative != root and relative.is_relative_to(root) for root in roots):
        raise GenerationError(f"refusing cleanup outside exact generated roots: {relative.as_posix()}")


def write_outputs(repo: pathlib.Path, result: BuildResult) -> tuple[int, int]:
    repo = repo.absolute()
    actual = _actual_managed_files(repo, result.managed_roots)
    expected = set(result.outputs)
    removed = 0
    for relative in sorted(actual - expected, reverse=True):
        _assert_cleanup_target(relative, result.managed_roots)
        path = repo.joinpath(*relative.parts)
        _reject_reparse(path, label="obsolete generated output")
        path.unlink()
        removed += 1
    for relative, content in sorted(result.outputs.items()):
        _inspect_target_chain(repo, relative, label="generated target")
        _atomic_write(repo.joinpath(*relative.parts), content)

    for root in result.managed_roots:
        root_path = repo.joinpath(*root.parts)
        if not root_path.exists():
            continue
        directories = sorted(
            (path for path in root_path.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            _reject_reparse(directory, label="managed output directory")
            try:
                directory.rmdir()
            except OSError:
                pass
    return len(result.outputs), removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail on missing, stale, or unexpected outputs")
    mode.add_argument("--write", action="store_true", help="write deterministic outputs and remove obsolete generated files")
    mode.add_argument("--list", action="store_true", help="list the exact generated output paths")
    args = parser.parse_args(argv)

    try:
        result = build_outputs(ROOT)
        if args.list:
            for path in sorted(result.outputs):
                print(path.as_posix())
            print(f"{len(result.outputs)} generated file(s)")
            return 0
        if args.write:
            written, removed = write_outputs(ROOT, result)
            problems = check_outputs(ROOT, result)
            if problems:
                for problem in problems:
                    print(problem)
                return 1
            print(
                f"agent surfaces generated: {written} file(s), "
                f"{removed} obsolete file(s) removed"
            )
            return 0
        problems = check_outputs(ROOT, result)
        if problems:
            for problem in problems:
                print(problem)
            print(f"agent surface check refused: {len(problems)} problem(s)")
            return 1
        print(f"agent surfaces current: {len(result.outputs)} file(s)")
        return 0
    except (GenerationError, OSError) as error:
        print(f"agent surface generation refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
