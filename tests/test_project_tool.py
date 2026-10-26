import hashlib
import json
import multiprocessing
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts" / "project_tool.py"


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
    return completed, json.loads(stream)


def intake(**overrides):
    value = {
        "goal": "制作桌面温湿度告警器",
        "requirements": [
            {"requirement_id": "R1", "text": "每秒采样一次温湿度", "acceptance_ids": ["A1"]}
        ],
        "acceptance_criteria": [
            {
                "acceptance_id": "A1", "text": "连续记录 60 秒且无丢样", "requires_hardware": True,
                "metric": "lost_samples", "operator": "eq", "threshold": 0, "unit": "count",
                "window": {"duration": 60, "unit": "s"},
                "observation_method": "instrument"
            }
        ],
        "exact_target": {
            "mcu": "STM32F103C8Tx",
            "package": "LQFP48",
            "board": "Blue Pill",
            "board_revision": "BP-2024-A",
            "toolchain": {
                "ide": {"name": "STM32CubeIDE", "version": "1.19.0"},
                "firmware_package": {"name": "STM32CubeF1", "version": "1.8.7"},
                "compiler": {"name": "GNU Arm Embedded", "version": "13.3"},
                "programmer": {"name": "ST-LINK", "version": "V2"},
            },
        },
        "resources": {
            "components": [{"component_id": "sensor-1", "name": "DHT22", "model": "DHT22", "quantity": 1}],
            "budget": {"amount": 100, "currency": "CNY"},
            "time_limit": {"hours": 48, "deadline": "2026-08-23T18:00:00+08:00"},
        },
        "resource_plan": {
            "pins": [{
                "pin": "PA1", "signal": "GPIO_INPUT", "function": "DHT22_DATA",
                "alternate_function": "GPIO"
            }],
            "clocks": {
                "sysclk_hz": 72000000, "hclk_hz": 72000000,
                "pclk1_hz": 36000000, "pclk2_hz": 72000000, "usb_hz": 48000000
            },
            "dma": [],
            "irqs": [{"irq": "EXTI1", "function": "GPIO_EXTI1"}],
            "flash_bytes": 24000,
            "ram_bytes": 8000,
            "power": {
                "rails": [{"name": "3V3", "voltage": 3.3, "max_current_ma": 500}],
                "loads": [
                    {"name": "MCU", "rail": "3V3", "voltage": 3.3, "current_ma": 50},
                    {"name": "DHT22", "rail": "3V3", "voltage": 3.3, "current_ma": 5}
                ]
            }
        },
        "safety": {"status": "passed", "gates": ["仅使用隔离低压 USB 供电"], "blocked_reasons": []},
        "required_stages": ["requirements", "design", "implementation", "build", "hardware_acceptance"],
        "clarification_questions": [],
        "next_action": "冻结引脚与时钟分配",
    }
    value.update(overrides)
    return value


def executable_intake(**overrides):
    value = intake(hardware_identity={
        "mcu": "STM32F103C8Tx", "package": "LQFP48", "board": "Blue Pill",
        "board_revision": "BP-2024-A", "board_evidence_hash": "a" * 64,
        "flash_capacity_bytes": 64 * 1024,
        "photo_refs": ["sha256:" + "b" * 64], "datasheet_refs": ["ST DS5319"],
    })
    value.update(overrides)
    return value


def zero_hardware_procurement(*, confirmed: bool = False):
    options = [
        {
            "option_id": "balanced", "name": "均衡开发板方案", "positioning": "新手低风险原型",
            "pros": ["资料完整", "接线简单"], "cons": ["体积略大"],
            "estimated_total": {"amount": 180, "currency": "CNY"}, "recommended": True,
            "recommendation_reason": "优先降低首次接线和调试难度",
        },
        {
            "option_id": "compact", "name": "紧凑低成本方案", "positioning": "预算优先",
            "pros": ["成本低"], "cons": ["板卡版本需要额外核验"],
            "estimated_total": {"amount": 120, "currency": "CNY"}, "recommended": False,
            "recommendation_reason": "适合愿意承担更多排错工作的用户",
        },
    ]
    shopping_list = [{
        "item_id": "board", "category": "主控板", "exact_model": "NUCLEO-F103RB", "quantity": 1,
        "priority": "required", "purchase_batch": "now", "selection_reason": "官方板卡资料齐全",
        "critical_specs": ["STM32F103RBT6", "板载 ST-LINK"], "allowed_substitutes": [],
        "avoid": ["型号不明兼容板"], "purchase_status": "planned", "source_refs": ["ST UM1724"],
    }]
    return {
        "inventory_status": "none_owned",
        "requirements_confirmation": "confirmed" if confirmed else "pending",
        "solution_options": options if confirmed else [],
        "selected_option_id": "balanced" if confirmed else None,
        "selection_confirmation": "confirmed" if confirmed else "pending",
        "shopping_list": shopping_list if confirmed else [],
        "shopping_list_confirmation": "confirmed" if confirmed else "pending",
    }


def init_project(projects: Path, value=None):
    return run_cli(
        projects,
        "init",
        "--project-id",
        "desk-sensor",
        "--intake",
        json.dumps(value or intake(), ensure_ascii=False),
    )[1]


def record(projects: Path, event_type: str, payload: dict, revision: int, key: str | None = None, ok=True):
    args = [
        "record", "--project-id", "desk-sensor", "--event-type", event_type,
        "--payload", json.dumps(payload, ensure_ascii=False), "--expected-revision", str(revision),
    ]
    if key is None:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
        key = f"test-{revision}-{digest}"
    args += ["--idempotency-key", key]
    return run_cli(projects, *args, ok=ok)[1]


def checkpoint_worker(script: str, projects: str, index: int) -> int:
    payload = json.dumps({"checkpoint_id": f"parallel-{index}", "next_action": f"并发动作 {index}"}, ensure_ascii=False)
    for _ in range(40):
        status = subprocess.run(
            [sys.executable, script, "--store", projects, "status", "--project-id", "desk-sensor"],
            text=True, encoding="utf-8", capture_output=True,
        )
        if status.returncode:
            continue
        revision = json.loads(status.stdout)["state"]["revision"]
        saved = subprocess.run(
            [
                sys.executable, script, "--store", projects, "record", "--project-id", "desk-sensor",
                "--event-type", "generation.checkpoint_recorded", "--payload-json", payload,
                "--idempotency-key", f"parallel-{index}", "--expected-revision", str(revision),
            ],
            text=True, encoding="utf-8", capture_output=True,
        )
        if saved.returncode == 0:
            return 0
        try:
            if json.loads(saved.stderr).get("error") != "revision_conflict":
                return saved.returncode
        except json.JSONDecodeError:
            return saved.returncode
    return 9


def test_init_creates_independent_utf8_store_and_compact_status(tmp_path):
    projects = tmp_path / "Projects"
    result = init_project(projects)
    project = projects / "desk-sensor"
    assert result["created"] is True
    assert result["state"]["revision"] == 1
    assert result["state"]["intake"]["goal"] == "制作桌面温湿度告警器"
    assert (project / "events" / "events.jsonl").exists()
    assert "温湿度" in (project / "state.json").read_text(encoding="utf-8")
    _, status = run_cli(projects, "status", "--project-id", "desk-sensor")
    assert len(status["resume_summary"]["questions"]) <= 3
    assert isinstance(status["resume_summary"]["next_action"], str)


def test_init_rejects_path_traversal_and_too_many_questions(tmp_path):
    _, bad_id = run_cli(
        tmp_path / "Projects", "init", "--project-id", "../escape",
        "--intake", json.dumps(intake(), ensure_ascii=False), ok=False,
    )
    assert bad_id["error"] == "invalid_project_id"
    value = intake(clarification_questions=["q1", "q2", "q3", "q4"])
    _, bad_questions = run_cli(
        tmp_path / "Projects", "init", "--project-id", "desk-sensor",
        "--intake", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert bad_questions["error"] == "invalid_intake"


def test_record_is_revisioned_idempotent_and_generation_only(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    payload = {"baseline_id": "base-1", "baseline_hash": "a" * 64, "note": "初始冻结"}
    first = record(projects, "generation.baseline_updated", payload, 1, "base-once")
    duplicate = record(projects, "generation.baseline_updated", payload, 1, "base-once")
    assert first["state"]["revision"] == 2
    assert duplicate["duplicate"] is True
    conflict = record(projects, "generation.checkpoint_recorded", {"stage_id": "requirements"}, 1, ok=False)
    assert conflict["error"] == "revision_conflict"
    rejected = record(projects, "learning.evidence_recorded", {}, 2, ok=False)
    assert rejected["error"] == "event_type_not_allowed"


def test_snapshot_lag_recovers_but_same_revision_divergence_fails_closed(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    project = projects / "desk-sensor"
    old = (project / "state.json").read_text(encoding="utf-8")
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": "b" * 64}, 1)
    (project / "state.json").write_text(old, encoding="utf-8")
    _, recovered = run_cli(projects, "status", "--project-id", "desk-sensor")
    assert recovered["recovered"] is True
    snapshot = json.loads((project / "state.json").read_text(encoding="utf-8"))
    snapshot["next_action"] = "被篡改的动作"
    (project / "state.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    _, failed = run_cli(projects, "rebuild", "--project-id", "desk-sensor", ok=False)
    assert failed["error"] == "snapshot_divergence"


def test_evidence_provenance_and_build_flash_do_not_pass_hardware(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": "b" * 64}, 1)
    build = record(projects, "generation.evidence_recorded", {
        "evidence_id": "ev-build", "kind": "build_result", "summary": "构建通过",
        "verification_level": "V5", "verification_status": "verified", "source": "tool",
        "baseline_hash": "b" * 64, "acceptance_ids": ["A1"], "hardware_verified": True,
    }, 2)
    saved = build["state"]["evidence"][0]
    assert saved["verification_level"] == "V2"
    assert saved["hardware_verified"] is False
    assert saved["acceptance_ids"] == []
    reported = record(projects, "generation.evidence_recorded", {
        "evidence_id": "ev-user", "kind": "hardware_observation", "summary": "用户称运行正常",
        "verification_level": "V5", "verification_status": "verified", "source": "reported_by_user",
        "baseline_hash": "b" * 64, "acceptance_ids": ["A1"], "hardware_verified": True,
    }, 3)
    user_ev = reported["state"]["evidence"][1]
    assert user_ev["source"] == "reported_by_user"
    assert user_ev["verification_status"] == "self_reported"
    assert user_ev["hardware_verified"] is False
    blocked = run_cli(
        projects, "release", "--project-id", "desk-sensor", "--expected-revision", "4",
        "--idempotency-key", "blocked-release", ok=False,
    )[1]
    assert blocked["error"] == "release_gate"
    assert "acceptance:A1" in blocked["details"]


def test_baseline_change_invalidates_prior_stage_and_evidence(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": "1" * 64}, 1)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "ev-design", "kind": "document_review", "summary": "需求审查通过",
        "verification_level": "V1", "verification_status": "verified", "source": "tool",
        "baseline_hash": "1" * 64,
    }, 2)
    record(projects, "generation.stage_recorded", {
        "stage_id": "requirements", "status": "passed", "baseline_hash": "1" * 64,
        "evidence_ids": ["ev-design"], "outputs": ["引脚表"], "known_not_verified": [],
    }, 3)
    changed = record(projects, "generation.baseline_updated", {"baseline_id": "b2", "baseline_hash": "2" * 64}, 4)
    assert changed["state"]["stages"]["requirements"]["status"] == "stale"
    assert changed["state"]["evidence"][0]["status"] == "stale"
    schema = json.loads((
        ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "schemas" / "stage-result.schema.json"
    ).read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(changed["state"]["stages"]["requirements"])


def test_flash_confirmation_is_one_time_bound_and_never_executes_flash(tmp_path):
    projects = tmp_path / "Projects"
    initialized = init_project(projects, executable_intake())
    signature = initialized["state"]["target_signature"]
    baseline = "b" * 64
    artifact = hashlib.sha256(b"firmware").hexdigest()
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    confirmation = record(projects, "generation.flash_confirmed", {
        "confirmation_id": "confirm-1", "explicit": True, "target_signature": signature,
        "baseline_hash": baseline, "artifact_hash": artifact,
    }, 2)
    assert confirmation["state"]["flash_confirmations"][0]["consumed"] is False
    flashed = record(projects, "generation.flash_recorded", {
        "confirmation_id": "confirm-1", "target_signature": signature,
        "baseline_hash": baseline, "artifact_hash": artifact, "result": "reported_success",
    }, 3)
    assert flashed["state"]["flash_confirmations"][0]["consumed"] is True
    assert flashed["state"]["flash_records"][0]["hardware_verified"] is False
    reused = record(projects, "generation.flash_recorded", {
        "confirmation_id": "confirm-1", "target_signature": signature,
        "baseline_hash": baseline, "artifact_hash": artifact, "result": "reported_success",
    }, 4, ok=False)
    assert reused["error"] == "flash_confirmation_consumed"


def test_legacy_intake_can_continue_offline_but_cannot_confirm_flash(tmp_path):
    projects = tmp_path / "Projects"
    initialized = init_project(projects)
    signature = initialized["state"]["target_signature"]
    baseline = "e" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    rejected = record(projects, "generation.flash_confirmed", {
        "confirmation_id": "legacy", "explicit": True, "target_signature": signature,
        "baseline_hash": baseline, "artifact_hash": "f" * 64,
    }, 2, ok=False)
    assert rejected["error"] == "hardware_identity_required"


def test_checkpoint_command_and_release_require_all_gates(tmp_path):
    projects = tmp_path / "Projects"
    initialized = init_project(projects)
    baseline = "c" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    revision = 2
    evidence_specs = [
        ("requirements", "V0", "document_review", []),
        ("design", "V1", "configuration_review", []),
        ("resources", "V3", "resource_report", []),
        ("hardware_plan", "V1", "design_review", []),
        ("implementation", "V4", "logic_test", []),
        ("build", "V2", "build_result", []),
        ("hardware_acceptance", "V5", "hardware_measurement", ["A1"]),
    ]
    for stage, level, kind, acceptance_ids in evidence_specs:
        evidence_id = f"ev-{stage}"
        evidence_payload = {
            "evidence_id": evidence_id, "kind": kind, "summary": f"{stage} evidence",
            "verification_level": level, "verification_status": "verified",
            "source": "verified_hardware_tool" if level == "V5" else "tool",
            "baseline_hash": baseline, "acceptance_ids": acceptance_ids,
            "hardware_verified": level == "V5",
        }
        if kind in {"build_result", "logic_test"}:
            evidence_payload["artifact_hash"] = "d" * 64
        if level == "V5":
            evidence_payload.update({
                "target_signature": initialized["state"]["target_signature"],
                "artifact_hash": "d" * 64, "raw_evidence_hash": "e" * 64,
                "operator": "fixture-A", "timestamp": "2026-08-21T00:00:00Z",
                "reproduction": {"steps": ["连接仪器", "采集 60 秒"], "result": "passed"},
            })
        record(projects, "generation.evidence_recorded", evidence_payload, revision)
        revision += 1
    record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "ev-build", "expected_observation": "状态机每秒更新",
        "actual_observation": {
            "expected": "状态机每秒更新", "observed": "主机逻辑测试观察到每秒更新",
            "result": "passed", "evidence_id": "ev-implementation"
        },
        "rollback": {
            "supported": True,
            "steps": [{"action": "restore_artifact", "artifact_hash": "d" * 64}],
            "verification_action": {"action": "rebuild_and_test", "evidence_id": "ev-build"}
        },
    }, revision)
    revision += 1
    for stage, _level, _kind, _acceptance_ids in evidence_specs:
        evidence_id = f"ev-{stage}"
        _, checkpoint = run_cli(
            projects, "checkpoint", "--project-id", "desk-sensor", "--stage-id", stage,
            "--status", "passed", "--evidence-ids", json.dumps([evidence_id]),
            "--outputs", json.dumps([f"{stage}-output"]), "--known-not-verified", "[]",
            "--baseline-hash", baseline, "--expected-revision", str(revision),
            "--idempotency-key", f"checkpoint-{stage}",
        )
        revision += 1
        assert checkpoint["state"]["stages"][stage]["status"] == "passed"
    _, released = run_cli(
        projects, "release", "--project-id", "desk-sensor", "--release-id", "rel-1",
        "--artifact-hash", "d" * 64, "--expected-revision", str(revision),
        "--idempotency-key", "release-rel-1",
    )
    assert released["state"]["release"]["status"] == "released"
    assert released["state"]["release"]["artifact_hash"] == "d" * 64
    evidence_schema = json.loads((
        ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "schemas" / "generation-evidence.schema.json"
    ).read_text(encoding="utf-8"))
    hardware_evidence = next(
        item for item in released["state"]["evidence"] if item["evidence_id"] == "ev-hardware_acceptance"
    )
    Draft202012Validator(evidence_schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(hardware_evidence)


def test_schema_and_workflow_contracts_exist():
    schemas = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "schemas"
    for name in ("project-intake.schema.json", "stage-result.schema.json", "generation-evidence.schema.json"):
        value = json.loads((schemas / name).read_text(encoding="utf-8"))
        assert value["$schema"].endswith("2020-12/schema")
    workflow = (
        ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "generation" / "project-workflow.md"
    ).read_text(encoding="utf-8")
    for term in ("ProjectIntake", "StageResult", "阶段门", "证据", "project_tool.py"):
        assert term in workflow


def test_documented_store_and_payload_json_cli_are_supported(tmp_path):
    projects = tmp_path / "Projects"
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--store", str(projects), "init",
            "--project-id", "cli-shape", "--payload-json", json.dumps(intake(), ensure_ascii=False),
            "--expected-revision", "0", "--idempotency-key", "init-cli-shape",
        ],
        text=True, encoding="utf-8", capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    event = json.loads((projects / "cli-shape" / "events" / "events.jsonl").read_text(encoding="utf-8"))
    assert event["idempotency_key"] == "init-cli-shape"
    status = subprocess.run(
        [sys.executable, str(SCRIPT), "--store", str(projects), "status", "--project-id", "cli-shape"],
        text=True, encoding="utf-8", capture_output=True,
    )
    assert status.returncode == 0
    assert json.loads(status.stdout)["state"]["project_id"] == "cli-shape"


def test_event_hash_chain_detects_tampering_even_when_json_remains_valid(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    ledger = projects / "desk-sensor" / "events" / "events.jsonl"
    event = json.loads(ledger.read_text(encoding="utf-8"))
    event["payload"]["intake"]["goal"] = "被篡改的项目目标"
    ledger.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    _, result = run_cli(projects, "validate", "--project-id", "desk-sensor", ok=False)
    assert result["error"] == "corrupt_event_log"


def test_concurrent_writers_are_serialized_without_lost_events(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        codes = pool.starmap(checkpoint_worker, [(str(SCRIPT), str(projects), index) for index in range(8)])
    assert codes == [0] * 8
    status = run_cli(projects, "status", "--project-id", "desk-sensor")[1]
    assert status["state"]["revision"] == 9
    assert len(status["state"]["checkpoints"]) == 8


def test_evidence_types_are_strict_aliases_are_capped_and_stage_compatible(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    baseline = "a" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    bad_bool = record(projects, "generation.evidence_recorded", {
        "evidence_id": "bad-bool", "kind": "hardware_measurement", "summary": "测得 3.3 V",
        "verification_level": "V5", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "hardware_verified": "false",
    }, 2, ok=False)
    assert bad_bool["error"] == "invalid_payload"
    unknown_kind = record(projects, "generation.evidence_recorded", {
        "evidence_id": "unknown-kind", "kind": "magic_proof ", "summary": "不可识别",
        "verification_level": "V5", "verification_status": "verified", "source": "tool ",
        "baseline_hash": baseline, "hardware_verified": True,
    }, 2, ok=False)
    assert unknown_kind["error"] == "invalid_payload"
    build = record(projects, "generation.evidence_recorded", {
        "evidence_id": "build-alias", "kind": "build_success ", "summary": "构建成功",
        "verification_level": "V5", "verification_status": "verified", "source": "tool ",
        "baseline_hash": baseline, "acceptance_ids": ["A1"], "hardware_verified": True,
    }, 2)
    saved = build["state"]["evidence"][0]
    assert saved["kind"] == "build_success"
    assert saved["source"] == "tool"
    assert saved["verification_level"] == "V2"
    assert saved["acceptance_ids"] == []
    incompatible = record(projects, "generation.stage_recorded", {
        "stage_id": "requirements", "status": "passed", "baseline_hash": baseline,
        "evidence_ids": ["build-alias"], "outputs": ["需求"], "known_not_verified": [],
    }, 3, ok=False)
    assert incompatible["error"] == "incompatible_evidence"


def test_core_stage_gates_cannot_be_deleted_and_requirements_need_acceptance_refs(tmp_path):
    projects = tmp_path / "Projects"
    result = init_project(projects)
    assert result["state"]["intake"]["required_stages"][:7] == [
        "requirements", "design", "resources", "hardware_plan",
        "implementation", "build", "hardware_acceptance",
    ]
    missing_ref = intake(requirements=[{"requirement_id": "R1", "text": "每秒采样", "acceptance_ids": []}])
    _, rejected = run_cli(
        tmp_path / "OtherProjects", "init", "--project-id", "bad-req",
        "--intake", json.dumps(missing_ref, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "invalid_intake"


def test_incomplete_intake_stops_baseline_and_returns_three_questions_one_action(tmp_path):
    projects = tmp_path / "Projects"
    _, created = run_cli(
        projects, "init", "--project-id", "vague",
        "--payload-json", json.dumps({"goal": "做一个智能小车"}, ensure_ascii=False),
    )
    summary = created["resume_summary"]
    assert 1 <= len(summary["questions"]) <= 3
    assert isinstance(summary["next_action"], str) and summary["next_action"]
    blocked = run_cli(
        projects, "record", "--project-id", "vague", "--event-type", "generation.baseline_updated",
        "--payload-json", json.dumps({"baseline_id": "b1", "baseline_hash": "1" * 64}),
        "--expected-revision", "1", "--idempotency-key", "vague-baseline", ok=False,
    )[1]
    assert blocked["error"] == "intake_gate"
    assert any(item.startswith("exact_target:") for item in blocked["details"])


@pytest.mark.parametrize("dangerous", [
    {"notes": {"wiring": "HC-SR04 Echo 5V 直接接 GPIO"}},
    {"parts": ["GPIO 直接驱动电机"]},
    {"nested": {"supply": ["mains 220V"]}},
    {"battery": "无保护锂电池充电"},
])
def test_nested_safety_payload_is_blocked_before_ledger_write(tmp_path, dangerous):
    projects = tmp_path / "Projects"
    init_project(projects)
    ledger = projects / "desk-sensor" / "events" / "events.jsonl"
    original = ledger.read_bytes()
    rejected = record(projects, "generation.checkpoint_recorded", dangerous, 1, ok=False)
    assert rejected["error"] == "blocked_safety"
    assert ledger.read_bytes() == original


def test_target_signature_controls_flash_and_baseline_change_invalidates_confirmation(tmp_path):
    projects = tmp_path / "Projects"
    initial = init_project(projects, executable_intake())
    signature = initial["state"]["target_signature"]
    baseline = "b" * 64
    artifact = "c" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    mismatch = record(projects, "generation.flash_confirmed", {
        "confirmation_id": "wrong", "explicit": True, "target_signature": "0" * 64,
        "baseline_hash": baseline, "artifact_hash": artifact,
    }, 2, ok=False)
    assert mismatch["error"] == "target_signature_mismatch"
    confirmed = record(projects, "generation.flash_confirmed", {
        "confirmation_id": "ok", "explicit": True, "target_signature": signature,
        "baseline_hash": baseline, "artifact_hash": artifact,
    }, 2)
    assert confirmed["state"]["flash_confirmations"][0]["status"] == "current"
    changed = record(projects, "generation.baseline_updated", {"baseline_id": "b2", "baseline_hash": "d" * 64}, 3)
    assert changed["state"]["flash_confirmations"][0]["status"] == "invalidated"


@pytest.mark.parametrize("key", [None, "", "   ", "bad key", "key/with/slash"])
def test_mutations_require_canonical_nonempty_idempotency_key_without_ledger_pollution(tmp_path, key):
    projects = tmp_path / "Projects"
    init_project(projects)
    ledger = projects / "desk-sensor" / "events" / "events.jsonl"
    original = ledger.read_bytes()
    args = [
        "record", "--project-id", "desk-sensor", "--event-type", "generation.checkpoint_recorded",
        "--payload-json", '{"next_action":"继续"}', "--expected-revision", "1",
    ]
    if key is not None:
        args += ["--idempotency-key", key]
    _, result = run_cli(projects, *args, ok=False)
    assert result["error"] == "invalid_idempotency_key"
    assert ledger.read_bytes() == original


@pytest.mark.parametrize("mutator, expected", [
    (lambda p: p["pins"].append({"pin": "PA1", "signal": "GPIO_INPUT", "function": "OTHER", "alternate_function": "GPIO"}), "pin_conflict:PA1"),
    (lambda p: p["dma"].extend([{"channel": "DMA1_CH2", "function": "SPI1_RX"}, {"channel": "DMA1_CH2", "function": "USART3_TX"}]), "dma_conflict:DMA1_CH2"),
    (lambda p: p["irqs"].append({"irq": "EXTI1", "function": "GPIO_EXTI1"}), "irq_conflict:EXTI1"),
    (lambda p: p["clocks"].update({"usb_hz": 47000000}), "usb_clock_not_48mhz"),
    (lambda p: p.update({"flash_bytes": 70000}), "flash_over_budget"),
    (lambda p: p.update({"ram_bytes": 21000}), "ram_over_budget"),
    (lambda p: p["power"]["loads"].append({"name": "heater", "rail": "3V3", "voltage": 3.3, "current_ma": 600}), "power_insufficient:3V3"),
])
def test_resource_conflicts_block_baseline_and_hardware_plan(tmp_path, mutator, expected):
    value = intake()
    if expected == "usb_clock_not_48mhz":
        value["resource_plan"]["pins"].append({
            "pin": "PA12", "signal": "USB_DP", "function": "USB_DP", "alternate_function": "USB"
        })
    mutator(value["resource_plan"])
    projects = tmp_path / "Projects"
    created = init_project(projects, value)
    assert expected in created["state"]["resource_blockers"]
    blocked = record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": "e" * 64}, 1, ok=False)
    assert blocked["error"] == "resource_gate"


def test_increment_model_requires_build_observation_and_rollback(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    baseline = "f" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "inc-build", "kind": "build_result", "summary": "增量构建成功",
        "verification_level": "V2", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "hardware_verified": False, "artifact_hash": "2" * 64,
    }, 2)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "inc-observe", "kind": "logic_test", "summary": "状态机输出符合预期",
        "verification_level": "V4", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "hardware_verified": False,
    }, 3)
    incomplete = record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "inc-build", "expected_observation": "状态切换",
        "actual_observation": "状态切换", "observation_evidence_id": "inc-observe", "rollback": "",
    }, 4, ok=False)
    assert incomplete["error"] == "invalid_increment"
    saved = record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "inc-build", "expected_observation": "状态切换",
        "actual_observation": {
            "expected": "状态切换", "observed": "状态切换", "result": "passed",
            "evidence_id": "inc-observe"
        },
        "rollback": {
            "supported": True,
            "steps": [{"action": "restore_artifact", "artifact_hash": "2" * 64}],
            "verification_action": {"action": "rebuild_and_test", "evidence_id": "inc-build"}
        },
    }, 4)
    assert saved["state"]["increments"][0]["increment_id"] == "I1"


def test_saved_runtime_instances_validate_against_all_three_schemas(tmp_path):
    projects = tmp_path / "Projects"
    initial = init_project(projects)
    baseline = "7" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    evidence = record(projects, "generation.evidence_recorded", {
        "evidence_id": "doc", "kind": "document_review", "summary": "需求逐条审查",
        "verification_level": "V0", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "hardware_verified": False,
    }, 2)["state"]["evidence"][0]
    stage = record(projects, "generation.stage_recorded", {
        "stage_id": "requirements", "status": "passed", "baseline_hash": baseline,
        "evidence_ids": ["doc"], "outputs": ["需求追踪表"], "known_not_verified": [],
    }, 3)["state"]["stages"]["requirements"]
    schemas = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "schemas"
    samples = [
        ("project-intake.schema.json", initial["state"]["intake"]),
        ("generation-evidence.schema.json", evidence),
        ("stage-result.schema.json", stage),
    ]
    for name, sample in samples:
        schema = json.loads((schemas / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(sample)


def test_requirement_text_needs_no_numeric_heuristic_when_acceptance_is_structured(tmp_path):
    value = intake(requirements=[{
        "requirement_id": "R1", "text": "设备工作正常", "acceptance_ids": ["A1"],
    }])
    projects = tmp_path / "Projects"
    init_project(projects, value)
    saved = record(
        projects, "generation.baseline_updated",
        {"baseline_id": "b1", "baseline_hash": "8" * 64}, 1,
    )
    assert saved["state"]["baseline"]["baseline_hash"] == "8" * 64


def test_explicit_empty_init_idempotency_key_is_rejected_before_creating_store(tmp_path):
    projects = tmp_path / "Projects"
    _, rejected = run_cli(
        projects, "init", "--project-id", "empty-init-key",
        "--payload-json", json.dumps(intake(), ensure_ascii=False),
        "--idempotency-key", "", ok=False,
    )
    assert rejected["error"] == "invalid_idempotency_key"
    assert not (projects / "empty-init-key" / "events" / "events.jsonl").exists()


def test_flash_or_program_evidence_cannot_satisfy_increment_build_evidence(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    baseline = "9" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "flash-only", "kind": "flash_success", "summary": "烧录工具报告成功",
        "verification_level": "V2", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "hardware_verified": False,
    }, 2)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "observed", "kind": "logic_test", "summary": "主机逻辑输出",
        "verification_level": "V4", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "hardware_verified": False,
    }, 3)
    rejected = record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "flash-only", "expected_observation": "输出 1",
        "actual_observation": "输出 1", "observation_evidence_id": "observed",
        "rollback": "恢复上一版本",
    }, 4, ok=False)
    assert rejected["error"] == "invalid_increment"


@pytest.mark.parametrize("source", ["imported_reference", "tool", "reported_by_user"])
def test_non_independent_sources_cannot_forge_v5_hardware_acceptance(tmp_path, source):
    projects = tmp_path / "Projects"
    initialized = init_project(projects)
    baseline = "a" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    saved = record(projects, "generation.evidence_recorded", {
        "evidence_id": f"fake-{source}", "kind": "hardware_measurement", "summary": "外部资料称硬件通过",
        "verification_level": "V5", "verification_status": "verified", "source": source,
        "baseline_hash": baseline, "acceptance_ids": ["A1"], "hardware_verified": True,
        "target_signature": initialized["state"]["target_signature"], "artifact_hash": "b" * 64,
        "raw_evidence_hash": "c" * 64, "operator": "someone", "timestamp": "2026-08-21T00:00:00Z",
        "reproduction": {"steps": ["复现"], "result": "passed"},
    }, 2)["state"]["evidence"][0]
    assert saved["hardware_verified"] is False
    assert saved["acceptance_ids"] == []


@pytest.mark.parametrize("dangerous", [
    {"wiring": "HC_SR04 的 ECHO 五伏接 PA1"},
    {"wiring": "超声模块 echo 5伏 接入 IO口"},
    {"wiring": "PB0 接 马达"},
    {"wiring": "ＧＰＩＯ－直连－ＭＯＴＯＲ"},
])
def test_safety_scanner_normalizes_unicode_separators_and_categories(tmp_path, dangerous):
    projects = tmp_path / "Projects"
    init_project(projects)
    ledger = projects / "desk-sensor" / "events" / "events.jsonl"
    original = ledger.read_bytes()
    rejected = record(projects, "generation.checkpoint_recorded", dangerous, 1, ok=False)
    assert rejected["error"] == "blocked_safety"
    assert ledger.read_bytes() == original


def test_text_numbers_and_versions_do_not_count_as_structured_acceptance(tmp_path):
    value = intake(
        requirements=[{"requirement_id": "R1", "text": "版本 2.0", "acceptance_ids": ["A1"]}],
        acceptance_criteria=[{
            "acceptance_id": "A1", "text": "版本 1 必须运行", "requires_hardware": False,
        }],
    )
    projects = tmp_path / "Projects"
    created = init_project(projects, value)
    assert "acceptance_structure:A1" in created["state"]["intake_blockers"]
    blocked = record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": "d" * 64}, 1, ok=False)
    assert blocked["error"] == "intake_gate"


@pytest.mark.parametrize("field,value", [
    ("mcu", "..."), ("package", "unknown"), ("board", "TBD"), ("board_revision", "---"),
])
def test_explicit_unknown_or_punctuation_exact_target_is_rejected(tmp_path, field, value):
    target = dict(intake()["exact_target"])
    target[field] = value
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "bad-target",
        "--payload-json", json.dumps(intake(exact_target=target), ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "invalid_intake"


def test_toolchain_without_compiler_or_firmware_version_blocks_baseline(tmp_path):
    target = dict(intake()["exact_target"])
    target["toolchain"] = "STM32CubeIDE 1.19.0"
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "text-toolchain",
        "--payload-json", json.dumps(intake(exact_target=target), ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "invalid_intake"


@pytest.mark.parametrize("pin,alternate", [("PZ99", "GPIO"), ("PA1", "IMPOSSIBLE_AF")])
def test_invalid_f103_pin_or_alternate_function_is_rejected(tmp_path, pin, alternate):
    value = intake()
    value["resource_plan"]["pins"] = [{
        "pin": pin, "signal": "GPIO_INPUT", "function": "TEST", "alternate_function": alternate
    }]
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "bad-pin",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "invalid_intake"


def test_unknown_pin_and_missing_bus_clock_block_baseline(tmp_path):
    value = intake()
    value["resource_plan"]["pins"] = [{
        "pin": "unknown", "signal": "GPIO_INPUT", "function": "DHT22_DATA", "alternate_function": "GPIO"
    }]
    value["resource_plan"]["clocks"].pop("pclk1_hz")
    projects = tmp_path / "Projects"
    created = init_project(projects, value)
    assert "pin_unknown" in created["state"]["resource_blockers"]
    assert "clock_unknown:pclk1_hz" in created["state"]["resource_blockers"]
    blocked = record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": "e" * 64}, 1, ok=False)
    assert blocked["error"] == "resource_gate"


def test_imported_document_cannot_be_increment_observation_and_rollback_is_structured(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    baseline = "f" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "build", "kind": "build_result", "summary": "构建成功",
        "verification_level": "V2", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "hardware_verified": False,
    }, 2)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "imported", "kind": "document_review", "summary": "外部文档",
        "verification_level": "V0", "verification_status": "verified", "source": "imported_reference",
        "baseline_hash": baseline, "hardware_verified": False,
    }, 3)
    rejected = record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "build", "expected_observation": "输出变化",
        "actual_observation": {
            "expected": "输出变化", "observed": "文档说会变化", "result": "passed", "evidence_id": "imported"
        },
        "rollback": {
            "steps": ["不可回滚"], "last_known_good_artifact": "none",
            "last_known_good_hash": "0" * 64, "verification_action": "无"
        },
    }, 4, ok=False)
    assert rejected["error"] == "invalid_increment"


def test_ultrasonic_mcu_wiring_requires_structured_echo_interface(tmp_path):
    value = intake(goal="制作超声测距器")
    value["resources"]["components"].append({
        "component_id": "sonar-1", "name": "超声测距模块", "model": "HC-SR04", "quantity": 1
    })
    value["resource_plan"]["pins"] = [{
        "pin": "PA1", "signal": "GPIO_INPUT", "function": "ULTRASONIC_ECHO",
        "alternate_function": "GPIO"
    }]
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "sonar-missing-gate",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "blocked_safety"

    value["safety"]["echo_interface"] = {
        "module_output_v": 5.0, "mcu_max_v": 3.3, "method": "divider",
        "resistor_values": {"high_ohm": 10000, "low_ohm": 20000},
    }
    value["notes"] = {"wiring": "Echo 接分压器再接 PA1"}
    created = run_cli(
        tmp_path / "Projects", "init", "--project-id", "sonar-safe",
        "--payload-json", json.dumps(value, ensure_ascii=False),
    )[1]
    assert created["state"]["intake"]["safety"]["echo_interface"]["method"] == "divider"


def test_ultrasonic_direct_connection_is_blocked_even_with_echo_interface(tmp_path):
    value = intake(goal="制作回波测距器", notes={"routing": "回波输出与 PA1 直接相连"})
    value["resources"]["components"].append({
        "component_id": "sonar-1", "name": "超声模块", "model": "HC_SR04", "quantity": 1
    })
    value["safety"]["echo_interface"] = {
        "module_output_v": 5, "mcu_max_v": 3.3, "method": "level_shifter",
        "source": "TXS0102 datasheet",
    }
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "sonar-direct",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "blocked_safety"


def test_plain_jie_echo_to_gpio_is_blocked_even_with_interface_metadata(tmp_path):
    value = intake(goal="制作回波测距器", notes={"wiring": "HC-SR04 Echo 5V 接 PA0"})
    value["resources"]["components"].append({
        "component_id": "sonar-1", "name": "超声模块", "model": "HC-SR04", "quantity": 1
    })
    value["safety"]["echo_interface"] = {
        "module_output_v": 5, "mcu_max_v": 3.3, "method": "divider",
        "resistor_values": {"high_ohm": 10000, "low_ohm": 20000},
    }
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "sonar-plain-jie",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "blocked_safety"


def test_motor_project_requires_driver_structure_and_matching_inventory(tmp_path):
    value = intake(goal="制作马达控制器")
    value["resources"]["components"].append({
        "component_id": "motor-1", "name": "直流电机", "model": "N20", "quantity": 2
    })
    value["resource_plan"]["pins"] = [{
        "pin": "PA1", "signal": "GPIO_OUTPUT", "function": "MOTOR_COMMAND",
        "alternate_function": "GPIO"
    }]
    _, missing = run_cli(
        tmp_path / "Projects", "init", "--project-id", "motor-missing-driver",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert missing["error"] == "blocked_safety"

    value["safety"]["motor_driver"] = {
        "driver_model": "TB6612FNG", "supply_domain": "VMOTOR_6V",
        "separate_from_gpio": True, "peak_current_ma": 1200, "stop_method": "coast_then_disable",
    }
    _, no_inventory = run_cli(
        tmp_path / "Projects", "init", "--project-id", "motor-no-inventory",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert no_inventory["error"] == "blocked_safety"

    value["resources"]["components"].append({
        "component_id": "driver-1", "name": "双路电机驱动", "model": "TB6612FNG", "quantity": 1
    })
    value["notes"] = {"wiring": "GPIO 接 TB6612 驱动电机"}
    created = run_cli(
        tmp_path / "Projects", "init", "--project-id", "motor-safe",
        "--payload-json", json.dumps(value, ensure_ascii=False),
    )[1]
    assert created["state"]["intake"]["safety"]["motor_driver"]["separate_from_gpio"] is True


def test_motor_direct_connection_wording_is_always_blocked(tmp_path):
    value = intake(goal="制作电机控制器", notes={"wiring": "马达输出与 PB0 直接相连"})
    value["resources"]["components"].extend([
        {"component_id": "motor-1", "name": "电机", "model": "N20", "quantity": 1},
        {"component_id": "driver-1", "name": "电机驱动", "model": "TB6612FNG", "quantity": 1},
    ])
    value["safety"]["motor_driver"] = {
        "driver_model": "TB6612FNG", "supply_domain": "VMOTOR_6V",
        "separate_from_gpio": True, "peak_current_ma": 1200, "stop_method": "disable_and_coast",
    }
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "motor-direct",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "blocked_safety"


def test_plain_jie_gpio_to_motor_is_blocked_even_with_driver_metadata(tmp_path):
    value = intake(goal="制作电机控制器", notes={"wiring": "GPIO 接 电机 PB0"})
    value["resources"]["components"].extend([
        {"component_id": "motor-1", "name": "电机", "model": "N20", "quantity": 1},
        {"component_id": "driver-1", "name": "电机驱动", "model": "TB6612FNG", "quantity": 1},
    ])
    value["safety"]["motor_driver"] = {
        "driver_model": "TB6612FNG", "supply_domain": "VMOTOR_6V",
        "separate_from_gpio": True, "peak_current_ma": 1200, "stop_method": "disable_and_coast",
    }
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "motor-plain-jie",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "blocked_safety"


@pytest.mark.parametrize("mutator", [
    lambda value: value["resources"].update({"components": [{"component_id": "...", "name": "---", "model": "...", "quantity": 1}]}),
    lambda value: value["resources"].update({"budget": {"amount": 0, "currency": "CNY"}}),
    lambda value: value["resources"].update({"time_limit": {"hours": 0, "deadline": "---"}}),
])
def test_structured_resources_reject_placeholders_and_nonpositive_limits(tmp_path, mutator):
    value = intake()
    mutator(value)
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "bad-resources",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "invalid_intake"


@pytest.mark.parametrize("mutator", [
    lambda plan: plan.update({"pins": [{
        "pin": "PA10", "signal": "USART1_TX", "function": "USART1_TX", "alternate_function": "USART1"
    }]}),
    lambda plan: plan.update({"dma": [{"channel": "DMA1_CH4", "function": "USART1_RX"}]}),
    lambda plan: plan.update({"irqs": [{"irq": "USART1", "function": "I2C1_EVENT"}]}),
    lambda plan: plan["clocks"].update({"hclk_hz": 36_000_000, "pclk2_hz": 72_000_000}),
])
def test_signal_dma_irq_and_clock_relationships_are_validated(tmp_path, mutator):
    value = intake()
    mutator(value["resource_plan"])
    _, rejected = run_cli(
        tmp_path / "Projects", "init", "--project-id", "bad-resource-map",
        "--payload-json", json.dumps(value, ensure_ascii=False), ok=False,
    )
    assert rejected["error"] == "invalid_intake"


def test_failed_observation_is_recorded_incomplete_and_complete_is_derived(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    baseline = "4" * 64
    artifact = "5" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "build", "kind": "build_result", "summary": "构建通过",
        "verification_level": "V2", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "artifact_hash": artifact,
    }, 2)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "runtime", "kind": "runtime_log", "summary": "运行结果不符",
        "verification_level": "V4", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline,
    }, 3)
    saved = record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "build", "expected_observation": "LED 翻转",
        "actual_observation": {
            "expected": "LED 翻转", "observed": "LED 未翻转", "result": "failed", "evidence_id": "runtime"
        },
        "rollback": {
            "supported": True,
            "steps": [{"action": "restore_artifact", "artifact_hash": artifact}],
            "verification_action": {"action": "rebuild_and_test", "evidence_id": "build"},
        },
        "complete": True,
    }, 4)["state"]["increments"][0]
    assert saved["complete"] is False


@pytest.mark.parametrize("kind,source", [
    ("measurement", "tool"),
    ("logic_test", "instrument_capture"),
    ("runtime_log", "authoritative_document"),
])
def test_observation_kind_source_pairs_are_fail_closed(tmp_path, kind, source):
    projects = tmp_path / "Projects"
    init_project(projects)
    baseline = "6" * 64
    artifact = "7" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "build", "kind": "build_result", "summary": "构建通过",
        "verification_level": "V2", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "artifact_hash": artifact,
    }, 2)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "observe", "kind": kind, "summary": "观察记录",
        "verification_level": "V4", "verification_status": "verified", "source": source,
        "baseline_hash": baseline,
    }, 3)
    rejected = record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "build", "expected_observation": "输出变化",
        "actual_observation": {
            "expected": "输出变化", "observed": "发生变化", "result": "passed", "evidence_id": "observe"
        },
        "rollback": {
            "supported": True,
            "steps": [{"action": "restore_artifact", "artifact_hash": artifact}],
            "verification_action": {"action": "rebuild_and_test", "evidence_id": "build"},
        },
    }, 4, ok=False)
    assert rejected["error"] == "invalid_increment"


def test_rollback_hash_must_reference_ledger_evidence_or_baseline(tmp_path):
    projects = tmp_path / "Projects"
    init_project(projects)
    baseline = "8" * 64
    artifact = "9" * 64
    record(projects, "generation.baseline_updated", {"baseline_id": "b1", "baseline_hash": baseline}, 1)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "build", "kind": "build_result", "summary": "构建通过",
        "verification_level": "V2", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline, "artifact_hash": artifact,
    }, 2)
    record(projects, "generation.evidence_recorded", {
        "evidence_id": "runtime", "kind": "logic_test", "summary": "逻辑通过",
        "verification_level": "V4", "verification_status": "verified", "source": "tool",
        "baseline_hash": baseline,
    }, 3)
    rejected = record(projects, "generation.increment_recorded", {
        "increment_id": "I1", "baseline_hash": baseline, "buildable": True,
        "build_evidence_id": "build", "expected_observation": "输出变化",
        "actual_observation": {
            "expected": "输出变化", "observed": "发生变化", "result": "passed", "evidence_id": "runtime"
        },
        "rollback": {
            "supported": True,
            "steps": [{"action": "restore_artifact", "artifact_hash": "a" * 64}],
            "verification_action": {"action": "skip", "evidence_id": "build"},
        },
    }, 4, ok=False)
    assert rejected["error"] == "invalid_increment"


def test_zero_hardware_start_uses_procurement_gates_and_beginner_question(tmp_path):
    result = init_project(tmp_path / "Projects", intake(procurement=zero_hardware_procurement()))
    blockers = result["state"]["intake_blockers"]
    assert "procurement:requirements_confirmation" in blockers
    assert "procurement:solution_options" in blockers
    assert "procurement:selection_confirmation" in blockers
    assert "procurement:shopping_list_confirmation" in blockers
    assert result["state"]["intake"]["clarification_questions"] == [
        "请确认 AI 整理的需求说明是否准确，或指出要修改的内容？"
    ]


def test_confirmed_zero_hardware_plan_is_schema_valid_without_claiming_hardware_identity(tmp_path):
    result = init_project(
        tmp_path / "Projects", intake(procurement=zero_hardware_procurement(confirmed=True))
    )
    state = result["state"]
    assert not [item for item in state["intake_blockers"] if item.startswith("procurement:")]
    assert "hardware_identity" not in state["intake"]
    schema = json.loads(
        (ROOT / ".agents/skills/stm32-ai-mentor/references/schemas/project-intake.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(state["intake"])


def test_procurement_requires_one_recommended_option_and_explicit_selection(tmp_path):
    invalid = zero_hardware_procurement(confirmed=True)
    invalid["solution_options"][0]["recommended"] = False
    _, result = run_cli(
        tmp_path / "Projects", "init", "--project-id", "bad-procurement",
        "--intake", json.dumps(intake(procurement=invalid), ensure_ascii=False), ok=False,
    )
    assert result["error"] == "invalid_intake"


def test_procurement_update_never_marks_items_received_implicitly(tmp_path):
    projects = tmp_path / "Projects"
    initial = init_project(projects, intake(procurement=zero_hardware_procurement()))
    result = record(
        projects, "generation.procurement_updated",
        {"procurement": zero_hardware_procurement(confirmed=True)},
        initial["state"]["revision"], key="procurement-confirmed",
    )
    assert result["state"]["intake"]["procurement"]["shopping_list"][0]["purchase_status"] == "planned"
    assert "hardware_identity" not in result["state"]["intake"]
