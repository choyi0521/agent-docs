from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .corpus import AXES, CorpusError, normalize_text
from .index import read_only_sqlite_uri


RRF_K = 60
TOKENIZE_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)
HANGUL_RE = re.compile(r"[가-힣]")
KOREAN_PARTICLES = (
    "으로부터",
    "에게서",
    "께서",
    "에서",
    "으로",
    "처럼",
    "보다",
    "부터",
    "까지",
    "에게",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "의",
    "에",
    "로",
    "도",
    "만",
)
ENGLISH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "be",
    "can",
    "for",
    "how",
    "in",
    "of",
    "or",
    "the",
    "to",
    "with",
}


@dataclass(frozen=True)
class SearchResult:
    record: dict[str, Any]
    score: float
    exact: bool
    channels: tuple[str, ...]
    matched_facets: tuple[str, ...]
    relation_paths: tuple[str, ...]


@dataclass(frozen=True)
class SearchResponse:
    query: str
    interpreted_facets: dict[str, tuple[str, ...]]
    filters: dict[str, tuple[str, ...]]
    coverage: str
    results: tuple[SearchResult, ...]
    source_candidates: tuple[dict[str, Any], ...]
    source_candidate_scope: str


def _load_taxonomy(snapshot: Path) -> dict[str, Any]:
    try:
        value = json.loads((snapshot / "taxonomy.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{snapshot}: cannot read indexed taxonomy: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("axes"), dict):
        raise CorpusError(f"{snapshot}: invalid indexed taxonomy")
    return value


def _english_stem(token: str) -> str:
    token = token.casefold()
    if len(token) > 4 and token.endswith("ly"):
        token = token[:-2]
    if len(token) > 5 and token.endswith("ation"):
        token = token[:-5] + "ate"
    elif len(token) > 4 and token.endswith(("ated", "ized")):
        token = token[:-1]
    elif len(token) > 4 and token.endswith("ed"):
        token = token[:-2]
    elif len(token) > 4 and token.endswith("ing"):
        token = token[:-3]
    if len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token


def _english_terms(text: str) -> set[str]:
    return {
        stem
        for token in TOKENIZE_RE.findall(text)
        if token.isascii()
        for stem in (_english_stem(token),)
        if stem and stem not in ENGLISH_STOP_WORDS
    }


def _query_has_alias(query: str, alias: str) -> bool:
    if not alias:
        return False
    if HANGUL_RE.search(alias):
        particles = "|".join(re.escape(value) for value in KOREAN_PARTICLES)
        pattern = (
            rf"(?<![A-Za-z0-9가-힣]){re.escape(alias)}"
            rf"(?:(?:{particles}))?(?![A-Za-z0-9가-힣])"
        )
        return re.search(pattern, query, flags=re.IGNORECASE) is not None
    alias_terms = _english_terms(alias)
    return bool(alias_terms and alias_terms.issubset(_english_terms(query)))


def _interpret_facets(query: str, taxonomy: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    normalized = normalize_text(query)
    found: dict[str, set[str]] = {axis: set() for axis in AXES}
    aliases = taxonomy.get("aliases", {})
    if not isinstance(aliases, dict):
        raise CorpusError("indexed taxonomy aliases must be an object")
    # Prefer the most specific phrase first. A shorter alias may still add a
    # second legitimate facet, but it cannot erase the longer match.
    for alias in sorted(aliases, key=lambda value: (-len(value), value)):
        if not _query_has_alias(normalized, alias):
            continue
        targets = aliases[alias]
        if not isinstance(targets, list):
            continue
        for target in targets:
            if not isinstance(target, dict):
                continue
            axis, value = target.get("axis"), target.get("value")
            if axis in found and isinstance(value, str):
                found[axis].add(value)
    return {axis: tuple(sorted(found[axis])) for axis in AXES}


def _validate_filters(
    filters: dict[str, Iterable[str]], taxonomy: dict[str, Any]
) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    axes = taxonomy["axes"]
    for axis in AXES:
        values = tuple(dict.fromkeys(filters.get(axis, ())))
        unknown = [value for value in values if value not in axes[axis]]
        if unknown:
            raise CorpusError(f"unknown {axis} filter(s): {', '.join(unknown)}")
        normalized[axis] = values
    return normalized


def _load_records(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    rows = connection.execute(
        "SELECT id, kind, status, title, question, summary, path, verified_at, health FROM records"
    )
    for row in rows:
        records[row[0]] = {
            "id": row[0],
            "kind": row[1],
            "status": row[2],
            "title": row[3],
            "question": row[4],
            "summary": row[5],
            "path": row[6],
            "verified_at": row[7],
            "health": json.loads(row[8]),
            "facets": {axis: [] for axis in AXES},
            "sources": [],
            "locators": [],
        }
    for record_id, axis, value in connection.execute(
        "SELECT record_id, axis, value FROM facets ORDER BY record_id, axis, value"
    ):
        records[record_id]["facets"][axis].append(value)
    for record_id, source_id, revision_kind, revision_value, role in connection.execute(
        "SELECT record_id, source_id, revision_kind, revision_value, role FROM record_sources "
        "ORDER BY record_id, source_id"
    ):
        records[record_id]["sources"].append(
            {
                "id": source_id,
                "revision": {"kind": revision_kind, "value": revision_value},
                "role": role,
            }
        )
    for record_id, source_id, locator_id, locator_kind, coordinates in connection.execute(
        "SELECT record_id, source_id, locator_id, locator_kind, coordinates FROM locators "
        "ORDER BY record_id, source_id, locator_id"
    ):
        records[record_id]["locators"].append(
            {
                "source": source_id,
                "id": locator_id,
                "kind": locator_kind,
                **json.loads(coordinates),
            }
        )
    return records


def _eligible_ids(
    records: dict[str, dict[str, Any]],
    filters: dict[str, tuple[str, ...]],
    include_inactive: bool,
) -> set[str]:
    eligible: set[str] = set()
    for record_id, record in records.items():
        if not include_inactive and record["status"] in {"superseded", "retired"}:
            continue
        if any(
            not set(values).issubset(record["facets"][axis])
            for axis, values in filters.items()
            if values
        ):
            continue
        eligible.add(record_id)
    return eligible


def _lexical_tokens(
    query: str, interpreted: dict[str, tuple[str, ...]], taxonomy: dict[str, Any]
) -> tuple[str, ...]:
    tokens = [token.casefold() for token in TOKENIZE_RE.findall(query) if len(token) > 1]
    for axis in AXES:
        for value in interpreted[axis]:
            tokens.extend(part for part in value.split("-") if len(part) > 1)
            label = taxonomy["axes"][axis][value]["label"]
            tokens.extend(part.casefold() for part in TOKENIZE_RE.findall(label) if len(part) > 1)
    return tuple(dict.fromkeys(tokens))


def _fts_query(tokens: tuple[str, ...]) -> str:
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _rrf_add(
    scores: dict[str, float],
    channels: dict[str, list[str]],
    ranked: Iterable[str],
    channel: str,
) -> None:
    for rank, record_id in enumerate(dict.fromkeys(ranked), start=1):
        scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (RRF_K + rank)
        channels.setdefault(record_id, []).append(channel)


def _source_candidates(
    connection: sqlite3.Connection,
    query: str,
    tokens: tuple[str, ...],
    limit: int,
) -> tuple[dict[str, Any], ...]:
    normalized = normalize_text(query)
    rows = connection.execute(
        "SELECT id, name, source_kind, url, revision_kind, revision_value, "
        "revision_label, license, access, topics, notes, retrieved_at FROM catalog_sources"
    ).fetchall()
    by_id = {
        row[0]: {
            "id": row[0],
            "name": row[1],
            "kind": row[2],
            "url": row[3],
            "revision": {"kind": row[4], "value": row[5]},
            "revision_label": row[6],
            "license": row[7],
            "access": row[8],
            "topics": json.loads(row[9]),
            "notes": row[10],
            "retrieved_at": row[11],
            "channels": [],
        }
        for row in rows
    }
    exact = [
        source_id
        for source_id, source in by_id.items()
        if normalized in {normalize_text(source_id), normalize_text(source["name"])}
    ]
    lexical: list[str] = []
    if tokens:
        lexical = [
            row[0]
            for row in connection.execute(
                "SELECT source_id, bm25(catalog_sources_fts, 0.0, 5.0, 3.0, 1.0) "
                "AS relevance FROM catalog_sources_fts WHERE catalog_sources_fts MATCH ? "
                "ORDER BY relevance, source_id LIMIT 100",
                (_fts_query(tokens),),
            )
        ]
    scores: dict[str, float] = {}
    channels: dict[str, list[str]] = {}
    _rrf_add(scores, channels, sorted(exact), "exact")
    _rrf_add(scores, channels, lexical, "full-text")
    ranked = sorted(
        scores,
        key=lambda source_id: (
            0 if source_id in exact else 1,
            -scores[source_id],
            source_id,
        ),
    )[:limit]
    result: list[dict[str, Any]] = []
    for source_id in ranked:
        source = by_id[source_id]
        source["channels"] = list(dict.fromkeys(channels[source_id]))
        result.append(source)
    return tuple(result)


def search(
    snapshot: Path,
    query: str,
    *,
    filters: dict[str, Iterable[str]] | None = None,
    include_inactive: bool = False,
    limit: int = 10,
) -> SearchResponse:
    if limit < 1 or limit > 100:
        raise CorpusError("limit must be between 1 and 100")
    taxonomy = _load_taxonomy(snapshot)
    explicit_filters = _validate_filters(filters or {}, taxonomy)
    interpreted = _interpret_facets(query, taxonomy)
    database = snapshot / "search.sqlite3"
    try:
        connection = sqlite3.connect(read_only_sqlite_uri(database), uri=True)
    except sqlite3.Error as exc:
        raise CorpusError(f"cannot open research index {database}: {exc}") from exc
    try:
        records = _load_records(connection)
        eligible = _eligible_ids(records, explicit_filters, include_inactive)
        normalized_query = normalize_text(query)

        exact_ranked: list[str] = []
        exact_reasons: dict[str, list[str]] = {}
        for record_id in sorted(eligible):
            record = records[record_id]
            reasons: list[str] = []
            if normalized_query == normalize_text(record_id):
                reasons.append("record-id")
            if normalized_query and normalized_query == normalize_text(record["title"]):
                reasons.append("title")
            for source in record["sources"]:
                if normalized_query == normalize_text(source["id"]):
                    reasons.append(f"source:{source['id']}")
            for locator in record["locators"]:
                coordinate_values = (
                    str(value)
                    for key, value in locator.items()
                    if key not in {"source", "id", "kind"}
                )
                if normalized_query and normalized_query in {
                    normalize_text(value)
                    for value in (
                        *coordinate_values,
                        f"{locator['source']}:{locator['id']}",
                    )
                }:
                    reasons.append(f"locator:{locator['source']}:{locator['id']}")
            if reasons:
                exact_ranked.append(record_id)
                exact_reasons[record_id] = reasons

        inferred_values = {
            axis: set(values) for axis, values in interpreted.items() if values
        }
        facet_ranked = sorted(
            eligible,
            key=lambda record_id: (
                -sum(
                    len(set(records[record_id]["facets"][axis]) & values)
                    for axis, values in inferred_values.items()
                ),
                record_id,
            ),
        )
        facet_ranked = [
            record_id
            for record_id in facet_ranked
            if any(
                set(records[record_id]["facets"][axis]) & values
                for axis, values in inferred_values.items()
            )
        ]

        tokens = _lexical_tokens(query, interpreted, taxonomy)
        source_candidates = _source_candidates(connection, query, tokens, limit)
        lexical_ranked: list[str] = []
        if tokens:
            rows = connection.execute(
                "SELECT record_id, bm25(records_fts, 0.0, 8.0, 7.0, 5.0, 4.0, "
                "1.0, 3.0, 2.0, 4.0, 2.0) AS relevance "
                "FROM records_fts WHERE records_fts MATCH ? "
                "ORDER BY relevance, record_id",
                (_fts_query(tokens),),
            )
            for row in rows:
                if row[0] in eligible:
                    lexical_ranked.append(row[0])
                    if len(lexical_ranked) == 200:
                        break

        seed_ids = list(dict.fromkeys((*exact_ranked, *facet_ranked[:5], *lexical_ranked[:5])))
        graph_ranked: list[str] = []
        relation_paths: dict[str, list[str]] = {}
        for seed in seed_ids:
            outgoing = connection.execute(
                "SELECT target_id, relation FROM relations WHERE record_id = ? ORDER BY 1, 2",
                (seed,),
            )
            for neighbor, relation in outgoing:
                if neighbor not in eligible or neighbor in seed_ids:
                    continue
                graph_ranked.append(neighbor)
                relation_paths.setdefault(neighbor, []).append(
                    f"{seed} --{relation}--> {neighbor}"
                )
            incoming = connection.execute(
                "SELECT record_id, relation FROM relations WHERE target_id = ? ORDER BY 1, 2",
                (seed,),
            )
            for neighbor, relation in incoming:
                if neighbor not in eligible or neighbor in seed_ids:
                    continue
                graph_ranked.append(neighbor)
                relation_paths.setdefault(neighbor, []).append(
                    f"{neighbor} --{relation}--> {seed}"
                )

        scores: dict[str, float] = {}
        channels: dict[str, list[str]] = {}
        _rrf_add(scores, channels, exact_ranked, "exact")
        _rrf_add(scores, channels, facet_ranked, "facet")
        _rrf_add(scores, channels, lexical_ranked, "full-text")
        _rrf_add(scores, channels, graph_ranked, "relation")

        if not query.strip() and any(explicit_filters.values()):
            _rrf_add(scores, channels, sorted(eligible), "filter")

        exact_set = set(exact_ranked)
        ranked_ids = sorted(
            (record_id for record_id in scores if record_id in eligible),
            key=lambda record_id: (
                0 if record_id in exact_set else 1,
                -scores[record_id],
                record_id,
            ),
        )[:limit]
        results: list[SearchResult] = []
        for record_id in ranked_ids:
            matched: list[str] = []
            for axis, values in interpreted.items():
                for value in sorted(set(records[record_id]["facets"][axis]) & set(values)):
                    matched.append(f"{axis}:{value}")
            result_channels = list(dict.fromkeys(channels.get(record_id, ())))
            result_channels.extend(exact_reasons.get(record_id, ()))
            results.append(
                SearchResult(
                    record=records[record_id],
                    score=scores[record_id],
                    exact=record_id in exact_set,
                    channels=tuple(result_channels),
                    matched_facets=tuple(matched),
                    relation_paths=tuple(sorted(set(relation_paths.get(record_id, ())))),
                )
            )

        if not results:
            coverage = "no-record-source-candidates" if source_candidates else "none"
        elif any(
            result.record["status"] == "reviewed" and not result.record["health"]
            for result in results
        ):
            coverage = "reviewed-catalog-current-candidates"
        else:
            coverage = "partial-or-stale-candidates"
        return SearchResponse(
            query=query,
            interpreted_facets=interpreted,
            filters=explicit_filters,
            coverage=coverage,
            results=tuple(results),
            source_candidates=source_candidates,
            source_candidate_scope=(
                "lexical catalog discovery only; research-record facet filters do not apply"
            ),
        )
    except sqlite3.Error as exc:
        raise CorpusError(f"research query failed: {exc}") from exc
    finally:
        connection.close()


def response_as_json(response: SearchResponse) -> dict[str, Any]:
    return {
        "query": response.query,
        "interpreted_facets": {
            axis: list(response.interpreted_facets[axis]) for axis in AXES
        },
        "filters": {axis: list(response.filters[axis]) for axis in AXES},
        "coverage": response.coverage,
        "source_candidate_scope": response.source_candidate_scope,
        "results": [
            {
                **result.record,
                "score": result.score,
                "exact": result.exact,
                "channels": list(result.channels),
                "matched_facets": list(result.matched_facets),
                "relation_paths": list(result.relation_paths),
            }
            for result in response.results
        ],
        "source_candidates": list(response.source_candidates),
    }
