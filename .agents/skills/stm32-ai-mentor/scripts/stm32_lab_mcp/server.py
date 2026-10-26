from __future__ import annotations

import argparse
from functools import wraps
import json
import os
from pathlib import Path
from typing import Mapping

from .core import SafetyError, STM32Lab


TOOL_NAMES = (
    "environment_inspect",
    "project_inspect",
    "cubemx_generate_staged",
    "build_run",
    "artifact_inspect",
    "test_host",
    "probe_list",
    "target_identify",
    "serial_list",
    "serial_capture",
    "flash_plan",
    "flash_execute",
    "target_reset",
    "test_target",
    "job_status",
    "job_cancel",
)


def _safe_tool(operation):
    """Preserve the MCP signature while returning fail-closed structured errors."""
    @wraps(operation)
    def invoke(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except SafetyError as exc:
            return {"ok": False, "error": {"code": "safety_denied", "message": str(exc)}}
        except Exception:
            return {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "STM32 laboratory operation failed without changing project state.",
                },
            }
    return invoke


def discover_workspace_root(start: str | Path) -> Path:
    current = Path(start).resolve(strict=True)
    if current.is_file():
        current = current.parent
    marker = Path(".agents") / "skills" / "stm32-ai-mentor" / "SKILL.md"
    for candidate in (current, *current.parents):
        if (candidate / marker).is_file():
            return candidate
    raise RuntimeError("cannot identify the STM32 AI Mentor workspace root")


def lab_from_environment(
    workspace_root: str | Path,
    environment: Mapping[str, str] | None = None,
) -> STM32Lab:
    values = os.environ if environment is None else environment
    resolved_workspace = Path(workspace_root).resolve(strict=True)
    policy_path = values.get("STM32_AI_MENTOR_POLICY")
    board_profiles = {}
    if policy_path:
        try:
            policy = json.loads(Path(policy_path).resolve(strict=True).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("external MCP permission policy is unreadable or invalid") from exc
        if not isinstance(policy, dict) or policy.get("schema_version") != 1:
            raise RuntimeError("external MCP permission policy version is invalid")
        allowed_tools = policy.get("stm32_lab", {}).get("allowed_tools")
        if set(allowed_tools or ()) != set(TOOL_NAMES):
            raise RuntimeError("external STM32 tool allowlist does not match the server surface")
        configured_roots = policy.get("workspace_roots")
        if not isinstance(configured_roots, list):
            raise RuntimeError("external MCP permission policy has no workspace_roots")
        allowed_roots = {
            Path(item).resolve(strict=True)
            for item in configured_roots
            if isinstance(item, str)
        }
        if resolved_workspace not in allowed_roots:
            raise RuntimeError("workspace root is not authorized by the external MCP permission policy")
        board_profiles = policy.get("stm32_lab", {}).get("board_profiles")
        if not isinstance(board_profiles, dict):
            raise RuntimeError("external MCP permission policy has no managed board profile registry")
    return STM32Lab(
        resolved_workspace,
        programmer=values.get("STM32_PROGRAMMER_CLI") or None,
        cmake=values.get("STM32_CMAKE") or None,
        cubemx=values.get("STM32_CUBEMX") or None,
        tool_versions={
            "STM32CubeProgrammer": values.get("STM32_PROGRAMMER_VERSION", "unverified"),
            "CMake": values.get("STM32_CMAKE_VERSION", "unverified"),
            "STM32CubeMX": values.get("STM32_CUBEMX_VERSION", "unverified"),
            "Python": values.get("STM32_PYTHON_VERSION", "unverified"),
        },
        board_profiles=board_profiles,
    )


def create_server(workspace_root: str | Path):
    """Create a stdio MCP server when the optional MCP SDK is installed."""
    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # Core remains importable/testable without network installs.
        try:  # Compatibility with the 1.x Python SDK used by some existing workstations.
            from mcp.server.fastmcp import FastMCP as MCPServer
        except ImportError:
            raise RuntimeError("The optional 'mcp' package is required to run the stdio server") from exc

    lab = lab_from_environment(workspace_root)
    mcp = MCPServer("stm32-lab-mcp")

    for tool_name in TOOL_NAMES:
        mcp.tool(name=tool_name)(_safe_tool(getattr(lab, tool_name)))
    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Narrow STM32 laboratory stdio MCP server")
    parser.add_argument("--workspace-root")
    args = parser.parse_args(argv)
    workspace_root = Path(args.workspace_root).resolve(strict=True) if args.workspace_root else discover_workspace_root(__file__)
    server = create_server(workspace_root)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
