from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping


class SafetyError(RuntimeError):
    """An operation was rejected because its identity or scope was not proven."""


Runner = Callable[[list[str], Path, float], Mapping[str, Any]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_runner(command: list[str], cwd: Path, timeout_s: float) -> Mapping[str, Any]:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
            shell=False,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "stdout": _decode_output(exc.stdout),
            "stderr": _decode_output(exc.stderr),
            "timed_out": True,
        }
    except OSError as exc:
        return {"exit_code": None, "stdout": "", "stderr": str(exc), "spawn_error": True}
    return {
        "exit_code": completed.returncode,
        "stdout": _decode_output(completed.stdout),
        "stderr": _decode_output(completed.stderr),
        "timed_out": False,
    }


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def parse_probe_list(output: str) -> list[dict[str, Any]]:
    """Parse CubeProgrammer list output without selecting a device."""
    probes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        sn_match = re.search(r"(?:ST-LINK\s+SN|Serial\s+number)\s*:\s*([0-9A-Za-z-]+)", line, re.I)
        if sn_match:
            if current:
                probes.append(current)
            current = {"serial_number": sn_match.group(1)}
            continue
        if current is None:
            continue
        firmware_match = re.search(r"ST-LINK\s+FW\s*:\s*(\S+)", line, re.I)
        if firmware_match:
            current["firmware_version"] = firmware_match.group(1)
        probe_match = re.search(r"ST-LINK\s*:\s*(.+)$", line, re.I)
        if probe_match and "SN" not in line.upper() and "FW" not in line.upper():
            current["model"] = probe_match.group(1).strip()
    if current:
        probes.append(current)
    return probes


def parse_target_identity(output: str, probe_serial: str) -> dict[str, Any]:
    device = re.search(r"Device\s+ID\s*:\s*(0x[0-9A-Fa-f]+)", output, re.I)
    voltage = re.search(r"(?:Target\s+voltage|Voltage)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*V?", output, re.I)
    if not device or not voltage:
        raise SafetyError("target identity is incomplete; device ID and target voltage are required")
    return {
        "probe_serial": probe_serial,
        "mcu_device_id": device.group(1).lower(),
        "target_voltage_v": float(voltage.group(1)),
    }


def _read_words(output: str, start_address: int, count: int) -> list[int]:
    """Parse the bounded STM32CubeProgrammer ``-r32`` display format."""
    normalized = output.replace("\r", "")
    line = re.search(
        rf"0x{start_address:08x}\s*[:=]\s*([^\n]+)", normalized, re.I,
    )
    if not line:
        raise SafetyError(f"factory identity read at 0x{start_address:08X} was not returned")
    words = [int(value, 16) for value in re.findall(r"(?:0x)?([0-9A-Fa-f]{8})", line.group(1))]
    if len(words) < count:
        raise SafetyError(f"factory identity read at 0x{start_address:08X} is incomplete")
    return words[:count]


def parse_f103_factory_identity(flash_output: str, uid_output: str) -> dict[str, Any]:
    """Read-only identity fields defined by the STM32F103 factory system memory."""
    flash_word = _read_words(flash_output, 0x1FFFF7E0, 1)[0]
    flash_kib = flash_word & 0xFFFF
    if not 1 <= flash_kib <= 2048:
        raise SafetyError("factory flash-size register is outside the supported range")
    uid_words = _read_words(uid_output, 0x1FFFF7E8, 3)
    return {
        "flash_capacity_bytes": flash_kib * 1024,
        "mcu_uid": "".join(f"{word:08x}" for word in uid_words),
    }


def parse_serial_devices(devices: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in devices:
        if isinstance(item, Mapping):
            get = item.get
        else:
            get = lambda key, default=None, value=item: getattr(value, key, default)
        device = str(get("device", ""))
        if not re.fullmatch(r"COM\d{1,3}", device, re.I):
            continue
        result.append(
            {
                "port": device.upper(),
                "description": str(get("description", "")),
                "vid": get("vid"),
                "pid": get("pid"),
                "serial_number": get("serial_number"),
                "location": get("location"),
            }
        )
    return result


def _map_summary(text: str) -> dict[str, Any]:
    sections: dict[str, int] = {}
    for name, raw_size in re.findall(
        r"^\s*(\.(?:text|data|bss|rodata))\s+0x[0-9A-Fa-f]+\s+0x([0-9A-Fa-f]+)",
        text,
        flags=re.MULTILINE,
    ):
        sections[name] = sections.get(name, 0) + int(raw_size, 16)
    regions: dict[str, dict[str, int]] = {}
    for name, origin, length in re.findall(
        r"^\s*(FLASH|RAM)\s+0x([0-9A-Fa-f]+)\s+0x([0-9A-Fa-f]+)",
        text,
        flags=re.MULTILINE | re.I,
    ):
        regions[name.upper()] = {"origin": int(origin, 16), "length": int(length, 16)}
    flash_used = sections.get(".text", 0) + sections.get(".rodata", 0) + sections.get(".data", 0)
    ram_used = sections.get(".data", 0) + sections.get(".bss", 0)
    return {
        "sections": sections,
        "regions": regions,
        "flash_used_bytes": flash_used,
        "ram_used_bytes": ram_used,
    }


@dataclass
class _FlashGrant:
    artifact_path: str
    artifact_sha256: str
    target_json: str
    baseline: str
    address: str
    expires_at: float
    consumed: bool = False


class STM32Lab:
    """Core service. It owns no project ledger and exposes no raw command surface."""

    MAX_COMMAND_TIMEOUT_S = 900.0
    MAX_SERIAL_TIMEOUT_S = 60.0
    MAX_SERIAL_BYTES = 1024 * 1024
    MAX_FLASH_IMAGE_BYTES = 2 * 1024 * 1024
    MAX_FLASH_GRANTS = 256
    ARTIFACT_SUFFIXES = {".elf", ".hex", ".bin"}
    FLASHABLE_SUFFIXES = {".bin"}
    PROFILE_FIELDS = {
        "board_evidence_hash", "flash_capacity_bytes", "mcu_device_ids",
        "allowed_mcu_uids", "allowed_probe_serials", "identity_layout",
        "flash_enabled", "evidence_refs",
    }
    IDENTITY_LAYOUTS = {"stm32f103-medium-density"}

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        runner: Runner | None = None,
        programmer: str | None = None,
        cmake: str | None = None,
        cubemx: str | None = None,
        probe_provider: Callable[[], list[dict[str, Any]]] | None = None,
        target_verifier: Callable[[Mapping[str, Any]], bool] | None = None,
        serial_provider: Callable[[], Iterable[Any]] | None = None,
        serial_opener: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        token_ttl_s: float = 120.0,
        tool_versions: Mapping[str, str] | None = None,
        board_profiles: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise SafetyError("workspace root must be an existing directory")
        self.workspace_root = root
        self.runner = runner or _default_runner
        self.programmer = programmer or shutil.which("STM32_Programmer_CLI.exe") or "STM32_Programmer_CLI.exe"
        self.cmake = cmake or shutil.which("cmake.exe") or shutil.which("cmake") or "cmake"
        self.cubemx = cubemx or shutil.which("STM32CubeMX.exe")
        self.probe_provider = probe_provider
        self.target_verifier = target_verifier
        self.serial_provider = serial_provider
        self.serial_opener = serial_opener
        self.clock = clock
        if token_ttl_s <= 0 or token_ttl_s > 600:
            raise ValueError("token_ttl_s must be in (0, 600]")
        self.token_ttl_s = token_ttl_s
        self.tool_versions = dict(tool_versions or {})
        self.board_profiles = self._normalise_board_profiles(board_profiles or {})
        self._grants: dict[str, _FlashGrant] = {}
        self._grant_lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    @classmethod
    def _normalise_board_profiles(
        cls, profiles: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(profiles, Mapping):
            raise SafetyError("managed board profiles must be an object")
        normalized: dict[str, dict[str, Any]] = {}
        for profile_id, raw in profiles.items():
            if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}", profile_id):
                raise SafetyError("managed board profile has an invalid identifier")
            if not isinstance(raw, Mapping) or set(raw) != cls.PROFILE_FIELDS:
                raise SafetyError(f"managed board profile {profile_id} has an invalid schema")
            evidence_hash = str(raw["board_evidence_hash"]).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", evidence_hash):
                raise SafetyError(f"managed board profile {profile_id} has an invalid evidence hash")
            capacity = raw["flash_capacity_bytes"]
            if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1024 <= capacity <= cls.MAX_FLASH_IMAGE_BYTES:
                raise SafetyError(f"managed board profile {profile_id} has an invalid flash capacity")
            device_ids = raw["mcu_device_ids"]
            uids = raw["allowed_mcu_uids"]
            probes = raw["allowed_probe_serials"]
            refs = raw["evidence_refs"]
            if (
                not isinstance(device_ids, list) or not device_ids
                or not all(isinstance(value, str) and re.fullmatch(r"0x[0-9A-Fa-f]{3,8}", value) for value in device_ids)
                or not isinstance(uids, list)
                or not all(isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{24}", value) for value in uids)
                or not isinstance(probes, list)
                or not all(isinstance(value, str) and re.fullmatch(r"[0-9A-Za-z-]{3,64}", value) for value in probes)
                or not isinstance(refs, list) or not refs
                or not all(isinstance(value, str) and value.strip() for value in refs)
            ):
                raise SafetyError(f"managed board profile {profile_id} has invalid identity evidence")
            layout = raw["identity_layout"]
            if layout not in cls.IDENTITY_LAYOUTS or not isinstance(raw["flash_enabled"], bool):
                raise SafetyError(f"managed board profile {profile_id} has an unsupported identity layout")
            if raw["flash_enabled"] and (not uids or not probes):
                raise SafetyError(f"flash-enabled board profile {profile_id} is not enrolled to a chip UID and probe")
            normalized[profile_id] = {
                "board_evidence_hash": evidence_hash,
                "flash_capacity_bytes": capacity,
                "mcu_device_ids": sorted({value.lower() for value in device_ids}),
                "allowed_mcu_uids": sorted({value.lower() for value in uids}),
                "allowed_probe_serials": sorted(set(probes)),
                "identity_layout": layout,
                "flash_enabled": raw["flash_enabled"],
                "evidence_refs": list(dict.fromkeys(refs)),
            }
        return normalized

    def _path(self, value: str | Path, *, must_exist: bool = True) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.workspace_root / path
        try:
            resolved = path.resolve(strict=must_exist)
        except (FileNotFoundError, OSError) as exc:
            raise SafetyError(f"workspace path does not exist: {path}") from exc
        if resolved != self.workspace_root and self.workspace_root not in resolved.parents:
            raise SafetyError("path is outside the approved workspace")
        return resolved

    @staticmethod
    def _timeout(value: float) -> float:
        timeout = float(value)
        if timeout <= 0 or timeout > STM32Lab.MAX_COMMAND_TIMEOUT_S:
            raise SafetyError("command timeout is outside the allowed range")
        return timeout

    @staticmethod
    def _target_json(target: Mapping[str, Any]) -> str:
        required = (
            "probe_serial", "mcu_device_id", "mcu_uid", "board_profile", "board_evidence_hash",
            "flash_capacity_bytes", "target_voltage_v",
        )
        missing = [key for key in required if target.get(key) in (None, "")]
        if missing:
            raise SafetyError(f"target identity is incomplete: {', '.join(missing)}")
        serial = str(target["probe_serial"])
        if not re.fullmatch(r"[0-9A-Za-z-]{3,64}", serial):
            raise SafetyError("probe serial has an invalid format")
        device_id = str(target["mcu_device_id"])
        if not re.fullmatch(r"0x[0-9A-Fa-f]{3,8}", device_id):
            raise SafetyError("MCU device ID has an invalid format")
        mcu_uid = str(target["mcu_uid"])
        if not re.fullmatch(r"[0-9A-Fa-f]{24}", mcu_uid):
            raise SafetyError("MCU UID has an invalid format")
        board_profile = str(target["board_profile"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}", board_profile):
            raise SafetyError("board profile has an invalid format")
        evidence_hash = str(target["board_evidence_hash"])
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", evidence_hash):
            raise SafetyError("board evidence hash must be SHA-256")
        capacity = target["flash_capacity_bytes"]
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1024 <= capacity <= STM32Lab.MAX_FLASH_IMAGE_BYTES:
            raise SafetyError("board flash capacity is outside the supported range")
        try:
            voltage = float(target["target_voltage_v"])
        except (TypeError, ValueError) as exc:
            raise SafetyError("target voltage has an invalid format") from exc
        if voltage < 1.6 or voltage > 3.6:
            raise SafetyError("target voltage is outside the supported 3.3 V target range")
        canonical = {key: target[key] for key in required}
        canonical["target_voltage_v"] = voltage
        canonical["mcu_device_id"] = device_id.lower()
        canonical["mcu_uid"] = mcu_uid.lower()
        canonical["board_evidence_hash"] = evidence_hash.lower()
        canonical["flash_capacity_bytes"] = capacity
        return json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _managed_profile(self, target: Mapping[str, Any], *, require_flash: bool) -> dict[str, Any]:
        profile_id = str(target.get("board_profile", ""))
        profile = self.board_profiles.get(profile_id)
        if profile is None:
            raise SafetyError("board profile is not present in the managed external registry")
        comparisons = {
            "board evidence hash": str(target.get("board_evidence_hash", "")).lower()
            == profile["board_evidence_hash"],
            "flash capacity": target.get("flash_capacity_bytes") == profile["flash_capacity_bytes"],
            "MCU device ID": str(target.get("mcu_device_id", "")).lower() in profile["mcu_device_ids"],
        }
        failed = [label for label, matched in comparisons.items() if not matched]
        if failed:
            raise SafetyError(f"target does not match managed board profile: {', '.join(failed)}")
        if require_flash:
            if not profile["flash_enabled"]:
                raise SafetyError("managed board profile is inspection-only and not enrolled for flashing")
            if str(target.get("mcu_uid", "")).lower() not in profile["allowed_mcu_uids"]:
                raise SafetyError("connected MCU UID is not enrolled for this board profile")
            if str(target.get("probe_serial", "")) not in profile["allowed_probe_serials"]:
                raise SafetyError("connected probe serial is not enrolled for this board profile")
        return profile

    @staticmethod
    def _diagnostic(stdout: str, stderr: str, exit_code: int | None) -> dict[str, Any]:
        joined = f"{stdout}\n{stderr}".lower()
        if exit_code == 0:
            category = "ok"
        elif "no st-link" in joined or "st-link not detected" in joined:
            category = "probe"
        elif "voltage" in joined:
            category = "power"
        elif "permission" in joined or "access is denied" in joined:
            category = "permission"
        elif "timeout" in joined:
            category = "timeout"
        else:
            category = "tool"
        return {"category": category, "message": (stderr or stdout).strip()[:2000]}

    def _verify_connected_target(self, target: Mapping[str, Any]) -> None:
        self._managed_profile(target, require_flash=True)
        if self.target_verifier is not None:
            try:
                matched = bool(self.target_verifier(target))
            except Exception as exc:
                raise SafetyError("connected target verification failed") from exc
            if not matched:
                raise SafetyError("connected target does not match the requested identity")
            return
        identified = self._query_target(
            str(target["probe_serial"]), board_profile=str(target["board_profile"]),
        )["observed_target"]
        same_device = str(identified["mcu_device_id"]).lower() == str(target["mcu_device_id"]).lower()
        same_uid = str(identified["mcu_uid"]).lower() == str(target["mcu_uid"]).lower()
        same_capacity = identified["flash_capacity_bytes"] == target["flash_capacity_bytes"]
        same_voltage = abs(float(identified["target_voltage_v"]) - float(target["target_voltage_v"])) <= 0.15
        if not same_device or not same_uid or not same_capacity or not same_voltage:
            raise SafetyError("connected target does not match the requested identity")

    def _run(self, command: list[str], cwd: Path, timeout_s: float, operation: str) -> dict[str, Any]:
        started = time.time()
        try:
            raw = dict(self.runner(command, cwd, self._timeout(timeout_s)))
        except Exception as exc:
            raw = {"exit_code": None, "stdout": "", "stderr": str(exc), "spawn_error": True}
        stdout = _decode_output(raw.get("stdout"))
        stderr = _decode_output(raw.get("stderr"))
        exit_code = raw.get("exit_code")
        diagnostic = self._diagnostic(stdout, stderr, exit_code)
        if raw.get("spawn_error"):
            diagnostic = {"category": "tool_crash", "message": stderr[:2000]}
        receipt = {
            "operation": operation,
            "ok": exit_code == 0 and not raw.get("timed_out") and not raw.get("spawn_error"),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": bool(raw.get("timed_out", False)),
            "started_at_unix": started,
            "duration_ms": max(0, int((time.time() - started) * 1000)),
            "tool": Path(command[0]).name,
            "tool_version": None,
            "diagnostic": diagnostic,
        }
        job_id = secrets.token_hex(8)
        executable = os.path.normcase(os.path.abspath(command[0])) if Path(command[0]).is_absolute() else command[0].lower()
        configured = {
            (os.path.normcase(os.path.abspath(value)) if value and Path(value).is_absolute() else str(value).lower()): name
            for name, value in (
                ("STM32CubeProgrammer", self.programmer), ("CMake", self.cmake),
                ("STM32CubeMX", self.cubemx), ("Python", os.sys.executable),
            ) if value
        }
        version_key = configured.get(executable, Path(command[0]).name)
        log_hash = hashlib.sha256(f"{stdout}\n--- stderr ---\n{stderr}".encode("utf-8")).hexdigest()
        receipt["tool_receipt"] = {
            "receipt_id": job_id,
            "tool": operation,
            "exit_code": int(exit_code) if isinstance(exit_code, int) else -1,
            "log_hash": log_hash,
            "diagnostic_class": diagnostic["category"],
            "tool_version": self.tool_versions.get(version_key, "unverified"),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "artifact_hashes": [],
        }
        self._jobs[job_id] = {"job_id": job_id, "status": "succeeded" if receipt["ok"] else "failed", "receipt": receipt}
        receipt["job_id"] = job_id
        return receipt

    def environment_inspect(self) -> dict[str, Any]:
        tools = {}
        for name, configured in (
            ("STM32CubeProgrammer", self.programmer),
            ("CMake", self.cmake),
            ("STM32CubeMX", self.cubemx),
        ):
            path = shutil.which(configured) if configured else None
            if not path and configured and Path(configured).is_file():
                path = str(Path(configured).resolve())
            tools[name] = {"available": bool(path), "path": path}
        return {
            "ok": True,
            "workspace_root": str(self.workspace_root),
            "platform": os.name,
            "tools": tools,
        }

    def project_inspect(self, project_path: str | Path = ".") -> dict[str, Any]:
        project = self._path(project_path)
        if not project.is_dir():
            raise SafetyError("project path must be a directory")
        ioc = sorted(str(path.relative_to(project)) for path in project.glob("*.ioc"))
        markers = {
            name: (project / name).is_file()
            for name in ("CMakeLists.txt", "Makefile", ".project", ".cproject")
        }
        return {"ok": True, "project_path": str(project), "ioc_files": ioc, "markers": markers}

    def cubemx_generate_staged(
        self,
        ioc_file: str | Path,
        staging_dir: str | Path,
        *,
        timeout_s: float = 180,
    ) -> dict[str, Any]:
        ioc = self._path(ioc_file)
        if ioc.suffix.lower() != ".ioc" or not ioc.is_file():
            raise SafetyError("CubeMX input must be an existing .ioc file")
        staging = self._path(staging_dir, must_exist=False)
        if staging.exists() and any(staging.iterdir()):
            raise SafetyError("staging directory must be new or empty")
        if not self.cubemx:
            raise SafetyError("STM32CubeMX is not configured")
        for path in (ioc, staging):
            if any(character in str(path) for character in ('"', "\r", "\n")):
                raise SafetyError("CubeMX staging paths contain unsupported characters")
        staging.mkdir(parents=True, exist_ok=True)
        staged_ioc = staging / ioc.name
        shutil.copy2(ioc, staged_ioc)
        script = staging / ".stm32cubemx-generate.txt"
        script.write_text(
            "\n".join(
                (
                    f'config load "{staged_ioc}"',
                    f'project path "{staging}"',
                    "project generate",
                    "exit",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        receipt = self._run([self.cubemx, "-q", str(script)], staging, timeout_s, "cubemx.generate_staged")
        receipt["source_ioc_sha256"] = _sha256(ioc)
        receipt["staging_path"] = str(staging)
        return receipt

    def build_run(
        self,
        project_path: str | Path,
        *,
        build_dir: str | Path | None = None,
        target: str | None = None,
        timeout_s: float = 300,
    ) -> dict[str, Any]:
        project = self._path(project_path)
        if not (project / "CMakeLists.txt").is_file():
            raise SafetyError("controlled build requires CMakeLists.txt")
        build = self._path(build_dir or project / "build", must_exist=False)
        if target is not None and not re.fullmatch(r"[A-Za-z0-9_.+-]{1,80}", target):
            raise SafetyError("build target has an invalid format")
        build.mkdir(parents=True, exist_ok=True)
        configure = self._run(
            [self.cmake, "-S", str(project), "-B", str(build), "-G", "Ninja"],
            project,
            timeout_s,
            "build.configure",
        )
        if not configure["ok"]:
            return {"ok": False, "configure": configure, "build": None}
        command = [self.cmake, "--build", str(build)]
        if target:
            command.extend(["--target", target])
        built = self._run(command, project, timeout_s, "build.run")
        if built["ok"]:
            hashes = {
                _sha256(path) for path in build.rglob("*")
                if path.is_file() and path.suffix.lower() in self.ARTIFACT_SUFFIXES | {".map"}
            }
            built["tool_receipt"]["artifact_hashes"] = sorted(hashes)
        return {"ok": built["ok"], "configure": configure, "build": built}

    def artifact_inspect(self, artifact_path: str | Path, *, map_file: str | Path | None = None) -> dict[str, Any]:
        artifact = self._path(artifact_path)
        if not artifact.is_file() or artifact.suffix.lower() not in self.ARTIFACT_SUFFIXES:
            raise SafetyError("artifact must be an existing ELF, HEX, or BIN file")
        result: dict[str, Any] = {
            "ok": True,
            "path": str(artifact),
            "kind": artifact.suffix.lower()[1:],
            "size_bytes": artifact.stat().st_size,
            "sha256": _sha256(artifact),
        }
        if map_file is not None:
            map_path = self._path(map_file)
            if not map_path.is_file() or map_path.suffix.lower() != ".map":
                raise SafetyError("map_file must be an existing .map file")
            result["map"] = _map_summary(map_path.read_text(encoding="utf-8", errors="replace"))
            result["map"]["path"] = str(map_path)
        return result

    def test_host(self, test_path: str | Path, *, timeout_s: float = 120) -> dict[str, Any]:
        path = self._path(test_path)
        if not path.exists() or not (path.is_dir() or path.suffix == ".py"):
            raise SafetyError("host test path must be a Python test file or directory")
        return self._run(
            [os.fspath(Path(os.sys.executable)), "-m", "pytest", str(path), "-q"],
            self.workspace_root,
            timeout_s,
            "test.host",
        )

    def probe_list(self, *, timeout_s: float = 15) -> dict[str, Any]:
        if self.probe_provider is not None:
            probes = list(self.probe_provider())
            return {"ok": True, "probes": probes, "count": len(probes)}
        receipt = self._run([self.programmer, "-l"], self.workspace_root, timeout_s, "probe.list")
        probes = parse_probe_list(receipt["stdout"]) if receipt["ok"] else []
        return {"ok": receipt["ok"], "probes": probes, "count": len(probes), "receipt": receipt}

    def _query_target(
        self, probe_serial: str | None = None, *, board_profile: str, timeout_s: float = 15,
    ) -> dict[str, Any]:
        profile = self.board_profiles.get(board_profile)
        if profile is None:
            raise SafetyError("board profile is not present in the managed external registry")
        listed = self.probe_list(timeout_s=timeout_s)
        probes = listed["probes"]
        if not probes:
            raise SafetyError("no connected ST-Link probe was identified")
        if probe_serial is None:
            if len(probes) != 1:
                raise SafetyError("multiple ST-Link probes are connected; provide an exact serial")
            probe_serial = str(probes[0]["serial_number"])
        matches = [item for item in probes if str(item.get("serial_number")) == probe_serial]
        if len(matches) != 1:
            raise SafetyError("requested ST-Link serial is not uniquely connected")
        connection_receipt = self._run(
            [self.programmer, "-c", f"port=SWD sn={probe_serial}"],
            self.workspace_root,
            timeout_s,
            "target.identify",
        )
        if not connection_receipt["ok"]:
            raise SafetyError("target identity query failed")
        if profile["identity_layout"] != "stm32f103-medium-density":
            raise SafetyError("managed board profile identity layout is unsupported")
        flash_receipt = self._run(
            [self.programmer, "-c", f"port=SWD sn={probe_serial}", "-r32", "0x1FFFF7E0", "0x4"],
            self.workspace_root, timeout_s, "target.flash_size",
        )
        uid_receipt = self._run(
            [self.programmer, "-c", f"port=SWD sn={probe_serial}", "-r32", "0x1FFFF7E8", "0xC"],
            self.workspace_root, timeout_s, "target.uid",
        )
        if not flash_receipt["ok"] or not uid_receipt["ok"]:
            raise SafetyError("factory flash-size or MCU UID read failed")
        identity = parse_target_identity(connection_receipt["stdout"], probe_serial)
        identity.update(parse_f103_factory_identity(flash_receipt["stdout"], uid_receipt["stdout"]))
        return {
            "ok": True, "observed_target": identity, "probe": matches[0],
            "receipts": [connection_receipt, flash_receipt, uid_receipt],
        }

    def target_identify(
        self,
        probe_serial: str | None = None,
        *,
        board_profile: str,
        timeout_s: float = 15,
    ) -> dict[str, Any]:
        profile = self.board_profiles.get(board_profile)
        if profile is None:
            raise SafetyError("board profile is not present in the managed external registry")
        observed = self._query_target(probe_serial, board_profile=board_profile, timeout_s=timeout_s)
        target = {
            **observed["observed_target"],
            "board_profile": board_profile,
            "board_evidence_hash": profile["board_evidence_hash"],
        }
        canonical = json.loads(self._target_json(target))
        self._managed_profile(canonical, require_flash=False)
        flash_eligible = (
            profile["flash_enabled"]
            and canonical["mcu_uid"] in profile["allowed_mcu_uids"]
            and canonical["probe_serial"] in profile["allowed_probe_serials"]
        )
        return {
            "ok": True,
            "target": canonical,
            "probe": observed["probe"],
            "machine_verified_fields": [
                "probe_serial", "mcu_device_id", "mcu_uid", "flash_capacity_bytes", "target_voltage_v",
            ],
            "evidence_bound_fields": ["board_profile", "board_evidence_hash"],
            "flash_eligible": flash_eligible,
            "flash_blockers": [] if flash_eligible else ["board_profile_not_enrolled_for_this_uid_and_probe"],
            "receipts": observed["receipts"],
        }

    def serial_list(self) -> dict[str, Any]:
        if self.serial_provider is not None:
            devices = self.serial_provider()
        else:
            try:
                from serial.tools import list_ports
            except ImportError:
                return {"ok": False, "ports": [], "count": 0, "diagnostic": {"category": "dependency", "message": "pyserial is not installed"}}
            devices = list_ports.comports()
        ports = parse_serial_devices(devices)
        return {"ok": True, "ports": ports, "count": len(ports)}

    def serial_capture(
        self,
        port: str,
        *,
        baudrate: int = 115200,
        timeout_s: float = 3.0,
        max_bytes: int = 64 * 1024,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"COM\d{1,3}", port, re.I):
            raise SafetyError("serial port must be an explicit Windows COM port")
        if baudrate not in {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600}:
            raise SafetyError("baudrate is not in the allowed set")
        timeout = float(timeout_s)
        if timeout <= 0 or timeout > self.MAX_SERIAL_TIMEOUT_S:
            raise SafetyError("serial timeout is outside the allowed range")
        if not isinstance(max_bytes, int) or max_bytes <= 0 or max_bytes > self.MAX_SERIAL_BYTES:
            raise SafetyError("max_bytes is outside the allowed range")
        opener = self.serial_opener
        if opener is None:
            try:
                import serial
            except ImportError as exc:
                raise SafetyError("pyserial is required for serial capture") from exc
            opener = serial.Serial
        try:
            device = opener(port=port.upper(), baudrate=baudrate, timeout=min(0.1, timeout))
        except (OSError, IOError) as exc:
            return {
                "ok": False,
                "port": port.upper(),
                "baudrate": baudrate,
                "bytes_captured": 0,
                "truncated": False,
                "text": "",
                "json_frames": [],
                "parse_errors": [],
                "diagnostic": {"category": "serial_unavailable", "message": str(exc)[:500]},
            }
        start = self.clock()
        data = bytearray()
        truncated = False
        disconnect_error: str | None = None
        try:
            while self.clock() - start < timeout:
                try:
                    chunk = device.read(min(4096, max_bytes - len(data) + 1))
                except (OSError, IOError) as exc:
                    disconnect_error = str(exc)
                    break
                if chunk:
                    remaining = max_bytes - len(data)
                    data.extend(chunk[:remaining])
                    if len(chunk) > remaining or len(data) >= max_bytes:
                        truncated = True
                        break
                else:
                    time.sleep(0.001)
        finally:
            device.close()
        text = bytes(data).decode("utf-8", errors="replace")
        frames: list[dict[str, Any]] = []
        parse_errors: list[dict[str, Any]] = []
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    frames.append(value)
                else:
                    parse_errors.append({"line": index, "category": "not_object"})
            except json.JSONDecodeError as exc:
                parse_errors.append({"line": index, "category": "invalid_json", "column": exc.colno})
        category = "serial_disconnected" if disconnect_error else "serial_flood" if truncated else "ok"
        message = disconnect_error or ("byte limit reached" if truncated else "capture complete")
        return {
            "ok": not truncated and disconnect_error is None,
            "port": port.upper(),
            "baudrate": baudrate,
            "bytes_captured": len(data),
            "truncated": truncated,
            "text": text,
            "json_frames": frames,
            "parse_errors": parse_errors,
            "diagnostic": {"category": category, "message": message[:500]},
        }

    def flash_plan(
        self,
        artifact_path: str | Path,
        *,
        target: Mapping[str, Any],
        baseline: str,
        address: str = "0x08000000",
    ) -> dict[str, Any]:
        artifact = self.artifact_inspect(artifact_path)
        if Path(artifact["path"]).suffix.lower() not in self.FLASHABLE_SUFFIXES:
            raise SafetyError("flash execution accepts only a raw BIN image at the fixed application address")
        if artifact["size_bytes"] <= 0 or artifact["size_bytes"] > self.MAX_FLASH_IMAGE_BYTES:
            raise SafetyError("BIN image size is outside the allowed flash range")
        if not isinstance(baseline, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", baseline):
            raise SafetyError("baseline is required and has an invalid format")
        if address.lower() != "0x08000000":
            raise SafetyError("flash address is not in the fixed application-address allowlist")
        target_json = self._target_json(target)
        canonical_target = json.loads(target_json)
        if artifact["size_bytes"] > canonical_target["flash_capacity_bytes"]:
            raise SafetyError("BIN image exceeds the exact board profile flash capacity")
        self._verify_connected_target(json.loads(target_json))
        token = secrets.token_urlsafe(32)
        expires_at = self.clock() + self.token_ttl_s
        with self._grant_lock:
            if len(self._grants) >= self.MAX_FLASH_GRANTS:
                self._grants = {
                    key: value for key, value in self._grants.items()
                    if not value.consumed and value.expires_at >= self.clock()
                }
            if len(self._grants) >= self.MAX_FLASH_GRANTS:
                raise SafetyError("too many active flash confirmations; wait for an existing plan to expire")
            self._grants[token] = _FlashGrant(
                artifact_path=artifact["path"],
                artifact_sha256=artifact["sha256"],
                target_json=target_json,
                baseline=baseline,
                address=address,
                expires_at=expires_at,
            )
        return {
            "ok": True,
            "target": canonical_target,
            "baseline": baseline,
            "address_range": {
                "start": address,
                "length_bytes": artifact["size_bytes"],
                "profile_capacity_bytes": canonical_target["flash_capacity_bytes"],
            },
            "artifact_path": artifact["path"],
            "artifact_sha256": artifact["sha256"],
            "confirmation_token": token,
            "expires_in_seconds": self.token_ttl_s,
            "warning": "One-time confirmation is required; build or flash success does not prove hardware function.",
        }

    def flash_execute(
        self,
        confirmation_token: str,
        artifact_path: str | Path,
        *,
        target: Mapping[str, Any],
        baseline: str,
        timeout_s: float = 120,
    ) -> dict[str, Any]:
        # Claim before hashing or probing.  Without this critical section two
        # concurrent execute calls could both pass the initial token check.
        with self._grant_lock:
            grant = self._grants.get(confirmation_token)
            if grant is None:
                raise SafetyError("unknown flash confirmation token")
            if grant.consumed:
                raise SafetyError("flash confirmation token was already consumed")
            if self.clock() > grant.expires_at:
                grant.consumed = True
                raise SafetyError("flash confirmation token expired")
            grant.consumed = True
        artifact = self.artifact_inspect(artifact_path)
        target_json = self._target_json(target)
        mismatch = (
            artifact["path"] != grant.artifact_path
            or artifact["sha256"] != grant.artifact_sha256
            or target_json != grant.target_json
            or baseline != grant.baseline
        )
        if mismatch:
            raise SafetyError("artifact, target, or baseline changed; flash token is invalid")
        target_data = json.loads(target_json)
        # The workspace artifact remains mutable.  Program a private, verified
        # copy so a concurrent editor cannot swap bytes after the approval hash
        # was calculated but before CubeProgrammer opens the file.
        with tempfile.TemporaryDirectory(prefix="stm32-ai-mentor-flash-") as temporary_dir:
            staged = Path(temporary_dir) / "approved-firmware.bin"
            shutil.copyfile(Path(artifact["path"]), staged)
            staged_hash = _sha256(staged)
            if staged_hash != grant.artifact_sha256:
                raise SafetyError("artifact changed while it was staged; flash was cancelled")
            os.chmod(staged, stat.S_IREAD)
            try:
                self._verify_connected_target(target_data)
                command = [
                    self.programmer,
                    "-c",
                    f"port=SWD sn={target_data['probe_serial']}",
                    "-w",
                    str(staged),
                    grant.address,
                    "-v",
                    "-rst",
                ]
                receipt = self._run(command, self.workspace_root, timeout_s, "flash.execute")
            finally:
                os.chmod(staged, stat.S_IWRITE | stat.S_IREAD)
        receipt.update(
            {
                "artifact_sha256": artifact["sha256"],
                "staged_artifact_sha256": staged_hash,
                "staged_copy_ephemeral": True,
                "target": target_data,
                "baseline": baseline,
                "verified_requested": True,
                "reset_requested": True,
            }
        )
        receipt["tool_receipt"]["artifact_hashes"] = [artifact["sha256"]]
        return receipt

    def target_reset(self, target: Mapping[str, Any], *, timeout_s: float = 15) -> dict[str, Any]:
        target_data = json.loads(self._target_json(target))
        self._verify_connected_target(target_data)
        return self._run(
            [self.programmer, "-c", f"port=SWD sn={target_data['probe_serial']}", "-rst"],
            self.workspace_root,
            timeout_s,
            "target.reset",
        )

    def test_target(
        self,
        port: str,
        *,
        required_events: list[str],
        baudrate: int = 115200,
        timeout_s: float = 3,
        max_bytes: int = 64 * 1024,
    ) -> dict[str, Any]:
        if not required_events or any(not isinstance(item, str) or not item for item in required_events):
            raise SafetyError("target test requires explicit event assertions")
        capture = self.serial_capture(port, baudrate=baudrate, timeout_s=timeout_s, max_bytes=max_bytes)
        observed = {str(frame.get("event")) for frame in capture["json_frames"] if "event" in frame}
        missing = [event for event in required_events if event not in observed]
        return {"ok": capture["ok"] and not missing, "required_events": required_events, "missing_events": missing, "capture": capture}

    def job_status(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise SafetyError("unknown job id")
        return dict(job)

    def job_cancel(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise SafetyError("unknown job id")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return {"ok": False, "job_id": job_id, "status": job["status"], "message": "job is already terminal"}
        job["status"] = "cancelled"
        return {"ok": True, "job_id": job_id, "status": "cancelled"}
