import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts" / "project_tool.py"
SCHEMAS = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "schemas"


def run_cli(projects: Path, *args: str, ok: bool = True):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-dir", str(projects), *args],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if ok and completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    if not ok:
        assert completed.returncode != 0
    stream = completed.stdout if completed.returncode == 0 else completed.stderr
    return json.loads(stream)


def intake(**overrides):
    value = {
        "goal": "制作桌面温湿度站",
        "requirements": [{"requirement_id": "R1", "text": "每秒输出一次", "acceptance_ids": ["A1"]}],
        "acceptance_criteria": [{
            "acceptance_id": "A1", "text": "连续输出 10 次", "requires_hardware": False,
            "metric": "samples", "operator": "gte", "threshold": 10, "unit": "count",
            "window": {"duration": 15, "unit": "s"}, "observation_method": "serial_log",
        }],
        "exact_target": {
            "mcu": "STM32F103C8Tx", "package": "LQFP48", "board": "Blue Pill",
            "board_revision": "BP-A", "toolchain": {
                "ide": {"name": "STM32CubeIDE", "version": "1.19.0"},
                "firmware_package": {"name": "STM32CubeF1", "version": "1.8.6"},
                "compiler": {"name": "GNU Arm Embedded", "version": "13.3"},
                "programmer": {"name": "STM32CubeProgrammer", "version": "2.23.0"},
            },
        },
        "resources": {
            "components": [{"component_id": "sensor", "name": "SHT31", "model": "SHT31-D", "quantity": 1}],
            "budget": {"amount": 100, "currency": "CNY"},
            "time_limit": {"hours": 24, "deadline": "2026-09-01T18:00:00+08:00"},
        },
        "resource_plan": {
            "pins": [{"pin": "PB6", "signal": "I2C1_SCL", "function": "SHT31_SCL", "alternate_function": "I2C1"}],
            "clocks": {"sysclk_hz": 72000000, "hclk_hz": 72000000, "pclk1_hz": 36000000, "pclk2_hz": 72000000},
            "dma": [], "irqs": [], "flash_bytes": 24000, "ram_bytes": 8000,
            "power": {
                "rails": [{"name": "3V3", "voltage": 3.3, "max_current_ma": 500}],
                "loads": [{"name": "station", "rail": "3V3", "voltage": 3.3, "current_ma": 80}],
            },
        },
        "safety": {"status": "passed", "gates": ["仅使用 3.3V 低压供电"], "blocked_reasons": []},
        "required_stages": [
            "requirements", "design", "resources", "hardware_plan", "implementation", "build", "hardware_acceptance",
        ],
        "clarification_questions": [],
        "next_action": "冻结 baseline",
    }
    value.update(overrides)
    return value


def extensions():
    return {
        "hardware_identity": {
            "mcu": "STM32F103C8Tx", "package": "LQFP48", "board": "Blue Pill", "board_revision": "BP-A",
            "board_evidence_hash": "0" * 64, "flash_capacity_bytes": 64 * 1024,
            "photo_refs": ["sha256:" + "1" * 64], "datasheet_refs": ["DS5319 Rev 20"],
        },
        "execution_profile": {
            "toolchain": "stm32cubeclt-1.22.0", "build_system": "cmake-ninja",
            "probe": {"kind": "st-link", "serial": "066DFF"},
            "serial": {"identity": "usb-vid_0483&pid_374b", "baudrate": 115200},
            "allowed_actions": ["build.run", "flash.plan", "flash.execute", "serial.capture"],
        },
        "test_contract": {
            "startup_timeout_ms": 3000, "serial_protocol": "json-lines-v1",
            "assertions": [{"assertion_id": "boot", "expression": "$.self_test == 'passed'"}],
            "measurement_tolerance": {"temperature_c": 1.0, "humidity_rh": 5.0}, "timeout_ms": 600000,
        },
        "eda_profile": {
            "board_outline": {"width_mm": 80, "height_mm": 50}, "layer_count": 2,
            "design_rules": {"min_track_mm": 0.2, "min_clearance_mm": 0.2},
            "manufacturer": "not-selected", "assembly": "hand",
            "mechanical_constraints": ["连接器位于板边"],
        },
        "cloud_policy": {
            "flux_upload_allowed": True, "authoritative_source": "kicad",
            "approved_data_classes": ["structured_requirements"],
        },
    }


def init_project(projects: Path, value: dict):
    return run_cli(
        projects, "init", "--project-id", "station", "--payload-json", json.dumps(value, ensure_ascii=False),
    )


def record(projects: Path, event_type: str, payload: dict, revision: int, ok: bool = True):
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return run_cli(
        projects, "record", "--project-id", "station", "--event-type", event_type,
        "--payload-json", json.dumps(payload), "--expected-revision", str(revision),
        "--idempotency-key", f"state-{revision}-{key}", ok=ok,
    )


def execution_run(baseline_hash: str, target_signature: str):
    return {
        "run_id": "run-001", "baseline_hash": baseline_hash, "target_signature": target_signature,
        "target_identity_hash": "2" * 64, "execution_plan_hash": "3" * 64,
        "tool_receipt_hashes": ["4" * 64, "5" * 64],
        "artifact_hashes": {"elf": "6" * 64, "map": "7" * 64}, "result": "passed",
    }


def design_release(baseline_hash: str, target_signature: str):
    return {
        "design_release_id": "carrier-r1", "baseline_hash": baseline_hash,
        "target_signature": target_signature, "design_release_hash": "8" * 64,
        "schematic_hash": "9" * 64, "pcb_hash": "a" * 64,
        "erc_report_hash": "b" * 64, "drc_report_hash": "c" * 64,
        "parity_report_hash": "2" * 64, "bom_hash": "d" * 64, "render_hash": "3" * 64,
        "cam_hashes": {"gerber": "e" * 64, "drill": "f" * 64, "pnp": "0" * 64, "step": "1" * 64},
        "status": "reviewed",
    }


def test_existing_intake_remains_valid_and_extensions_are_strict(tmp_path):
    legacy = init_project(tmp_path / "legacy", intake())
    assert legacy["state"]["revision"] == 1
    assert "hardware_identity" not in legacy["state"]["intake"]

    extended_value = intake(**extensions())
    extended = init_project(tmp_path / "extended", extended_value)
    for field, expected in extensions().items():
        assert extended["state"]["intake"][field] == expected

    changed_identity = extensions()
    changed_identity["hardware_identity"]["flash_capacity_bytes"] = 128 * 1024
    changed = init_project(tmp_path / "changed-capacity", intake(**changed_identity))
    assert changed["state"]["target_signature"] != extended["state"]["target_signature"]

    schema = json.loads((SCHEMAS / "project-intake.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    validator.validate(extended["state"]["intake"])
    with pytest.raises(ValidationError):
        validator.validate(intake(hardware_identity={"mcu": "STM32F103C8Tx", "unexpected": True}))

    rejected = run_cli(
        tmp_path / "invalid", "init", "--project-id", "station", "--payload-json",
        json.dumps(intake(execution_profile={**extensions()["execution_profile"], "raw_shell": True})), ok=False,
    )
    assert rejected["error"] == "invalid_intake"

    invalid_capacity = extensions()
    invalid_capacity["hardware_identity"]["flash_capacity_bytes"] = 4 * 1024 * 1024
    rejected_capacity = run_cli(
        tmp_path / "invalid-capacity", "init", "--project-id", "station", "--payload-json",
        json.dumps(intake(**invalid_capacity)), ok=False,
    )
    assert rejected_capacity["error"] == "invalid_intake"


def test_execution_contract_schemas_are_strict_and_valid():
    samples = {
        "target-identity.schema.json": {
            "probe_serial": "066DFF", "mcu_device_id": "0x0410", "mcu_uid": "112233445566778899aabbcc",
            "board_profile": "bluepill-bp-a",
            "board_evidence_hash": "a" * 64, "flash_capacity_bytes": 64 * 1024, "target_voltage_v": 3.29,
        },
        "execution-plan.schema.json": {
            "baseline_hash": "1" * 64, "firmware_hash": "2" * 64,
            "target_identity_hash": "3" * 64, "tool_versions": {"cubeclt": "1.22.0"},
            "operations": ["build.run", "flash.plan"], "risks": ["目标身份需复核"],
            "rollback": {"artifact_hash": "4" * 64, "verification_action": "build.run"},
        },
        "tool-receipt.schema.json": {
            "receipt_id": "receipt-build", "tool": "build.run", "exit_code": 0,
            "log_hash": "5" * 64, "diagnostic_class": "success", "tool_version": "1.22.0",
            "timestamp": "2026-08-26T12:00:00+08:00", "artifact_hashes": ["6" * 64],
        },
        "design-release.schema.json": design_release("7" * 64, "8" * 64),
    }
    for name, sample in samples.items():
        schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
        validator.validate(sample)
        with pytest.raises(ValidationError):
            validator.validate({**sample, "raw_log": "secret or unbounded output"})


def test_execution_and_design_events_store_only_hash_references_and_become_stale(tmp_path):
    projects = tmp_path / "Projects"
    initialized = init_project(projects, intake(**extensions()))
    signature = initialized["state"]["target_signature"]
    baseline = "a" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)

    run_payload = execution_run(baseline, signature)
    saved_run = record(projects, "generation.execution_run_recorded", run_payload, 2)["state"]["execution_runs"][0]
    assert saved_run["status"] == "current"
    assert saved_run["tool_receipt_hashes"] == run_payload["tool_receipt_hashes"]
    assert not any(key in saved_run for key in ("tool_receipts", "logs", "paths", "execution_plan", "target_identity"))

    release_payload = design_release(baseline, signature)
    saved_release = record(projects, "generation.design_release_recorded", release_payload, 3)["state"]["design_releases"][0]
    assert saved_release["status"] == "reviewed"
    assert not any(key in saved_release for key in ("erc_report", "drc_report", "bom", "gerber", "paths"))

    linked_stage = record(projects, "generation.stage_recorded", {
        "stage_id": "design", "status": "in_progress", "baseline_hash": baseline,
        "evidence_ids": [], "outputs": [], "known_not_verified": [],
        "execution_run_ids": ["run-001"], "design_release_ids": ["carrier-r1"],
    }, 4)["state"]["stages"]["design"]
    assert linked_stage["execution_run_ids"] == ["run-001"]
    assert linked_stage["design_release_ids"] == ["carrier-r1"]

    changed = record(
        projects, "generation.baseline_updated", {"baseline_id": "b2", "baseline_hash": "b" * 64}, 5,
    )["state"]
    assert changed["execution_runs"][0]["status"] == "stale"
    assert changed["design_releases"][0]["status"] == "stale"
    rebuilt = run_cli(projects, "rebuild", "--project-id", "station")["state"]
    assert rebuilt["execution_runs"] == changed["execution_runs"]
    assert rebuilt["design_releases"] == changed["design_releases"]


def test_target_change_stales_execution_design_and_preserves_single_use_flash_semantics(tmp_path):
    projects = tmp_path / "Projects"
    initialized = init_project(projects, intake(**extensions()))
    signature = initialized["state"]["target_signature"]
    baseline = "a" * 64
    artifact = "c" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    record(projects, "generation.execution_run_recorded", execution_run(baseline, signature), 2)
    record(projects, "generation.design_release_recorded", design_release(baseline, signature), 3)
    record(projects, "generation.flash_confirmed", {
        "confirmation_id": "confirm-once", "explicit": True, "target_signature": signature,
        "baseline_hash": baseline, "artifact_hash": artifact,
    }, 4)

    new_target = dict(intake()["exact_target"])
    new_target["board_revision"] = "BP-B"
    new_identity = dict(extensions()["hardware_identity"])
    new_identity["board_revision"] = "BP-B"
    new_identity["board_evidence_hash"] = "d" * 64
    changed = record(projects, "generation.target_updated", {
        "exact_target": new_target, "hardware_identity": new_identity,
    }, 5)["state"]
    assert changed["execution_runs"][0]["status"] == "stale"
    assert changed["design_releases"][0]["status"] == "stale"
    assert changed["flash_confirmations"][0]["status"] == "invalidated"

    rejected = record(projects, "generation.flash_recorded", {
        "confirmation_id": "confirm-once", "target_signature": signature,
        "baseline_hash": baseline, "artifact_hash": artifact, "result": "verified",
    }, 6, ok=False)
    assert rejected["error"] in {"flash_confirmation_invalidated", "baseline_mismatch"}


def test_embedded_receipts_or_unbound_hashes_are_rejected_without_mutating_ledger(tmp_path):
    projects = tmp_path / "Projects"
    initialized = init_project(projects, intake(**extensions()))
    signature = initialized["state"]["target_signature"]
    baseline = "a" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    ledger = projects / "station" / "events" / "events.jsonl"
    original = ledger.read_bytes()

    embedded = {**execution_run(baseline, signature), "tool_receipts": [{"exit_code": 0}]}
    rejected = record(projects, "generation.execution_run_recorded", embedded, 2, ok=False)
    assert rejected["error"] == "invalid_execution_run"
    assert ledger.read_bytes() == original

    unbound = design_release("b" * 64, signature)
    rejected = record(projects, "generation.design_release_recorded", unbound, 2, ok=False)
    assert rejected["error"] == "baseline_mismatch"
    assert ledger.read_bytes() == original
