"""Safe, small KiCad command adapter.

This module deliberately does not implement a shell, Flux write-back, or board
ordering.  A caller supplies structured request objects; every CLI argument is
constructed here from a workspace-contained design and generated output path.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


DESIGN_SUFFIXES = {"schematic": ".kicad_sch", "pcb": ".kicad_pcb"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
MAX_CONTENT_BYTES = 5 * 1024 * 1024
Runner = Callable[..., Mapping[str, Any]]
IpcProbe = Callable[[], Mapping[str, Any]]


class EdaLabError(Exception):
    """A machine-readable denial or execution failure."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def receipt(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "details": self.details}}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_hashes(path: Path, *, relative_to: Path) -> dict[str, str]:
    """Hash a file or every file in a non-empty artifact directory."""
    if path.is_file():
        return {str(path.relative_to(relative_to)).replace("\\", "/"): _sha256_path(path)}
    if path.is_dir():
        files = sorted(item for item in path.rglob("*") if item.is_file())
        return {
            str(item.relative_to(relative_to)).replace("\\", "/"): _sha256_path(item)
            for item in files
        }
    return {}


def _is_reparse_point(path: Path) -> bool:
    """Treat symbolic links and Windows junctions as untrusted write targets."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _default_runner(command: list[str], *, cwd: Path, timeout: int) -> Mapping[str, Any]:
    completed = subprocess.run(  # noqa: S603 - arguments are built exclusively below
        command, cwd=str(cwd), text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=timeout, shell=False, check=False,
    )
    return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def detect_kicad_cli(candidate: str | None = None) -> str | None:
    """Resolve only an executable program, never a command string with arguments."""
    value = candidate or shutil.which("kicad-cli")
    if not value or any(char in value for char in "\r\n\x00"):
        return None
    path = Path(value)
    if path.is_absolute() and not path.is_file():
        return None
    # A bare executable name is acceptable because subprocess receives an argv list.
    return str(path) if path.is_absolute() else value


def inspect_kicad_ipc() -> dict[str, Any]:
    """Read-only availability probe; never exposes a socket path or API token."""
    try:
        binding_version = importlib.metadata.version("kicad-python")
        import kipy
    except (ImportError, importlib.metadata.PackageNotFoundError):
        return {"binding_available": False, "binding_version": None, "connected": False}
    try:
        client = kipy.KiCad(client_name="stm32-ai-mentor-inspect", timeout_ms=500)
        client.ping()
        kicad_version = str(client.get_version())
    except Exception:
        return {"binding_available": True, "binding_version": binding_version, "connected": False}
    return {
        "binding_available": True,
        "binding_version": binding_version,
        "connected": True,
        "kicad_version": kicad_version,
        "scope": "KiCad 10 running-GUI PCB IPC; schematic and headless export remain CLI/offline",
    }


class EdaLabMcp:
    """The nine explicitly permitted EDA operations.

    The service owns no project ledger.  Its receipts are intended to be written
    by the main agent through the authoritative project tool.
    """

    def __init__(
        self,
        *,
        workspace_roots: list[str | Path],
        kicad_cli: str | None = None,
        runner: Runner | None = None,
        command_timeout_seconds: int = 120,
        kicad_version: str = "unverified",
        ipc_probe: IpcProbe | None = None,
    ) -> None:
        if not workspace_roots:
            raise ValueError("workspace_roots cannot be empty")
        self.workspace_roots = tuple(Path(root).resolve() for root in workspace_roots)
        self.kicad_cli = detect_kicad_cli(kicad_cli)
        self.runner: Runner = runner or _default_runner
        self.command_timeout_seconds = command_timeout_seconds
        self.kicad_version = kicad_version
        self.ipc_probe = ipc_probe or inspect_kicad_ipc
        if not isinstance(command_timeout_seconds, int) or not 1 <= command_timeout_seconds <= 900:
            raise ValueError("command_timeout_seconds must be in [1, 900]")
        self.tools = {
            "design_inspect": self.design_inspect,
            "design_snapshot": self.design_snapshot,
            "schematic_apply_transaction": self.schematic_apply_transaction,
            "pcb_apply_transaction": self.pcb_apply_transaction,
            "erc_run": self.erc_run,
            "drc_run": self.drc_run,
            "parity_run": self.parity_run,
            "render_run": self.render_run,
            "release_export": self.release_export,
        }

    def dispatch(self, tool_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(tool_name)
        if tool is None:
            raise EdaLabError("tool_denied", "工具不在 EDA 白名单中。", {"tool": tool_name})
        return tool(payload)

    @staticmethod
    def _payload(payload: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise EdaLabError("invalid_payload", "payload 必须是对象。")
        unknown = set(payload) - allowed
        if unknown:
            raise EdaLabError("invalid_payload", "payload 含有不允许的字段；不接受 raw arguments 或路径覆写。", sorted(unknown))
        return dict(payload)

    def _design_dir(self, payload: Mapping[str, Any], allowed: set[str]) -> Path:
        self._payload(payload, allowed)
        raw = payload.get("design_dir")
        if not isinstance(raw, str) or not raw.strip():
            raise EdaLabError("invalid_payload", "design_dir 必须是非空路径。")
        try:
            design_dir = Path(raw).resolve(strict=True)
        except OSError as exc:
            raise EdaLabError("design_missing", "设计目录不存在或无法解析。") from exc
        if not design_dir.is_dir():
            raise EdaLabError("design_missing", "design_dir 必须是目录。")
        if not any(design_dir.is_relative_to(root) for root in self.workspace_roots):
            raise EdaLabError("workspace_denied", "设计目录不在允许的 workspace 内。")
        return design_dir

    @staticmethod
    def _unique_design_file(design_dir: Path, kind: str) -> Path:
        suffix = DESIGN_SUFFIXES[kind]
        matches = sorted(path for path in design_dir.glob(f"*{suffix}") if path.is_file())
        if len(matches) != 1:
            raise EdaLabError(
                "design_ambiguous", f"目录必须恰好含有一个 {suffix} 文件。", {"found": [item.name for item in matches]},
            )
        selected = matches[0]
        if _is_reparse_point(selected) or selected.resolve(strict=True).parent != design_dir.resolve(strict=True):
            raise EdaLabError("design_link_denied", "设计文件不能是符号链接、结点或工作区外重解析目标。")
        return selected

    def _design_files(self, design_dir: Path) -> dict[str, Path]:
        return {kind: self._unique_design_file(design_dir, kind) for kind in DESIGN_SUFFIXES}

    @staticmethod
    def _metadata_dir(design_dir: Path) -> Path:
        # This fixed internal folder is the only non-design write location.
        path = design_dir / ".stm32-ai-mentor"
        if path.exists() and _is_reparse_point(path):
            raise EdaLabError("metadata_link_denied", "EDA 元数据目录不能是符号链接或重解析点。")
        path.mkdir(exist_ok=True)
        resolved = path.resolve(strict=True)
        if not resolved.is_dir() or resolved.parent != design_dir.resolve(strict=True):
            raise EdaLabError("metadata_workspace_denied", "EDA 元数据目录解析到了设计 workspace 之外。")
        return path

    def _internal_dir(self, design_dir: Path, name: str) -> Path:
        parent = self._metadata_dir(design_dir)
        path = parent / name
        if path.exists() and _is_reparse_point(path):
            raise EdaLabError("metadata_link_denied", "EDA 内部目录不能是符号链接或重解析点。")
        path.mkdir(exist_ok=True)
        resolved = path.resolve(strict=True)
        if not resolved.is_dir() or parent.resolve(strict=True) not in resolved.parents:
            raise EdaLabError("metadata_workspace_denied", "EDA 内部目录解析到了元数据范围之外。")
        return path

    def _new_run_dir(self, design_dir: Path, label: str) -> Path:
        run_dir = self._internal_dir(design_dir, "runs") / f"{label}-{uuid.uuid4().hex[:12]}"
        run_dir.mkdir(exist_ok=False)
        return run_dir

    def _snapshot(self, design_dir: Path, reason: str) -> dict[str, Any]:
        files = self._design_files(design_dir)
        snapshots = self._internal_dir(design_dir, "snapshots")
        snapshot_dir = snapshots / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
        snapshot_dir.mkdir()
        snapshot_path = snapshot_dir / "snapshot.json"
        hashes = {path.name: _sha256_path(path) for path in files.values()}
        backups: dict[str, str] = {}
        for path in files.values():
            backup = snapshot_dir / path.name
            shutil.copyfile(path, backup)
            # A backup that does not match its manifest must never be offered as a rollback point.
            if _sha256_path(backup) != hashes[path.name]:
                raise EdaLabError("snapshot_failed", "设计快照哈希不一致；事务未开始。", {"file": path.name})
            backups[path.name] = str(backup)
        data = {
            "created_at": _utc_now(), "reason": reason, "design_dir": str(design_dir),
            "hashes": hashes, "backups": backups,
        }
        temporary = snapshot_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, snapshot_path)
        return {"snapshot_path": str(snapshot_path), "hashes": hashes, "backups": backups}

    def design_inspect(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir"})
        files = self._design_files(design_dir)
        return {
            "ok": True, "tool": "design_inspect", "design_dir": str(design_dir),
            "files": {kind: {"name": path.name, "sha256": _sha256_path(path), "bytes": path.stat().st_size} for kind, path in files.items()},
            "kicad_cli_detected": self.kicad_cli is not None,
            "ipc": dict(self.ipc_probe()),
            "cloud_policy": "Flux is non-authoritative; local KiCad remains the release source.",
        }

    def design_snapshot(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir", "reason"})
        reason = payload.get("reason", "manual snapshot")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise EdaLabError("invalid_payload", "reason 必须是 1–500 字符。")
        return {"ok": True, "tool": "design_snapshot", "design_dir": str(design_dir), **self._snapshot(design_dir, reason)}

    def _apply_transaction(self, payload: Mapping[str, Any], kind: str) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir", "content", "reason"})
        ipc = dict(self.ipc_probe())
        if ipc.get("connected"):
            raise EdaLabError(
                "kicad_gui_active",
                "检测到正在运行的 KiCad IPC 会话；为避免 GUI 内存状态与磁盘文件冲突，已拒绝离线整文件事务。",
                {"kind": kind, "required_action": "关闭对应编辑器，或改用后续结构化 PCB IPC 操作"},
            )
        content = payload.get("content")
        reason = payload.get("reason")
        if not isinstance(content, str) or not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise EdaLabError("invalid_payload", "事务需要完整 content 与非空 reason。")
        raw = content.encode("utf-8")
        expected_prefix = "(kicad_sch" if kind == "schematic" else "(kicad_pcb"
        if len(raw) > MAX_CONTENT_BYTES or "\x00" in content or not content.lstrip().startswith(expected_prefix):
            raise EdaLabError("invalid_content", f"content 必须是受控的完整 {DESIGN_SUFFIXES[kind]} 内容。")
        target = self._unique_design_file(design_dir, kind)
        snapshot = self._snapshot(design_dir, reason)
        before_hash = _sha256_path(target)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8", newline="\n")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            readback = target.read_bytes()
            after_hash = hashlib.sha256(readback).hexdigest()
            if readback != raw:
                raise OSError("write readback differs from the approved transaction")
        except OSError as exc:
            backup = Path(snapshot["backups"][target.name])
            rollback = target.with_name(f".{target.name}.{uuid.uuid4().hex}.rollback")
            try:
                shutil.copyfile(backup, rollback)
                os.replace(rollback, target)
            finally:
                rollback.unlink(missing_ok=True)
            if _sha256_path(target) != before_hash:
                raise EdaLabError("transaction_rollback_failed", "写后校验失败且自动回滚未能恢复原哈希。") from exc
            raise EdaLabError(
                "transaction_readback_failed", "写后回读与请求内容不一致；已自动恢复事务前快照。",
                {"target": target.name, "restored_hash": before_hash},
            ) from exc
        return {
            "ok": True, "tool": f"{kind}_apply_transaction", "design_dir": str(design_dir), "target": target.name,
            "before_hash": before_hash, "after_hash": after_hash, "readback_match": True, **snapshot,
            "transaction_mode": "offline_atomic_file_replace", "ipc_used": False,
        }

    def schematic_apply_transaction(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._apply_transaction(payload, "schematic")

    def pcb_apply_transaction(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._apply_transaction(payload, "pcb")

    def _cli(self) -> str:
        if not self.kicad_cli:
            raise EdaLabError("kicad_unavailable", "未发现可执行 KiCad CLI；为避免虚构检查结果已停止。")
        return self.kicad_cli

    def _run_cli(
        self,
        tool: str,
        design_dir: Path,
        command: list[str],
        run_dir: Path,
        *,
        expected_outputs: tuple[Path, ...] = (),
    ) -> dict[str, Any]:
        # Command is intentionally a list, has no caller-supplied raw arguments, and is logged as a receipt.
        try:
            result = dict(self.runner(command, cwd=design_dir, timeout=self.command_timeout_seconds))
        except subprocess.TimeoutExpired as exc:
            raise EdaLabError(
                "kicad_timeout", "KiCad CLI 超时并已停止；未将检查或导出标为通过。",
                {"tool": tool, "timeout_seconds": self.command_timeout_seconds},
            ) from exc
        except OSError as exc:
            raise EdaLabError(
                "kicad_process_failed", "KiCad CLI 进程无法启动或异常退出；未将操作标为通过。",
                {"tool": tool, "message": str(exc)[:500]},
            ) from exc
        except Exception as exc:
            raise EdaLabError(
                "kicad_runner_failed", "KiCad 执行适配器异常；未将操作标为通过。",
                {"tool": tool, "exception_type": type(exc).__name__},
            ) from exc
        returncode = result.get("returncode")
        output_hashes: dict[str, str] = {}
        missing_outputs: list[str] = []
        for output in expected_outputs:
            hashes = _artifact_hashes(output, relative_to=run_dir)
            if not hashes:
                missing_outputs.append(str(output))
            output_hashes.update(hashes)
        receipt = {
            "ok": returncode == 0 and not missing_outputs,
            "tool": tool, "command": command, "cwd": str(design_dir), "run_dir": str(run_dir),
            "returncode": returncode, "stdout": str(result.get("stdout", "")), "stderr": str(result.get("stderr", "")),
            "ran_at": _utc_now(), "kicad_cli": self.kicad_cli,
            "artifact_hashes": output_hashes, "missing_outputs": missing_outputs,
        }
        log_hash = hashlib.sha256(
            f"{receipt['stdout']}\n--- stderr ---\n{receipt['stderr']}".encode("utf-8")
        ).hexdigest()
        receipt["tool_receipt"] = {
            "receipt_id": uuid.uuid4().hex,
            "tool": tool,
            "exit_code": int(returncode) if isinstance(returncode, int) else -1,
            "log_hash": log_hash,
            "diagnostic_class": (
                "success" if returncode == 0 and not missing_outputs
                else "artifact_missing" if missing_outputs else "kicad_failed"
            ),
            "tool_version": self.kicad_version,
            "timestamp": receipt["ran_at"],
            "artifact_hashes": sorted(set(output_hashes.values())),
        }
        receipt_path = run_dir / f"{tool}-receipt.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipt["receipt_path"] = str(receipt_path)
        if returncode != 0:
            raise EdaLabError("kicad_command_failed", "KiCad CLI 返回失败；未将设计标为通过。", receipt)
        if missing_outputs:
            raise EdaLabError("kicad_artifact_missing", "KiCad 声称成功但未生成必需产物；未将操作标为通过。", receipt)
        return receipt

    def erc_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir"})
        schematic = self._unique_design_file(design_dir, "schematic")
        cli = self._cli()
        run_dir = self._new_run_dir(design_dir, "erc")
        report = run_dir / "erc.rpt"
        command = [
            cli, "sch", "erc", "--severity-all", "--exit-code-violations",
            "--output", str(report), str(schematic),
        ]
        return self._run_cli("erc_run", design_dir, command, run_dir, expected_outputs=(report,))

    def drc_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir"})
        pcb = self._unique_design_file(design_dir, "pcb")
        cli = self._cli()
        run_dir = self._new_run_dir(design_dir, "drc")
        report = run_dir / "drc.rpt"
        command = [
            cli, "pcb", "drc", "--severity-all", "--exit-code-violations",
            "--output", str(report), str(pcb),
        ]
        return self._run_cli("drc_run", design_dir, command, run_dir, expected_outputs=(report,))

    def parity_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir"})
        pcb = self._unique_design_file(design_dir, "pcb")
        # KiCad itself provides this parity check as a constrained DRC option.
        # It remains evidence, not a substitute for human review of placement/routing.
        cli = self._cli()
        run_dir = self._new_run_dir(design_dir, "parity")
        report = run_dir / "parity.rpt"
        command = [
            cli, "pcb", "drc", "--schematic-parity", "--severity-all", "--exit-code-violations",
            "--output", str(report), str(pcb),
        ]
        return self._run_cli("parity_run", design_dir, command, run_dir, expected_outputs=(report,))

    def render_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir"})
        pcb = self._unique_design_file(design_dir, "pcb")
        cli = self._cli()
        run_dir = self._new_run_dir(design_dir, "render")
        image = run_dir / "pcb-top.png"
        return self._run_cli(
            "render_run", design_dir,
            [cli, "pcb", "render", "--output", str(image), str(pcb)],
            run_dir, expected_outputs=(image,),
        )

    @staticmethod
    def _safe_release_id(value: Any) -> str:
        if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
            raise EdaLabError("invalid_release_id", "release_id 只能使用字母、数字、下划线和连字符。")
        return value

    def release_export(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        design_dir = self._design_dir(payload, {"design_dir", "release_id"})
        release_id = self._safe_release_id(payload.get("release_id"))
        files = self._design_files(design_dir)
        cli = self._cli()
        run_dir = self._new_run_dir(design_dir, f"release-{release_id}")
        release_snapshot = self._snapshot(design_dir, f"freeze source for release {release_id}")
        frozen_source_hashes = dict(release_snapshot["hashes"])
        frozen_files = {
            kind: Path(release_snapshot["backups"][source.name])
            for kind, source in files.items()
        }
        check_dir = run_dir / "checks"
        check_dir.mkdir()
        check_commands = {
            "erc": [
                cli, "sch", "erc", "--severity-all", "--exit-code-violations",
                "--output", str(check_dir / "erc.rpt"), str(frozen_files["schematic"]),
            ],
            "drc": [
                cli, "pcb", "drc", "--severity-all", "--exit-code-violations",
                "--output", str(check_dir / "drc.rpt"), str(frozen_files["pcb"]),
            ],
            "parity": [
                cli, "pcb", "drc", "--schematic-parity", "--severity-all", "--exit-code-violations",
                "--output", str(check_dir / "parity.rpt"), str(frozen_files["pcb"]),
            ],
        }
        checks = {
            name: self._run_cli(
                f"release_export.{name}", design_dir, command, run_dir,
                expected_outputs=(check_dir / f"{name}.rpt",),
            )
            for name, command in check_commands.items()
        }
        outputs = {
            "bom": run_dir / "bom.csv", "gerber": run_dir / "gerbers", "drill": run_dir / "drill.drl",
            "pnp": run_dir / "positions.csv", "step": run_dir / "board.step", "render": run_dir / "board.png",
        }
        # KiCad's Gerber and drill exporters expect output directories, not a caller-controlled filename.
        outputs["drill"] = run_dir / "drill"
        outputs["gerber"].mkdir()
        outputs["drill"].mkdir()
        commands = [
            ("bom", [cli, "sch", "export", "bom", "--output", str(outputs["bom"]), str(frozen_files["schematic"])]),
            ("gerber", [cli, "pcb", "export", "gerbers", "--output", str(outputs["gerber"]), str(frozen_files["pcb"])]),
            ("drill", [cli, "pcb", "export", "drill", "--output", str(outputs["drill"]), str(frozen_files["pcb"])]),
            ("pnp", [cli, "pcb", "export", "pos", "--output", str(outputs["pnp"]), str(frozen_files["pcb"])]),
            ("step", [cli, "pcb", "export", "step", "--output", str(outputs["step"]), str(frozen_files["pcb"])]),
            ("render", [cli, "pcb", "render", "--output", str(outputs["render"]), str(frozen_files["pcb"])]),
        ]
        receipts = [
            self._run_cli(
                f"release_export.{name}", design_dir, command, run_dir,
                expected_outputs=(outputs[name],),
            )
            for name, command in commands
        ]
        artifact_hashes: dict[str, str] = {}
        for path in outputs.values():
            artifact_hashes.update(_artifact_hashes(path, relative_to=run_dir))
        current_source_hashes = {path.name: _sha256_path(path) for path in files.values()}
        if current_source_hashes != frozen_source_hashes:
            raise EdaLabError(
                "release_source_changed", "发布过程中原理图或 PCB 已变化；本次产物作废，必须重新检查和导出。",
                {"frozen": frozen_source_hashes, "current": current_source_hashes},
            )
        manifest = {
            "release_id": release_id, "created_at": _utc_now(), "design_dir": str(design_dir),
            "outputs": {name: str(path) for name, path in outputs.items()},
            "artifact_hashes": artifact_hashes,
            "source_hashes": frozen_source_hashes,
            "source_snapshot": release_snapshot["snapshot_path"],
            "exported_from_snapshot": True,
            "receipts": [receipt["receipt_path"] for receipt in receipts],
            "checks": checks,
            "cloud_policy": "Flux is non-authoritative; local KiCad remains the release source.",
            "order_board": "not_supported",
            "release_status": "automation_checked_draft",
            "unresolved_items": [
                "Human review of connector orientation, mounting holes, enclosure clearance and critical placement is not represented by KiCad CLI checks.",
                "Fabricator-specific DFM and procurement availability must be reviewed before board ordering.",
            ],
        }
        manifest_path = run_dir / "design-release.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "tool": "release_export", "run_dir": str(run_dir), "manifest_path": str(manifest_path), "manifest": manifest}
