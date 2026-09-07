from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .corpus import (
    AXES,
    RELATION_TYPES,
    Corpus,
    CorpusError,
    assert_no_redirecting_ancestors,
    assert_plain_contained_path,
    load_corpus,
    record_as_ir,
    stable_json,
)


INDEX_FORMAT = "research-index/v3"
INDEX_SCHEMA_VERSION = 3
EXTRACTOR_VERSION = 2
RANKER_VERSION = 1
LOGICAL_ARTIFACTS = (
    "records.jsonl",
    "sources.jsonl",
    "relations.jsonl",
    "taxonomy.json",
)
HASHED_ARTIFACTS = (*LOGICAL_ARTIFACTS, "search.sqlite3")
INSTALL_ID_RE = re.compile(r"^[0-9a-f]{20}(?:-repair-[0-9a-f]{16})?$")
SHARING_RETRY_ATTEMPTS = 40
SHARING_RETRY_SECONDS = 0.025


def _compute_implementation_hash() -> str:
    package = Path(__file__).resolve().parent
    files = [package.parent / "research.py", *package.glob("*.py")]
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


IMPLEMENTATION_HASH = _compute_implementation_hash()


def implementation_hash() -> str:
    return IMPLEMENTATION_HASH


def read_only_sqlite_uri(path: Path) -> str:
    """Return a URI whose path metacharacters cannot change SQLite URI options."""

    return f"{path.resolve().as_uri()}?mode=ro"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _database_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "artifact_hashes"}


def _verify_artifact_hashes(snapshot: Path, manifest: dict[str, Any]) -> None:
    hashes = manifest.get("artifact_hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(HASHED_ARTIFACTS):
        raise CorpusError(f"{snapshot}: manifest has invalid artifact hashes")
    for name in HASHED_ARTIFACTS:
        expected = hashes[name]
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise CorpusError(f"{snapshot}: invalid artifact hash for {name}")
        path = snapshot / name
        try:
            actual = _file_hash(path)
        except OSError as exc:
            raise CorpusError(f"{snapshot}: cannot hash artifact {name}: {exc}") from exc
        if actual != expected:
            raise CorpusError(f"{snapshot}: artifact hash mismatch for {name}")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _logical_files(corpus: Corpus) -> dict[str, str]:
    records = "".join(
        stable_json(record_as_ir(record)) + "\n"
        for record in sorted(corpus.records.values(), key=lambda item: item.id)
    )
    sources = "".join(
        stable_json(
            {
                "id": source.id,
                "name": source.name,
                "kind": source.kind,
                "url": source.url,
                "revision": source.revision.as_dict(),
                "revision_label": source.revision_label,
                "tracking": source.tracking,
                "license": source.license,
                "access": source.access,
                "topics": list(source.topics),
                "notes": source.notes,
                "retrieved_at": source.retrieved_at,
            }
        )
        + "\n"
        for source in sorted(corpus.sources.values(), key=lambda item: item.id)
    )
    relations = "".join(
        stable_json({"from": record.id, "relation": relation, "to": target}) + "\n"
        for record in sorted(corpus.records.values(), key=lambda item: item.id)
        for relation in RELATION_TYPES
        for target in record.relations[relation]
    )
    taxonomy = stable_json(
        {
            "schema": "research-taxonomy-index/v1",
            "axes": {
                axis: {
                    value: {"label": term.label, "aliases": list(term.aliases)}
                    for value, term in sorted(corpus.taxonomy.axes[axis].items())
                }
                for axis in AXES
            },
            "aliases": {
                alias: [{"axis": axis, "value": value} for axis, value in targets]
                for alias, targets in corpus.taxonomy.alias_map.items()
            },
        },
        pretty=True,
    )
    return {
        "records.jsonl": records,
        "sources.jsonl": sources,
        "relations.jsonl": relations,
        "taxonomy.json": taxonomy,
    }


def _logical_hash(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def corpus_logical_hash(corpus: Corpus) -> str:
    return _logical_hash(_logical_files(corpus))


def _facet_text(corpus: Corpus, record_id: str) -> str:
    record = corpus.records[record_id]
    pieces: list[str] = []
    for axis in AXES:
        for value in record.facets[axis]:
            term = corpus.taxonomy.axes[axis][value]
            pieces.extend((axis, value, term.label, *term.aliases))
    return " ".join(pieces)


def _metadata_value(value: Any) -> str:
    return value if isinstance(value, str) else stable_json(value)


def _create_database(path: Path, corpus: Corpus, manifest: dict[str, Any]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA foreign_keys=ON;

            CREATE TABLE metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE catalog_sources (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              url TEXT,
              revision_kind TEXT NOT NULL,
              revision_value TEXT NOT NULL,
              revision_label TEXT,
              license TEXT NOT NULL,
              access TEXT NOT NULL,
              topics TEXT NOT NULL,
              notes TEXT NOT NULL,
              retrieved_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE catalog_sources_fts USING fts5(
              source_id UNINDEXED,
              name,
              topics,
              notes,
              tokenize='unicode61 remove_diacritics 2'
            );
            CREATE TABLE records (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              title TEXT NOT NULL,
              question TEXT NOT NULL,
              summary TEXT NOT NULL,
              body TEXT NOT NULL,
              path TEXT NOT NULL,
              verified_at TEXT NOT NULL,
              health TEXT NOT NULL
            );
            CREATE TABLE facets (
              record_id TEXT NOT NULL REFERENCES records(id),
              axis TEXT NOT NULL,
              value TEXT NOT NULL,
              PRIMARY KEY (record_id, axis, value)
            );
            CREATE INDEX facets_lookup ON facets(axis, value, record_id);
            CREATE TABLE record_sources (
              record_id TEXT NOT NULL REFERENCES records(id),
              source_id TEXT NOT NULL,
              revision_kind TEXT NOT NULL,
              revision_value TEXT NOT NULL,
              role TEXT NOT NULL,
              PRIMARY KEY (record_id, source_id)
            );
            CREATE INDEX source_lookup ON record_sources(source_id, record_id);
            CREATE TABLE locators (
              record_id TEXT NOT NULL REFERENCES records(id),
              source_id TEXT NOT NULL,
              locator_id TEXT NOT NULL,
              locator_kind TEXT NOT NULL,
              coordinates TEXT NOT NULL,
              PRIMARY KEY (record_id, source_id, locator_id)
            );
            CREATE TABLE relations (
              record_id TEXT NOT NULL REFERENCES records(id),
              relation TEXT NOT NULL,
              target_id TEXT NOT NULL REFERENCES records(id) DEFERRABLE INITIALLY DEFERRED,
              PRIMARY KEY (record_id, relation, target_id)
            );
            CREATE INDEX relation_target_lookup ON relations(target_id, relation, record_id);
            CREATE TABLE consumers (
              record_id TEXT NOT NULL REFERENCES records(id),
              path TEXT NOT NULL,
              PRIMARY KEY (record_id, path)
            );
            CREATE VIRTUAL TABLE records_fts USING fts5(
              record_id UNINDEXED,
              title,
              question,
              summary,
              claims,
              body,
              facets,
              sources,
              locators,
              consumers,
              tokenize='unicode61 remove_diacritics 2'
            );
            """
        )
        for key, value in sorted(_database_metadata(manifest).items()):
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                (key, _metadata_value(value)),
            )

        for source in sorted(corpus.sources.values(), key=lambda item: item.id):
            topics = " ".join(source.topics)
            connection.execute(
                "INSERT INTO catalog_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source.id,
                    source.name,
                    source.kind,
                    source.url,
                    source.revision.kind,
                    source.revision.value,
                    source.revision_label,
                    source.license,
                    source.access,
                    stable_json(list(source.topics)),
                    source.notes,
                    source.retrieved_at,
                ),
            )
            connection.execute(
                "INSERT INTO catalog_sources_fts VALUES (?, ?, ?, ?)",
                (source.id, source.name, topics, source.notes),
            )

        for record in sorted(corpus.records.values(), key=lambda item: item.id):
            connection.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.kind,
                    record.status,
                    record.title,
                    record.question,
                    record.summary,
                    record.body,
                    record.relative_path,
                    record.verified_at,
                    stable_json(list(record.health)),
                ),
            )
            for axis in AXES:
                for value in record.facets[axis]:
                    connection.execute(
                        "INSERT INTO facets VALUES (?, ?, ?)", (record.id, axis, value)
                    )
            source_pieces: list[str] = []
            locator_pieces: list[str] = []
            for source in record.sources:
                catalog_source = corpus.sources[source["id"]]
                connection.execute(
                    "INSERT INTO record_sources VALUES (?, ?, ?, ?, ?)",
                    (
                        record.id,
                        source["id"],
                        source["revision"]["kind"],
                        source["revision"]["value"],
                        source["role"],
                    ),
                )
                source_pieces.extend(
                    (source["id"], catalog_source.name, *catalog_source.topics)
                )
                for locator in source["locators"]:
                    coordinates = {
                        key: value
                        for key, value in locator.items()
                        if key not in {"id", "kind"}
                    }
                    connection.execute(
                        "INSERT INTO locators VALUES (?, ?, ?, ?, ?)",
                        (
                            record.id,
                            source["id"],
                            locator["id"],
                            locator["kind"],
                            stable_json(coordinates),
                        ),
                    )
                    locator_pieces.extend(
                        (source["id"], locator["id"], locator["kind"], *map(str, coordinates.values()))
                    )
            for relation in RELATION_TYPES:
                for target in record.relations[relation]:
                    connection.execute(
                        "INSERT INTO relations VALUES (?, ?, ?)",
                        (record.id, relation, target),
                    )
            for consumer in record.consumers:
                connection.execute("INSERT INTO consumers VALUES (?, ?)", (record.id, consumer))
            connection.execute(
                "INSERT INTO records_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.title,
                    record.question,
                    record.summary,
                    " ".join(claim["statement"] for claim in record.claims),
                    record.body,
                    _facet_text(corpus, record.id),
                    " ".join(source_pieces),
                    " ".join(locator_pieces),
                    " ".join(record.consumers),
                ),
            )
        connection.commit()
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise CorpusError(f"generated SQLite index failed integrity_check: {result!r}")
    except sqlite3.OperationalError as exc:
        raise CorpusError(f"cannot build SQLite FTS5 index: {exc}") from exc
    finally:
        connection.close()


def _snapshot_is_complete(
    snapshot: Path,
    manifest: dict[str, Any],
    files: dict[str, str],
    candidate_database: Path,
) -> bool:
    try:
        if _read_manifest(snapshot / "manifest.json") != manifest:
            return False
        for name, content in files.items():
            if (snapshot / name).read_text(encoding="utf-8") != content:
                return False
        database = snapshot / "search.sqlite3"
        _verify_artifact_hashes(snapshot, manifest)
        if _file_hash(database) != _file_hash(candidate_database):
            return False
        connection = sqlite3.connect(read_only_sqlite_uri(database), uri=True)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()
        return bool(
            result
            and result[0] == "ok"
            and all(
                metadata.get(key) == _metadata_value(value)
                for key, value in _database_metadata(manifest).items()
            )
        )
    except (OSError, json.JSONDecodeError, sqlite3.Error, CorpusError):
        return False


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(stable_json(value, pretty=True))
        for attempt in range(SHARING_RETRY_ATTEMPTS):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt + 1 == SHARING_RETRY_ATTEMPTS:
                    raise
                time.sleep(SHARING_RETRY_SECONDS)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_text_with_sharing_retry(path: Path) -> str:
    for attempt in range(SHARING_RETRY_ATTEMPTS):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if attempt + 1 == SHARING_RETRY_ATTEMPTS:
                raise
            time.sleep(SHARING_RETRY_SECONDS)
    raise AssertionError("sharing retry loop did not return or raise")


@contextmanager
def _index_lock(index_root: Path):
    _assert_safe_index_path(index_root, index_root)
    index_root.mkdir(parents=True, exist_ok=True)
    _assert_safe_index_path(index_root, index_root)
    lock_path = index_root / ".build.lock"
    _assert_safe_index_path(index_root, lock_path)
    stream = lock_path.open("a+b")
    try:
        if os.fstat(stream.fileno()).st_nlink != 1:
            raise CorpusError(f"refusing shared research index lock file: {lock_path}")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError) as exc:
            raise CorpusError(f"another research index build holds {lock_path}") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


def _assert_safe_index_path(index_root: Path, path: Path) -> None:
    assert_no_redirecting_ancestors(index_root, purpose="research index mutation")
    assert_plain_contained_path(index_root, path, purpose="research index mutation")


def _remove_uninstalled_candidate(path: Path, snapshots: Path) -> None:
    if not os.path.lexists(path):
        return
    _assert_safe_index_path(snapshots.parent, path)
    if path.is_symlink():
        path.unlink()
    elif getattr(path, "is_junction", lambda: False)():
        path.rmdir()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _candidate_install_path(snapshots: Path, build_id: str) -> Path:
    base = snapshots / build_id
    if not os.path.lexists(base):
        return base
    while True:
        candidate = snapshots / f"{build_id}-repair-{secrets.token_hex(8)}"
        if not os.path.lexists(candidate):
            return candidate


def build_index(corpus: Corpus, index_root: Path, *, clean: bool = False) -> Path:
    # Every build constructs a complete candidate without reading an old
    # projection. Installation may retain a byte-identical, fully attested
    # snapshot so repeated clean gates do not leak physical generations.
    _ = clean
    index_root = index_root.absolute()
    _assert_safe_index_path(index_root, index_root)
    files = _logical_files(corpus)
    logical_hash = _logical_hash(files)
    executable_hash = implementation_hash()
    build_material = (
        f"{INDEX_SCHEMA_VERSION}\0{EXTRACTOR_VERSION}\0{RANKER_VERSION}\0"
        f"{executable_hash}\0{sqlite3.sqlite_version}\0"
        f"{corpus.input_hash}\0{logical_hash}"
    )
    build_id = hashlib.sha256(build_material.encode("utf-8")).hexdigest()[:20]
    manifest: dict[str, Any] = {
        "format": INDEX_FORMAT,
        "index_schema": INDEX_SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "ranker_version": RANKER_VERSION,
        "implementation_hash": executable_hash,
        "sqlite_version": sqlite3.sqlite_version,
        "build_id": build_id,
        "input_hash": corpus.input_hash,
        "logical_hash": logical_hash,
        "record_count": len(corpus.records),
        "source_count": len(corpus.sources),
    }

    snapshots = index_root / "snapshots"
    index_root.mkdir(parents=True, exist_ok=True)
    _assert_safe_index_path(index_root, index_root)
    snapshots.mkdir(parents=True, exist_ok=True)
    _assert_safe_index_path(index_root, snapshots)
    temporary = Path(tempfile.mkdtemp(prefix=".build-", dir=snapshots))
    target: Path | None = None
    try:
        for name, content in files.items():
            _write_text(temporary / name, content)
        _create_database(temporary / "search.sqlite3", corpus, manifest)
        manifest["artifact_hashes"] = {
            name: _file_hash(temporary / name) for name in HASHED_ARTIFACTS
        }
        _write_text(temporary / "manifest.json", stable_json(manifest, pretty=True))

        with _index_lock(index_root):
            _assert_safe_index_path(index_root, snapshots)
            fresh = load_corpus(corpus.paths)
            if (
                fresh.input_hash != corpus.input_hash
                or corpus_logical_hash(fresh) != logical_hash
            ):
                raise CorpusError(
                    "canonical research inputs changed during index build; run build again"
                )

            reusable_candidates = sorted(
                (
                    path
                    for path in snapshots.iterdir()
                    if INSTALL_ID_RE.fullmatch(path.name)
                    and path.name.startswith(build_id)
                ),
                key=lambda path: (path.name != build_id, path.name),
            )
            for candidate in reusable_candidates:
                _assert_safe_index_path(index_root, candidate)
                if candidate.is_dir() and _snapshot_is_complete(
                    candidate, manifest, files, temporary / "search.sqlite3"
                ):
                    target = candidate
                    break

            if target is None:
                target = _candidate_install_path(snapshots, build_id)
                _assert_safe_index_path(index_root, target)
                os.replace(temporary, target)
            _atomic_write_json(
                index_root / "current.json",
                {
                    "format": INDEX_FORMAT,
                    "build_id": build_id,
                    "snapshot": target.name,
                },
            )
    finally:
        _remove_uninstalled_candidate(temporary, snapshots)
    assert target is not None
    return target


def current_snapshot(index_root: Path) -> Path:
    index_root = index_root.absolute()
    assert_no_redirecting_ancestors(index_root, purpose="research index read")
    pointer_path = index_root / "current.json"
    try:
        pointer = json.loads(_read_text_with_sharing_retry(pointer_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"no usable research index at {pointer_path}; run build") from exc
    if not isinstance(pointer, dict) or pointer.get("format") != INDEX_FORMAT:
        raise CorpusError(f"{pointer_path}: unsupported index pointer")
    build_id = pointer.get("build_id")
    if not isinstance(build_id, str) or not re_full_build_id(build_id):
        raise CorpusError(f"{pointer_path}: invalid build id")
    install_id = pointer.get("snapshot")
    if (
        not isinstance(install_id, str)
        or not INSTALL_ID_RE.fullmatch(install_id)
        or not install_id.startswith(build_id)
    ):
        raise CorpusError(f"{pointer_path}: invalid snapshot id")
    snapshot = index_root / "snapshots" / install_id
    _assert_safe_index_path(index_root, snapshot)
    if not snapshot.is_dir():
        raise CorpusError(f"{pointer_path}: missing snapshot {build_id}")
    manifest = _read_manifest(snapshot / "manifest.json")
    if manifest.get("build_id") != build_id or manifest.get("format") != INDEX_FORMAT:
        raise CorpusError(f"{snapshot}: manifest does not match pointer")
    expected_versions = {
        "index_schema": INDEX_SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "ranker_version": RANKER_VERSION,
    }
    for key, expected in expected_versions.items():
        if manifest.get(key) != expected:
            raise CorpusError(
                f"{snapshot}: incompatible {key} {manifest.get(key)!r}; rebuild with {expected}"
            )
    expected_strings = {
        "implementation_hash": implementation_hash(),
        "sqlite_version": sqlite3.sqlite_version,
    }
    for key, expected in expected_strings.items():
        if manifest.get(key) != expected:
            raise CorpusError(
                f"{snapshot}: incompatible {key} {manifest.get(key)!r}; rebuild"
            )
    _verify_artifact_hashes(snapshot, manifest)
    database = snapshot / "search.sqlite3"
    try:
        connection = sqlite3.connect(read_only_sqlite_uri(database), uri=True)
        try:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise CorpusError(f"{snapshot}: cannot validate SQLite metadata: {exc}") from exc
    for key, expected in _database_metadata(manifest).items():
        serialized = _metadata_value(expected)
        if metadata.get(key) != serialized:
            raise CorpusError(
                f"{snapshot}: SQLite metadata has incompatible {key} "
                f"{metadata.get(key)!r}; rebuild"
            )
    return snapshot


def re_full_build_id(value: str) -> bool:
    return len(value) == 20 and all(character in "0123456789abcdef" for character in value)


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{path}: invalid manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise CorpusError(f"{path}: manifest must be an object")
    return value
