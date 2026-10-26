#!/usr/bin/env python3
"""Real stdio MCP entry point for the narrow EDA execution service."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .service import EdaLabError, EdaLabMcp


TOOL_NAMES = (
    "design_inspect",
    "design_snapshot",
    "schematic_apply_transaction",
    "pcb_apply_transaction",
    "erc_run",
    "drc_run",
    "parity_run",
    "render_run",
    "release_export",
)


def _external_policy(values: Mapping[str, str]) -> dict[str, Any] | None:
    raw = values.get("STM32_AI_MENTOR_POLICY")
    if not raw:
        return None
    try:
        path = Path(raw).resolve(strict=True)
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EdaLabError("policy_invalid", "外部 MCP 权限策略不可读或格式错误。") from exc
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise EdaLabError("policy_invalid", "外部 MCP 权限策略版本无效。")
    allowed = policy.get("eda_lab", {}).get("allowed_tools")
    if set(allowed or ()) != set(TOOL_NAMES):
        raise EdaLabError("policy_invalid", "外部策略的 EDA 工具白名单与服务不一致。")
    return policy


def _roots(environment: Mapping[str, str] | None = None) -> list[Path]:
    values = os.environ if environment is None else environment
    policy = _external_policy(values)
    if policy is not None:
        configured = policy.get("workspace_roots")
        if not isinstance(configured, list):
            raise EdaLabError("policy_invalid", "外部策略未声明 workspace_roots。")
        roots = [Path(item).resolve(strict=True) for item in configured if isinstance(item, str)]
    else:
        raw = values.get("STM32_AI_MENTOR_EDA_WORKSPACES", "")
        roots = [Path(item).resolve(strict=True) for item in raw.split(os.pathsep) if item]
    if not roots:
        raise EdaLabError("workspace_unconfigured", "未配置 EDA workspace 白名单；服务拒绝启动。")
    return roots


def lab_from_environment(environment: Mapping[str, str] | None = None) -> EdaLabMcp:
    values = os.environ if environment is None else environment
    return EdaLabMcp(
        workspace_roots=_roots(values),
        kicad_cli=values.get("KICAD_CLI") or None,
        kicad_version=values.get("KICAD_CLI_VERSION", "unverified"),
    )


def _safe_call(operation: Callable[[Mapping[str, Any]], dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    """Turn expected denials into structured receipts without exposing a traceback."""
    try:
        return operation(payload)
    except EdaLabError as exc:
        return exc.receipt()
    except Exception:
        return {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": "EDA operation failed without changing the project ledger.",
                "details": None,
            },
        }


def create_server(environment: Mapping[str, str] | None = None):
    """Create the actual MCP server used by Codex's project configuration."""
    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # Core remains importable without the optional SDK.
        try:  # Compatibility with the 1.x Python SDK used by some existing workstations.
            from mcp.server.fastmcp import FastMCP as MCPServer
        except ImportError:
            raise RuntimeError("The optional 'mcp' package is required to run the stdio server") from exc

    lab = lab_from_environment(environment)
    mcp = MCPServer("eda-lab-mcp")

    @mcp.tool(name="design_inspect")
    def design_inspect(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.design_inspect, payload)

    @mcp.tool(name="design_snapshot")
    def design_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.design_snapshot, payload)

    @mcp.tool(name="schematic_apply_transaction")
    def schematic_apply_transaction(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.schematic_apply_transaction, payload)

    @mcp.tool(name="pcb_apply_transaction")
    def pcb_apply_transaction(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.pcb_apply_transaction, payload)

    @mcp.tool(name="erc_run")
    def erc_run(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.erc_run, payload)

    @mcp.tool(name="drc_run")
    def drc_run(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.drc_run, payload)

    @mcp.tool(name="parity_run")
    def parity_run(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.parity_run, payload)

    @mcp.tool(name="render_run")
    def render_run(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.render_run, payload)

    @mcp.tool(name="release_export")
    def release_export(payload: dict[str, Any]) -> dict[str, Any]:
        return _safe_call(lab.release_export, payload)

    return mcp


def main() -> int:
    server = create_server()
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
