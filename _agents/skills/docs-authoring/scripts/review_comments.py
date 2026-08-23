#!/usr/bin/env python3
"""Validate and update the public agent-docs review-comment store."""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import json
import os
import pathlib
import re
import stat
import sys
import tempfile
import time
import unicodedata
from collections.abc import Callable
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl


SCHEMA_VERSION = 1
DEFAULT_REVIEW_DATA = ".agent-docs/review-comments.json"
OUTPUT_SENTINEL_NAME = ".agent-docs-output"
OUTPUT_SENTINEL_VALUE = b"agent-docs-output-v1\n"
LOCK_HEADER = b"agent-docs-review-lock-v1\n"
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
MAX_REQUEST_BYTES = 16 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_COMMENTS = 1000
MAX_ROUTE_UNITS = 512
MAX_ANCHOR_UNITS = 256
MAX_QUOTE_UNITS = 2000
MAX_BODY_UNITS = 8000
MAX_REPLY_UNITS = 8000

ID_PATTERN = re.compile(r"^rc_[0-9a-f]{32}$")
TIMESTAMP_PATTERN = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"\.(?P<fraction>[0-9]{7})Z$"
)
STATUSES = ("open", "answered", "resolved")
ROOT_FIELDS = frozenset({"schemaVersion", "comments"})
REQUIRED_COMMENT_FIELDS = frozenset(
    {"id", "route", "body", "status", "createdAt", "updatedAt"}
)
OPTIONAL_COMMENT_FIELDS = frozenset({"anchor", "quote", "reply"})
COMMENT_FIELD_ORDER = (
    "id",
    "route",
    "anchor",
    "quote",
    "body",
    "status",
    "reply",
    "createdAt",
    "updatedAt",
)


class ReviewCommentError(ValueError):
    """A review store or requested transition is invalid."""


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ReviewCommentError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _utf16_units(value: str, *, label: str) -> int:
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as error:
        raise ReviewCommentError(f"{label} contains an unpaired surrogate") from error


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ReviewCommentError(f"{label} must be a string")
    return value


def _has_forbidden_text_control(value: str) -> bool:
    return any(
        unicodedata.category(character) == "Cc" and character not in "\r\n\t"
        for character in value
    )


def _validate_text(value: Any, *, label: str, maximum: int, trimmed: bool = False) -> str:
    text = _require_string(value, label=label)
    if not text.strip():
        raise ReviewCommentError(f"{label} must not be blank")
    if trimmed and text != text.strip():
        raise ReviewCommentError(f"{label} must be trimmed")
    if _utf16_units(text, label=label) > maximum:
        raise ReviewCommentError(f"{label} exceeds {maximum} UTF-16 characters")
    if _has_forbidden_text_control(text):
        raise ReviewCommentError(f"{label} contains a forbidden control character")
    return text


def _validate_route(value: Any, *, label: str) -> str:
    route = _require_string(value, label=label)
    units = _utf16_units(route, label=label)
    if not 1 <= units <= MAX_ROUTE_UNITS:
        raise ReviewCommentError(f"{label} must contain 1..{MAX_ROUTE_UNITS} UTF-16 characters")
    if route != route.strip() or not route.startswith("/") or "//" in route:
        raise ReviewCommentError(f"{label} must be a trimmed absolute site path")
    if any(character in route for character in ("\\", "?", "#")):
        raise ReviewCommentError(f"{label} must not contain a backslash, query, or fragment")
    if any(character.isspace() or unicodedata.category(character) == "Cc" for character in route):
        raise ReviewCommentError(f"{label} must not contain whitespace or control characters")
    if len(route) > 1 and route.endswith("/"):
        raise ReviewCommentError(f"{label} must not have a trailing slash")
    if any(segment in (".", "..") for segment in route.split("/")):
        raise ReviewCommentError(f"{label} must not contain dot path segments")
    return route


def _validate_anchor(value: Any, *, label: str) -> str:
    anchor = _require_string(value, label=label)
    units = _utf16_units(anchor, label=label)
    if not 1 <= units <= MAX_ANCHOR_UNITS:
        raise ReviewCommentError(f"{label} must contain 1..{MAX_ANCHOR_UNITS} UTF-16 characters")
    if anchor != anchor.strip() or "#" in anchor:
        raise ReviewCommentError(f"{label} must be trimmed and must not contain '#'")
    if any(character.isspace() or unicodedata.category(character) == "Cc" for character in anchor):
        raise ReviewCommentError(f"{label} must not contain whitespace or control characters")
    return anchor


def _validate_timestamp(value: Any, *, label: str) -> str:
    timestamp = _require_string(value, label=label)
    match = TIMESTAMP_PATTERN.fullmatch(timestamp)
    if match is None:
        raise ReviewCommentError(
            f"{label} must use UTC yyyy-MM-ddTHH:mm:ss.fffffffZ format"
        )
    try:
        dt.datetime.strptime(
            f"{match.group('date')}.{match.group('fraction')[:6]}Z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
        )
    except ValueError as error:
        raise ReviewCommentError(f"{label} is not a valid UTC timestamp") from error
    return timestamp


def validate_comment(value: Any, *, index: int) -> dict[str, Any]:
    label = f"comments[{index}]"
    if not isinstance(value, dict):
        raise ReviewCommentError(f"{label} must be an object")
    fields = set(value)
    allowed = REQUIRED_COMMENT_FIELDS | OPTIONAL_COMMENT_FIELDS
    missing = sorted(REQUIRED_COMMENT_FIELDS - fields)
    unknown = sorted(fields - allowed)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ReviewCommentError(f"{label} has invalid fields ({'; '.join(details)})")

    identifier = _require_string(value["id"], label=f"{label}.id")
    if ID_PATTERN.fullmatch(identifier) is None:
        raise ReviewCommentError(f"{label}.id must be 'rc_' followed by 32 lowercase hex digits")
    _validate_route(value["route"], label=f"{label}.route")
    if "anchor" in value:
        _validate_anchor(value["anchor"], label=f"{label}.anchor")
    if "quote" in value:
        _validate_text(value["quote"], label=f"{label}.quote", maximum=MAX_QUOTE_UNITS)
    _validate_text(value["body"], label=f"{label}.body", maximum=MAX_BODY_UNITS, trimmed=True)
    status_value = value["status"]
    if status_value not in STATUSES:
        raise ReviewCommentError(f"{label}.status must be one of {', '.join(STATUSES)}")
    if "reply" in value:
        _validate_text(
            value["reply"], label=f"{label}.reply", maximum=MAX_REPLY_UNITS, trimmed=True
        )
    if status_value in ("answered", "resolved") and "reply" not in value:
        raise ReviewCommentError(
            f"{label}.reply is required when status is answered or resolved"
        )
    created = _validate_timestamp(value["createdAt"], label=f"{label}.createdAt")
    updated = _validate_timestamp(value["updatedAt"], label=f"{label}.updatedAt")
    if updated < created:
        raise ReviewCommentError(f"{label}.updatedAt must not precede createdAt")
    return value


def validate_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewCommentError("review data must be an object")
    fields = set(value)
    if fields != ROOT_FIELDS:
        missing = sorted(ROOT_FIELDS - fields)
        unknown = sorted(fields - ROOT_FIELDS)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ReviewCommentError(f"review data has invalid fields ({'; '.join(details)})")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != SCHEMA_VERSION:
        raise ReviewCommentError(f"schemaVersion must be integer {SCHEMA_VERSION}")
    comments = value["comments"]
    if not isinstance(comments, list):
        raise ReviewCommentError("comments must be an array")
    if len(comments) > MAX_COMMENTS:
        raise ReviewCommentError(f"comments exceeds the {MAX_COMMENTS}-record limit")
    seen: set[str] = set()
    for index, comment in enumerate(comments):
        validated = validate_comment(comment, index=index)
        identifier = validated["id"]
        if identifier in seen:
            raise ReviewCommentError(f"duplicate comment id: {identifier}")
        seen.add(identifier)
    return value


def _is_reparse(path: pathlib.Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _reject_reparse_chain(path: pathlib.Path, *, label: str) -> None:
    current = pathlib.Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if os.path.lexists(current) and _is_reparse(current):
            raise ReviewCommentError(f"{label} crosses a symlink or reparse point: {current}")


def _within(root: pathlib.Path, candidate: pathlib.Path) -> bool:
    try:
        return os.path.commonpath((os.path.normcase(root), os.path.normcase(candidate))) == os.path.normcase(root)
    except ValueError:
        return False


def resolve_review_data(repo_root: str, review_data: str) -> tuple[pathlib.Path, pathlib.Path]:
    repo = pathlib.Path(os.path.abspath(repo_root))
    if not repo.is_dir():
        raise ReviewCommentError(f"repository root is not a directory: {repo_root}")
    if repo.parent == repo:
        raise ReviewCommentError("repository root must not be a filesystem root")
    _reject_reparse_chain(repo, label="repository root")
    if not review_data or review_data != review_data.strip() or "\0" in review_data:
        raise ReviewCommentError("review data path must be a trimmed nonempty path")
    requested = pathlib.Path(review_data)
    candidate = requested if requested.is_absolute() else repo / requested
    target = pathlib.Path(os.path.abspath(candidate))
    if target == repo or not _within(repo, target):
        raise ReviewCommentError("review data path must remain inside the repository")
    if target.is_dir():
        raise ReviewCommentError("review data path must be a file, not a directory")
    reserved = repo / ".agent-docs"
    if target == reserved or not _within(reserved, target):
        raise ReviewCommentError("review data path must be a file under .agent-docs")

    relative = pathlib.Path(os.path.relpath(target, repo))
    current = repo
    for part in relative.parts:
        current /= part
        if not os.path.lexists(current):
            continue
        if _is_reparse(current):
            raise ReviewCommentError(f"review data path crosses a symlink or reparse point: {current}")

    ancestor = target.parent
    while True:
        sentinel = ancestor / OUTPUT_SENTINEL_NAME
        if os.path.lexists(sentinel):
            if _is_reparse(sentinel):
                raise ReviewCommentError("generated-output sentinel must not be a symlink or reparse point")
            if sentinel.is_file():
                try:
                    marker = (
                        sentinel.read_bytes()
                        if sentinel.stat().st_size == len(OUTPUT_SENTINEL_VALUE)
                        else b""
                    )
                except OSError as error:
                    raise ReviewCommentError(f"cannot inspect generated-output sentinel: {error}") from error
                if marker == OUTPUT_SENTINEL_VALUE:
                    raise ReviewCommentError("review data path must not be inside generated output")
        if ancestor == repo:
            break
        ancestor = ancestor.parent
    return repo, target


def _read_bytes(path: pathlib.Path) -> bytes:
    try:
        info = path.lstat()
    except OSError as error:
        raise ReviewCommentError(f"cannot inspect review data: {error}") from error
    if _is_reparse(path) or not stat.S_ISREG(info.st_mode):
        raise ReviewCommentError("review data must be a regular file, not a symlink or reparse point")
    if info.st_size > MAX_FILE_BYTES:
        raise ReviewCommentError(f"review data exceeds the {MAX_FILE_BYTES}-byte limit")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ReviewCommentError(f"cannot read review data: {error}") from error
    if len(data) > MAX_FILE_BYTES:
        raise ReviewCommentError(f"review data exceeds the {MAX_FILE_BYTES}-byte limit")
    return data


def load_document(path: pathlib.Path) -> tuple[dict[str, Any], bytes]:
    data = _read_bytes(path)
    try:
        text = data.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_json_object)
    except ReviewCommentError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise ReviewCommentError(f"review data is not strict UTF-8 JSON: {error}") from error
    return validate_document(value), data


def _canonical_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {field: comment[field] for field in COMMENT_FIELD_ORDER if field in comment}


def _canonical_document(value: dict[str, Any]) -> dict[str, Any]:
    comments = [_canonical_comment(comment) for comment in value["comments"]]
    return {"schemaVersion": SCHEMA_VERSION, "comments": comments}


def encode_document(value: dict[str, Any]) -> bytes:
    validate_document(value)
    rendered = json.dumps(
        _canonical_document(value), ensure_ascii=False, indent=2, separators=(",", ": ")
    ) + "\n"
    data = rendered.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ReviewCommentError(f"updated review data exceeds the {MAX_FILE_BYTES}-byte limit")
    return data


def atomic_write(
    repo: pathlib.Path,
    path: pathlib.Path,
    *,
    expected: bytes,
    document: dict[str, Any],
) -> None:
    data = encode_document(document)
    resolve_review_data(str(repo), str(path))
    if _read_bytes(path) != expected:
        raise ReviewCommentError("review data changed during the update; reload and retry")
    mode = stat.S_IMODE(path.lstat().st_mode)
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_name, mode)
        if _read_bytes(path) != expected:
            raise ReviewCommentError("review data changed during the update; reload and retry")
        resolve_review_data(str(repo), str(path))
        os.replace(temporary_name, path)
        temporary_name = None
        if hasattr(os, "O_DIRECTORY"):
            try:
                parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(parent_descriptor)
                finally:
                    os.close(parent_descriptor)
            except OSError:
                pass
    except ReviewCommentError:
        raise
    except OSError as error:
        raise ReviewCommentError(f"cannot atomically update review data: {error}") from error
    finally:
        if temporary_name is not None:
            try:
                pathlib.Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def utc_now_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"


def next_updated_timestamp(comment: dict[str, Any]) -> str:
    return max(utc_now_timestamp(), comment["createdAt"], comment["updatedAt"])


def _validate_request_size(value: dict[str, Any]) -> None:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_REQUEST_BYTES:
        raise ReviewCommentError(f"mutation request exceeds the {MAX_REQUEST_BYTES}-byte limit")


def _find_comment(document: dict[str, Any], identifier: str) -> dict[str, Any]:
    if ID_PATTERN.fullmatch(identifier) is None:
        raise ReviewCommentError("comment id must be 'rc_' followed by 32 lowercase hex digits")
    for comment in document["comments"]:
        if comment["id"] == identifier:
            return comment
    raise ReviewCommentError(f"comment not found: {identifier}")


def _render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


class ReviewDataLock:
    def __init__(
        self,
        repo: pathlib.Path,
        data_path: pathlib.Path,
        path: pathlib.Path,
        descriptor: int,
    ):
        self.repo = repo
        self.data_path = data_path
        self.path = path
        self.descriptor = descriptor

    def __enter__(self) -> "ReviewDataLock":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        release_error: OSError | None = None
        try:
            _unlock_descriptor(self.descriptor)
        except OSError as error:
            release_error = error
        finally:
            os.close(self.descriptor)
            self.descriptor = -1
        if release_error is not None and _type is None:
            raise ReviewCommentError(
                f"cannot release review data lock: {release_error}"
            ) from release_error


def _lock_path(data_path: pathlib.Path) -> pathlib.Path:
    return data_path.with_name(f".{data_path.name}.lock")


def _try_lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _initialize_lock_file(descriptor: int, *, created: bool) -> None:
    size = os.fstat(descriptor).st_size
    os.lseek(descriptor, 0, os.SEEK_SET)
    if size == 0:
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, LOCK_HEADER)
        os.fsync(descriptor)
    else:
        if size != len(LOCK_HEADER):
            raise ReviewCommentError("review data lock has invalid content")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.read(descriptor, len(LOCK_HEADER)) != LOCK_HEADER:
            raise ReviewCommentError("review data lock has invalid content")
    if created and os.name != "nt":
        os.chmod(descriptor, 0o600)


def acquire_review_data_lock(
    repo: pathlib.Path,
    data_path: pathlib.Path,
    *,
    timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> ReviewDataLock:
    if timeout_seconds < 0:
        raise ReviewCommentError("lock timeout must not be negative")
    lock_path = _lock_path(data_path)
    deadline = time.monotonic() + timeout_seconds
    while True:
        resolve_review_data(str(repo), str(data_path))
        if os.path.lexists(lock_path) and _is_reparse(lock_path):
            raise ReviewCommentError("review data lock must not be a symlink or reparse point")
        created = False
        try:
            descriptor = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            created = True
        except FileExistsError:
            try:
                descriptor = os.open(
                    lock_path, os.O_RDWR | getattr(os, "O_BINARY", 0)
                )
            except OSError as error:
                raise ReviewCommentError(f"cannot open review data lock: {error}") from error
        except OSError as error:
            raise ReviewCommentError(f"cannot acquire review data lock: {error}") from error
        try:
            opened = os.fstat(descriptor)
            current = lock_path.lstat()
            if _is_reparse(lock_path) or not stat.S_ISREG(opened.st_mode):
                raise ReviewCommentError("review data lock must be a regular non-reparse file")
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ReviewCommentError("review data lock changed while opening")
            _try_lock_descriptor(descriptor)
        except OSError as error:
            os.close(descriptor)
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ReviewCommentError(f"cannot lock review data: {error}") from error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReviewCommentError("timed out waiting for the review data lock")
            time.sleep(min(LOCK_POLL_SECONDS, remaining))
            continue
        except ReviewCommentError:
            os.close(descriptor)
            raise
        try:
            _initialize_lock_file(descriptor, created=created)
            resolve_review_data(str(repo), str(data_path))
        except Exception:
            try:
                _unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)
            raise
        return ReviewDataLock(repo, data_path, lock_path, descriptor)


def _mutate(
    repo: pathlib.Path,
    path: pathlib.Path,
    operation: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    with acquire_review_data_lock(repo, path):
        document, original = load_document(path)
        operation(document)
        atomic_write(repo, path, expected=original, document=document)
        return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, inspect, reply to, and transition saved documentation review comments."
    )
    parser.add_argument("--repo-root", default=".", help="repository root (default: current directory)")
    parser.add_argument(
        "--review-data",
        default=DEFAULT_REVIEW_DATA,
        help=f"JSON path under .agent-docs (default: {DEFAULT_REVIEW_DATA})",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="validate the complete store")
    listing = commands.add_parser("list", help="list comments as stable JSON")
    listing.add_argument("--status", choices=("all",) + STATUSES, default="all")
    showing = commands.add_parser("show", help="show one comment as JSON")
    showing.add_argument("id")
    replying = commands.add_parser("reply", help="store a reply and mark answered by default")
    replying.add_argument("id")
    replying.add_argument("--reply", required=True, help="reply text")
    replying.add_argument(
        "--keep-open",
        action="store_true",
        help="keep a blocked comment open after recording the reply",
    )
    resolving = commands.add_parser("resolve", help="resolve a handled comment with a saved reply")
    resolving.add_argument("id")
    reopening = commands.add_parser("reopen", help="mark a comment open while preserving its reply")
    reopening.add_argument("id")
    return parser


def run(args: argparse.Namespace) -> str:
    repo, path = resolve_review_data(args.repo_root, args.review_data)
    if args.command == "validate":
        document, _data = load_document(path)
        return f"review comments: {len(document['comments'])} comment(s), valid\n"
    if args.command == "list":
        document, _data = load_document(path)
        comments = document["comments"]
        if args.status != "all":
            comments = [comment for comment in comments if comment["status"] == args.status]
        ordered = sorted(comments, key=lambda item: (item["createdAt"], item["id"]))
        return _render_json([_canonical_comment(comment) for comment in ordered])
    if args.command == "show":
        document, _data = load_document(path)
        return _render_json(_canonical_comment(_find_comment(document, args.id)))

    result: dict[str, Any] = {}

    def change(document: dict[str, Any]) -> None:
        comment = _find_comment(document, args.id)
        if args.command == "reply":
            if comment["status"] == "resolved":
                raise ReviewCommentError("resolved comments must be reopened before replying")
            reply = _validate_text(
                args.reply, label="reply", maximum=MAX_REPLY_UNITS, trimmed=True
            )
            status_value = "open" if args.keep_open else "answered"
            request = {"reply": reply}
            if args.keep_open:
                request["status"] = status_value
            _validate_request_size(request)
            comment["reply"] = reply
            comment["status"] = status_value
        elif args.command == "resolve":
            if "reply" not in comment:
                raise ReviewCommentError(
                    "resolve requires a saved reply; reply after handling the documentation first"
                )
            _validate_request_size({"status": "resolved"})
            comment["status"] = "resolved"
        elif args.command == "reopen":
            _validate_request_size({"status": "open"})
            comment["status"] = "open"
        else:  # pragma: no cover - argparse owns the command set
            raise ReviewCommentError(f"unsupported command: {args.command}")
        comment["updatedAt"] = next_updated_timestamp(comment)
        result.update(comment)

    _mutate(repo, path, change)
    return _render_json(_canonical_comment(result))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        output = run(parser.parse_args(argv))
    except ReviewCommentError as error:
        print(f"review comments error: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
