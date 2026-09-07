from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit


DOCUMENT_SCHEMA = "research/v2"
TAXONOMY_SCHEMA = "research-taxonomy/v1"
AXES = ("domains", "mechanisms", "qualities", "platforms")
KINDS = {"study", "comparison", "synthesis"}
STATUSES = {"draft", "reviewed", "superseded", "retired"}
SOURCE_ROLES = {"primary", "contrast", "counterexample", "context"}
CLAIM_TYPES = {"observation", "interpretation", "recommendation", "non-finding"}
RELATION_TYPES = (
    "supports",
    "contradicts",
    "refines",
    "supersedes",
    "superseded_by",
    "related",
)

TOKEN_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RECORD_ID_RE = re.compile(
    r"^(?:cr|rr)-[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{8}$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FULL_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SUPPORTED_SCHEMA_KEYS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "description",
    "type",
    "additionalProperties",
    "required",
    "properties",
    "const",
    "enum",
    "pattern",
    "minLength",
    "items",
    "uniqueItems",
    "format",
}
SUPPORTED_SCHEMA_TYPES = {
    "object",
    "array",
    "string",
    "integer",
    "number",
    "boolean",
    "null",
}
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SOURCE_KINDS = {
    "git-repository",
    "local-repository",
    "web-page",
    "publication",
    "dataset",
    "artifact",
}
REVISION_KINDS = {"git-commit", "content-digest"}
LOCATOR_FIELDS = {
    "source-tree": ({"path"}, {"symbol", "line_start", "line_end", "note"}),
    "document": (set(), {"page", "section", "quote_digest", "note"}),
    "web": (set(), {"fragment", "selector", "quote_digest", "note"}),
    "dataset": (set(), {"table", "row", "column", "query", "note"}),
    "media": ({"timecode"}, {"note"}),
    "artifact": (set(), {"path", "member", "note"}),
}


class CorpusError(RuntimeError):
    """A tracked corpus input violates the research contract."""


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CorpusError(f"cannot inspect corpus path {path}: {exc}") from exc


def assert_plain_contained_path(root: Path, path: Path, *, purpose: str) -> None:
    """Reject projection or canonical paths redirected outside their declared root."""

    lexical_root = root.absolute()
    candidate = path.absolute()
    try:
        relative = candidate.relative_to(lexical_root)
    except ValueError as exc:
        raise CorpusError(f"{purpose} escapes its declared root: {path}") from exc

    cursor = lexical_root
    if _is_link_or_reparse_point(cursor):
        raise CorpusError(
            f"refusing {purpose} through a link or reparse point: {cursor}"
        )
    for part in relative.parts:
        cursor /= part
        if _is_link_or_reparse_point(cursor):
            raise CorpusError(
                f"refusing {purpose} through a link or reparse point: {cursor}"
            )

    try:
        candidate.resolve(strict=False).relative_to(lexical_root.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise CorpusError(f"{purpose} escapes its declared root: {path}") from exc


def assert_no_redirecting_ancestors(path: Path, *, purpose: str) -> None:
    """Reject an existing symlink/junction anywhere in an intended mutation path."""

    absolute = path.absolute()
    anchor = Path(absolute.anchor)
    cursor = anchor
    relative_parts = absolute.parts[1:] if absolute.anchor else absolute.parts
    for part in relative_parts:
        cursor /= part
        if _is_link_or_reparse_point(cursor):
            raise CorpusError(
                f"refusing {purpose} through a link or reparse point: {cursor}"
            )


@dataclass(frozen=True)
class CorpusPaths:
    corpus: Path
    docs_root: Path | None = None

    @property
    def catalog(self) -> Path:
        return self.corpus / "catalog"

    @property
    def docs(self) -> Path:
        return self.docs_root if self.docs_root is not None else self.corpus / "docs"

    @property
    def records(self) -> Path:
        return self.docs / "records"

    @property
    def schemas(self) -> Path:
        return self.corpus / "schemas"

    @property
    def taxonomy(self) -> Path:
        return self.schemas / "taxonomy.json"

    @property
    def record_schema(self) -> Path:
        return self.schemas / "research-record.schema.json"

    @property
    def default_index(self) -> Path:
        return self.corpus / "cache" / "index"

    def logical_input_path(self, path: Path) -> str:
        """Return a stable corpus-relative name for hashing and search output.

        A colocated docs tree keeps its historical ``docs/...`` spelling.  A
        separately declared published docs root is mounted at the same logical
        ``docs/`` namespace so machine-local absolute paths never enter an
        index digest.
        """

        try:
            return path.relative_to(self.corpus).as_posix()
        except ValueError:
            return (PurePosixPath("docs") / path.relative_to(self.docs)).as_posix()


@dataclass(frozen=True)
class SourceRevision:
    kind: str
    value: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}

    def key(self) -> str:
        return f"{self.kind}:{self.value}"


@dataclass(frozen=True)
class CatalogSource:
    id: str
    name: str
    kind: str
    # None exactly for the local repository, which has no remote to name.
    url: str | None
    revision: SourceRevision
    revision_label: str | None
    tracking: dict[str, str] | None
    license: str
    access: str
    topics: tuple[str, ...]
    notes: str
    # When this exact revision was taken. A reader judging a record needs to
    # know how old the evidence is, not only which revision it names.
    retrieved_at: str
    path: Path


@dataclass(frozen=True)
class TaxonomyTerm:
    value: str
    label: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Taxonomy:
    axes: dict[str, dict[str, TaxonomyTerm]]
    alias_map: dict[str, tuple[tuple[str, str], ...]]


@dataclass(frozen=True)
class ResearchRecord:
    id: str
    kind: str
    status: str
    title: str
    question: str
    summary: str
    facets: dict[str, tuple[str, ...]]
    sources: tuple[dict[str, Any], ...]
    claims: tuple[dict[str, Any], ...]
    relations: dict[str, tuple[str, ...]]
    consumers: tuple[str, ...]
    verified_at: str
    revalidate_when: tuple[str, ...]
    body: str
    path: Path
    relative_path: str
    content_hash: str
    health: tuple[str, ...]

    def source_ids(self) -> tuple[str, ...]:
        return tuple(source["id"] for source in self.sources)

    def locator_rows(self) -> Iterable[tuple[str, str, str, str]]:
        for source in self.sources:
            for locator in source["locators"]:
                yield (
                    source["id"],
                    locator["id"],
                    locator["kind"],
                    stable_json(
                        {
                            key: value
                            for key, value in locator.items()
                            if key not in {"id", "kind"}
                        }
                    ),
                )


@dataclass(frozen=True)
class Corpus:
    paths: CorpusPaths
    sources: dict[str, CatalogSource]
    taxonomy: Taxonomy
    records: dict[str, ResearchRecord]
    input_hash: str


class _DuplicateJsonKey(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey(f"duplicate object key {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value!r}")


def _parse_json(text: str, where: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except ValueError as exc:
        raise CorpusError(f"{where}: cannot read valid JSON: {exc}") from exc


def _read_json(path: Path, data: bytes) -> Any:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CorpusError(f"{path}: canonical JSON must be UTF-8: {exc}") from exc
    return _parse_json(text, str(path))


def _check_supported_schema(schema: Any, where: str) -> None:
    if not isinstance(schema, dict):
        raise CorpusError(f"{where}: schema node must be an object")
    unknown = sorted(set(schema) - SUPPORTED_SCHEMA_KEYS)
    if unknown:
        raise CorpusError(
            f"{where}: unsupported JSON Schema keyword(s): {', '.join(unknown)}"
        )
    if "$schema" in schema and schema["$schema"] != SCHEMA_DRAFT:
        raise CorpusError(f"{where}: unsupported JSON Schema dialect {schema['$schema']!r}")
    for annotation in ("$id", "title", "description"):
        if annotation in schema and not isinstance(schema[annotation], str):
            raise CorpusError(f"{where}.{annotation}: expected a string")
    if "$ref" in schema and not isinstance(schema["$ref"], str):
        raise CorpusError(f"{where}.$ref: expected a string")
    if "type" in schema and (
        not isinstance(schema["type"], str)
        or schema["type"] not in SUPPORTED_SCHEMA_TYPES
    ):
        raise CorpusError(f"{where}.type: unsupported schema type {schema['type']!r}")
    if "additionalProperties" in schema and not isinstance(
        schema["additionalProperties"], bool
    ):
        raise CorpusError(
            f"{where}.additionalProperties: only boolean values are supported"
        )
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise CorpusError(f"{where}.required: expected an array of strings")
    if len(required) != len(set(required)):
        raise CorpusError(f"{where}.required: duplicate property names are not allowed")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            raise CorpusError(f"{where}.enum: expected a non-empty array")
        identities = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in enum]
        if len(identities) != len(set(identities)):
            raise CorpusError(f"{where}.enum: duplicate values are not allowed")
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str):
            raise CorpusError(f"{where}.pattern: expected a string")
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            raise CorpusError(f"{where}.pattern: invalid regular expression: {exc}") from exc
    if "minLength" in schema and (
        not isinstance(schema["minLength"], int)
        or isinstance(schema["minLength"], bool)
        or schema["minLength"] < 0
    ):
        raise CorpusError(f"{where}.minLength: expected a non-negative integer")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise CorpusError(f"{where}.uniqueItems: expected a boolean")
    if "format" in schema and schema["format"] != "date":
        raise CorpusError(f"{where}.format: unsupported format {schema['format']!r}")

    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        raise CorpusError(f"{where}.$defs: expected an object")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise CorpusError(f"{where}.properties: expected an object")
    if "items" in schema and not isinstance(schema["items"], dict):
        raise CorpusError(f"{where}.items: only one schema object is supported")

    for name, child in definitions.items():
        if not isinstance(name, str):
            raise CorpusError(f"{where}.$defs: property names must be strings")
        _check_supported_schema(child, f"{where}.$defs.{name}")
    for name, child in properties.items():
        if not isinstance(name, str):
            raise CorpusError(f"{where}.properties: property names must be strings")
        _check_supported_schema(child, f"{where}.properties.{name}")
    if "items" in schema:
        _check_supported_schema(schema["items"], f"{where}.items")


def _schema_ref(root: dict[str, Any], reference: str, where: str) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not reference.startswith(prefix) or "/" in reference[len(prefix) :]:
        raise CorpusError(f"{where}: only local $defs references are supported")
    name = reference[len(prefix) :]
    target = root.get("$defs", {}).get(name)
    if not isinstance(target, dict):
        raise CorpusError(f"{where}: unresolved schema reference {reference!r}")
    return target


def _matches_schema_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise CorpusError(f"unsupported JSON Schema type {expected!r}")


def _validate_against_schema(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    where: str,
) -> None:
    if "$ref" in schema:
        _validate_against_schema(value, _schema_ref(root, schema["$ref"], where), root, where)
        # Draft 2020-12 permits validation siblings next to $ref.  Resolve the
        # referenced schema first, then keep evaluating this schema object so a
        # supported sibling such as pattern cannot be silently ignored.
    if "const" in schema and value != schema["const"]:
        raise CorpusError(f"{where}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise CorpusError(f"{where}: expected one of {schema['enum']!r}")
    expected_type = schema.get("type")
    if expected_type is not None:
        if not isinstance(expected_type, str) or not _matches_schema_type(value, expected_type):
            raise CorpusError(f"{where}: expected JSON Schema type {expected_type}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise CorpusError(f"{where}: string is shorter than minLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise CorpusError(f"{where}: string does not match {schema['pattern']!r}")
        if schema.get("format") == "date":
            if not FULL_DATE_RE.fullmatch(value):
                raise CorpusError(f"{where}: expected an ISO full-date in YYYY-MM-DD form")
            try:
                dt.date.fromisoformat(value)
            except ValueError as exc:
                raise CorpusError(f"{where}: expected an ISO date") from exc
    if isinstance(value, list):
        if schema.get("uniqueItems"):
            identities = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(identities) != len(set(identities)):
                raise CorpusError(f"{where}: array items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_against_schema(item, item_schema, root, f"{where}[{index}]")
    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise CorpusError(f"{where}: missing required field(s): {', '.join(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise CorpusError(f"{where}: unknown field(s): {', '.join(extra)}")
        for key, child in properties.items():
            if key in value:
                _validate_against_schema(value[key], child, root, f"{where}.{key}")


def _nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusError(f"{where}: expected a non-empty string")
    return value.strip()


def _string_list(value: Any, where: str, *, token: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CorpusError(f"{where}: expected an array")
    result = tuple(_nonempty_string(item, f"{where}[]") for item in value)
    if len(set(result)) != len(result):
        raise CorpusError(f"{where}: duplicate values are not allowed")
    if token:
        invalid = [item for item in result if not TOKEN_RE.fullmatch(item)]
        if invalid:
            raise CorpusError(f"{where}: invalid token(s): {', '.join(invalid)}")
    return result


def _exact_keys(value: dict[str, Any], required: set[str], where: str) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise CorpusError(f"{where}: {'; '.join(details)}")


def _closed_keys(
    value: dict[str, Any], required: set[str], optional: set[str], where: str
) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required - optional)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise CorpusError(f"{where}: {'; '.join(details)}")


def _revision(value: Any, where: str) -> SourceRevision:
    if not isinstance(value, dict):
        raise CorpusError(f"{where}: revision must be an object")
    _exact_keys(value, {"kind", "value"}, where)
    kind = _nonempty_string(value["kind"], f"{where}.kind")
    revision_value = _nonempty_string(value["value"], f"{where}.value")
    if kind not in REVISION_KINDS:
        raise CorpusError(f"{where}.kind: unsupported revision kind {kind!r}")
    if kind == "git-commit" and not COMMIT_RE.fullmatch(revision_value):
        raise CorpusError(f"{where}.value: expected a lowercase 40-character commit")
    if kind == "content-digest" and not DIGEST_RE.fullmatch(revision_value):
        raise CorpusError(f"{where}.value: expected sha256:<64 lowercase hex characters>")
    return SourceRevision(kind=kind, value=revision_value)


def _retrieved_at(value: Any, where: str) -> str:
    text = _nonempty_string(value, where)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CorpusError(f"{where}: expected an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CorpusError(f"{where}: timestamp must include an offset")
    return text


def _tracking(value: Any, where: str, source_kind: str) -> dict[str, str] | None:
    if value is None:
        if source_kind == "git-repository":
            raise CorpusError(f"{where}: git repositories require git-ref tracking")
        if source_kind == "local-repository":
            raise CorpusError(f"{where}: local repositories require local-head tracking")
        return None
    if not isinstance(value, dict):
        raise CorpusError(f"{where}: tracking must be an object")
    kind = _nonempty_string(value.get("kind"), f"{where}.kind")
    if kind == "git-ref":
        _closed_keys(value, {"kind", "ref"}, {"default_branch"}, where)
        if source_kind != "git-repository":
            raise CorpusError(f"{where}: git-ref tracking requires a git-repository source")
        result = {"kind": kind, "ref": _nonempty_string(value["ref"], f"{where}.ref")}
        if "default_branch" in value:
            result["default_branch"] = _nonempty_string(
                value["default_branch"], f"{where}.default_branch"
            )
        return result
    if kind == "local-head":
        _exact_keys(value, {"kind"}, where)
        if source_kind != "local-repository":
            raise CorpusError(f"{where}: local-head tracking requires a local-repository source")
        return {"kind": kind}
    if kind == "manual":
        _exact_keys(value, {"kind", "note"}, where)
        if source_kind in {"git-repository", "local-repository"}:
            raise CorpusError(f"{where}: {source_kind} sources cannot use manual tracking")
        return {"kind": kind, "note": _nonempty_string(value["note"], f"{where}.note")}
    raise CorpusError(f"{where}.kind: unsupported tracking kind {kind!r}")


def _relative_posix_path(value: Any, where: str) -> str:
    text = _nonempty_string(value, where)
    if "\\" in text:
        raise CorpusError(f"{where}: use repository-relative POSIX separators")
    parts = text.split("/")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or re.match(r"^[A-Za-z]:", text)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise CorpusError(f"{where}: expected a contained repository-relative path")
    return text


def _load_catalog(
    paths: CorpusPaths,
    inputs: dict[Path, bytes],
    catalog_paths: tuple[Path, ...],
) -> dict[str, CatalogSource]:
    sources: dict[str, CatalogSource] = {}
    assert_plain_contained_path(
        paths.corpus, paths.catalog, purpose="canonical catalog input"
    )
    if not paths.catalog.is_dir():
        raise CorpusError(f"missing catalog directory: {paths.catalog}")
    for path in catalog_paths:
        assert_plain_contained_path(
            paths.corpus, path, purpose="canonical catalog input"
        )
        raw = _read_json(path, inputs[path])
        if not isinstance(raw, dict):
            raise CorpusError(f"{path}: manifest root must be an object")
        _closed_keys(
            raw,
            {
                "schema",
                "id",
                "name",
                "kind",
                "license",
                "access",
                "topics",
                "notes",
                "revision",
                "retrieved_at",
            },
            # url moved to the optional set so the per-kind rule below can
            # require it everywhere except the local repository, which has no
            # remote to name.
            {"revision_label", "tracking", "url"},
            str(path),
        )
        if raw["schema"] != 2 or isinstance(raw["schema"], bool):
            raise CorpusError(f"{path}: schema must be 2")
        source_id = _nonempty_string(raw.get("id"), f"{path}: id")
        if not TOKEN_RE.fullmatch(source_id) or path.stem != source_id:
            raise CorpusError(f"{path}: id must be a lowercase token matching the file name")
        source_kind = _nonempty_string(raw["kind"], f"{path}: kind")
        if source_kind not in SOURCE_KINDS:
            raise CorpusError(f"{path}: unsupported source kind {source_kind!r}")
        revision = _revision(raw["revision"], f"{path}: revision")
        expected_revision_kind = (
            "git-commit"
            if source_kind in {"git-repository", "local-repository"}
            else "content-digest"
        )
        if revision.kind != expected_revision_kind:
            raise CorpusError(
                f"{path}: {source_kind} requires revision.kind {expected_revision_kind!r}"
            )
        tracking = _tracking(raw.get("tracking"), f"{path}: tracking", source_kind)
        _retrieved_at(raw["retrieved_at"], f"{path}: retrieved_at")
        url: str | None
        if source_kind == "local-repository":
            if "url" in raw:
                raise CorpusError(
                    f"{path}: a local-repository source has no remote and must omit url"
                )
            url = None
        else:
            if "url" not in raw:
                raise CorpusError(f"{path}: url is required for source kind {source_kind!r}")
            url = _nonempty_string(raw["url"], f"{path}: url")
            try:
                parsed_url = urlsplit(url)
                invalid_url = (
                    url != url.strip()
                    or any(character in url for character in "\x00\r\n\t")
                    or parsed_url.scheme != "https"
                    or parsed_url.hostname is None
                    or parsed_url.username is not None
                    or parsed_url.password is not None
                    or parsed_url.path in {"", "/"}
                )
                if source_kind == "git-repository":
                    invalid_url = invalid_url or (
                        parsed_url.query != ""
                        or parsed_url.fragment != ""
                    )
            except ValueError:
                invalid_url = True
            if invalid_url:
                raise CorpusError(f"{path}: url is not valid for source kind {source_kind!r}")
        access = _nonempty_string(raw["access"], f"{path}: access")
        if access not in {"public", "authenticated", "restricted"}:
            raise CorpusError(f"{path}: access must be public, authenticated, or restricted")
        topics = _string_list(raw["topics"], f"{path}: topics")
        if not topics:
            raise CorpusError(f"{path}: topics must not be empty")
        if source_id in sources:
            raise CorpusError(f"{path}: duplicate source id {source_id}")
        sources[source_id] = CatalogSource(
            id=source_id,
            name=_nonempty_string(raw.get("name"), f"{path}: name"),
            kind=source_kind,
            url=url,
            revision=revision,
            revision_label=(
                _nonempty_string(raw["revision_label"], f"{path}: revision_label")
                if "revision_label" in raw
                else None
            ),
            tracking=tracking,
            license=_nonempty_string(raw.get("license"), f"{path}: license"),
            access=access,
            topics=topics,
            notes=_nonempty_string(raw.get("notes"), f"{path}: notes"),
            retrieved_at=_nonempty_string(raw["retrieved_at"], f"{path}: retrieved_at"),
            path=path,
        )
    return sources


def load_catalog(corpus_root: Path) -> dict[str, CatalogSource]:
    """Read source identities without requiring records, schemas, or local source bytes.

    Metadata validation grants no network permission. Acquisition tools must
    enforce their own host and access policy before contacting a source.
    """
    paths = CorpusPaths(corpus_root.absolute())
    assert_no_redirecting_ancestors(paths.catalog, purpose="canonical catalog input")
    if not paths.catalog.is_dir():
        raise CorpusError(f"missing catalog directory: {paths.catalog}")
    entries = tuple(sorted(paths.catalog.iterdir(), key=lambda path: path.name))
    for path in entries:
        assert_plain_contained_path(paths.corpus, path, purpose="canonical catalog input")
        if not path.is_file() or path.suffix != ".json":
            raise CorpusError(f"catalog accepts only flat JSON manifests: {path}")
    try:
        first = {path: path.read_bytes() for path in entries}
        second = {path: path.read_bytes() for path in entries}
        after = tuple(sorted(paths.catalog.iterdir(), key=lambda path: path.name))
    except OSError as exc:
        raise CorpusError(f"cannot capture source catalog: {exc}") from exc
    if first != second or entries != after:
        raise CorpusError("canonical source catalog changed while being read; try again")
    return _load_catalog(paths, second, entries)


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _load_taxonomy(paths: CorpusPaths, inputs: dict[Path, bytes]) -> Taxonomy:
    assert_plain_contained_path(
        paths.corpus, paths.taxonomy, purpose="canonical taxonomy input"
    )
    raw = _read_json(paths.taxonomy, inputs[paths.taxonomy])
    if not isinstance(raw, dict):
        raise CorpusError(f"{paths.taxonomy}: taxonomy root must be an object")
    _exact_keys(raw, {"schema", "axes"}, str(paths.taxonomy))
    if raw["schema"] != TAXONOMY_SCHEMA:
        raise CorpusError(f"{paths.taxonomy}: unsupported schema {raw['schema']!r}")
    axes_raw = raw["axes"]
    if not isinstance(axes_raw, dict) or set(axes_raw) != set(AXES):
        raise CorpusError(f"{paths.taxonomy}: axes must be exactly {', '.join(AXES)}")

    axes: dict[str, dict[str, TaxonomyTerm]] = {}
    aliases: dict[str, list[tuple[str, str]]] = {}
    for axis in AXES:
        terms_raw = axes_raw[axis]
        if not isinstance(terms_raw, dict):
            raise CorpusError(f"{paths.taxonomy}: axes.{axis} must be an object")
        terms: dict[str, TaxonomyTerm] = {}
        for value, term_raw in sorted(terms_raw.items()):
            if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
                raise CorpusError(
                    f"{paths.taxonomy}: axes.{axis} contains invalid token {value!r}"
                )
            if not isinstance(term_raw, dict):
                raise CorpusError(f"{paths.taxonomy}: axes.{axis}.{value} must be an object")
            _exact_keys(term_raw, {"label", "aliases"}, f"{paths.taxonomy}: {axis}.{value}")
            label = _nonempty_string(term_raw["label"], f"{paths.taxonomy}: {axis}.{value}.label")
            term_aliases = _string_list(
                term_raw["aliases"], f"{paths.taxonomy}: {axis}.{value}.aliases"
            )
            terms[value] = TaxonomyTerm(value=value, label=label, aliases=term_aliases)
            for alias in (value, label, *term_aliases):
                aliases.setdefault(normalize_text(alias), []).append((axis, value))
        axes[axis] = terms
    return Taxonomy(
        axes=axes,
        alias_map={key: tuple(sorted(values)) for key, values in sorted(aliases.items())},
    )


def _split_record(path: Path, data: bytes) -> tuple[dict[str, Any], str, str]:
    try:
        text = data.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise CorpusError(f"{path}: research record must be UTF-8: {exc}") from exc
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise CorpusError(f"{path}: record must start with JSON front matter between --- lines")
    try:
        metadata = _parse_json(match.group(1), f"{path}: front matter")
    except CorpusError:
        raise
    if not isinstance(metadata, dict):
        raise CorpusError(f"{path}: front matter root must be an object")
    body = text[match.end() :]
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return metadata, body, content_hash


def _validate_locator(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CorpusError(f"{where}: locator must be an object")
    locator_kind = _nonempty_string(raw.get("kind"), f"{where}.kind")
    if locator_kind not in LOCATOR_FIELDS:
        raise CorpusError(f"{where}.kind: unsupported locator kind {locator_kind!r}")
    required, optional = LOCATOR_FIELDS[locator_kind]
    _closed_keys(raw, {"id", "kind", *required}, optional, where)
    locator_id = _nonempty_string(raw["id"], f"{where}.id")
    if not TOKEN_RE.fullmatch(locator_id):
        raise CorpusError(f"{where}.id: expected a lowercase token")

    if locator_kind == "document" and not any(
        key in raw for key in ("page", "section", "quote_digest")
    ):
        raise CorpusError(f"{where}: document locator requires page, section, or quote_digest")
    if locator_kind == "web" and not any(
        key in raw for key in ("fragment", "selector", "quote_digest")
    ):
        raise CorpusError(f"{where}: web locator requires fragment, selector, or quote_digest")
    if locator_kind == "dataset" and not any(key in raw for key in ("table", "query")):
        raise CorpusError(f"{where}: dataset locator requires table or query")
    if locator_kind == "artifact" and not any(key in raw for key in ("path", "member")):
        raise CorpusError(f"{where}: artifact locator requires path or member")

    result: dict[str, Any] = {"id": locator_id, "kind": locator_kind}
    for key in sorted((required | optional) & set(raw)):
        value = raw[key]
        if key in {"line_start", "line_end"}:
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise CorpusError(f"{where}.{key}: expected a positive integer")
            result[key] = value
        elif key == "quote_digest":
            digest = _nonempty_string(value, f"{where}.{key}")
            if not DIGEST_RE.fullmatch(digest):
                raise CorpusError(f"{where}.{key}: expected sha256:<64 lowercase hex characters>")
            result[key] = digest
        elif key == "path":
            result[key] = _relative_posix_path(value, f"{where}.{key}")
        else:
            result[key] = _nonempty_string(value, f"{where}.{key}")
    if "line_end" in result and "line_start" not in result:
        raise CorpusError(f"{where}.line_end: line_start is required")
    if "line_end" in result and result["line_end"] < result["line_start"]:
        raise CorpusError(f"{where}.line_end: must be at or after line_start")
    return result


def _validate_source(
    raw: Any, where: str, catalog: dict[str, CatalogSource]
) -> tuple[dict[str, Any], set[str]]:
    if not isinstance(raw, dict):
        raise CorpusError(f"{where}: source must be an object")
    _exact_keys(raw, {"id", "revision", "role", "locators"}, where)
    source_id = _nonempty_string(raw["id"], f"{where}.id")
    if source_id not in catalog:
        raise CorpusError(f"{where}.id: unknown catalog source {source_id!r}")
    revision = _revision(raw["revision"], f"{where}.revision")
    if revision.kind != catalog[source_id].revision.kind:
        raise CorpusError(
            f"{where}.revision.kind: expected {catalog[source_id].revision.kind!r} "
            f"for source {source_id!r}"
        )
    role = _nonempty_string(raw["role"], f"{where}.role")
    if role not in SOURCE_ROLES:
        raise CorpusError(f"{where}.role: unsupported role {role!r}")
    locators_raw = raw["locators"]
    if not isinstance(locators_raw, list):
        raise CorpusError(f"{where}.locators: expected an array")
    locators: list[dict[str, Any]] = []
    refs: set[str] = set()
    for index, locator_raw in enumerate(locators_raw):
        locator_where = f"{where}.locators[{index}]"
        locator = _validate_locator(locator_raw, locator_where)
        ref = f"{source_id}:{locator['id']}"
        if ref in refs:
            raise CorpusError(f"{locator_where}.id: duplicate evidence locator {ref}")
        refs.add(ref)
        locators.append(locator)
    return {
        "id": source_id,
        "revision": revision.as_dict(),
        "role": role,
        "locators": locators,
    }, refs


def _load_record(
    path: Path,
    data: bytes,
    paths: CorpusPaths,
    catalog: dict[str, CatalogSource],
    taxonomy: Taxonomy,
    record_schema: dict[str, Any],
) -> ResearchRecord:
    raw, body, content_hash = _split_record(path, data)
    _validate_against_schema(raw, record_schema, record_schema, str(path))
    required = {
        "schema",
        "id",
        "kind",
        "status",
        "title",
        "question",
        "summary",
        "facets",
        "sources",
        "claims",
        "relations",
        "consumers",
        "verified_at",
        "revalidate_when",
    }
    _exact_keys(raw, required, str(path))
    if raw["schema"] != DOCUMENT_SCHEMA:
        raise CorpusError(f"{path}: unsupported schema {raw['schema']!r}")
    record_id = _nonempty_string(raw["id"], f"{path}: id")
    if not RECORD_ID_RE.fullmatch(record_id) or path.stem != record_id:
        raise CorpusError(f"{path}: id must match the canonical record id and file name")
    kind = _nonempty_string(raw["kind"], f"{path}: kind")
    status = _nonempty_string(raw["status"], f"{path}: status")
    if kind not in KINDS:
        raise CorpusError(f"{path}: unsupported kind {kind!r}")
    if status not in STATUSES:
        raise CorpusError(f"{path}: unsupported status {status!r}")

    facets_raw = raw["facets"]
    if not isinstance(facets_raw, dict):
        raise CorpusError(f"{path}: facets must be an object")
    _exact_keys(facets_raw, set(AXES), f"{path}: facets")
    facets: dict[str, tuple[str, ...]] = {}
    for axis in AXES:
        values = _string_list(facets_raw[axis], f"{path}: facets.{axis}", token=True)
        unknown = [value for value in values if value not in taxonomy.axes[axis]]
        if unknown:
            raise CorpusError(
                f"{path}: facets.{axis} contains unknown value(s): {', '.join(unknown)}"
            )
        facets[axis] = values

    sources_raw = raw["sources"]
    if not isinstance(sources_raw, list):
        raise CorpusError(f"{path}: sources must be an array")
    sources: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    evidence_refs: set[str] = set()
    for index, source_raw in enumerate(sources_raw):
        source, refs = _validate_source(source_raw, f"{path}: sources[{index}]", catalog)
        if source["id"] in source_ids:
            raise CorpusError(f"{path}: source {source['id']!r} is declared more than once")
        source_ids.add(source["id"])
        sources.append(source)
        evidence_refs.update(refs)
    if status == "reviewed" and any(not source["locators"] for source in sources):
        raise CorpusError(f"{path}: every reviewed source requires a precise locator")

    claims_raw = raw["claims"]
    if not isinstance(claims_raw, list):
        raise CorpusError(f"{path}: claims must be an array")
    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    for index, claim_raw in enumerate(claims_raw):
        where = f"{path}: claims[{index}]"
        if not isinstance(claim_raw, dict):
            raise CorpusError(f"{where}: claim must be an object")
        _exact_keys(claim_raw, {"id", "type", "statement", "evidence"}, where)
        claim_id = _nonempty_string(claim_raw["id"], f"{where}.id")
        if not TOKEN_RE.fullmatch(claim_id) or claim_id in claim_ids:
            raise CorpusError(f"{where}.id: expected a unique lowercase token")
        claim_ids.add(claim_id)
        claim_type = _nonempty_string(claim_raw["type"], f"{where}.type")
        if claim_type not in CLAIM_TYPES:
            raise CorpusError(f"{where}.type: unsupported claim type {claim_type!r}")
        evidence = _string_list(claim_raw["evidence"], f"{where}.evidence")
        unknown_evidence = [ref for ref in evidence if ref not in evidence_refs]
        if unknown_evidence:
            raise CorpusError(
                f"{where}.evidence: unknown locator(s): {', '.join(unknown_evidence)}"
            )
        if status == "reviewed" and claim_type == "observation" and not evidence:
            raise CorpusError(f"{where}: a reviewed observation requires evidence")
        claims.append(
            {
                "id": claim_id,
                "type": claim_type,
                "statement": _nonempty_string(claim_raw["statement"], f"{where}.statement"),
                "evidence": list(evidence),
            }
        )

    relations_raw = raw["relations"]
    if not isinstance(relations_raw, dict):
        raise CorpusError(f"{path}: relations must be an object")
    _exact_keys(relations_raw, set(RELATION_TYPES), f"{path}: relations")
    relations: dict[str, tuple[str, ...]] = {}
    for relation in RELATION_TYPES:
        targets = _string_list(relations_raw[relation], f"{path}: relations.{relation}")
        if record_id in targets:
            raise CorpusError(f"{path}: relations.{relation} cannot refer to itself")
        relations[relation] = targets

    consumers = tuple(
        _relative_posix_path(value, f"{path}: consumers[]")
        for value in _string_list(raw["consumers"], f"{path}: consumers")
    )
    verified_at = _nonempty_string(raw["verified_at"], f"{path}: verified_at")
    if not FULL_DATE_RE.fullmatch(verified_at):
        raise CorpusError(f"{path}: verified_at must be YYYY-MM-DD")
    try:
        dt.date.fromisoformat(verified_at)
    except ValueError as exc:
        raise CorpusError(f"{path}: verified_at must be YYYY-MM-DD") from exc
    revalidate_when = _string_list(raw["revalidate_when"], f"{path}: revalidate_when")

    if status == "reviewed":
        if not sources or not claims:
            raise CorpusError(f"{path}: a reviewed record requires sources and claims")
        if not any(claim["type"] == "observation" for claim in claims):
            raise CorpusError(
                f"{path}: a reviewed record requires an evidence-backed observation"
            )
        if not revalidate_when:
            raise CorpusError(
                f"{path}: a reviewed record requires at least one revalidation trigger"
            )
        if kind == "comparison" and len(source_ids) < 2:
            raise CorpusError(f"{path}: a reviewed comparison requires two catalog sources")
    if status == "superseded" and not relations["superseded_by"]:
        raise CorpusError(f"{path}: a superseded record must name its successor")

    # The catalog pin is the staleness reference for external sources. The
    # local repository advances every commit, so its records are graded by
    # per-path drift (research.py status) instead of a catalog comparison
    # that would flag everything forever.
    health = tuple(
        sorted(
            f"source-revision-stale:{source['id']}"
            for source in sources
            if catalog[source["id"]].kind != "local-repository"
            and source["revision"] != catalog[source["id"]].revision.as_dict()
        )
    )
    return ResearchRecord(
        id=record_id,
        kind=kind,
        status=status,
        title=_nonempty_string(raw["title"], f"{path}: title"),
        question=_nonempty_string(raw["question"], f"{path}: question"),
        summary=_nonempty_string(raw["summary"], f"{path}: summary"),
        facets=facets,
        sources=tuple(sources),
        claims=tuple(claims),
        relations=relations,
        consumers=consumers,
        verified_at=verified_at,
        revalidate_when=revalidate_when,
        body=body,
        path=path,
        relative_path=paths.logical_input_path(path),
        content_hash=content_hash,
        health=health,
    )


def _validate_relations(records: dict[str, ResearchRecord]) -> None:
    for record in records.values():
        for relation, targets in record.relations.items():
            missing = [target for target in targets if target not in records]
            if missing:
                raise CorpusError(
                    f"{record.path}: relations.{relation} names missing record(s): "
                    f"{', '.join(missing)}"
                )
        for target in record.relations["supersedes"]:
            if record.id not in records[target].relations["superseded_by"]:
                raise CorpusError(
                    f"{record.path}: supersedes {target}, but the target lacks "
                    f"superseded_by {record.id}"
                )
        for successor in record.relations["superseded_by"]:
            if record.id not in records[successor].relations["supersedes"]:
                raise CorpusError(
                    f"{record.path}: superseded_by {successor}, but the successor lacks "
                    f"supersedes {record.id}"
                )


def _input_hash(paths: CorpusPaths, inputs: dict[Path, bytes]) -> str:
    digest = hashlib.sha256()
    for path, data in sorted(
        inputs.items(), key=lambda item: paths.logical_input_path(item[0])
    ):
        relative = paths.logical_input_path(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _canonical_layout(
    paths: CorpusPaths,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[tuple[str, str], ...]]:
    for directory, purpose in (
        (paths.catalog, "canonical catalog input"),
        (paths.records, "canonical record input"),
    ):
        declared_root = paths.docs if directory == paths.records else paths.corpus
        assert_plain_contained_path(declared_root, directory, purpose=purpose)
        if not directory.is_dir():
            raise CorpusError(f"missing canonical input directory: {directory}")

    catalog_entries = sorted(paths.catalog.iterdir(), key=lambda item: item.name)
    record_entries = sorted(paths.records.iterdir(), key=lambda item: item.name)
    for path in (*catalog_entries, *record_entries):
        purpose = (
            "canonical catalog input"
            if path.parent == paths.catalog
            else "canonical record input"
        )
        declared_root = paths.docs if path.parent == paths.records else paths.corpus
        assert_plain_contained_path(declared_root, path, purpose=purpose)

    invalid_catalog = [
        path for path in catalog_entries if not path.is_file() or path.suffix != ".json"
    ]
    if invalid_catalog:
        names = ", ".join(path.name for path in invalid_catalog)
        raise CorpusError(
            f"catalog accepts only flat JSON manifests; unexpected entry(s): {names}"
        )
    nested_records = [path for path in record_entries if path.is_dir()]
    if nested_records:
        names = ", ".join(path.name for path in nested_records)
        raise CorpusError(
            "nested research records are not supported; place stable record files "
            f"directly under docs/records: {names}"
        )
    invalid_records = [
        path
        for path in record_entries
        if path.is_file() and path.suffix != ".md"
    ]
    if invalid_records:
        names = ", ".join(path.name for path in invalid_records)
        raise CorpusError(
            f"record storage accepts only Markdown files; unexpected entry(s): {names}"
        )
    record_paths = tuple(
        path for path in record_entries if path.is_file() and path.name != "_index.md"
    )
    signature = tuple(
        sorted(
            (
                paths.logical_input_path(path),
                "directory" if path.is_dir() else "file",
            )
            for path in (*catalog_entries, *record_entries)
        )
    )
    return tuple(catalog_entries), record_paths, signature


def _capture_canonical_inputs(
    paths: CorpusPaths,
) -> tuple[dict[Path, bytes], tuple[Path, ...], tuple[Path, ...]]:
    catalog_paths, record_paths, before_layout = _canonical_layout(paths)
    file_paths = (
        paths.taxonomy,
        paths.record_schema,
        *catalog_paths,
        *record_paths,
    )
    for path in file_paths:
        declared_root = paths.docs if path in record_paths else paths.corpus
        assert_plain_contained_path(
            declared_root, path, purpose="canonical research input"
        )
        if not path.is_file():
            raise CorpusError(f"missing canonical input file: {path}")

    def capture() -> dict[Path, bytes]:
        result: dict[Path, bytes] = {}
        for path in file_paths:
            try:
                result[path] = path.read_bytes()
            except OSError as exc:
                raise CorpusError(f"cannot capture canonical input {path}: {exc}") from exc
        return result

    first = capture()
    second = capture()
    after_catalog, after_records, after_layout = _canonical_layout(paths)
    if (
        first != second
        or before_layout != after_layout
        or catalog_paths != after_catalog
        or record_paths != after_records
    ):
        raise CorpusError("canonical research inputs changed while being read; try again")
    return second, catalog_paths, record_paths


def load_corpus(paths: CorpusPaths) -> Corpus:
    inputs, catalog_paths, record_paths = _capture_canonical_inputs(paths)
    sources = _load_catalog(paths, inputs, catalog_paths)
    taxonomy = _load_taxonomy(paths, inputs)
    assert_plain_contained_path(
        paths.corpus, paths.record_schema, purpose="canonical schema input"
    )
    record_schema = _read_json(paths.record_schema, inputs[paths.record_schema])
    _check_supported_schema(record_schema, str(paths.record_schema))

    records: dict[str, ResearchRecord] = {}
    for path in record_paths:
        record = _load_record(
            path, inputs[path], paths, sources, taxonomy, record_schema
        )
        if record.id in records:
            raise CorpusError(f"{path}: duplicate research record id {record.id}")
        records[record.id] = record
    _validate_relations(records)

    return Corpus(
        paths=paths,
        sources=sources,
        taxonomy=taxonomy,
        records=records,
        input_hash=_input_hash(paths, inputs),
    )


def record_as_ir(record: ResearchRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind,
        "status": record.status,
        "title": record.title,
        "question": record.question,
        "summary": record.summary,
        "facets": {axis: list(record.facets[axis]) for axis in AXES},
        "sources": list(record.sources),
        "claims": list(record.claims),
        "relations": {relation: list(record.relations[relation]) for relation in RELATION_TYPES},
        "consumers": list(record.consumers),
        "verified_at": record.verified_at,
        "revalidate_when": list(record.revalidate_when),
        "body": record.body,
        "path": record.relative_path,
        "content_hash": record.content_hash,
        "health": list(record.health),
    }


def stable_json(value: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
