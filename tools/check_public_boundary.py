#!/usr/bin/env python3
"""Reject files that do not belong in the public documentation toolkit.

The check walks the complete candidate tree rather than a publication allowlist.
It intentionally ignores only the repository's top-level ``.git`` directory.
Generated agent surfaces are therefore checked exactly like authored files.
Byte-for-byte parity of ``.agents`` and ``.claude`` is deliberately delegated
to ``sync_agent_instructions.py --check``; this guard never trusts those copies
or a publication manifest as a reason to skip their contents.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import pathlib
import re
import stat
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit


ROOT = pathlib.Path(os.path.abspath(pathlib.Path(__file__).parent.parent))
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 512
MAX_DIRECTORY_BYTES = 12 * 1024 * 1024
MAX_CANDIDATE_FILES = 5_000
MAX_CANDIDATE_BYTES = 32 * 1024 * 1024

FORBIDDEN_DIRECTORIES = frozenset(
    {
        "__pycache__",
        ".cache",
        ".nyc_output",
        ".pytest_cache",
        ".venv",
        "artifacts",
        "bin",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "lcov-report",
        "node_modules",
        "obj",
        "out",
        "temp",
        "testresults",
        "tmp",
    }
)

SENSITIVE_FILE_NAMES = frozenset(
    {
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
    }
)
SENSITIVE_SUFFIXES = frozenset({".key", ".kdbx", ".ovpn", ".p12", ".pem", ".pfx"})
# Auditable text formats such as SVG and HTML intentionally remain allowed;
# opaque archives, raster/media assets, fonts, and compiled formats do not.
ARCHIVE_MEDIA_SUFFIXES = frozenset(
    {
        ".7z",
        ".a",
        ".avi",
        ".blend",
        ".bmp",
        ".bz2",
        ".cab",
        ".class",
        ".com",
        ".db",
        ".deb",
        ".dll",
        ".dmg",
        ".docx",
        ".dylib",
        ".eot",
        ".epub",
        ".exe",
        ".flac",
        ".gif",
        ".gz",
        ".heic",
        ".ico",
        ".iso",
        ".jar",
        ".jpeg",
        ".jpg",
        ".lib",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".msi",
        ".nupkg",
        ".o",
        ".ogg",
        ".otf",
        ".pdf",
        ".pdb",
        ".png",
        ".pptx",
        ".pyc",
        ".rar",
        ".rpm",
        ".so",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".tgz",
        ".tif",
        ".tiff",
        ".ttf",
        ".wasm",
        ".wav",
        ".war",
        ".webm",
        ".webp",
        ".whl",
        ".woff",
        ".woff2",
        ".xlsx",
        ".xz",
        ".zip",
        ".zst",
    }
)

# Build distinctive private identifiers at runtime so the checker does not need
# to contain or publish them itself.
_RESERVED_PRODUCT = "ming" + "leap"
_SHORT_PREFIX = "m" + "gl"
_OLD_SNIPPET_PREFIX = "me" + "_snippet_"

FORBIDDEN_TEXT = (
    (_RESERVED_PRODUCT, "reserved product identifier"),
    (_SHORT_PREFIX + "_", "reserved environment or symbol prefix"),
    (_SHORT_PREFIX + ".", "reserved namespace prefix"),
    (_OLD_SNIPPET_PREFIX, "retired snippet prefix"),
)


def _path_pattern(*parts: str) -> re.Pattern[str]:
    separator = r"[\\/]"
    body = separator.join(re.escape(part) for part in parts)
    return re.compile(
        rf"(?<![A-Za-z0-9_.-]){body}(?=$|[\\/\s:'\"`])",
        re.IGNORECASE,
    )


FORBIDDEN_PATH_TEXT = (
    (_path_pattern("legacy", "engine"), "retired product path"),
    (_path_pattern("legacy", "platform"), "retired product path"),
    (_path_pattern("docs", "engine"), "private documentation path"),
    (_path_pattern("docs", "agent"), "private documentation path"),
    (_path_pattern("research", "store"), "private source-store path"),
    (re.compile(re.escape("asset" + "-pipeline"), re.IGNORECASE), "private asset path"),
)

WINDOWS_USER_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/](?:Users|Documents[ ]and[ ]Settings)[\\/][^\\/\s:'\"<>|]+)"
)
POSIX_USER_PATH = re.compile(r"(?i)(?<![A-Za-z0-9])/(?:home|Users)/[^/\s:'\"<>]+")
ROOT_USER_PATH = re.compile(r"(?i)(?<![A-Za-z0-9])/root(?=/|\s|$)")
FILE_URI = re.compile(r"(?i)file:///[A-Za-z0-9]", re.ASCII)

URL = re.compile(r"(?i)https?://[^\\\s<>\"'`)}\]]+")
PRIVATE_HOST_SUFFIXES = (".corp", ".home", ".internal", ".intranet", ".lan", ".local")
LOCAL_PREVIEW_HOSTS = frozenset({"0.0.0.0", "127.0.0.1", "::1", "localhost"})
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)

ALLOWED_GITHUB_REPOSITORIES = frozenset(
    (owner.casefold(), repository.casefold())
    for owner, repository in (
        ("choyi0521", "agent-docs"),
        ("example", "project"),
        ("fb55", "entities"),
        ("inikulin", "parse5"),
        ("jgraph", "drawio-desktop"),
        ("jgraph", "drawio-mcp"),
        ("jsdom", "jsdom"),
        ("xunit", "xunit"),
        ("xoofx", "markdig"),
        ("ZSeven-W", "openpencil"),
    )
)
ALLOWED_GITHUB_ACTION_REPOSITORIES = frozenset(
    {
        ("actions", "checkout"),
        ("actions", "setup-dotnet"),
        ("actions", "setup-node"),
        ("actions", "setup-python"),
    }
)

ACTION_USES = re.compile(
    r"(?im)^\s*(?:-\s*)?uses:\s*[\"']?"
    r"(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
    r"@(?P<ref>[^\"'\s#]+)[\"']?"
)
IMMUTABLE_GIT_REF = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
LFS_POINTER_HEADER = "version " + "https" + "://git-" + "lfs.github.com/spec/v1"
INTERNAL_HOST_NAME = re.compile(
    r"(?i)(?<![A-Za-z0-9.-])(?:[A-Za-z0-9-]+\.)+"
    r"(?:corp|home|internal|intranet|lan|local)\b"
)
IPV4_ADDRESS = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")

PRIVATE_KEY_MARKERS = tuple(
    "-" * 5 + "BEGIN " + kind + "-" * 5
    for kind in (
        "PRIVATE" + " KEY",
        "RSA " + "PRIVATE" + " KEY",
        "EC " + "PRIVATE" + " KEY",
        "OPENSSH " + "PRIVATE" + " KEY",
        "PGP " + "PRIVATE" + " KEY BLOCK",
    )
)

SECRET_PATTERNS = (
    ("cloud access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Git hosting token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("chat service token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("payment service secret", re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b")),
    ("API credential", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "authorization bearer token",
        re.compile(r"(?i)\bauthorization\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._~+/-]{16,}"),
    ),
)

CREDENTIAL_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?:
        pass(?:word|wd)?|pwd|secret|client[_-]?secret|api[_-]?key|
        access[_-]?token|auth[_-]?token|bearer[_-]?token
    )\b
    \s*(?:=|:)\s*
    (?:
        [\"'](?P<quoted>[^\"'\r\n]{8,})[\"']|
        (?P<bare>[A-Za-z0-9+/=_-]{12,})(?=$|\s|[,;}\]])
    )
    """
)
SAFE_CREDENTIAL_VALUES = frozenset(
    {
        "changeme",
        "example",
        "not-set",
        "placeholder",
        "redacted",
        "replace-me",
    }
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    kind: str
    detail: str

    def render(self) -> str:
        safe_path = _redact_path_for_log(self.path)
        location = safe_path if self.line == 0 else f"{safe_path}:{self.line}"
        return f"{location}: {self.kind}: {self.detail}"


def _redact_path_for_log(value: str) -> str:
    rendered = "".join(
        character if character.isprintable() else f"\\u{ord(character):04x}"
        for character in value
    )
    for forbidden, _ in FORBIDDEN_TEXT:
        rendered = re.sub(re.escape(forbidden), "<redacted>", rendered, flags=re.IGNORECASE)
    for pattern, _ in FORBIDDEN_PATH_TEXT:
        rendered = pattern.sub("<redacted-path>", rendered)
    for _, pattern in SECRET_PATTERNS:
        rendered = pattern.sub("<redacted>", rendered)
    for marker in PRIVATE_KEY_MARKERS:
        rendered = rendered.replace(marker, "<redacted>")
    rendered = CREDENTIAL_ASSIGNMENT.sub("<redacted-credential>", rendered)
    rendered = INTERNAL_HOST_NAME.sub("<redacted-host>", rendered)
    for pattern in (WINDOWS_USER_PATH, POSIX_USER_PATH, ROOT_USER_PATH, FILE_URI):
        rendered = pattern.sub("<redacted-path>", rendered)

    def redact_address(match: re.Match[str]) -> str:
        try:
            address = ipaddress.ip_address(match.group(0))
        except ValueError:
            return match.group(0)
        return "<redacted-address>" if _address_is_internal(address) else match.group(0)

    rendered = IPV4_ADDRESS.sub(redact_address, rendered)
    return rendered


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_reparse(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(stat_result.st_mode) or bool(attributes & reparse_flag)


def _regular_entry_size(entry: os.DirEntry[str]) -> int:
    """Return a direct regular file's size without following unsafe links."""
    try:
        stat_result = entry.stat(follow_symlinks=False)
    except OSError:
        return 0
    if _is_reparse(stat_result) or not stat.S_ISREG(stat_result.st_mode):
        return 0
    return stat_result.st_size


def _is_sensitive_file(path: pathlib.Path) -> bool:
    name = path.name.casefold()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    return name in SENSITIVE_FILE_NAMES or path.suffix.casefold() in SENSITIVE_SUFFIXES


def _is_forbidden_directory(name: str) -> bool:
    """Return whether *name* is generated output, independent of its depth."""
    folded = name.casefold()
    coverage_name = folded.removeprefix(".")
    return (
        folded in FORBIDDEN_DIRECTORIES
        or folded == ".tmp"
        or folded.startswith(".tmp-")
        or coverage_name == "coverage"
        or coverage_name.startswith(("coverage-", "coverage_", "coverage."))
    )


def _scan_relative_path(relative: str, *, is_file: bool) -> list[Finding]:
    """Check names as metadata so unsafe values cannot hide in empty paths."""
    findings: list[Finding] = []
    try:
        relative.encode("utf-8", "strict")
    except UnicodeEncodeError:
        findings.append(Finding(relative, 0, "invalid path", "path names must be valid UTF-8"))
    if any(ord(character) < 32 or ord(character) == 127 for character in relative):
        findings.append(Finding(relative, 0, "invalid path", "path names must not contain control characters"))
    folded = relative.casefold()

    for forbidden, detail in FORBIDDEN_TEXT:
        if forbidden.casefold() in folded:
            findings.append(Finding(relative, 0, "private identifier", detail))

    for pattern, detail in FORBIDDEN_PATH_TEXT:
        if pattern.search(relative):
            findings.append(Finding(relative, 0, "private path", detail))

    for pattern in (WINDOWS_USER_PATH, POSIX_USER_PATH, ROOT_USER_PATH, FILE_URI):
        if pattern.search(relative):
            findings.append(Finding(relative, 0, "absolute user path", "local user path is not public metadata"))
    if INTERNAL_HOST_NAME.search(relative):
        findings.append(Finding(relative, 0, "internal host", "private or internal hostname"))
    for address_match in IPV4_ADDRESS.finditer(relative):
        try:
            address = ipaddress.ip_address(address_match.group(0))
        except ValueError:
            continue
        if _address_is_internal(address):
            findings.append(Finding(relative, 0, "internal host", "private network address"))
            break
    for detail, pattern in SECRET_PATTERNS:
        if pattern.search(relative):
            findings.append(Finding(relative, 0, "secret", detail))
    for marker in PRIVATE_KEY_MARKERS:
        if marker in relative:
            findings.append(Finding(relative, 0, "secret", "private-key material"))
    for match in CREDENTIAL_ASSIGNMENT.finditer(relative):
        value = match.group("quoted") or match.group("bare") or ""
        if not _credential_value_is_safe(value):
            findings.append(Finding(relative, 0, "secret", "literal credential assignment"))

    name = pathlib.PurePosixPath(relative).name.casefold()
    if name == ".gitmodules":
        findings.append(Finding(relative, 0, "nested repository", "submodule metadata is not allowed"))
    if is_file and pathlib.PurePosixPath(relative).suffix.casefold() in ARCHIVE_MEDIA_SUFFIXES:
        findings.append(Finding(relative, 0, "unsupported file type", "archives, media, and compiled files are not allowed"))
    return findings


def _credential_value_is_safe(value: str) -> bool:
    cleaned = value.strip().casefold()
    return (
        not cleaned
        or cleaned in SAFE_CREDENTIAL_VALUES
        or cleaned.startswith(("$", "%", "<", "*"))
        or "example" in cleaned
        or "placeholder" in cleaned
        or "redacted" in cleaned
    )


def _address_is_internal(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if str(address) in LOCAL_PREVIEW_HOSTS:
        return False
    if any(address.version == network.version and address in network for network in DOCUMENTATION_NETWORKS):
        return False
    return address.is_private or address.is_link_local or address.is_loopback


def _private_host_reason(raw_url: str) -> str | None:
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname
    except ValueError:
        return "malformed URL"

    if parsed.username is not None or parsed.password is not None:
        return "URL embeds credentials"
    if host is None:
        return None

    normalized = host.casefold().rstrip(".")
    if normalized in LOCAL_PREVIEW_HOSTS:
        return None
    if normalized.endswith(PRIVATE_HOST_SUFFIXES):
        return "private or internal hostname"
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        # Single-label names are private by convention. Punctuation-only
        # listener placeholders used in source code are not host disclosures.
        if "." not in normalized and normalized.replace("-", "").isalnum():
            return "unqualified internal hostname"
        return None
    if _address_is_internal(address):
        return "private network address"
    return None


def _github_repository_reason(raw_url: str) -> str | None:
    """Require GitHub links to name a repository from the public allowlist."""
    try:
        parsed = urlsplit(raw_url.rstrip(".,;:!?"))
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold().rstrip(".")
    supported_hosts = {"github.com", "www.github.com", "raw.githubusercontent.com"}
    if host not in supported_hosts:
        if host.endswith(".github.com") or host.endswith(".githubusercontent.com"):
            return "GitHub host is not approved for public repository links"
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    # npm lock files may contain GitHub Sponsors funding metadata. It is a
    # public profile rather than a code origin, so keep this single namespace
    # exception narrow and validate the account-shaped path component.
    if (
        host in {"github.com", "www.github.com"}
        and len(segments) == 2
        and segments[0].casefold() == "sponsors"
        and re.fullmatch(r"[A-Za-z0-9_.-]+", segments[1])
    ):
        return None
    if len(segments) < 2:
        return "GitHub URL does not identify an allowlisted repository"
    owner = segments[0].casefold()
    repository = segments[1].removesuffix(".git").casefold()
    if (owner, repository) not in ALLOWED_GITHUB_REPOSITORIES:
        return "GitHub repository is not in the public allowlist"
    return None


def _scan_text(relative: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    folded = text.casefold()

    for forbidden, detail in FORBIDDEN_TEXT:
        offset = folded.find(forbidden.casefold())
        if offset >= 0:
            findings.append(Finding(relative, _line_number(text, offset), "private identifier", detail))

    for pattern, detail in FORBIDDEN_PATH_TEXT:
        match = pattern.search(text)
        if match:
            findings.append(Finding(relative, _line_number(text, match.start()), "private path", detail))

    for pattern in (WINDOWS_USER_PATH, POSIX_USER_PATH, ROOT_USER_PATH, FILE_URI):
        match = pattern.search(text)
        if match:
            findings.append(
                Finding(relative, _line_number(text, match.start()), "absolute user path", "local user path is not public metadata")
            )

    for match in URL.finditer(text):
        raw_url = match.group(0)
        reason = _private_host_reason(raw_url)
        if reason:
            findings.append(Finding(relative, _line_number(text, match.start()), "internal host", reason))
        repository_reason = _github_repository_reason(raw_url)
        if repository_reason:
            findings.append(
                Finding(relative, _line_number(text, match.start()), "unapproved repository", repository_reason)
            )

    internal_name = INTERNAL_HOST_NAME.search(text)
    if internal_name:
        findings.append(
            Finding(relative, _line_number(text, internal_name.start()), "internal host", "private or internal hostname")
        )
    for address_match in IPV4_ADDRESS.finditer(text):
        try:
            address = ipaddress.ip_address(address_match.group(0))
        except ValueError:
            continue
        if _address_is_internal(address):
            findings.append(
                Finding(relative, _line_number(text, address_match.start()), "internal host", "private network address")
            )
            break

    for match in ACTION_USES.finditer(text):
        action = match.group("action")
        owner, repository, *_ = action.split("/")
        if (owner.casefold(), repository.casefold()) not in ALLOWED_GITHUB_ACTION_REPOSITORIES:
            findings.append(
                Finding(relative, _line_number(text, match.start()), "unapproved action", "action repository is not allowlisted")
            )
        if not IMMUTABLE_GIT_REF.fullmatch(match.group("ref")):
            findings.append(
                Finding(relative, _line_number(text, match.start()), "mutable action", "remote actions must use a full commit hash")
            )

    for marker in PRIVATE_KEY_MARKERS:
        offset = text.find(marker)
        if offset >= 0:
            findings.append(Finding(relative, _line_number(text, offset), "secret", "private-key material"))

    for detail, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(Finding(relative, _line_number(text, match.start()), "secret", detail))

    for match in CREDENTIAL_ASSIGNMENT.finditer(text):
        value = match.group("quoted") or match.group("bare") or ""
        if not _credential_value_is_safe(value):
            findings.append(
                Finding(relative, _line_number(text, match.start()), "secret", "literal credential assignment")
            )

    return findings


def _scan_file(root: pathlib.Path, path: pathlib.Path, relative: str) -> list[Finding]:
    findings: list[Finding] = []
    if _is_sensitive_file(path):
        findings.append(Finding(relative, 0, "sensitive file", "credential or key file name"))
        return findings

    try:
        size = path.stat(follow_symlinks=False).st_size
        if size > MAX_TEXT_BYTES:
            return [Finding(relative, 0, "oversized file", f"text files must not exceed {MAX_TEXT_BYTES} bytes")]
        data = path.read_bytes()
    except OSError as error:
        return [Finding(relative, 0, "unreadable file", error.__class__.__name__)]

    if b"\x00" in data:
        return [Finding(relative, 0, "binary file", "NUL byte found")]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [Finding(relative, 0, "binary file", "file is not UTF-8 text")]
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        return [Finding(relative, 0, "binary file", "unsupported control byte found")]
    if text.startswith((LFS_POINTER_HEADER + "\n", LFS_POINTER_HEADER + "\r\n")):
        return [Finding(relative, 1, "Git LFS pointer", "large-file placeholders are not public source files")]
    if path.name.casefold() == ".git" and text.lstrip().casefold().startswith("gitdir:"):
        return [Finding(relative, 1, "nested repository", "gitdir metadata is not allowed")]

    findings.extend(_scan_text(relative, text))
    return findings


def scan_tree(root: pathlib.Path) -> list[Finding]:
    """Return every public-boundary violation below *root*."""
    root = pathlib.Path(os.path.abspath(root))
    if not root.is_dir():
        return [Finding(".", 0, "invalid root", "candidate root is not a directory")]
    try:
        if _is_reparse(os.lstat(root)):
            return [Finding(".", 0, "reparse point", "candidate root must be a real directory")]
    except OSError as error:
        return [Finding(".", 0, "invalid root", error.__class__.__name__)]

    findings: list[Finding] = []
    candidate_files = 0
    candidate_bytes = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold(), reverse=True)
        except OSError as error:
            relative = pathlib.Path(directory).relative_to(root).as_posix() or "."
            findings.append(Finding(relative, 0, "unreadable directory", error.__class__.__name__))
            continue

        relative_directory = pathlib.Path(directory).relative_to(root).as_posix() or "."
        counted_entries = [
            entry
            for entry in entries
            if not (directory == root and entry.name.casefold() == ".git")
        ]
        if len(counted_entries) > MAX_DIRECTORY_ENTRIES:
            findings.append(
                Finding(relative_directory, 0, "oversized directory", f"directories must not exceed {MAX_DIRECTORY_ENTRIES} entries")
            )
        directory_bytes = sum(_regular_entry_size(entry) for entry in counted_entries)
        if directory_bytes > MAX_DIRECTORY_BYTES:
            findings.append(
                Finding(relative_directory, 0, "oversized directory", f"direct file bytes must not exceed {MAX_DIRECTORY_BYTES}")
            )

        for entry in entries:
            path = pathlib.Path(entry.path)
            relative_path = path.relative_to(root)
            relative = relative_path.as_posix()

            # Repository metadata is outside the publication candidate. A
            # nested repository remains an error and is never traversed.
            if directory == root and entry.name.casefold() == ".git":
                continue

            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError as error:
                findings.append(Finding(relative, 0, "unreadable path", error.__class__.__name__))
                continue

            if _is_reparse(stat_result):
                findings.append(Finding(relative, 0, "reparse point", "symlinks and junctions are not allowed"))
                continue
            if stat.S_ISDIR(stat_result.st_mode):
                findings.extend(_scan_relative_path(relative, is_file=False))
                if entry.name.casefold() == ".git":
                    findings.append(Finding(relative, 0, "nested repository", "nested .git metadata is not allowed"))
                elif _is_forbidden_directory(entry.name):
                    findings.append(Finding(relative, 0, "generated directory", "generated output is not a publication input"))
                else:
                    pending.append(path)
                continue
            if not stat.S_ISREG(stat_result.st_mode):
                findings.append(Finding(relative, 0, "special file", "only regular UTF-8 files are allowed"))
                continue
            candidate_files += 1
            candidate_bytes += stat_result.st_size
            findings.extend(_scan_relative_path(relative, is_file=True))
            if entry.name.casefold() == ".git":
                findings.append(Finding(relative, 0, "nested repository", "nested .git metadata is not allowed"))
                continue
            findings.extend(_scan_file(root, path, relative))

    if candidate_files > MAX_CANDIDATE_FILES:
        findings.append(Finding(".", 0, "oversized tree", f"candidate must not exceed {MAX_CANDIDATE_FILES} files"))
    if candidate_bytes > MAX_CANDIDATE_BYTES:
        findings.append(Finding(".", 0, "oversized tree", f"candidate must not exceed {MAX_CANDIDATE_BYTES} bytes"))

    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="candidate repository root")
    args = parser.parse_args(argv)

    findings = scan_tree(args.root)
    for finding in findings:
        print(finding.render())
    if findings:
        print(f"public boundary: {len(findings)} violation(s)")
        return 1
    print("public boundary: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
