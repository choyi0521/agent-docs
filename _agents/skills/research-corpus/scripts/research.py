#!/usr/bin/env python3
"""Validate, index, search, and render the tracked research knowledge base."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import subprocess
import tempfile
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from research_index.corpus import (
    AXES, RELATION_TYPES, Corpus, CorpusError, CorpusPaths,
    assert_no_redirecting_ancestors, assert_plain_contained_path, load_corpus, stable_json,
)
from research_index.index import build_index, current_snapshot
from research_index.query import response_as_json, search
from research_index.views import render_views


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build disposable search projections from tracked research documents."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="explicit research corpus root",
    )
    parser.add_argument(
        "--docs-root",
        type=Path,
        help=(
            "authored record and generated navigation root (defaults to <corpus>/docs)"
        ),
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        help="derived index root (defaults to <corpus>/cache/index)",
    )
    parser.add_argument("--repository-root", type=Path,
                        help="explicit consumer Git repository for local citation status")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="initialize a new, absent corpus directory")
    new = commands.add_parser("new", help="create a new draft research record")
    new.add_argument("slug", help="lowercase hyphenated question name")
    new.add_argument("--title", required=True)
    new.add_argument("--question", required=True)

    commands.add_parser("validate", help="validate canonical records and all foreign keys")

    status = commands.add_parser(
        "status",
        help=(
            "show records whose cited revisions differ from the catalog, and "
            "local-repository citations whose paths changed since the cited commit"
        ),
    )
    status.add_argument("--all", action="store_true", help="include catalog-current records")
    status.add_argument("--json", action="store_true", dest="as_json")

    build = commands.add_parser("build", help="build a new immutable search snapshot")
    build.add_argument(
        "--clean",
        action="store_true",
        help="construct and verify a complete candidate without relying on a prior index",
    )

    query = commands.add_parser("search", help="query the current validated index")
    query.add_argument("query", help="question, id, source, path, symbol, or search terms")
    query.add_argument("--domain", action="append", default=[])
    query.add_argument("--mechanism", action="append", default=[])
    query.add_argument("--quality", action="append", default=[])
    query.add_argument("--platform", action="append", default=[])
    query.add_argument("--include-inactive", action="store_true")
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--json", action="store_true", dest="as_json")
    query.add_argument("--explain", action="store_true")
    query.add_argument(
        "--ephemeral",
        action="store_true",
        help="build and query a disposable index outside the corpus, then remove it",
    )

    render = commands.add_parser("render", help="regenerate taxonomy and record navigation")
    render.add_argument("--check", action="store_true", help="fail instead of writing on drift")
    return parser


def _load(args: argparse.Namespace) -> tuple[Corpus, Path]:
    corpus_path = args.corpus.absolute()
    docs_root = args.docs_root.absolute() if args.docs_root is not None else None
    corpus = load_corpus(CorpusPaths(corpus_path, docs_root))
    index_root = (args.index_root or corpus.paths.default_index).absolute()
    return corpus, index_root


def _initialize(args: argparse.Namespace) -> Path:
    target = args.corpus.absolute()
    if args.docs_root is not None or args.index_root is not None:
        raise CorpusError("init uses <corpus>/docs and <corpus>/cache; configure overrides later")
    assert_no_redirecting_ancestors(target, purpose="new research corpus")
    if os.path.lexists(target):
        raise CorpusError(f"init requires a new, absent target directory: {target}")
    assets = {
        name: (ASSETS / name).read_text(encoding="utf-8")
        for name in ("research-record.schema.json", "taxonomy.json")
    }
    # Exclusive creation refuses existing user data, including an empty directory.
    target.mkdir(parents=True, exist_ok=False)
    for relative in ("catalog", "schemas", "docs/records"):
        (target / relative).mkdir(parents=True, exist_ok=False)
    for name, content in assets.items():
        (target / "schemas" / name).write_text(content, encoding="utf-8", newline="\n")
    (target / "docs" / "_index.md").write_text(
        "---\nnav:\n  - records/\n  - views/\n---\n# Research\n\n"
        "Research records preserve questions, evidence, and conclusions. "
        "Browse the records or their generated topic and source views.\n",
        encoding="utf-8", newline="\n",
    )
    (target / ".gitignore").write_text("/cache/\n", encoding="utf-8", newline="\n")
    return target


def _new_record(corpus: Corpus, slug: str, title: str, question: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise CorpusError("slug must use lowercase letters, digits, and single hyphens")
    if not title.strip() or not question.strip() or any(c in title for c in "\r\n"):
        raise CorpusError("title must be one nonempty line and question must be nonempty")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    record_id = f"rr-{today}-{slug}-{secrets.token_hex(4)}"
    path = corpus.paths.records / f"{record_id}.md"
    assert_no_redirecting_ancestors(path, purpose="new research record")
    assert_plain_contained_path(corpus.paths.docs, path, purpose="new research record")
    metadata = {
        "schema": "research/v2", "id": record_id, "kind": "study", "status": "draft",
        "title": title.strip(), "question": question.strip(),
        "summary": "Draft: evidence has not been collected or reviewed.",
        "facets": {axis: [] for axis in AXES}, "sources": [], "claims": [],
        "relations": {relation: [] for relation in RELATION_TYPES}, "consumers": [],
        "verified_at": today, "revalidate_when": [],
    }
    text = "---\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n---\n"
    text += f"# {title.strip()}\n\n## Context and constraints\n\n{question.strip()}\n\n"
    text += ("## Observations\n\nNo evidence has been reviewed yet.\n\n"
             "## Interpretation\n\nNo conclusion yet.\n\n"
             "## Recommendation and uncertainty\n\nRecord the remaining questions after inspection.\n")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return path


def _manifest(snapshot: Path) -> dict[str, Any]:
    try:
        value = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{snapshot}: cannot read index manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise CorpusError(f"{snapshot}: index manifest must be an object")
    return value


@contextmanager
def _attested_snapshot(corpus: Corpus, index_root: Path) -> Iterator[Path]:
    snapshot = current_snapshot(index_root)
    manifest = _manifest(snapshot)
    with tempfile.TemporaryDirectory(prefix="research-attestation-") as temporary:
        expected_snapshot = build_index(corpus, Path(temporary), clean=True)
        expected_manifest = _manifest(expected_snapshot)
        if manifest != expected_manifest:
            raise CorpusError(
                "research index is stale or does not match a canonical rebuild; run build"
            )
        # Query the private canonical candidate, not the shared store that was
        # just attested. This closes the validation/use gap for concurrent tools.
        yield expected_snapshot


def _print_response(response: Any, explain: bool) -> None:
    interpreted = [
        f"{axis}={','.join(values)}"
        for axis, values in response.interpreted_facets.items()
        if values
    ]
    filters = [
        f"{axis}={','.join(values)}" for axis, values in response.filters.items() if values
    ]
    print(f"coverage: {response.coverage}")
    if interpreted:
        print(f"interpreted: {'; '.join(interpreted)}")
    elif explain:
        print("interpreted: none (free text only; no controlled facet inferred)")
    if filters:
        print(f"filters: {'; '.join(filters)}")
    if not response.results:
        print(
            "no matching research record; confirm the question and constraints "
            "before new research"
        )
    for index, result in enumerate(response.results, start=1):
        record = result.record
        health = ", ".join(record["health"]) if record["health"] else "catalog-current"
        print(
            f"{index}. {record['title']} [{record['id']}] "
            f"{record['kind']}/{record['status']} health={health}"
        )
        print(f"   {record['summary']}")
        print(f"   path: {record['path']}")
        if explain:
            print(f"   channels: {', '.join(result.channels) or 'none'}")
            if result.matched_facets:
                print(f"   matched facets: {', '.join(result.matched_facets)}")
            if result.relation_paths:
                print(f"   relation paths: {'; '.join(result.relation_paths)}")
            for source in record["sources"]:
                revision = source["revision"]
                print(
                    f"   source: {source['id']}@{revision['kind']}:{revision['value']}"
                )
            for locator in record["locators"]:
                coordinates = ", ".join(
                    f"{key}={value}"
                    for key, value in locator.items()
                    if key not in {"source", "id", "kind"}
                )
                print(
                    f"   locator: {locator['source']}:{locator['id']} "
                    f"{locator['kind']} {coordinates}"
                )
    if response.source_candidates:
        print(f"catalog source candidates ({response.source_candidate_scope}):")
        for source in response.source_candidates:
            revision = source["revision"]
            print(
                f"- {source['name']} "
                f"[{source['id']}@{revision['kind']}:{revision['value']}] "
                f"topics={','.join(source['topics'])} via={','.join(source['channels'])}"
            )


def _git(repository_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    # Local evidence must be inspected in the caller's repository, not the
    # installed tool directory or an ambient GIT_DIR/GIT_WORK_TREE override.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
                        "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repository_root),
         "-c", "core.fsmonitor=false", *arguments],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=environment, timeout=15,
    )


def _local_path_drift(
    pinned: str, path: str, cache: dict[tuple[str, str], dict[str, Any]],
    *, repository_root: Path | None = None,
) -> dict[str, Any]:
    key = (pinned, path)
    if key in cache:
        return cache[key]
    if repository_root is None:
        result: dict[str, Any] = {
            "state": "unverifiable", "detail": "--repository-root is required for local evidence"
        }
    elif not (repository_root / path).exists():
        result = {"state": "unverifiable", "detail": "cited path is missing from the working tree"}
    else:
        try:
            exists = _git(repository_root, "cat-file", "-e", f"{pinned}:{path}")
            ancestor = _git(repository_root, "merge-base", "--is-ancestor", pinned, "HEAD")
            if exists.returncode or ancestor.returncode:
                result = {"state": "unverifiable",
                          "detail": "cited path or ancestor commit is unavailable"}
            else:
                literal = f":(literal){path}"
                history = _git(repository_root, "log", "--format=%H", f"{pinned}..HEAD",
                               "--", literal)
                dirty = _git(repository_root, "status", "--porcelain=v1",
                             "--untracked-files=all", "--ignore-submodules=none", "--", literal)
                tracked = _git(repository_root, "ls-files", "-v", "-z", "--", literal)
                hidden = any(entry and (entry[0].islower() or entry[0] == "S")
                             for entry in tracked.stdout.split("\0"))
                if history.returncode or dirty.returncode or tracked.returncode:
                    result = {"state": "unverifiable", "detail": "Git evidence status failed"}
                elif hidden:
                    result = {"state": "unverifiable",
                              "detail": "cited path uses assume-unchanged or skip-worktree flags"}
                else:
                    commits = history.stdout.split()
                    result = ({"state": "drifted", "changes": len(commits)}
                              if commits or dirty.stdout else {"state": "current"})
                    if dirty.stdout:
                        result["dirty"] = True
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"state": "unverifiable", "detail": f"cannot run Git: {exc}"}
    cache[key] = result
    return result


def _record_statuses(corpus: Corpus, include_current: bool,
                     repository_root: Path | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    drift_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for record in sorted(corpus.records.values(), key=lambda value: value.id):
        sources: list[dict[str, Any]] = []
        for cited in record.sources:
            catalog_source = corpus.sources[cited["id"]]
            if catalog_source.kind == "local-repository":
                pinned = cited["revision"]["value"]
                paths = sorted(
                    {locator["path"] for locator in cited["locators"] if "path" in locator}
                )
                drift = [
                    {"path": path, **_local_path_drift(
                        pinned, path, drift_cache, repository_root=repository_root)}
                    for path in paths
                ]
                sources.append(
                    {
                        "id": cited["id"],
                        "cited_revision": cited["revision"],
                        "catalog_revision": None,
                        "current": bool(drift) and all(entry["state"] == "current" for entry in drift),
                        "local_drift": drift,
                    }
                )
                continue
            current = catalog_source.revision.as_dict()
            sources.append(
                {
                    "id": cited["id"],
                    "cited_revision": cited["revision"],
                    "catalog_revision": current,
                    "current": cited["revision"] == current,
                }
            )
        state = "current" if all(source["current"] for source in sources) else "revalidation-required"
        if include_current or state != "current":
            results.append(
                {
                    "id": record.id,
                    "title": record.title,
                    "state": state,
                    "verified_at": record.verified_at,
                    "revalidate_when": list(record.revalidate_when),
                    "sources": sources,
                }
            )
    return results


def _print_record_statuses(results: list[dict[str, Any]], as_json: bool) -> None:
    if as_json:
        print(stable_json(results, pretty=True), end="")
        return
    if not results:
        print("no cited source revision requires revalidation")
        return
    for result in results:
        print(
            f"{result['state']:<21} {result['id']} verified={result['verified_at']} "
            f"{result['title']}"
        )
        for source in result["sources"]:
            if source["current"] and result["state"] != "current":
                continue
            cited = source["cited_revision"]
            if source.get("local_drift") is not None:
                for entry in source["local_drift"]:
                    if entry["state"] == "current":
                        continue
                    detail = (
                        f"{entry['changes']} committed change(s) since the cited commit"
                        + ("; uncommitted changes present" if entry.get("dirty") else "")
                        if entry["state"] == "drifted"
                        else f"unverifiable: {entry['detail']}"
                    )
                    print(
                        f"  {source['id']}@{cited['value'][:12]}: {entry['path']} -> {detail}"
                    )
                continue
            current = source["catalog_revision"]
            marker = "=" if source["current"] else "->"
            print(
                f"  {source['id']}: {cited['kind']}:{cited['value']} {marker} "
                f"{current['kind']}:{current['value']}"
            )




def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            target = _initialize(args)
            print(f"initialized research corpus at {target}")
            return 0
        corpus, index_root = _load(args)
        if args.command == "new":
            path = _new_record(corpus, args.slug, args.title, args.question)
            print(corpus.paths.logical_input_path(path))
            return 0
        if args.command == "validate":
            stale = sum(bool(record.health) for record in corpus.records.values())
            print(
                f"validated {len(corpus.records)} research record(s), "
                f"{len(corpus.sources)} catalog source(s), {stale} stale record(s)"
            )
            return 0
        if args.command == "status":
            results = _record_statuses(corpus, args.all, args.repository_root)
            _print_record_statuses(results, args.as_json)
            return 0
        if args.command == "build":
            snapshot = build_index(corpus, index_root, clean=args.clean)
            manifest = _manifest(snapshot)
            print(
                f"built {manifest['build_id']} from {manifest['record_count']} record(s); "
                f"logical {manifest['logical_hash']}"
            )
            return 0
        if args.command == "search":
            filters = {
                "domains": args.domain,
                "mechanisms": args.mechanism,
                "qualities": args.quality,
                "platforms": args.platform,
            }
            if args.ephemeral:
                with tempfile.TemporaryDirectory(prefix="research-index-") as temporary:
                    snapshot = build_index(corpus, Path(temporary), clean=True)
                    response = search(
                        snapshot,
                        args.query,
                        filters=filters,
                        include_inactive=args.include_inactive,
                        limit=args.limit,
                    )
            else:
                with _attested_snapshot(corpus, index_root) as snapshot:
                    response = search(
                        snapshot,
                        args.query,
                        filters=filters,
                        include_inactive=args.include_inactive,
                        limit=args.limit,
                    )
            if args.as_json:
                print(stable_json(response_as_json(response), pretty=True), end="")
            else:
                _print_response(response, args.explain)
            return 0
        if args.command == "render":
            changed = render_views(corpus, check=args.check)
            if changed:
                for path in changed:
                    print(corpus.paths.logical_input_path(path))
                if args.check:
                    print("generated research views are stale", file=sys.stderr)
                    return 1
                print(f"rendered {len(changed)} changed research view file(s)")
            else:
                print("research views are current")
            return 0
        raise AssertionError(f"unhandled command {args.command}")
    except (CorpusError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
