#!/usr/bin/env python3
"""Inspect a source catalog or fetch one pinned public Git tree into an explicit cache.

This is a reader's cache, not a Git checkout or a build sandbox. It never runs
source code, changes a catalog pin, repairs an existing tree, or prunes a cache.
The Git executable, OS trust store, DNS and local filesystem must be trusted.
Locks coordinate this tool's processes; hostile concurrent local writers are
outside its security boundary. Use a private cache directory and current Git.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from urllib.parse import urlsplit

from research_index.corpus import CatalogSource, CorpusError, load_catalog


MAX_FILES = 20_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_PROOF_BYTES = 32 * 1024 * 1024
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_STAGE_BYTES = 1024 * 1024 * 1024
MAX_COMMAND_SECONDS = 120
MAX_FETCH_SECONDS = 600
MAX_DEPTH = 64
SHA = re.compile(r"^[0-9a-f]{40}$")
HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
RESERVED = re.compile(r"^(?:con|prn|aux|nul|conin\$|conout\$|clock\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)", re.I)
CACHE_MARKER = {"schema": 1, "kind": "research-source-cache"}


def object_id(kind: str, data: bytes) -> str:
    return hashlib.sha1(f"{kind} {len(data)}\0".encode("ascii") + data).hexdigest()


def checked_path(path: Path, *, directory: bool | None = None) -> os.stat_result:
    """Reject links/reparse points and hardlinked regular files without following them."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ):
        raise CorpusError(f"linked or reparse path is not allowed: {path}")
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            raise CorpusError(f"hardlinked file is not allowed: {path}")
        if directory is True:
            raise CorpusError(f"expected a directory: {path}")
    elif stat.S_ISDIR(info.st_mode):
        if directory is False:
            raise CorpusError(f"expected a regular file: {path}")
    else:
        raise CorpusError(f"unsupported filesystem entry: {path}")
    return info


def checked_ancestors(path: Path) -> Path:
    # Normalize lexically first, then use only the returned absolute path. Do
    # not resolve() before inspection: that would erase linked ancestors.
    absolute = Path(os.path.abspath(path))
    for ancestor in reversed((absolute, *absolute.parents)):
        if os.path.lexists(ancestor):
            checked_path(ancestor, directory=True)
    return absolute


def read_regular(path: Path, limit: int) -> bytes:
    info = checked_path(path, directory=False)
    if info.st_size > limit:
        raise CorpusError(f"file exceeds the {limit}-byte limit: {path}")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise CorpusError(f"file exceeds the {limit}-byte limit: {path}")
    return payload


def strict_json(payload: bytes) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise CorpusError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError) as error:
        raise CorpusError(f"invalid cache JSON: {error}") from error


def same_directory(first: Path, second: Path) -> bool:
    # Even resolved Windows paths can retain different namespace prefixes.
    return first == second or (
        first.exists() and second.exists() and first.samefile(second)
    )


def cache_root(path: Path, corpus: Path, *, create: bool) -> Path:
    # Check the supplied path before resolving; then compare canonical names so
    # Windows short-name aliases cannot bypass corpus or home containment.
    root = checked_ancestors(path).resolve()
    corpus = corpus.resolve()
    if root == Path(root.anchor) or same_directory(root, Path("~").expanduser().resolve()):
        raise CorpusError("choose a dedicated cache directory, not a filesystem or home root")
    if any(same_directory(ancestor, corpus) for ancestor in (root, *root.parents)):
        raise CorpusError("the source cache must be outside the canonical corpus")
    for ancestor in (root, *root.parents):
        if os.path.lexists(ancestor / ".git"):
            raise CorpusError("the source cache must be outside Git working trees")
    if not root.exists():
        if not create:
            return root
        root.mkdir(parents=True, exist_ok=False)
    checked_path(root, directory=True)
    marker = root / "cache.json"
    if not os.path.lexists(marker):
        if not create:
            raise CorpusError(f"cache ownership marker is missing: {marker}")
        if any(root.iterdir()):
            raise CorpusError(f"refusing a nonempty directory that is not a source cache: {root}")
        with marker.open("xb") as stream:
            stream.write(json.dumps(CACHE_MARKER, sort_keys=True).encode("utf-8") + b"\n")
    if strict_json(read_regular(marker, 1024)) != CACHE_MARKER:
        raise CorpusError(f"unrecognized cache ownership marker: {marker}")
    for child in root.iterdir():
        if child.name not in {"cache.json", "sources", "locks", "staging"}:
            raise CorpusError(f"unexpected entry in cache root: {child}")
        checked_path(child, directory=child.name != "cache.json")
    return root


def make_child(parent: Path, name: str) -> Path:
    checked_path(parent, directory=True)
    child = parent / name
    if not os.path.lexists(child):
        child.mkdir()
    checked_path(child, directory=True)
    return child


@contextmanager
def source_lock(root: Path, source_id: str):
    locks = make_child(root, "locks")
    lock = locks / f"{source_id}.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise CorpusError(
            f"source is locked: {lock}; do not remove a lock until its owner has stopped"
        ) from error
    identity = os.fstat(descriptor)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor != -1:
            os.close(descriptor)
        current = checked_path(lock, directory=False)
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise CorpusError(f"lock ownership changed; leaving it untouched: {lock}")
        lock.unlink()


def allowed_url(source: CatalogSource, hosts: list[str]) -> str:
    if source.kind != "git-repository" or source.access != "public":
        raise CorpusError("fetch supports only public git-repository sources")
    if source.revision.kind != "git-commit" or not SHA.fullmatch(source.revision.value):
        raise CorpusError("fetch requires a full lowercase 40-character Git commit")
    allowed: set[str] = set()
    for host in hosts:
        if host != host.lower() or not HOST.fullmatch(host):
            raise CorpusError("--allow-host requires a lowercase DNS hostname, not a URL or IP")
        allowed.add(host)
    if not allowed:
        raise CorpusError("fetch requires an explicit --allow-host HOST")
    url = source.url or ""
    try:
        parsed = urlsplit(url)
        invalid = (
            parsed.scheme != "https" or parsed.username is not None
            or parsed.password is not None or parsed.hostname not in allowed
            or parsed.port is not None or parsed.query or parsed.fragment
            or parsed.path in {"", "/"} or url != url.strip()
            or any(ord(character) < 33 or character in "\\%" for character in url)
        )
        try:
            ipaddress.ip_address(parsed.hostname or "")
            invalid = True
        except ValueError:
            pass
    except ValueError as error:
        raise CorpusError("invalid acquisition URL") from error
    if invalid:
        raise CorpusError("fetch requires plain HTTPS on an explicitly allowed host, without credentials or port")
    return url


def git_environment(private: Path) -> dict[str, str]:
    # Allowlist rather than stripping known GIT_* variables: it also excludes
    # proxy credentials, askpass programs, shell/loader injection and curl config.
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}
    }
    environment.update({
        "HOME": str(private), "USERPROFILE": str(private),
        "XDG_CONFIG_HOME": str(private), "TMPDIR": str(private),
        "TMP": str(private), "TEMP": str(private),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_ALLOW_PROTOCOL": "https", "GIT_PROTOCOL_FROM_USER": "0",
        "LC_ALL": "C", "LANG": "C",
    })
    return environment


def scan_error(error: OSError) -> None:
    raise CorpusError(f"cannot inspect every cache entry: {error}") from error


def tree_bytes(root: Path) -> int:
    total = 0
    for directory, directories, files in os.walk(root, followlinks=False, onerror=scan_error):
        for name in directories + files:
            info = checked_path(Path(directory) / name)
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > MAX_STAGE_BYTES:
                    raise CorpusError("staging exceeded its 1 GiB disk limit")
    return total


class GitReader:
    """Fresh, isolated Git transport and raw-object reader; never a source checkout."""

    def __init__(self, stage: Path):
        executable = shutil.which("git")
        if not executable:
            raise CorpusError("Git is required for fetch")
        self.executable = str(Path(executable).resolve())
        self.stage = stage
        self.private = make_child(stage, "private")
        self.empty = make_child(self.private, "empty")
        self.repository = stage / "objects.git"
        self.environment = git_environment(self.private)
        self.deadline = time.monotonic() + MAX_FETCH_SECONDS
        settings = {
            "credential.helper": "", "credential.interactive": "false",
            "core.askPass": "", "core.hooksPath": str(self.empty),
            "init.templateDir": str(self.empty), "core.attributesFile": os.devnull,
            "core.excludesFile": os.devnull, "http.proxy": "",
            "http.followRedirects": "false", "http.sslVerify": "true",
            "http.authMethod": "basic",
            "http.lowSpeedLimit": "1024", "http.lowSpeedTime": "30",
            "protocol.allow": "never", "protocol.https.allow": "always",
            "fetch.recurseSubmodules": "false", "fetch.fsckObjects": "true",
            "transfer.fsckObjects": "true", "gc.auto": "0",
            "maintenance.auto": "false", "core.protectNTFS": "true",
            "core.protectHFS": "true", "core.longpaths": "true",
        }
        self.options = [piece for key, value in settings.items() for piece in ("-c", f"{key}={value}")]

    def run(self, arguments: list[str], *, data: bytes = b"", limit: int = MAX_PROOF_BYTES) -> bytes:
        if time.monotonic() >= self.deadline:
            raise CorpusError("Git command exceeded its time limit")
        command = [self.executable, "--no-pager", "--no-replace-objects", *self.options, *arguments]
        with tempfile.TemporaryFile(dir=self.private) as incoming, \
                tempfile.TemporaryFile(dir=self.private) as output, \
                tempfile.TemporaryFile(dir=self.private) as errors:
            incoming.write(data)
            incoming.seek(0)
            process = subprocess.Popen(
                command, cwd=self.private, env=self.environment,
                stdin=incoming, stdout=output, stderr=errors,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            deadline = min(self.deadline, time.monotonic() + MAX_COMMAND_SECONDS)
            try:
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise CorpusError("Git command exceeded its time limit")
                    if os.fstat(output.fileno()).st_size > limit or os.fstat(errors.fileno()).st_size > 1024 * 1024:
                        raise CorpusError("Git command exceeded its output limit")
                    tree_bytes(self.stage)
                    time.sleep(0.05)
            except BaseException:
                self.stop_process_tree(process)
                raise
            if os.fstat(output.fileno()).st_size > limit or os.fstat(errors.fileno()).st_size > 1024 * 1024:
                raise CorpusError("Git command exceeded its output limit")
            tree_bytes(self.stage)
            if process.returncode:
                # Do not echo arbitrary transport output or URLs into logs.
                raise CorpusError(f"Git command failed (exit {process.returncode}); source or pin may be unavailable")
            output.seek(0)
            return output.read(limit + 1)

    def stop_process_tree(self, process: subprocess.Popen) -> None:
        if os.name == "nt":
            # Kill descendants before killing their parent so the Windows tree
            # walker can still find git-remote-https and index-pack. Git and the
            # operating system tools are trusted, not adversarial executables.
            system = self.environment.get("SystemRoot", self.environment.get("SYSTEMROOT", ""))
            killer = Path(system) / "System32" / "taskkill.exe"
            try:
                subprocess.run(
                    [str(killer), "/PID", str(process.pid), "/T", "/F"],
                    env=self.environment, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
            finally:
                if process.poll() is None:
                    process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=10)

    def fetch(self, url: str, commit: str) -> None:
        self.run(["init", "--bare", "--object-format=sha1", "--template", str(self.empty), str(self.repository)])
        self.run([
            "--git-dir", str(self.repository), "fetch", "--depth=1", "--no-tags",
            "--no-recurse-submodules", "--no-write-fetch-head", "--", url, commit,
        ], limit=1024 * 1024)

    def objects(self, identities: list[str], kind: str, limit: int) -> dict[str, bytes]:
        result = self.run(
            ["--git-dir", str(self.repository), "cat-file", "--batch"],
            data="".join(identity + "\n" for identity in identities).encode("ascii"), limit=limit,
        )
        values: dict[str, bytes] = {}
        offset = 0
        for identity in identities:
            end = result.find(b"\n", offset)
            fields = result[offset:end].split(b" ") if end >= 0 else []
            if len(fields) != 3 or fields[:2] != [identity.encode("ascii"), kind.encode("ascii")] or not fields[2].isdigit():
                raise CorpusError(f"missing or invalid Git {kind} object")
            size = int(fields[2])
            start = end + 1
            body = result[start:start + size]
            offset = start + size + 1
            if len(body) != size or result[offset - 1:offset] != b"\n" or object_id(kind, body) != identity:
                raise CorpusError(f"Git {kind} object failed its identity check")
            values[identity] = body
        if offset != len(result):
            raise CorpusError("unexpected trailing Git object output")
        return values

    def sizes(self, identities: list[str]) -> dict[str, int]:
        result = self.run(
            ["--git-dir", str(self.repository), "cat-file", "--batch-check"],
            data="".join(identity + "\n" for identity in identities).encode("ascii"),
            limit=MAX_FILES * 100,
        )
        lines = result.splitlines()
        if len(lines) != len(identities):
            raise CorpusError("incomplete Git blob size response")
        sizes: dict[str, int] = {}
        for identity, line in zip(identities, lines):
            fields = line.split(b" ")
            if len(fields) != 3 or fields[:2] != [identity.encode("ascii"), b"blob"] or not fields[2].isdigit():
                raise CorpusError("missing or invalid Git blob")
            sizes[identity] = int(fields[2])
            if sizes[identity] > MAX_FILE_BYTES:
                raise CorpusError("source file exceeds the 64 MiB limit")
        return sizes


def path_component(raw: bytes) -> str:
    try:
        name = raw.decode("utf-8")
    except UnicodeError as error:
        raise CorpusError("source paths must be valid UTF-8") from error
    if (
        not name or name in {".", ".."} or name.casefold() == ".git"
        or name[-1] in ". " or RESERVED.match(name)
        or any(ord(character) < 32 or ord(character) == 127 or character in '/\\:<>"|?*~' for character in name)
        or len(name.encode("utf-16-le")) > 480
    ):
        raise CorpusError(f"unsupported or unsafe source path component: {name!r}")
    return name


def tree_entries(payload: bytes) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    offset = 0
    while offset < len(payload):
        space = payload.find(b" ", offset)
        end = payload.find(b"\0", space + 1)
        if space < 0 or end < 0 or end + 21 > len(payload):
            raise CorpusError("invalid Git tree object")
        mode = payload[offset:space].decode("ascii", errors="replace")
        if mode not in {"40000", "100644", "100755"}:
            raise CorpusError("source contains an unsupported tree entry (symlinks and gitlinks are not fetched)")
        entries.append((mode, path_component(payload[space + 1:end]), payload[end + 1:end + 21].hex()))
        offset = end + 21
    return entries


def root_tree(commit: bytes) -> str:
    first = commit.split(b"\n", 1)[0]
    if len(first) != 45 or not first.startswith(b"tree "):
        raise CorpusError("commit lacks a valid root tree")
    identity = first[5:].decode("ascii", errors="replace")
    if not SHA.fullmatch(identity):
        raise CorpusError("commit lacks a valid root tree")
    return identity


def expected_tree(root: str, trees: dict[str, bytes]) -> tuple[dict[str, str], set[str]]:
    files: dict[str, str] = {}
    directories: set[str] = set()
    occupied: set[str] = set()
    used: set[str] = set()
    pending = [("", root, 0)]
    while pending:
        prefix, identity, depth = pending.pop()
        if depth > MAX_DEPTH or len(files) + len(directories) > MAX_FILES:
            raise CorpusError("source exceeds the file count or directory depth limit")
        payload = trees.get(identity)
        if payload is None or object_id("tree", payload) != identity:
            raise CorpusError("tree proof does not match the pinned commit")
        used.add(identity)
        for mode, name, child in tree_entries(payload):
            relative = f"{prefix}/{name}" if prefix else name
            if len(relative.encode("utf-8")) > 2048:
                raise CorpusError("source path exceeds the path length limit")
            canonical = unicodedata.normalize("NFC", relative).casefold()
            if canonical in occupied:
                raise CorpusError(f"source contains duplicate or case-colliding paths: {relative}")
            occupied.add(canonical)
            if mode == "40000":
                directories.add(relative)
                pending.append((relative, child, depth + 1))
            else:
                files[relative] = child
    if len(files) + len(directories) > MAX_FILES or set(trees) != used:
        raise CorpusError("source exceeds its file count limit or has unused tree proof")
    return files, directories


def proof_tree(proof: object, source: CatalogSource) -> tuple[dict[str, str], set[str]]:
    if not isinstance(proof, dict) or set(proof) != {"schema", "source_id", "url", "commit", "commit_object", "trees"}:
        raise CorpusError("invalid snapshot proof fields")
    if (
        type(proof["schema"]) is not int or proof["schema"] != 1
        or proof["source_id"] != source.id or proof["url"] != source.url
        or proof["commit"] != source.revision.value or not isinstance(proof["trees"], dict)
    ):
        raise CorpusError("snapshot proof belongs to a different source or revision")
    try:
        commit = base64.b64decode(proof["commit_object"], validate=True)
        trees = {
            identity: base64.b64decode(value, validate=True)
            for identity, value in proof["trees"].items()
            if isinstance(identity, str) and SHA.fullmatch(identity)
        }
    except (ValueError, TypeError) as error:
        raise CorpusError("invalid raw object encoding in snapshot proof") from error
    if len(trees) != len(proof["trees"]) or object_id("commit", commit) != source.revision.value:
        raise CorpusError("snapshot proof does not match the pinned commit")
    if sum(map(len, trees.values())) > MAX_TREE_BYTES:
        raise CorpusError("tree proof exceeds its size limit")
    return expected_tree(root_tree(commit), trees)


def verify_snapshot(snapshot: Path, source: CatalogSource) -> Path:
    checked_ancestors(snapshot)
    checked_path(snapshot, directory=True)
    if {path.name for path in snapshot.iterdir()} != {"proof.json", "tree"}:
        raise CorpusError(f"snapshot has missing or extra top-level entries: {snapshot}")
    files, directories = proof_tree(strict_json(read_regular(snapshot / "proof.json", MAX_PROOF_BYTES)), source)
    tree = snapshot / "tree"
    checked_path(tree, directory=True)
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    total = 0
    for directory, children, names in os.walk(tree, followlinks=False, onerror=scan_error):
        base = Path(directory)
        for name in children:
            child = base / name
            checked_path(child, directory=True)
            relative = child.relative_to(tree).as_posix()
            if relative not in directories:
                raise CorpusError(f"snapshot has an extra directory: {relative}")
            actual_directories.add(relative)
        for name in names:
            child = base / name
            relative = child.relative_to(tree).as_posix()
            if relative not in files:
                raise CorpusError(f"snapshot has an extra file: {relative}")
            info = checked_path(child, directory=False)
            if info.st_size > MAX_FILE_BYTES:
                raise CorpusError(f"snapshot file exceeds its size limit: {relative}")
            total += info.st_size
            if total > MAX_TOTAL_BYTES:
                raise CorpusError("snapshot exceeds its total size limit")
            digest = hashlib.sha1(f"blob {info.st_size}\0".encode("ascii"))
            count = 0
            with child.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    count += len(chunk)
                    if count > MAX_FILE_BYTES:
                        raise CorpusError("snapshot file grew beyond its size limit")
                    digest.update(chunk)
            if count != info.st_size or digest.hexdigest() != files[relative]:
                raise CorpusError(f"snapshot bytes do not match the pinned commit: {relative}")
            actual_files.add(relative)
    if actual_files != set(files) or actual_directories != directories:
        raise CorpusError("snapshot has missing files or directories")
    return tree


def write_snapshot(reader: GitReader, source: CatalogSource, snapshot: Path) -> None:
    commit_id = source.revision.value
    commit = reader.objects([commit_id], "commit", MAX_PROOF_BYTES)[commit_id]
    trees: dict[str, bytes] = {}
    pending = {root_tree(commit)}
    tree_size = 0
    while pending:
        batch = sorted(pending)[:128]
        pending.difference_update(batch)
        acquired = reader.objects(batch, "tree", MAX_TREE_BYTES)
        trees.update(acquired)
        for payload in acquired.values():
            tree_size += len(payload)
            if tree_size > MAX_TREE_BYTES or len(trees) > MAX_FILES:
                raise CorpusError("source exceeds its tree proof limit")
            for mode, _, identity in tree_entries(payload):
                if mode == "40000" and identity not in trees:
                    pending.add(identity)
    files, directories = expected_tree(root_tree(commit), trees)
    identities = sorted(set(files.values()))
    sizes = reader.sizes(identities)
    if sum(sizes[identity] for identity in files.values()) > MAX_TOTAL_BYTES:
        raise CorpusError("source exceeds its 512 MiB total file limit")
    snapshot.mkdir()
    tree = make_child(snapshot, "tree")
    for relative in sorted(directories, key=lambda value: (value.count("/"), value)):
        (tree / relative).mkdir()
    paths_by_blob: dict[str, list[str]] = {}
    for relative, identity in files.items():
        paths_by_blob.setdefault(identity, []).append(relative)
    offset = 0
    while offset < len(identities):
        batch: list[str] = []
        size = 0
        while offset < len(identities) and (not batch or size + sizes[identities[offset]] <= 8 * 1024 * 1024):
            identity = identities[offset]
            batch.append(identity)
            size += sizes[identity]
            offset += 1
        blobs = reader.objects(batch, "blob", size + len(batch) * 100)
        for identity, payload in blobs.items():
            if len(payload) != sizes[identity]:
                raise CorpusError("Git blob size changed during acquisition")
            for relative in paths_by_blob[identity]:
                with (tree / relative).open("xb") as stream:
                    stream.write(payload)
    proof = {
        "schema": 1, "source_id": source.id, "url": source.url,
        "commit": commit_id, "commit_object": base64.b64encode(commit).decode("ascii"),
        "trees": {identity: base64.b64encode(payload).decode("ascii") for identity, payload in sorted(trees.items())},
    }
    payload = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > MAX_PROOF_BYTES:
        raise CorpusError("snapshot proof exceeds its size limit")
    with (snapshot / "proof.json").open("xb") as stream:
        stream.write(payload)
    verify_snapshot(snapshot, source)


def snapshot_path(root: Path, source: CatalogSource) -> Path:
    return root / "sources" / source.id / source.revision.value


def fetch(source: CatalogSource, root: Path, hosts: list[str]) -> Path:
    url = allowed_url(source, hosts)
    with source_lock(root, source.id):
        destination = snapshot_path(root, source)
        checked_ancestors(destination)
        if os.path.lexists(destination):
            return verify_snapshot(destination, source)
        sources = make_child(root, "sources")
        owner = make_child(sources, source.id)
        staging = make_child(root, "staging")
        stage = Path(tempfile.mkdtemp(prefix=f"{source.id}-", dir=staging))
        try:
            reader = GitReader(stage)
            reader.fetch(url, source.revision.value)
            snapshot = stage / "snapshot"
            write_snapshot(reader, source, snapshot)
            checked_path(owner, directory=True)
            if os.path.lexists(destination):
                raise CorpusError("snapshot destination appeared during fetch; refusing to overwrite it")
            # Cooperating writers hold the same exclusive source lock. A hostile
            # writer racing this check is outside the trusted-local-filesystem contract.
            snapshot.rename(destination)
            result = verify_snapshot(destination, source)
            # Only delete this invocation's newly allocated, verified staging tree.
            try:
                checked_ancestors(stage)
                tree_bytes(stage)
                if os.name == "nt":
                    # Git object files are read-only on Windows. Only this
                    # invocation's verified, single-link staging files change.
                    for directory, _, names in os.walk(stage, followlinks=False, onerror=scan_error):
                        for name in names:
                            path = Path(directory) / name
                            info = checked_path(path, directory=False)
                            path.chmod(info.st_mode | stat.S_IWRITE)
                shutil.rmtree(stage)
            except (CorpusError, OSError):
                print(f"snapshot verified; temporary acquisition data retained at {stage}", file=sys.stderr)
            return result
        except BaseException as error:
            raise CorpusError(f"fetch did not complete: {error}; staging retained at {stage}") from error


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=__doc__,
        epilog="Limits: 20,000 files/directories; 64 MiB per file; 512 MiB source bytes; "
        "1 GiB staged data (sampled during Git execution); 120 seconds per Git command, "
        "600 seconds per Git session. Symlinks and submodules are unsupported. "
        "Files retain blob bytes, not executable permissions. Failed stages are retained.",
    )
    result.add_argument("--corpus", required=True, type=Path, help="canonical corpus containing catalog/*.json")
    result.add_argument("--cache-root", type=Path, help="dedicated external cache, outside the corpus and Git worktrees")
    result.add_argument("--allow-host", action="append", default=[], metavar="HOST", help="explicit public HTTPS acquisition host; repeat as needed")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list catalog identities without network or cache access")
    commands.add_parser("verify", help="validate catalog metadata only; does not verify downloaded bytes")
    status = commands.add_parser("status", help="verify local snapshot bytes only; never contacts an upstream")
    status.add_argument("source_id", nargs="?")
    download = commands.add_parser("fetch", help="download one public pinned Git tree, or verify its existing bytes")
    download.add_argument("source_id")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        catalog = load_catalog(arguments.corpus)
        if arguments.command == "verify":
            print(f"verified {len(catalog)} source manifest(s); local bytes were not inspected")
            return 0
        if arguments.command == "list":
            for source in catalog.values():
                print(f"{source.id}\t{source.kind}\t{source.revision.value}\t{source.name}")
            return 0
        if arguments.cache_root is None:
            raise CorpusError("status and fetch require an explicit --cache-root")
        source_id = arguments.source_id
        if source_id is not None and source_id not in catalog:
            raise CorpusError(f"unknown source id: {source_id}")
        if arguments.command == "fetch":
            source = catalog[source_id]
            allowed_url(source, arguments.allow_host)
            root = cache_root(arguments.cache_root, arguments.corpus, create=True)
            print(fetch(source, root, arguments.allow_host))
            return 0
        root = cache_root(arguments.cache_root, arguments.corpus, create=False)
        failed = False
        for source in ([catalog[source_id]] if source_id else catalog.values()):
            if source.kind != "git-repository":
                print(f"not-fetchable\t{source.id}\tthis command supports Git source trees only")
                continue
            snapshot = snapshot_path(root, source)
            try:
                checked_ancestors(snapshot)
                if not os.path.lexists(snapshot):
                    print(f"missing\t{source.id}")
                else:
                    print(f"verified\t{source.id}\t{verify_snapshot(snapshot, source)}")
            except (CorpusError, OSError) as error:
                print(f"invalid\t{source.id}\t{error}")
                failed = True
        return 1 if failed else 0
    except (CorpusError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
