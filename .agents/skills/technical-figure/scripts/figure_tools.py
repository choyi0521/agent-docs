#!/usr/bin/env python3
"""Discover and smoke-test the optional figure authoring toolchain."""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable


TOOL_NAMES = ("graphviz", "drawio", "blender", "openpencil")
ENV_OVERRIDES = {
    "graphviz": "AGENT_DOCS_GRAPHVIZ",
    "drawio": "AGENT_DOCS_DRAWIO",
    "blender": "AGENT_DOCS_BLENDER",
    "openpencil": "AGENT_DOCS_OPENPENCIL",
}
COMMAND_NAMES = {
    "graphviz": ("dot",),
    "drawio": ("drawio", "draw.io"),
    "blender": ("blender",),
    "openpencil": ("op",),
}
CAPABILITIES = {
    "graphviz": "headless graph layout and SVG export",
    "drawio": "editable diagram source and desktop CLI export",
    "blender": "background Python scene build and render",
    "openpencil": "editable .op document, CLI, and headless file server",
}


def _windows_candidates(tool: str) -> list[Path]:
    if platform.system() != "Windows":
        return []

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    local_data_raw = os.environ.get("LOCALAPPDATA")
    user_profile_raw = os.environ.get("USERPROFILE")
    local_data = Path(local_data_raw) if local_data_raw else None
    user_profile = Path(user_profile_raw) if user_profile_raw else None

    if tool == "graphviz":
        return [program_files / "Graphviz" / "bin" / "dot.exe"]
    if tool == "drawio":
        values = [
            program_files / "draw.io" / "draw.io.exe",
            program_files / "draw.io" / "drawio.exe",
        ]
        if local_data:
            values.extend(
                [
                    local_data / "Programs" / "draw.io" / "draw.io.exe",
                    local_data / "Programs" / "draw.io" / "drawio.exe",
                ]
            )
        return values
    if tool == "blender":
        preferred = [
            program_files / "Blender Foundation" / "Blender 4.5" / "blender.exe",
            program_files / "Blender Foundation" / "Blender 5.2" / "blender.exe",
        ]
        discovered = [
            Path(value)
            for value in sorted(
                glob.glob(
                    str(program_files / "Blender Foundation" / "Blender *" / "blender.exe")
                )
            )
        ]
        return preferred + discovered
    if tool == "openpencil":
        values: list[Path] = []
        if local_data:
            values.extend(
                [
                    local_data / "OpenPencil" / "bin" / "op.exe",
                    local_data / "Programs" / "OpenPencil" / "op.exe",
                    local_data / "Microsoft" / "WinGet" / "Links" / "op.exe",
                ]
            )
        if user_profile:
            values.extend(
                [
                    user_profile / ".openpencil" / "bin" / "op.exe",
                    user_profile / ".local" / "bin" / "op.exe",
                ]
            )
        return values
    raise ValueError(f"unknown tool: {tool}")


def find_tool(tool: str) -> Path | None:
    override = os.environ.get(ENV_OVERRIDES[tool])
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    for command in COMMAND_NAMES[tool]:
        resolved = shutil.which(command)
        if resolved:
            candidates.append(Path(resolved))
    candidates.extend(_windows_candidates(tool))

    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False)).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_file():
            return candidate.resolve()
    return None


def run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def version_for(tool: str, executable: Path) -> tuple[bool, str]:
    arguments = {
        "graphviz": ["-V"],
        "drawio": ["--version"],
        "blender": ["--version"],
        "openpencil": ["--version"],
    }[tool]
    try:
        result = run([str(executable), *arguments], timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    first_line = output.splitlines()[0] if output else f"exit {result.returncode}"
    return result.returncode == 0, first_line


def probe() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for tool in TOOL_NAMES:
        executable = find_tool(tool)
        if executable is None:
            result[tool] = {
                "available": False,
                "path": None,
                "version": None,
                "capability": CAPABILITIES[tool],
                "override": ENV_OVERRIDES[tool],
            }
            continue
        version_ok, version = version_for(tool, executable)
        result[tool] = {
            "available": version_ok,
            "path": str(executable),
            "version": version,
            "capability": CAPABILITIES[tool],
            "override": ENV_OVERRIDES[tool],
        }
    return result


def command_doctor(arguments: argparse.Namespace) -> int:
    report = probe()
    if arguments.json:
        display_report = {
            tool: {
                **item,
                "path": (
                    item["path"]
                    if arguments.show_paths or not item["path"]
                    else Path(str(item["path"])).name
                ),
            }
            for tool, item in report.items()
        }
        print(json.dumps(display_report, indent=2, sort_keys=True))
    else:
        for tool in TOOL_NAMES:
            item = report[tool]
            marker = "PASS" if item["available"] else "MISS"
            print(f"[{marker}] {tool}: {item['version'] or 'not found'}")
            if item["path"] and arguments.show_paths:
                print(f"       {item['path']}")
            elif not item["path"]:
                print(f"       override with {item['override']}")
            print(f"       {item['capability']}")

    requested = tuple(arguments.require or ())
    required = TOOL_NAMES if "all" in requested else requested
    missing = [tool for tool in required if not report[tool]["available"]]
    if missing:
        print(f"required tools unavailable: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


def smoke_graphviz(executable: Path, directory: Path) -> str:
    source = directory / "graphviz-smoke.dot"
    output = directory / "graphviz-smoke.svg"
    source.write_text(
        'digraph figure_smoke { rankdir=LR; source -> transform -> output; }\n',
        encoding="utf-8",
        newline="\n",
    )
    result = run([str(executable), "-Tsvg", "-o", str(output), str(source)])
    if result.returncode or not output.is_file() or "<svg" not in output.read_text(encoding="utf-8"):
        raise RuntimeError((result.stderr or result.stdout or "SVG was not created").strip())
    return str(output)


def smoke_drawio(executable: Path, directory: Path) -> str:
    source = directory / "drawio-smoke.drawio"
    output = directory / "drawio-smoke.drawio.svg"
    source.write_text(
        """<mxfile host="app.diagrams.net"><diagram id="smoke" name="Page-1"><mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1" pageWidth="827" pageHeight="1169"><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="editable source" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="160" height="60" as="geometry"/></mxCell></root></mxGraphModel></diagram></mxfile>\n""",
        encoding="utf-8",
        newline="\n",
    )
    result = run(
        [
            str(executable),
            "--export",
            "--format",
            "svg",
            "--embed-diagram",
            "--border",
            "10",
            "--output",
            str(output),
            str(source),
        ],
        timeout=90,
    )
    if result.returncode or not output.is_file():
        raise RuntimeError((result.stderr or result.stdout or "SVG was not created").strip())
    return str(output)


def smoke_blender(executable: Path, directory: Path) -> str:
    script = directory / "blender-smoke.py"
    output = directory / "blender-smoke.png"
    script.write_text(
        """import bpy
from mathutils import Vector

scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 256
scene.render.resolution_y = 192
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = __import__('sys').argv[-1]

bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.0))
cube = bpy.context.object
cube.name = 'FigureSmokeCube'

bpy.ops.object.camera_add(location=(4.0, -4.0, 3.0))
camera = bpy.context.object
camera.name = 'FigureSmokeCamera'
camera.rotation_euler = ((Vector((0.0, 0.0, 0.0)) - camera.location).to_track_quat('-Z', 'Y').to_euler())
scene.camera = camera
bpy.ops.render.render(write_still=True)
""",
        encoding="utf-8",
        newline="\n",
    )
    result = run(
        [
            str(executable),
            "--background",
            "--factory-startup",
            "--python",
            str(script),
            "--",
            str(output),
        ],
        timeout=150,
    )
    if result.returncode or not output.is_file() or output.stat().st_size < 100:
        raise RuntimeError((result.stderr or result.stdout or "PNG was not created").strip())
    return str(output)


def smoke_openpencil(executable: Path, directory: Path) -> str:
    del directory
    result = run([str(executable), "start", "--help"], timeout=30)
    output = "\n".join((result.stdout, result.stderr)).casefold()
    if result.returncode or "headless" not in output or "file" not in output:
        raise RuntimeError((result.stderr or result.stdout or "headless CLI surface not found").strip())
    return "CLI exposes start --headless --file"


SMOKE_FUNCTIONS = {
    "graphviz": smoke_graphviz,
    "drawio": smoke_drawio,
    "blender": smoke_blender,
    "openpencil": smoke_openpencil,
}


def _selected_tools(value: str) -> Iterable[str]:
    return TOOL_NAMES if value == "all" else (value,)


def command_smoke(arguments: argparse.Namespace) -> int:
    selected = tuple(_selected_tools(arguments.tool))
    explicit_directory = Path(arguments.output_dir).resolve() if arguments.output_dir else None
    manager = (
        contextlib.nullcontext(explicit_directory)
        if explicit_directory is not None
        else tempfile.TemporaryDirectory(prefix="agent-docs-figure-smoke-")
    )
    failures: list[str] = []
    with manager as managed:
        directory = Path(managed)
        directory.mkdir(parents=True, exist_ok=True)
        for tool in selected:
            executable = find_tool(tool)
            if executable is None:
                failures.append(f"{tool}: executable not found")
                print(f"[FAIL] {failures[-1]}")
                continue
            try:
                artifact = SMOKE_FUNCTIONS[tool](executable, directory)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                failures.append(f"{tool}: {error}")
                print(f"[FAIL] {failures[-1]}")
            else:
                print(f"[PASS] {tool}: {artifact}")
        if explicit_directory is not None:
            print(f"smoke outputs: {directory}")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="report installed figure tools")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor.add_argument(
        "--show-paths",
        action="store_true",
        help="include absolute executable paths (redacted by default)",
    )
    doctor.add_argument(
        "--require",
        nargs="*",
        choices=(*TOOL_NAMES, "all"),
        help="exit non-zero when a named tool is unavailable",
    )
    doctor.set_defaults(handler=command_doctor)

    smoke = subparsers.add_parser("smoke", help="exercise one or every figure tool")
    smoke.add_argument("--tool", choices=(*TOOL_NAMES, "all"), default="all")
    smoke.add_argument("--output-dir", help="keep generated smoke artifacts here")
    smoke.set_defaults(handler=command_smoke)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
