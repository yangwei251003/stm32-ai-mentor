import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts" / "state_tool.py"


def run_cli(profile: Path, *args: str, ok: bool = True):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--profile-dir", str(profile), *args],
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


def record_worker(script: str, profile: str, index: int):
    payload = json.dumps(
        {
            "evidence_id": f"ev-{index}",
            "kind": "serial_log",
            "summary": f"并发证据 {index}",
            "verification_status": "verified",
        },
        ensure_ascii=False,
    )
    for _ in range(40):
        status = subprocess.run(
            [sys.executable, script, "--profile-dir", profile, "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if status.returncode != 0:
            continue
        revision = json.loads(status.stdout)["state"]["revision"]
        result = subprocess.run(
            [
                sys.executable,
                script,
                "--profile-dir",
                profile,
                "record",
                "--event-type",
                "learning.evidence_recorded",
                "--payload",
                payload,
                "--idempotency-key",
                f"parallel-{index}",
                "--expected-revision",
                str(revision),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0:
            return 0
        error = json.loads(result.stderr)
        if error.get("error") != "revision_conflict":
            return result.returncode
    return 9


def test_init_is_utf8_and_does_not_overwrite(tmp_path):
    profile = tmp_path / "中文学习档案"
    _, first = run_cli(profile, "init")
    assert first["state"]["profile"]["name"] == "Kevin"
    state_path = profile / "state.json"
    original = state_path.read_text(encoding="utf-8")
    _, second = run_cli(profile, "init")
    assert second["created"] is False
    assert state_path.read_text(encoding="utf-8") == original
    assert (profile / "learning_state.md").exists()
    assert (profile / "ability_assessment.md").exists()
    assert (profile / "weak_points.md").exists()


def test_complete_learning_session_and_rebuild(tmp_path):
    profile = tmp_path / "Student_Profile"
    run_cli(profile, "init")
    initial_snapshot = (profile / "state.json").read_text(encoding="utf-8")
    run_cli(profile, "begin", "--project-id", "device_status_light", "--title", "设备运行状态灯", "--required-milestone-ids", '["M1","M2","M3"]', "--expected-revision", "1")
    run_cli(
        profile,
        "record",
        "--event-type",
        "learning.readiness_recorded",
        "--payload",
        '{"score":4,"total":5,"wrong_topics":["上拉电阻"]}',
        "--expected-revision", "2",
    )
    run_cli(
        profile,
        "record",
        "--event-type",
        "learning.evidence_recorded",
        "--payload",
        '{"evidence_id":"build-1","kind":"build_result","summary":"编译成功","verification_status":"verified","verification_level":"V2","source":"tool","purpose":"learning"}',
        "--expected-revision", "3",
    )
    run_cli(
        profile,
        "record",
        "--event-type",
        "learning.evidence_recorded",
        "--payload",
        '{"evidence_id":"functional-1","kind":"hardware_observation","summary":"双状态灯按输入状态互斥切换","verification_status":"verified","verification_level":"V5","source":"tool","purpose":"acceptance","hardware_verified":true}',
        "--expected-revision", "4",
    )
    run_cli(
        profile,
        "record",
        "--event-type",
        "learning.mastery_updated",
        "--payload",
        '{"dimension":"practice","level":2,"evidence_ids":["build-1"]}',
        "--expected-revision", "5",
    )
    run_cli(profile, "record", "--event-type", "learning.milestone_updated", "--payload", '{"milestone_id":"M1","status":"completed","evidence_ids":["build-1"]}', "--expected-revision", "6")
    run_cli(profile, "record", "--event-type", "learning.milestone_updated", "--payload", '{"milestone_id":"M2","status":"completed"}', "--expected-revision", "7")
    run_cli(profile, "record", "--event-type", "learning.milestone_updated", "--payload", '{"milestone_id":"M3","status":"completed"}', "--expected-revision", "8")
    for revision, level in enumerate(("required", "life_application", "optional_challenge", "reflection"), 9):
        run_cli(profile, "record", "--event-type", "learning.homework_assigned", "--payload", json.dumps({"homework_id":f"hw-{level}","level":level,"title":level,"project_id":"device_status_light","due_at":"2026-08-30T00:00:00Z"}), "--expected-revision", str(revision))
    _, finished = run_cli(profile, "finish", "--outcome", "completed", "--expected-revision", "13")
    state = finished["state"]
    session_id = state["completed_courses"][0]["session_id"]
    assert state["prestudy"]["passed"] is True
    assert state["mastery"]["practice"]["level"] == 2
    assert state["current_course"] is None
    assert state["completed_courses"][0]["project_id"] == "device_status_light"
    (profile / "state.json").write_text(initial_snapshot, encoding="utf-8")
    _, rebuilt = run_cli(profile, "rebuild")
    assert rebuilt["state"]["revision"] == state["revision"]
    assert rebuilt["state"]["completed_courses"][0]["session_id"] == session_id


def test_mastery_cannot_advance_without_verified_evidence(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    _, error = run_cli(
        profile,
        "record",
        "--event-type",
        "learning.mastery_updated",
        "--payload",
        '{"dimension":"theory","level":1}',
        "--expected-revision", "1",
        ok=False,
    )
    assert error["error"] == "evidence_required"


def test_idempotency_and_revision_conflict(tmp_path):
    profile = tmp_path / "profile"
    _, initial = run_cli(profile, "init")
    revision = initial["state"]["revision"]
    args = (
        "record",
        "--event-type",
        "learning.misconception_recorded",
        "--payload",
        '{"topic":"GPIO","description":"把输入悬空当作低电平"}',
        "--idempotency-key",
        "same-event",
        "--expected-revision",
        str(revision),
    )
    _, first = run_cli(profile, *args)
    _, duplicate = run_cli(profile, *args)
    assert duplicate["duplicate"] is True
    assert duplicate["state"]["revision"] == first["state"]["revision"]
    _, error = run_cli(
        profile,
        "record",
        "--event-type",
        "learning.misconception_recorded",
        "--payload",
        '{"topic":"UART","description":"忽略共地"}',
        "--expected-revision",
        str(revision),
        ok=False,
    )
    assert error["error"] == "revision_conflict"


def test_concurrent_writes_are_serialized(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    with multiprocessing.get_context("spawn").Pool(6) as pool:
        codes = pool.starmap(
            record_worker,
            [(str(SCRIPT), str(profile), index) for index in range(12)],
        )
    assert codes == [0] * 12
    _, status = run_cli(profile, "status")
    assert len(status["state"]["evidence"]) == 12
    assert status["state"]["revision"] == 13


def test_status_recovers_when_snapshot_lags_ledger(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    old_state = (profile / "state.json").read_text(encoding="utf-8")
    run_cli(
        profile,
        "record",
        "--event-type",
        "learning.unverified_conclusion_recorded",
        "--payload",
        '{"claim":"实板 LED 已亮","reason":"尚无照片或测量证据"}',
        "--expected-revision", "1",
    )
    (profile / "state.json").write_text(old_state, encoding="utf-8")
    _, status = run_cli(profile, "status")
    assert status["recovered"] is True
    assert len(status["state"]["unverified_conclusions"]) == 1


def test_corrupt_event_log_fails_closed(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    with (profile / "events" / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{broken-json\n")
    _, result = run_cli(profile, "validate", ok=False)
    assert result["valid"] is False
    assert result["error"] == "corrupt_event_log"


def test_only_learning_namespace_is_allowed(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    _, result = run_cli(
        profile,
        "record",
        "--event-type",
        "generation.project_created",
        "--payload",
        "{}",
        ok=False,
    )
    assert result["error"] == "event_type_not_allowed"


def test_abandoned_directory_lock_is_recovered(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    lock = profile / ".write.lock"
    lock.mkdir()
    owner = lock / "owner.json"
    owner.write_text(
        '{"pid":2147483647,"token":"dead-writer"}', encoding="utf-8"
    )
    stale_time = time.time() - 120
    os.utime(owner, (stale_time, stale_time))
    _, result = run_cli(profile, "status")
    assert result["state"]["revision"] == 1
    assert not lock.exists()


def test_recent_dead_owner_is_not_enough_to_remove_lock(tmp_path):
    lock = tmp_path / ".write.lock"
    lock.mkdir()
    (lock / "owner.json").write_text(
        '{"pid":2147483647,"token":"recent-dead-writer"}', encoding="utf-8"
    )
    probe = (
        "import runpy,sys; from pathlib import Path; "
        "m=runpy.run_path(sys.argv[1]); m['_clear_abandoned_lock'](Path(sys.argv[2]))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(SCRIPT), str(lock)], capture_output=True
    )
    assert completed.returncode == 0
    assert lock.exists()


def test_snapshot_divergence_fails_closed(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    snapshot = json.loads((profile / "state.json").read_text(encoding="utf-8"))
    snapshot["revision"] = 2
    (profile / "state.json").write_text(json.dumps(snapshot), encoding="utf-8")
    _, ahead = run_cli(profile, "status", ok=False)
    assert ahead["error"] == "snapshot_ahead_of_ledger"

    snapshot["revision"] = 1
    snapshot["last_event_id"] = "different-event"
    (profile / "state.json").write_text(json.dumps(snapshot), encoding="utf-8")
    _, mismatch = run_cli(profile, "rebuild", ok=False)
    assert mismatch["error"] == "snapshot_divergence"


def test_same_revision_materialized_tampering_fails_closed_without_writing(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    snapshot_path = profile / "state.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["mastery"]["theory"]["level"] = 4
    tampered = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    snapshot_path.write_text(tampered, encoding="utf-8", newline="\n")

    _, status = run_cli(profile, "status", ok=False)
    assert status["error"] == "snapshot_divergence"
    assert snapshot_path.read_text(encoding="utf-8") == tampered

    _, validation = run_cli(profile, "validate", ok=False)
    assert validation["valid"] is False
    assert validation["error"] == "snapshot_divergence"
    assert snapshot_path.read_text(encoding="utf-8") == tampered


def test_extensions_survive_status_record_and_rebuild(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    snapshot = json.loads((profile / "state.json").read_text(encoding="utf-8"))
    snapshot["extensions"] = {"generation": {"draft_id": "future-v2"}}
    (profile / "state.json").write_text(json.dumps(snapshot), encoding="utf-8")
    _, status = run_cli(profile, "status")
    assert status["state"]["extensions"]["generation"]["draft_id"] == "future-v2"
    _, recorded = run_cli(
        profile,
        "record",
        "--event-type",
        "learning.misconception_recorded",
        "--payload",
        '{"topic":"时钟","description":"混淆 APB 与系统时钟"}',
        "--expected-revision",
        "1",
    )
    assert recorded["state"]["extensions"] == snapshot["extensions"]
    _, rebuilt = run_cli(profile, "rebuild")
    assert rebuilt["state"]["extensions"] == snapshot["extensions"]


def test_expected_revision_is_required_but_idempotent_retry_wins(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    base = (
        "record",
        "--event-type",
        "learning.misconception_recorded",
        "--payload",
        '{"topic":"共地","description":"忘记共地"}',
    )
    _, missing = run_cli(profile, *base, ok=False)
    assert missing["error"] == "expected_revision_required"
    _, first = run_cli(
        profile, *base, "--idempotency-key", "retry-first", "--expected-revision", "1"
    )
    _, retry = run_cli(profile, *base, "--idempotency-key", "retry-first")
    assert first["state"]["revision"] == 2
    assert retry["duplicate"] is True


def test_remediation_and_reported_evidence_keep_provenance(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    run_cli(profile, "begin", "--project-id", "doorbell_button_nightlight", "--title", "电子门铃/按键夜灯", "--required-milestone-ids", '["M1","M2","M3"]', "--expected-revision", "1")
    run_cli(profile, "record", "--event-type", "learning.readiness_recorded", "--payload", '{"score":3,"total":5,"wrong_topics":["消抖"]}', "--expected-revision", "2")
    _, remediated = run_cli(
        profile,
        "record",
        "--event-type",
        "learning.remediation_recorded",
        "--payload",
        '{"wrong_topic":"消抖","concept":"机械触点抖动","micro_lesson":"把一次按压想成一串快速开关，再用稳定窗口过滤。","duration_minutes":5,"new_question_set_id":"P002-R2"}',
        "--expected-revision",
        "3",
    )
    assert remediated["state"]["prestudy"]["remediations"][0]["new_question_set_id"] == "P002-R2"
    _, evidence = run_cli(
        profile,
        "record",
        "--event-type",
        "learning.evidence_recorded",
        "--payload",
        '{"evidence_id":"photo-report","kind":"hardware_observation","summary":"用户称 LED 已亮","verification_status":"verified","source":"reported_by_user","hardware_verified":true}',
        "--expected-revision",
        "4",
    )
    saved = evidence["state"]["evidence"][0]
    assert saved["verification_status"] == "self_reported"
    assert saved["hardware_verified"] is False
    assert "not_independently_observed" in saved["limitations"]


def test_evidence_references_and_completion_gate(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    run_cli(profile, "begin", "--project-id", "traffic_light_state_machine", "--title", "十字路口交通灯", "--required-milestone-ids", '["M1","M2","M3"]', "--expected-revision", "1")
    run_cli(profile, "record", "--event-type", "learning.readiness_recorded", "--payload", '{"score":5,"total":5}', "--expected-revision", "2")
    _, bad_ref = run_cli(profile, "record", "--event-type", "learning.milestone_updated", "--payload", '{"milestone_id":"M1","status":"completed","evidence_ids":["missing"]}', "--expected-revision", "3", ok=False)
    assert bad_ref["error"] == "unknown_evidence"
    _, blocked = run_cli(profile, "finish", "--outcome", "completed", "--expected-revision", "3", ok=False)
    assert blocked["error"] == "completion_gate"
    assert "milestone:M1" in blocked["details"]
    _, paused = run_cli(profile, "finish", "--outcome", "paused", "--expected-revision", "3")
    assert paused["state"]["completed_courses"][0]["status"] == "paused"


def test_status_has_compact_resume_summary(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    _, status = run_cli(profile, "status")
    assert set(status["resume_summary"]) == {
        "unfinished_homework", "due_reviews", "last_checkpoint", "phase", "next_action"
    }


def test_all_required_milestones_gate_completion_and_checkpoint_survives(tmp_path):
    profile = tmp_path / "profile"
    run_cli(profile, "init")
    run_cli(
        profile,
        "begin",
        "--project-id", "breathing_nightlight_buzzer",
        "--title", "呼吸夜灯与提示蜂鸣器",
        "--required-milestone-ids", '["M1","M2","M3"]',
        "--expected-revision", "1",
    )
    run_cli(profile, "record", "--event-type", "learning.readiness_recorded", "--payload", '{"score":5,"total":5}', "--expected-revision", "2")
    run_cli(profile, "record", "--event-type", "learning.evidence_recorded", "--payload", '{"evidence_id":"accept-1","kind":"hardware_observation","summary":"呼吸灯与蜂鸣器在实物上按状态运行","source":"tool","verification_status":"verified","verification_level":"V5","purpose":"acceptance","hardware_verified":true}', "--expected-revision", "3")
    for revision, level in enumerate(("required", "life_application", "optional_challenge", "reflection"), 4):
        run_cli(profile, "record", "--event-type", "learning.homework_assigned", "--payload", json.dumps({"homework_id":f"p4-{level}","level":level,"title":level,"project_id":"breathing_nightlight_buzzer","due_at":"2026-09-01T00:00:00Z"}), "--expected-revision", str(revision))
    run_cli(profile, "record", "--event-type", "learning.milestone_updated", "--payload", '{"milestone_id":"M1","status":"completed","evidence_ids":["accept-1"]}', "--expected-revision", "8")
    _, blocked = run_cli(profile, "finish", "--outcome", "completed", "--expected-revision", "9", ok=False)
    assert "milestone:M2" in blocked["details"]
    assert "milestone:M3" in blocked["details"]
    run_cli(profile, "record", "--event-type", "learning.milestone_updated", "--payload", '{"milestone_id":"M2","status":"completed"}', "--expected-revision", "9")
    run_cli(profile, "record", "--event-type", "learning.milestone_updated", "--payload", '{"milestone_id":"M3","status":"completed"}', "--expected-revision", "10")
    _, finished = run_cli(profile, "finish", "--outcome", "completed", "--expected-revision", "11")
    assert finished["state"]["resume_pointer"]["milestone_id"] == "M3"
    _, status = run_cli(profile, "status")
    assert status["resume_summary"]["last_checkpoint"]["milestone_id"] == "M3"
