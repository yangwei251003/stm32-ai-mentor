#!/usr/bin/env python3
"""Install the two execution MCP servers outside the mutable project workspace.

The installed launchers pin the server-source manifest, external permission
policy, tool lock, and concrete tool binaries.  Updating project files alone can
therefore never change code that Codex auto-starts; this installer must be run
again deliberately after review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any


PACKAGES = ("stm32_lab_mcp", "eda_lab_mcp")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _launcher(
    *,
    server: str,
    workspace: Path,
    install_dir: Path,
    source_manifest_hash: str,
    policy: Path,
    policy_hash: str,
    tool_lock: Path,
    tool_lock_hash: str,
) -> str:
    entry = (
        "from stm32_lab_mcp.server import create_server\n"
        "server = create_server(WORKSPACE)"
        if server == "stm32"
        else
        "from eda_lab_mcp.server import create_server\n"
        "server = create_server(os.environ)"
    )
    tool_setup = """
installed = tools["installed"]
verify_tool("python", Path(sys.executable), installed["python"]["sha256"])
if SERVER == "stm32":
    programmer = installed["stm32_cube_programmer"]
    cmake = installed["cmake"]
    verify_tool("STM32CubeProgrammer", Path(programmer["path"]), programmer["sha256"])
    verify_tool("CMake", Path(cmake["path"]), cmake["sha256"])
    os.environ["STM32_PROGRAMMER_CLI"] = programmer["path"]
    os.environ["STM32_CMAKE"] = cmake["path"]
    os.environ["STM32_PROGRAMMER_VERSION"] = programmer["version"]
    os.environ["STM32_CMAKE_VERSION"] = cmake["version"]
    os.environ["STM32_PYTHON_VERSION"] = installed["python"]["version"]
    os.environ.pop("STM32_CUBEMX", None)
else:
    kicad = installed["kicad_cli"]
    verify_tool("KiCad CLI", Path(kicad["path"]), kicad["sha256"])
    os.environ["KICAD_CLI"] = kicad["path"]
    os.environ["KICAD_CLI_VERSION"] = kicad["version"]
os.environ["STM32_AI_MENTOR_POLICY"] = str(POLICY)
"""
    return f'''#!/usr/bin/env python3
"""Generated guarded launcher. Reinstall deliberately; do not hand-edit."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys

SERVER = {server!r}
WORKSPACE = Path({str(workspace)!r})
INSTALL_DIR = Path({str(install_dir)!r})
SOURCE_MANIFEST = INSTALL_DIR / "verified-files.json"
SOURCE_MANIFEST_HASH = {source_manifest_hash!r}
POLICY = Path({str(policy)!r})
POLICY_HASH = {policy_hash!r}
TOOL_LOCK = Path({str(tool_lock)!r})
TOOL_LOCK_HASH = {tool_lock_hash!r}

def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

def require_hash(label: str, path: Path, expected: str) -> None:
    if not path.is_file() or digest(path).lower() != expected.lower():
        raise SystemExit(f"{{label}} integrity check failed; MCP server refused to start")

def verify_tool(label: str, path: Path, expected: str) -> None:
    require_hash(label, path.resolve(strict=True), expected)

require_hash("server manifest", SOURCE_MANIFEST, SOURCE_MANIFEST_HASH)
require_hash("permission policy", POLICY, POLICY_HASH)
require_hash("tool lock", TOOL_LOCK, TOOL_LOCK_HASH)
manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
for relative, expected in manifest["files"].items():
    candidate = (INSTALL_DIR / relative).resolve(strict=True)
    if INSTALL_DIR.resolve(strict=True) not in candidate.parents:
        raise SystemExit("installed MCP source escaped its managed directory")
    require_hash(relative, candidate, expected)
tools = json.loads(TOOL_LOCK.read_text(encoding="utf-8"))
{tool_setup}
sys.path.insert(0, str(INSTALL_DIR))
os.chdir(INSTALL_DIR)
{entry}
server.run(transport="stdio")
'''


def install_runtime(
    *, workspace: Path, runtime_root: Path, policy: Path, tool_lock: Path,
) -> dict[str, Any]:
    workspace = workspace.resolve(strict=True)
    source_root = workspace / ".agents" / "skills" / "stm32-ai-mentor" / "scripts"
    policy = policy.resolve(strict=True)
    tool_lock = tool_lock.resolve(strict=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_root = runtime_root.resolve(strict=True)
    destination = runtime_root / "current"
    previous = runtime_root / "previous"
    if destination.parent != runtime_root or previous.parent != runtime_root:
        raise ValueError("managed runtime targets escaped runtime_root")

    with tempfile.TemporaryDirectory(prefix="mcp-install-", dir=runtime_root) as raw_stage:
        stage = Path(raw_stage)
        files: dict[str, str] = {}
        for package in PACKAGES:
            source_package = source_root / package
            target_package = stage / package
            target_package.mkdir()
            for source in sorted(source_package.glob("*.py")):
                target = target_package / source.name
                shutil.copy2(source, target)
                files[target.relative_to(stage).as_posix()] = sha256(target)
        source_manifest = {"schema_version": 1, "files": files}
        atomic_json(stage / "verified-files.json", source_manifest)
        manifest_hash = sha256(stage / "verified-files.json")
        policy_hash = sha256(policy)
        tool_lock_hash = sha256(tool_lock)
        for server in ("stm32", "eda"):
            launcher = stage / f"{server}_lab_server.py"
            launcher.write_text(
                _launcher(
                    server=server, workspace=workspace, install_dir=destination,
                    source_manifest_hash=manifest_hash, policy=policy, policy_hash=policy_hash,
                    tool_lock=tool_lock, tool_lock_hash=tool_lock_hash,
                ),
                encoding="utf-8", newline="\n",
            )
        receipt = {
            "schema_version": 1,
            "workspace": str(workspace),
            "install_dir": str(destination),
            "source_manifest_sha256": manifest_hash,
            "policy_sha256": policy_hash,
            "tool_lock_sha256": tool_lock_hash,
            "launcher_sha256": {
                server: sha256(stage / f"{server}_lab_server.py") for server in ("stm32", "eda")
            },
        }
        atomic_json(stage / "install-receipt.json", receipt)

        if previous.exists():
            if previous.resolve(strict=True).parent != runtime_root:
                raise ValueError("previous runtime is outside runtime_root")
            shutil.rmtree(previous)
        if destination.exists():
            if destination.resolve(strict=True).parent != runtime_root:
                raise ValueError("current runtime is outside runtime_root")
            os.replace(destination, previous)
        try:
            os.replace(stage, destination)
        except Exception:
            if previous.exists() and not destination.exists():
                os.replace(previous, destination)
            raise
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install guarded STM32 AI Mentor MCP servers")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--tool-lock", required=True)
    args = parser.parse_args(argv)
    receipt = install_runtime(
        workspace=Path(args.workspace), runtime_root=Path(args.runtime_root),
        policy=Path(args.policy), tool_lock=Path(args.tool_lock),
    )
    json.dump(receipt, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
