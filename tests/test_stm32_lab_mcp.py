from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stm32_lab_mcp.core import (  # noqa: E402
    SafetyError,
    STM32Lab,
    parse_f103_factory_identity,
    parse_probe_list,
)


class FakeRunner:
    def __init__(self, stdout: str = "ok") -> None:
        self.stdout = stdout
        self.calls: list[tuple[list[str], Path, float]] = []

    def __call__(self, command: list[str], cwd: Path, timeout_s: float):
        self.calls.append((command, cwd, timeout_s))
        return {"exit_code": 0, "stdout": self.stdout, "stderr": ""}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "含中文 workspace"
    root.mkdir()
    return root


DEFAULT_UID = "112233445566778899aabbcc"


def managed_profiles(target: dict, *, flash_enabled: bool = True) -> dict:
    return {
        target["board_profile"]: {
            "board_evidence_hash": target["board_evidence_hash"],
            "flash_capacity_bytes": target["flash_capacity_bytes"],
            "mcu_device_ids": [target["mcu_device_id"]],
            "allowed_mcu_uids": [target["mcu_uid"]] if flash_enabled else [],
            "allowed_probe_serials": [target["probe_serial"]] if flash_enabled else [],
            "identity_layout": "stm32f103-medium-density",
            "flash_enabled": flash_enabled,
            "evidence_refs": ["test evidence bundle"],
        }
    }


def test_factory_identity_parser_requires_flash_size_and_uid():
    parsed = parse_f103_factory_identity(
        "0x1FFFF7E0 : 00000080\n",
        "0x1FFFF7E8 : 11223344 55667788 99AABBCC\n",
    )
    assert parsed == {"flash_capacity_bytes": 128 * 1024, "mcu_uid": DEFAULT_UID}
    with pytest.raises(SafetyError, match="incomplete|not returned"):
        parse_f103_factory_identity("", "")


def test_workspace_paths_fail_closed_outside_root(workspace: Path, tmp_path: Path):
    lab = STM32Lab(workspace)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(SafetyError, match="workspace"):
        lab.project_inspect(outside)


def test_probe_parser_does_not_choose_between_duplicate_probes():
    output = """
      ST-LINK SN  : 066CFF555052717867064941
      ST-LINK FW  : V2J45S7
      ST-LINK SN  : 0671FF485550755187031637
      ST-LINK FW  : V2J45S7
    """
    probes = parse_probe_list(output)
    assert [item["serial_number"] for item in probes] == [
        "066CFF555052717867064941",
        "0671FF485550755187031637",
    ]

    target = {
        "probe_serial": probes[0]["serial_number"], "mcu_device_id": "0x410", "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1", "board_evidence_hash": "a" * 64,
        "flash_capacity_bytes": 128 * 1024, "target_voltage_v": 3.3,
    }
    lab = STM32Lab(Path.cwd(), probe_provider=lambda: probes, board_profiles=managed_profiles(target))
    with pytest.raises(SafetyError, match="multiple"):
        lab.target_identify(board_profile="nucleo-f103rb-r1")


def test_target_identify_returns_the_strict_identity_contract(workspace: Path):
    serial = "066CFF555052717867064941"
    target = {
        "probe_serial": serial, "mcu_device_id": "0x410", "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1", "board_evidence_hash": "a" * 64,
        "flash_capacity_bytes": 128 * 1024, "target_voltage_v": 3.3,
    }
    runner = FakeRunner(
        "Device ID : 0x410\nTarget voltage : 3.30 V\n"
        "0x1FFFF7E0 : 00000080\n0x1FFFF7E8 : 11223344 55667788 99AABBCC\n"
    )
    lab = STM32Lab(
        workspace, runner=runner,
        probe_provider=lambda: [{"serial_number": serial, "model": "ST-LINK/V2"}],
        board_profiles=managed_profiles(target),
    )
    result = lab.target_identify(serial, board_profile="nucleo-f103rb-r1")
    assert set(result["target"]) == {
        "probe_serial", "mcu_device_id", "mcu_uid", "board_profile", "board_evidence_hash",
        "flash_capacity_bytes", "target_voltage_v",
    }
    assert result["machine_verified_fields"] == [
        "probe_serial", "mcu_device_id", "mcu_uid", "flash_capacity_bytes", "target_voltage_v",
    ]
    assert "board_profile" in result["evidence_bound_fields"]


def test_flash_token_is_single_use_and_bound_to_target_baseline_and_artifact(
    workspace: Path,
):
    firmware = workspace / "app.bin"
    firmware.write_bytes(b"firmware-v1")
    runner = FakeRunner()
    target = {
        "probe_serial": "066CFF555052717867064941",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1",
        "board_evidence_hash": "a" * 64,
        "flash_capacity_bytes": 128 * 1024,
        "target_voltage_v": 3.31,
    }
    lab = STM32Lab(
        workspace,
        runner=runner,
        programmer="STM32_Programmer_CLI.exe",
        target_verifier=lambda candidate: candidate == target,
        board_profiles=managed_profiles(target),
    )

    plan = lab.flash_plan(
        firmware,
        target=target,
        baseline="baseline-7",
        address="0x08000000",
    )
    assert plan["artifact_sha256"] == hashlib.sha256(b"firmware-v1").hexdigest()
    assert plan["confirmation_token"]

    receipt = lab.flash_execute(
        plan["confirmation_token"],
        firmware,
        target=target,
        baseline="baseline-7",
    )
    assert receipt["ok"] is True
    command = runner.calls[-1][0]
    assert command[:4] == [
        "STM32_Programmer_CLI.exe", "-c",
        "port=SWD sn=066CFF555052717867064941", "-w",
    ]
    assert Path(command[4]).name == "approved-firmware.bin"
    assert command[5:] == ["0x08000000", "-v", "-rst"]
    assert receipt["staged_artifact_sha256"] == receipt["artifact_sha256"]
    assert set(receipt["tool_receipt"]) == {
        "receipt_id", "tool", "exit_code", "log_hash", "diagnostic_class",
        "tool_version", "timestamp", "artifact_hashes",
    }
    assert receipt["tool_receipt"]["artifact_hashes"] == [receipt["artifact_sha256"]]
    assert not any("erase" in part.lower() or "ob" == part.lower() for part in command)

    with pytest.raises(SafetyError, match="consumed"):
        lab.flash_execute(
            plan["confirmation_token"],
            firmware,
            target=target,
            baseline="baseline-7",
        )


def test_changed_firmware_invalidates_flash_token(workspace: Path):
    firmware = workspace / "app.bin"
    firmware.write_bytes(b"firmware-v1")
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "bluepill-confirmed-r2",
        "board_evidence_hash": "b" * 64,
        "flash_capacity_bytes": 64 * 1024,
        "target_voltage_v": 3.3,
    }
    lab = STM32Lab(
        workspace, runner=FakeRunner(), target_verifier=lambda _candidate: True,
        board_profiles=managed_profiles(target),
    )
    plan = lab.flash_plan(firmware, target=target, baseline="b1")
    firmware.write_bytes(b"firmware-v2")

    with pytest.raises(SafetyError, match="artifact"):
        lab.flash_execute(plan["confirmation_token"], firmware, target=target, baseline="b1")


def test_server_declares_exact_narrow_tool_names_without_requiring_mcp_sdk():
    server = importlib.import_module("stm32_lab_mcp.server")
    assert server.TOOL_NAMES == (
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
    assert "raw_shell" not in server.TOOL_NAMES
    assert server.discover_workspace_root(SCRIPTS) == ROOT


def test_server_reads_only_fixed_tool_paths_from_environment(workspace: Path):
    server = importlib.import_module("stm32_lab_mcp.server")
    environment = {
        "STM32_PROGRAMMER_CLI": r"C:\ST\CubeProgrammer\STM32_Programmer_CLI.exe",
        "STM32_CMAKE": r"C:\ST\CubeCLT\CMake\bin\cmake.exe",
        "STM32_CUBEMX": r"C:\ST\CubeMX\STM32CubeMX.exe",
        "SHELL": r"C:\malicious.exe --raw",
    }
    lab = server.lab_from_environment(workspace, environment)
    assert lab.programmer == environment["STM32_PROGRAMMER_CLI"]
    assert lab.cmake == environment["STM32_CMAKE"]
    assert lab.cubemx == environment["STM32_CUBEMX"]
    assert "malicious" not in (lab.programmer + lab.cmake + lab.cubemx)


def test_server_wrapper_turns_expected_and_unexpected_failures_into_structured_results():
    server = importlib.import_module("stm32_lab_mcp.server")

    def denied():
        raise SafetyError("blocked")

    def crashed():
        raise RuntimeError("secret traceback detail")

    assert server._safe_tool(denied)()["error"] == {"code": "safety_denied", "message": "blocked"}
    unexpected = server._safe_tool(crashed)()
    assert unexpected["error"]["code"] == "internal_error"
    assert "secret" not in unexpected["error"]["message"]


def test_external_policy_restricts_workspace_and_tool_surface(workspace: Path, tmp_path: Path):
    server = importlib.import_module("stm32_lab_mcp.server")
    target = {
        "probe_serial": "ABC123", "mcu_device_id": "0x410", "mcu_uid": DEFAULT_UID,
        "board_profile": "test-board", "board_evidence_hash": "a" * 64,
        "flash_capacity_bytes": 64 * 1024, "target_voltage_v": 3.3,
    }
    policy = tmp_path / "permissions.json"
    policy.write_text(json.dumps({
        "schema_version": 1,
        "workspace_roots": [str(workspace)],
        "stm32_lab": {
            "allowed_tools": list(server.TOOL_NAMES),
            "board_profiles": managed_profiles(target),
        },
    }), encoding="utf-8")
    lab = server.lab_from_environment(workspace, {"STM32_AI_MENTOR_POLICY": str(policy)})
    assert lab.workspace_root == workspace.resolve()

    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(RuntimeError, match="not authorized"):
        server.lab_from_environment(other, {"STM32_AI_MENTOR_POLICY": str(policy)})

    changed = json.loads(policy.read_text(encoding="utf-8"))
    changed["stm32_lab"]["allowed_tools"].append("raw_shell")
    policy.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(RuntimeError, match="allowlist"):
        server.lab_from_environment(workspace, {"STM32_AI_MENTOR_POLICY": str(policy)})


def test_artifact_inspection_hashes_binary_and_summarizes_map(workspace: Path):
    artifact = workspace / "build" / "app.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"\x00\x01\x02")
    map_file = artifact.with_suffix(".map")
    map_file.write_text(
        "Memory Configuration\nFLASH 0x08000000 0x00020000\nRAM 0x20000000 0x00005000\n"
        " .text 0x08000000 0x00000120\n .data 0x20000000 0x00000020\n"
        " .bss 0x20000020 0x00000040\n",
        encoding="utf-8",
    )
    result = STM32Lab(workspace).artifact_inspect(artifact, map_file=map_file)
    assert result["sha256"] == hashlib.sha256(b"\x00\x01\x02").hexdigest()
    assert result["size_bytes"] == 3
    assert result["map"]["sections"][".text"] == 0x120


def test_serial_capture_has_byte_limit_and_parses_json_diagnostics(workspace: Path):
    class Port:
        chunks = [
            b'{"event":"boot","self_test":"ok"}\n',
            b'{"event":"sample","temperature_c":24.5}\n',
        ]

        def read(self, _size: int) -> bytes:
            return self.chunks.pop(0) if self.chunks else b""

        def close(self) -> None:
            pass

    lab = STM32Lab(workspace, serial_opener=lambda **_kwargs: Port())
    result = lab.serial_capture("COM7", baudrate=115200, timeout_s=0.05, max_bytes=256)
    assert result["truncated"] is False
    assert [frame["event"] for frame in result["json_frames"]] == ["boot", "sample"]

    with pytest.raises(SafetyError, match="max_bytes"):
        lab.serial_capture("COM7", max_bytes=2_000_000)


def test_receipts_are_json_serializable(workspace: Path):
    result = STM32Lab(workspace).project_inspect(workspace)
    json.dumps(result, ensure_ascii=False)


def test_command_receipt_exposes_a_ledger_safe_tool_receipt(workspace: Path):
    project = workspace / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text("project(smoke)\n", encoding="utf-8")
    lab = STM32Lab(workspace, runner=FakeRunner(), cmake="cmake.exe", tool_versions={"CMake": "4.4.2"})
    result = lab.build_run(project)
    receipt = result["build"]["tool_receipt"]
    assert receipt["tool"] == "build.run"
    assert receipt["tool_version"] == "4.4.2"
    assert len(receipt["log_hash"]) == 64


def test_flash_plan_fails_closed_when_target_is_not_connected(workspace: Path):
    firmware = workspace / "app.bin"
    firmware.write_bytes(b"firmware")
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1",
        "board_evidence_hash": "c" * 64,
        "flash_capacity_bytes": 128 * 1024,
        "target_voltage_v": 3.3,
    }
    lab = STM32Lab(
        workspace, target_verifier=lambda _candidate: False,
        board_profiles=managed_profiles(target),
    )

    with pytest.raises(SafetyError, match="connected target"):
        lab.flash_plan(firmware, target=target, baseline="b1")


def test_controlled_build_uses_only_cmake_templates(workspace: Path):
    project = workspace / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text("project(smoke)\n", encoding="utf-8")
    runner = FakeRunner()
    lab = STM32Lab(workspace, runner=runner, cmake="cmake.exe")

    result = lab.build_run(project, target="firmware")
    assert result["ok"] is True
    assert runner.calls[0][0] == [
        "cmake.exe",
        "-S",
        str(project.resolve()),
        "-B",
        str((project / "build").resolve()),
        "-G",
        "Ninja",
    ]
    assert runner.calls[1][0][-2:] == ["--target", "firmware"]

    with pytest.raises(SafetyError, match="target"):
        lab.build_run(project, target="firmware; Remove-Item C:\\")


def test_flash_plan_rejects_arbitrary_memory_addresses(workspace: Path):
    firmware = workspace / "app.bin"
    firmware.write_bytes(b"firmware")
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1",
        "board_evidence_hash": "d" * 64,
        "flash_capacity_bytes": 128 * 1024,
        "target_voltage_v": 3.3,
    }
    lab = STM32Lab(
        workspace, target_verifier=lambda _candidate: True,
        board_profiles=managed_profiles(target),
    )

    for address in ("0x20000000", "0x08001000"):
        with pytest.raises(SafetyError, match="address"):
            lab.flash_plan(firmware, target=target, baseline="b1", address=address)


def test_flash_rejects_address_bearing_artifacts_even_though_they_can_be_inspected(workspace: Path):
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1",
        "board_evidence_hash": "e" * 64,
        "flash_capacity_bytes": 128 * 1024,
        "target_voltage_v": 3.3,
    }
    lab = STM32Lab(
        workspace, target_verifier=lambda _candidate: True,
        board_profiles=managed_profiles(target),
    )
    for suffix, content in ((".hex", b":00000001FF\n"), (".elf", b"not-a-real-elf")):
        artifact = workspace / f"app{suffix}"
        artifact.write_bytes(content)
        assert lab.artifact_inspect(artifact)["kind"] == suffix[1:]
        with pytest.raises(SafetyError, match="BIN"):
            lab.flash_plan(artifact, target=target, baseline="b1")


def test_flash_token_claim_is_atomic_under_concurrent_execute(workspace: Path):
    firmware = workspace / "app.bin"
    firmware.write_bytes(b"firmware")
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1",
        "board_evidence_hash": "f" * 64,
        "flash_capacity_bytes": 128 * 1024,
        "target_voltage_v": 3.3,
    }
    barrier = threading.Barrier(2)

    class RacingLab(STM32Lab):
        race = False

        def artifact_inspect(self, *args, **kwargs):
            result = super().artifact_inspect(*args, **kwargs)
            if self.race:
                try:
                    barrier.wait(timeout=0.2)
                except threading.BrokenBarrierError:
                    pass
            return result

    runner = FakeRunner()
    lab = RacingLab(
        workspace, runner=runner, target_verifier=lambda _candidate: True,
        board_profiles=managed_profiles(target),
    )
    plan = lab.flash_plan(firmware, target=target, baseline="b1")
    lab.race = True
    outcomes: list[str] = []

    def execute() -> None:
        try:
            lab.flash_execute(plan["confirmation_token"], firmware, target=target, baseline="b1")
            outcomes.append("flashed")
        except SafetyError:
            outcomes.append("denied")

    threads = [threading.Thread(target=execute), threading.Thread(target=execute)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert sorted(outcomes) == ["denied", "flashed"]
    assert sum(1 for command, _cwd, _timeout in runner.calls if "-w" in command) == 1


def test_flash_executes_an_immutable_staged_copy_not_the_mutable_workspace_file(workspace: Path):
    firmware = workspace / "app.bin"
    original = b"firmware-approved"
    replacement = b"firmware-swapped"
    firmware.write_bytes(original)
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1",
        "board_evidence_hash": "1" * 64,
        "flash_capacity_bytes": 128 * 1024,
        "target_voltage_v": 3.3,
    }

    class ReadingRunner(FakeRunner):
        programmed_bytes: bytes | None = None

        def __call__(self, command, cwd, timeout_s):
            if "-w" in command:
                self.programmed_bytes = Path(command[command.index("-w") + 1]).read_bytes()
            return super().__call__(command, cwd, timeout_s)

    runner = ReadingRunner()
    mutate_on_second_verification = {"count": 0}

    def verifier(_candidate):
        mutate_on_second_verification["count"] += 1
        if mutate_on_second_verification["count"] == 2:
            firmware.write_bytes(replacement)
        return True

    lab = STM32Lab(
        workspace, runner=runner, target_verifier=verifier,
        board_profiles=managed_profiles(target),
    )
    plan = lab.flash_plan(firmware, target=target, baseline="b1")
    receipt = lab.flash_execute(plan["confirmation_token"], firmware, target=target, baseline="b1")

    assert runner.programmed_bytes == original
    assert receipt["artifact_sha256"] == hashlib.sha256(original).hexdigest()
    flashed_path = Path(runner.calls[-1][0][runner.calls[-1][0].index("-w") + 1])
    assert flashed_path != firmware.resolve()
    assert not flashed_path.exists()


def test_flash_plan_enforces_the_profile_specific_flash_capacity(workspace: Path):
    firmware = workspace / "too-large.bin"
    firmware.write_bytes(b"x" * 1025)
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "test-board-1k",
        "board_evidence_hash": "2" * 64,
        "flash_capacity_bytes": 1024,
        "target_voltage_v": 3.3,
    }
    lab = STM32Lab(
        workspace, target_verifier=lambda _candidate: True,
        board_profiles=managed_profiles(target),
    )
    with pytest.raises(SafetyError, match="capacity"):
        lab.flash_plan(firmware, target=target, baseline="b1")


def test_flash_plan_rejects_forged_or_unenrolled_board_profile(workspace: Path):
    firmware = workspace / "app.bin"
    firmware.write_bytes(b"firmware")
    target = {
        "probe_serial": "ABC123", "mcu_device_id": "0x410", "mcu_uid": DEFAULT_UID,
        "board_profile": "managed-board", "board_evidence_hash": "4" * 64,
        "flash_capacity_bytes": 128 * 1024, "target_voltage_v": 3.3,
    }
    forged_registry = managed_profiles(target)
    forged_registry[target["board_profile"]]["flash_capacity_bytes"] = 64 * 1024
    with pytest.raises(SafetyError, match="managed board profile"):
        STM32Lab(
            workspace, target_verifier=lambda _candidate: True,
            board_profiles=forged_registry,
        ).flash_plan(firmware, target=target, baseline="b1")

    with pytest.raises(SafetyError, match="inspection-only"):
        STM32Lab(
            workspace, target_verifier=lambda _candidate: True,
            board_profiles=managed_profiles(target, flash_enabled=False),
        ).flash_plan(firmware, target=target, baseline="b1")


def test_target_identify_rejects_factory_capacity_mismatch(workspace: Path):
    serial = "ABC123"
    target = {
        "probe_serial": serial, "mcu_device_id": "0x410", "mcu_uid": DEFAULT_UID,
        "board_profile": "managed-board", "board_evidence_hash": "5" * 64,
        "flash_capacity_bytes": 64 * 1024, "target_voltage_v": 3.3,
    }
    runner = FakeRunner(
        "Device ID : 0x410\nTarget voltage : 3.30 V\n"
        "0x1FFFF7E0 : 00000080\n0x1FFFF7E8 : 11223344 55667788 99AABBCC\n"
    )
    lab = STM32Lab(
        workspace, runner=runner, probe_provider=lambda: [{"serial_number": serial}],
        board_profiles=managed_profiles(target),
    )
    with pytest.raises(SafetyError, match="flash capacity"):
        lab.target_identify(serial, board_profile=target["board_profile"])


def test_target_identity_rejects_bad_voltage_as_structured_safety_error(workspace: Path):
    firmware = workspace / "app.bin"
    firmware.write_bytes(b"firmware")
    target = {
        "probe_serial": "ABC123",
        "mcu_device_id": "0x410",
        "mcu_uid": DEFAULT_UID,
        "board_profile": "nucleo-f103rb-r1",
        "board_evidence_hash": "3" * 64,
        "flash_capacity_bytes": 128 * 1024,
        "target_voltage_v": "bad",
    }
    with pytest.raises(SafetyError, match="voltage"):
        STM32Lab(
            workspace, target_verifier=lambda _candidate: True,
            board_profiles=managed_profiles(target),
        ).flash_plan(
            firmware, target=target, baseline="b1",
        )


def test_build_process_crash_becomes_structured_receipt(workspace: Path):
    project = workspace / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text("project(smoke)\n", encoding="utf-8")

    def crashed_runner(_command, _cwd, _timeout):
        raise OSError("process vanished")

    result = STM32Lab(workspace, runner=crashed_runner).build_run(project)
    assert result["ok"] is False
    assert result["configure"]["diagnostic"]["category"] == "tool_crash"


def test_serial_disconnect_returns_structured_diagnostic(workspace: Path):
    class DisconnectedPort:
        def read(self, _size: int) -> bytes:
            raise OSError("device disconnected")

        def close(self) -> None:
            pass

    lab = STM32Lab(workspace, serial_opener=lambda **_kwargs: DisconnectedPort())
    result = lab.serial_capture("COM8", timeout_s=0.05)
    assert result["ok"] is False
    assert result["diagnostic"]["category"] == "serial_disconnected"


def test_cubemx_generation_uses_a_fixed_quiet_script_and_staging_path(workspace: Path):
    ioc = workspace / "source" / "station.ioc"
    ioc.parent.mkdir()
    ioc.write_text("Mcu.Name=STM32F103C8Tx\n", encoding="utf-8")
    runner = FakeRunner()
    lab = STM32Lab(workspace, runner=runner, cubemx="STM32CubeMX.exe")

    result = lab.cubemx_generate_staged(ioc, workspace / "stage")
    assert result["ok"] is True
    command = runner.calls[0][0]
    assert command[:2] == ["STM32CubeMX.exe", "-q"]
    script = Path(command[2])
    lines = script.read_text(encoding="utf-8").splitlines()
    assert lines == [
        f'config load "{(workspace / "stage" / "station.ioc").resolve()}"',
        f'project path "{(workspace / "stage").resolve()}"',
        "project generate",
        "exit",
    ]
