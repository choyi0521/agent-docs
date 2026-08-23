#!/usr/bin/env python3
"""Validate canonical agent guidance and every generated discovery surface.

The checker derives its exact file set from the v2 manifests. It verifies the
strict generation/publication intersection, public-content safety, deterministic
output drift, and local Markdown links without recursively discovering new
packages.

    python -B tools/check_agent_instructions.py
    python -B tools/check_agent_instructions.py --list
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import urllib.parse

import sync_agent_instructions as sync


ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)\s]+)")
SAFE_EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})
UNSAFE_SCHEMES = frozenset({"data", "file", "javascript", "vbscript"})


def _relative(repo: pathlib.Path, path: pathlib.Path) -> pathlib.PurePosixPath:
    try:
        return pathlib.PurePosixPath(path.absolute().relative_to(repo.absolute()).as_posix())
    except ValueError as error:
        raise sync.GenerationError(f"path escapes the repository: {path}") from error


def _covered_files(repo: pathlib.Path, result: sync.BuildResult) -> list[pathlib.Path]:
    covered: dict[str, pathlib.Path] = {}
    for relative in result.canonical_markdown:
        path = repo.joinpath(*relative.parts)
        covered[relative.as_posix()] = path
    readme = pathlib.PurePosixPath("_agents/README.md")
    readme_path = repo.joinpath(*readme.parts)
    if readme_path.is_file():
        covered[readme.as_posix()] = readme_path
    for relative in result.outputs:
        if relative.suffix.casefold() != ".md":
            continue
        path = repo.joinpath(*relative.parts)
        if path.is_file():
            covered[relative.as_posix()] = path
    return [covered[key] for key in sorted(covered)]


def _local_target(raw_target: str) -> str:
    target = raw_target
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return urllib.parse.unquote(target.split("#", 1)[0].split("?", 1)[0])


def _markdown_link_problems(repo: pathlib.Path, path: pathlib.Path, text: str) -> list[str]:
    problems: list[str] = []
    source = _relative(repo, path).as_posix()
    seen: set[str] = set()
    for match in MARKDOWN_LINK.finditer(text):
        raw_target = match.group("target")
        if raw_target in seen:
            continue
        seen.add(raw_target)
        if raw_target.startswith("#"):
            continue
        parsed = urllib.parse.urlsplit(raw_target)
        scheme = parsed.scheme.casefold()
        if scheme in SAFE_EXTERNAL_SCHEMES:
            continue
        if scheme in UNSAFE_SCHEMES or (scheme and len(scheme) > 1):
            problems.append(f"{source}: unsafe Markdown link scheme: {raw_target}")
            continue
        target = _local_target(raw_target)
        if not target:
            continue
        if "\\" in target or target.startswith("/") or re.match(r"^[A-Za-z]:", target):
            problems.append(f"{source}: local link is not repository-relative: {raw_target}")
            continue
        candidate = pathlib.Path(os.path.abspath(path.parent / pathlib.Path(target)))
        try:
            relative = _relative(repo, candidate)
        except sync.GenerationError:
            problems.append(f"{source}: local link escapes the repository: {raw_target}")
            continue
        if not candidate.exists():
            problems.append(f"{source}: dead local link: {raw_target}")
            continue
        try:
            sync._resolve_existing_exact(  # The checker shares the generator's casing contract.
                repo,
                relative,
                label=f"Markdown link in {source}",
                expect_directory=candidate.is_dir(),
            )
        except sync.GenerationError as error:
            problems.append(f"{source}: invalid local link {raw_target}: {error}")
    return problems


def check_repository(repo: pathlib.Path = ROOT) -> tuple[list[pathlib.Path], list[str]]:
    repo = repo.absolute()
    result = sync.build_outputs(repo)
    files = _covered_files(repo, result)
    problems = sync.check_outputs(repo, result)
    for path in files:
        relative = _relative(repo, path).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            sync.validate_public_text(text, label=relative)
        except (OSError, UnicodeError, sync.GenerationError) as error:
            problems.append(f"{relative}: {error}")
            continue
        problems.extend(_markdown_link_problems(repo, path, text))
    return files, sorted(set(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="show the exact manifest-derived Markdown set")
    args = parser.parse_args(argv)
    try:
        files, problems = check_repository(ROOT)
    except (sync.GenerationError, OSError) as error:
        print(f"agent instruction check refused: {error}", file=sys.stderr)
        return 2
    if args.list:
        for path in files:
            print(_relative(ROOT, path).as_posix())
        print(f"{len(files)} Markdown file(s) covered")
        return 0
    if problems:
        for problem in problems:
            print(problem)
        print(f"agent instruction check refused: {len(problems)} problem(s)")
        return 1
    print(f"agent instructions clean: {len(files)} Markdown file(s), {len(sync.build_outputs(ROOT).outputs)} generated file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
