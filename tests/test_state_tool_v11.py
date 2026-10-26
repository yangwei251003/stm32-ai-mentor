import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts" / "state_tool.py"


def run_cli(profile: Path, *args: str, ok: bool = True) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--profile-dir", str(profile), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    stream = completed.stdout if completed.returncode == 0 else completed.stderr
    if ok:
        assert completed.returncode == 0, completed.stderr
    else:
        assert completed.returncode != 0, completed.stdout
    return json.loads(stream)


def run_with_script(script: Path, profile: Path, *args: str, ok: bool = True) -> dict:
    completed = subprocess.run(
        [sys.executable, str(script), "--profile-dir", str(profile), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    stream = completed.stdout if completed.returncode == 0 else completed.stderr
    if ok:
        assert completed.returncode == 0, completed.stderr
    else:
        assert completed.returncode != 0, completed.stdout
    return json.loads(stream)


def write_legacy_ledger(profile: Path, events: list[dict]) -> None:
    ledger = profile / "events" / "events.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def legacy_event(revision: int, event_type: str, payload: dict) -> dict:
    return {
        "schema_version": 1,
        "event_id": f"legacy-{revision}",
        "event_type": event_type,
        "timestamp": f"2026-08-20T0{revision}:00:00Z",
        "revision": revision,
        "idempotency_key": f"legacy-key-{revision}",
        "payload": payload,
    }


def file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


BLOCKED_LEGACY_LIVE_WRITES = [
    ("learning.profile_initialized", {"profile": {"name": "Changed"}}),
    ("learning.profile_updated", {"hardware_baseline": {"mcu": "STM32F103C8Tx"}}),
    (
        "learning.course_begun",
        {
            "project_id": "device_status_light",
            "title": "设备运行状态灯",
            "session_id": "new-course",
            "required_milestone_ids": ["M1", "M2", "M3"],
        },
    ),
    ("learning.readiness_recorded", {"score": 5, "total": 5}),
    (
        "learning.remediation_recorded",
        {
            "wrong_topic": "GPIO",
            "concept": "输入输出",
            "micro_lesson": "复习输入输出。",
            "duration_minutes": 3,
            "new_question_set_id": "NEW-Q2",
        },
    ),
    (
        "learning.evidence_recorded",
        {"evidence_id": "ev", "kind": "serial_log", "summary": "日志"},
    ),
    ("learning.mastery_updated", {"dimension": "theory", "level": 0}),
    ("learning.milestone_updated", {"milestone_id": "M1", "status": "completed"}),
    (
        "learning.homework_assigned",
        {
            "homework_id": "hw",
            "level": "required",
            "title": "作业",
            "project_id": "custom",
            "due_at": "2026-09-01T00:00:00Z",
        },
    ),
    ("learning.homework_updated", {"homework_id": "old-hw", "status": "submitted"}),
    (
        "learning.misconception_recorded",
        {"topic": "GPIO", "description": "误区"},
    ),
    (
        "learning.unverified_conclusion_recorded",
        {"claim": "功能正常", "reason": "无实物证据"},
    ),
    (
        "learning.review_scheduled",
        {"review_id": "review", "topic": "GPIO", "due_at": "2026-09-01T00:00:00Z"},
    ),
    ("learning.review_completed", {"review_id": "old-review"}),
    ("learning.course_finished", {"outcome": "paused"}),
    ("learning.course_finished", {"outcome": "completed"}),
]


def init(profile: Path) -> None:
    run_cli(profile, "init")


def begin_p01(profile: Path) -> dict:
    return run_cli(
        profile,
        "begin",
        "--project-id",
        "device_status_light",
        "--title",
        "设备运行状态灯",
        "--required-milestone-ids",
        '["M1","M2","M3"]',
        "--expected-revision",
        "1",
    )


def record(
    profile: Path,
    event_type: str,
    payload: dict,
    revision: int,
    *,
    idempotency_key: str | None = None,
    ok: bool = True,
) -> dict:
    args = [
        "record",
        "--event-type",
        event_type,
        "--payload",
        json.dumps(payload, ensure_ascii=False),
        "--expected-revision",
        str(revision),
    ]
    if idempotency_key is not None:
        args.extend(["--idempotency-key", idempotency_key])
    return run_cli(profile, *args, ok=ok)


def satisfy_course_requirements_except_acceptance(profile: Path) -> int:
    init(profile)
    begin_p01(profile)
    record(profile, "learning.readiness_recorded", {"score": 5, "total": 5}, 2)
    revision = 3
    for milestone_id in ("M1", "M2", "M3"):
        record(
            profile,
            "learning.milestone_updated",
            {"milestone_id": milestone_id, "status": "completed"},
            revision,
        )
        revision += 1
    for level in ("required", "life_application", "optional_challenge", "reflection"):
        record(
            profile,
            "learning.homework_assigned",
            {
                "homework_id": f"hw-{level}",
                "level": level,
                "title": level,
                "project_id": "device_status_light",
                "due_at": "2026-09-01T00:00:00Z",
            },
            revision,
        )
        revision += 1
    return revision


def test_begin_accepts_only_ready_detailed_project_and_exact_milestone_contract(tmp_path):
    profile = tmp_path / "profile"
    init(profile)

    unknown = run_cli(
        profile,
        "begin",
        "--project-id",
        "not_in_catalog",
        "--title",
        "不存在",
        "--required-milestone-ids",
        '["M1"]',
        "--expected-revision",
        "1",
        ok=False,
    )
    assert unknown["error"] == "unknown_project"

    catalog_only = run_cli(
        profile,
        "begin",
        "--project-id",
        "smart_home-001",
        "--title",
        "目录项目",
        "--required-milestone-ids",
        '["M1"]',
        "--expected-revision",
        "1",
        ok=False,
    )
    assert catalog_only["error"] == "project_not_ready"

    wrong_milestones = run_cli(
        profile,
        "begin",
        "--project-id",
        "device_status_light",
        "--title",
        "设备运行状态灯",
        "--required-milestone-ids",
        '["M1","M3"]',
        "--expected-revision",
        "1",
        ok=False,
    )
    assert wrong_milestones["error"] == "milestone_contract_mismatch"
    assert wrong_milestones["details"]["expected"] == ["M1", "M2", "M3"]

    begun = begin_p01(profile)
    course = begun["state"]["current_course"]
    assert course["catalog_status"] == "ready-for-class"
    assert course["required_milestone_ids"] == ["M1", "M2", "M3"]


def test_raw_course_event_cannot_bypass_begin_catalog_validation(tmp_path):
    profile = tmp_path / "profile"
    init(profile)

    bypass = record(
        profile,
        "learning.course_begun",
        {
            "project_id": "arbitrary_project",
            "title": "任意完整项目",
            "session_id": "bypass-attempt",
            "required_milestone_ids": ["M1"],
        },
        1,
        ok=False,
    )

    assert bypass["error"] == "unknown_project"

    missing_contract = record(
        profile,
        "learning.course_begun",
        {
            "project_id": "device_status_light",
            "title": "设备运行状态灯",
            "session_id": "new-event-must-be-explicit",
        },
        1,
        ok=False,
    )
    assert missing_contract["error"] == "invalid_payload"


def test_known_legacy_p01_contract_is_frozen_and_does_not_read_current_catalog(tmp_path):
    isolated_skill = tmp_path / "isolated" / ".agents" / "skills" / "stm32-ai-mentor"
    isolated_script = isolated_skill / "scripts" / "state_tool.py"
    isolated_script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, isolated_script)
    profile = tmp_path / "legacy"
    events = [
        legacy_event(1, "learning.profile_initialized", {"profile": {"student_id": "kevin", "name": "Kevin"}}),
        legacy_event(
            2,
            "learning.course_begun",
            {"project_id": "P01", "title": "旧 P01 标题", "session_id": "legacy-session"},
        ),
    ]
    write_legacy_ledger(profile, events)

    first = run_with_script(isolated_script, profile, "status")
    catalog = isolated_skill / "references" / "projects" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"projects":[{"id":"P01","status":"changed"}]}', encoding="utf-8")
    rebuilt = run_with_script(isolated_script, profile, "rebuild")

    course = first["state"]["current_course"]
    assert course["required_milestone_ids"] == ["M1", "M2", "M3"]
    assert course["legacy_contract_unknown"] is False
    assert rebuilt["state"] == first["state"]


@pytest.mark.parametrize("project_id", ["smart_home-001", "custom"])
def test_unknown_legacy_course_with_old_milestone_and_finish_replays_as_fact(tmp_path, project_id):
    profile = tmp_path / project_id
    events = [
        legacy_event(1, "learning.profile_initialized", {"profile": {"student_id": "kevin", "name": "Kevin"}}),
        legacy_event(
            2,
            "learning.course_begun",
            {"project_id": project_id, "title": "旧课程", "session_id": f"legacy-{project_id}"},
        ),
        legacy_event(
            3,
            "learning.milestone_updated",
            {"milestone_id": "OLD-M1", "status": "completed"},
        ),
        legacy_event(4, "learning.course_finished", {"outcome": "completed", "summary": "旧事实"}),
    ]
    write_legacy_ledger(profile, events)

    status = run_cli(profile, "status")
    rebuilt = run_cli(profile, "rebuild")

    completed = status["state"]["completed_courses"][0]
    assert completed["project_id"] == project_id
    assert completed["status"] == "completed"
    assert completed["legacy_contract_unknown"] is True
    assert completed["milestones"][0]["milestone_id"] == "OLD-M1"
    assert rebuilt["state"] == status["state"]


def test_active_unknown_legacy_course_is_blocked_until_cancelled_and_restarted(tmp_path):
    profile = tmp_path / "legacy-active"
    events = [
        legacy_event(1, "learning.profile_initialized", {"profile": {"student_id": "kevin", "name": "Kevin"}}),
        legacy_event(
            2,
            "learning.course_begun",
            {"project_id": "custom", "title": "旧自定义课", "session_id": "legacy-custom"},
        ),
    ]
    write_legacy_ledger(profile, events)

    status = run_cli(profile, "status")
    assert status["state"]["current_course"]["legacy_contract_unknown"] is True
    assert status["state"]["resume_pointer"]["phase"] == "blocked_legacy_migration"
    blocked_milestone = record(
        profile,
        "learning.milestone_updated",
        {"milestone_id": "M1", "status": "completed"},
        2,
        ok=False,
    )
    assert blocked_milestone["error"] == "legacy_migration_required"
    blocked_finish = run_cli(
        profile,
        "finish",
        "--outcome",
        "completed",
        "--expected-revision",
        "2",
        ok=False,
    )
    assert blocked_finish["error"] == "legacy_migration_required"

    cancelled = run_cli(
        profile,
        "finish",
        "--outcome",
        "cancelled",
        "--expected-revision",
        "2",
    )
    assert cancelled["state"]["current_course"] is None


@pytest.mark.parametrize(
    "event_type,payload",
    BLOCKED_LEGACY_LIVE_WRITES,
    ids=[f"{event_type}-{index}" for index, (event_type, _) in enumerate(BLOCKED_LEGACY_LIVE_WRITES)],
)
def test_every_live_write_is_blocked_during_unknown_legacy_migration(
    tmp_path, event_type, payload
):
    profile = tmp_path / "legacy-active"
    write_legacy_ledger(
        profile,
        [
            legacy_event(
                1,
                "learning.profile_initialized",
                {"profile": {"student_id": "kevin", "name": "Kevin"}},
            ),
            legacy_event(
                2,
                "learning.course_begun",
                {"project_id": "custom", "title": "旧自定义课", "session_id": "legacy-custom"},
            ),
        ],
    )
    run_cli(profile, "status")
    before = file_bytes(profile)

    rejected = record(profile, event_type, payload, 2, ok=False)

    assert rejected["error"] == "legacy_migration_required"
    assert file_bytes(profile) == before


@pytest.mark.parametrize(
    "event_type,payload,idempotency_key",
    [
        (
            "learning.evidence_recorded",
            {"evidence_id": "direct-ev", "kind": "serial_log", "summary": "日志"},
            None,
        ),
        (
            "learning.profile_updated",
            {
                "hardware_baseline": {
                    "mcu": "STM32F103C8Tx",
                    "package": "LQFP48",
                    "board": "第三方 Blue Pill",
                    "board_revision": "待确认",
                    "logic_voltage": "3.3V",
                    "evidence_ids": [],
                }
            },
            None,
        ),
        (
            "learning.homework_assigned",
            {
                "homework_id": "direct-hw",
                "level": "required",
                "title": "作业",
                "project_id": "custom",
                "due_at": "2026-09-01T00:00:00Z",
            },
            None,
        ),
        (
            "learning.course_begun",
            {
                "project_id": "custom",
                "title": "旧自定义课",
                "session_id": "legacy-custom",
            },
            "legacy-key-2",
        ),
    ],
    ids=["evidence", "profile", "homework", "idempotent-retry"],
)
def test_direct_legacy_rejection_does_not_materialize_missing_views(
    tmp_path, event_type, payload, idempotency_key
):
    profile = tmp_path / "ledger-only-legacy"
    write_legacy_ledger(
        profile,
        [
            legacy_event(
                1,
                "learning.profile_initialized",
                {"profile": {"student_id": "kevin", "name": "Kevin"}},
            ),
            legacy_event(
                2,
                "learning.course_begun",
                {"project_id": "custom", "title": "旧自定义课", "session_id": "legacy-custom"},
            ),
        ],
    )
    before = file_bytes(profile)
    assert set(before) == {"events/events.jsonl"}

    rejected = record(
        profile,
        event_type,
        payload,
        2,
        idempotency_key=idempotency_key,
        ok=False,
    )

    assert rejected["error"] == "legacy_migration_required"
    assert file_bytes(profile) == before


def test_direct_legacy_cancel_materializes_and_appends(tmp_path):
    profile = tmp_path / "ledger-only-legacy-cancel"
    write_legacy_ledger(
        profile,
        [
            legacy_event(
                1,
                "learning.profile_initialized",
                {"profile": {"student_id": "kevin", "name": "Kevin"}},
            ),
            legacy_event(
                2,
                "learning.course_begun",
                {"project_id": "custom", "title": "旧自定义课", "session_id": "legacy-custom"},
            ),
        ],
    )

    cancelled = run_cli(
        profile,
        "finish",
        "--outcome",
        "cancelled",
        "--expected-revision",
        "2",
    )

    ledger_lines = (profile / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert cancelled["recovered"] is True
    assert cancelled["state"]["revision"] == 3
    assert cancelled["state"]["current_course"] is None
    assert len(ledger_lines) == 3
    assert {
        "manifest.json",
        "state.json",
        "learning_state.md",
        "ability_assessment.md",
        "weak_points.md",
    }.issubset(file_bytes(profile))


def test_legal_write_recovers_lagging_snapshot_and_appends(tmp_path):
    profile = tmp_path / "lagging-profile"
    init(profile)
    revision_one = (profile / "state.json").read_bytes()
    record(
        profile,
        "learning.misconception_recorded",
        {"topic": "GPIO", "description": "把输入悬空当作低电平"},
        1,
    )
    (profile / "state.json").write_bytes(revision_one)

    recorded = record(
        profile,
        "learning.unverified_conclusion_recorded",
        {"claim": "LED 已亮", "reason": "尚无实物证据"},
        2,
    )

    snapshot = json.loads((profile / "state.json").read_text(encoding="utf-8"))
    ledger_lines = (profile / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert recorded["recovered"] is True
    assert recorded["state"]["revision"] == 3
    assert snapshot["revision"] == 3
    assert len(ledger_lines) == 3


def test_direct_write_fails_closed_on_same_revision_snapshot_divergence(tmp_path):
    profile = tmp_path / "divergent-profile"
    init(profile)
    snapshot_path = profile / "state.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["mastery"]["theory"]["level"] = 4
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    before = file_bytes(profile)

    rejected = record(
        profile,
        "learning.misconception_recorded",
        {"topic": "GPIO", "description": "该事件不应被写入"},
        1,
        ok=False,
    )

    assert rejected["error"] == "snapshot_divergence"
    assert file_bytes(profile) == before


def test_unknown_legacy_read_only_commands_do_not_change_ledger(tmp_path):
    profile = tmp_path / "legacy-read-only"
    write_legacy_ledger(
        profile,
        [
            legacy_event(
                1,
                "learning.profile_initialized",
                {"profile": {"student_id": "kevin", "name": "Kevin"}},
            ),
            legacy_event(
                2,
                "learning.course_begun",
                {"project_id": "custom", "title": "旧自定义课", "session_id": "legacy-custom"},
            ),
        ],
    )
    ledger = profile / "events" / "events.jsonl"
    original = ledger.read_bytes()

    run_cli(profile, "status")
    validated = run_cli(profile, "validate")
    rebuilt = run_cli(profile, "rebuild")

    assert validated["valid"] is True
    assert rebuilt["state"]["resume_pointer"]["phase"] == "blocked_legacy_migration"
    assert ledger.read_bytes() == original


def test_readiness_cannot_be_bypassed_and_failed_attempt_requires_fresh_remediation(tmp_path):
    profile = tmp_path / "profile"
    init(profile)
    begin_p01(profile)

    bypass = record(
        profile,
        "learning.milestone_updated",
        {"milestone_id": "M1", "status": "in_progress", "requires_readiness": False},
        2,
        ok=False,
    )
    assert bypass["error"] == "readiness_gate"

    record(
        profile,
        "learning.readiness_recorded",
        {"score": 3, "total": 5, "wrong_topics": ["LED 限流"], "question_set_id": "P01-Q1"},
        2,
    )
    retry_without_remediation = record(
        profile,
        "learning.readiness_recorded",
        {"score": 5, "total": 5, "question_set_id": "P01-Q2"},
        3,
        ok=False,
    )
    assert retry_without_remediation["error"] == "remediation_required"

    reused_questions = record(
        profile,
        "learning.remediation_recorded",
        {
            "wrong_topic": "LED 限流",
            "concept": "电流限制",
            "micro_lesson": "用欧姆定律检查 LED 电流。",
            "duration_minutes": 3,
            "new_question_set_id": "P01-Q1",
        },
        3,
        ok=False,
    )
    assert reused_questions["error"] == "fresh_questions_required"

    record(
        profile,
        "learning.remediation_recorded",
        {
            "wrong_topic": "LED 限流",
            "concept": "电流限制",
            "micro_lesson": "用欧姆定律检查 LED 电流。",
            "duration_minutes": 3,
            "new_question_set_id": "P01-R2",
        },
        3,
    )
    stale_questions = record(
        profile,
        "learning.readiness_recorded",
        {"score": 5, "total": 5, "question_set_id": "P01-Q1"},
        4,
        ok=False,
    )
    assert stale_questions["error"] == "fresh_questions_required"

    passed = record(
        profile,
        "learning.readiness_recorded",
        {"score": 5, "total": 5, "question_set_id": "P01-R2"},
        4,
    )
    assert passed["state"]["prestudy"]["passed"] is True


def test_milestones_enforce_membership_dependencies_and_forward_transitions(tmp_path):
    profile = tmp_path / "profile"
    init(profile)
    begin_p01(profile)
    record(profile, "learning.readiness_recorded", {"score": 5, "total": 5}, 2)

    unknown = record(
        profile,
        "learning.milestone_updated",
        {"milestone_id": "M9", "status": "in_progress"},
        3,
        ok=False,
    )
    assert unknown["error"] == "unknown_milestone"

    out_of_order = record(
        profile,
        "learning.milestone_updated",
        {"milestone_id": "M2", "status": "in_progress"},
        3,
        ok=False,
    )
    assert out_of_order["error"] == "milestone_dependency"
    assert out_of_order["details"] == ["M1"]

    record(profile, "learning.milestone_updated", {"milestone_id": "M1", "status": "completed"}, 3)
    backwards = record(
        profile,
        "learning.milestone_updated",
        {"milestone_id": "M1", "status": "in_progress"},
        4,
        ok=False,
    )
    assert backwards["error"] == "invalid_milestone_transition"

    current = record(
        profile,
        "learning.milestone_updated",
        {"milestone_id": "M2", "status": "in_progress", "next_action": "完成双状态互斥逻辑"},
        4,
    )
    pointer = current["state"]["resume_pointer"]
    assert pointer["milestone_id"] == "M2"
    assert pointer["next_action"] == "完成双状态互斥逻辑"

    status = run_cli(profile, "status")
    checkpoint = status["resume_summary"]["last_checkpoint"]
    assert checkpoint["last_completed"]["milestone_id"] == "M1"
    assert checkpoint["current_milestone"]["milestone_id"] == "M2"
    assert checkpoint["project_id"] == "device_status_light"


def test_status_after_begin_exposes_m1_before_any_milestone_event(tmp_path):
    profile = tmp_path / "profile"
    init(profile)
    begin_p01(profile)

    status = run_cli(profile, "status")

    checkpoint = status["resume_summary"]["last_checkpoint"]
    assert checkpoint["last_completed"] is None
    assert checkpoint["current_milestone"]["milestone_id"] == "M1"
    assert checkpoint["current_milestone"]["status"] == "pending"


def test_nonfunctional_and_self_reported_evidence_cannot_complete_hardware_course(tmp_path):
    profile = tmp_path / "profile"
    revision = satisfy_course_requirements_except_acceptance(profile)
    for index, (kind, level) in enumerate(
        (
            ("build_result", "V2"),
            ("compile_result", "V2"),
            ("configuration", "V1"),
            ("simulation", "V4"),
            ("flash_result", "V2"),
        ),
        1,
    ):
        record(
            profile,
            "learning.evidence_recorded",
            {
                "evidence_id": f"nonfunctional-{index}",
                "kind": kind,
                "summary": f"{kind} 成功",
                "verification_status": "verified",
                "verification_level": level,
                "source": "tool",
                "purpose": "acceptance",
            },
            revision,
        )
        revision += 1

    blocked = run_cli(
        profile,
        "finish",
        "--outcome",
        "completed",
        "--expected-revision",
        str(revision),
        ok=False,
    )
    assert "functional_acceptance_evidence" in blocked["details"]

    record(
        profile,
        "learning.evidence_recorded",
        {
            "evidence_id": "self-reported-v5",
            "kind": "hardware_observation",
            "summary": "用户称状态灯功能正常",
            "verification_status": "verified",
            "verification_level": "V5",
            "source": "reported_by_user",
            "purpose": "acceptance",
            "hardware_verified": True,
        },
        revision,
    )
    revision += 1
    still_blocked = run_cli(
        profile,
        "finish",
        "--outcome",
        "completed",
        "--expected-revision",
        str(revision),
        ok=False,
    )
    assert "functional_acceptance_evidence" in still_blocked["details"]

    record(
        profile,
        "learning.evidence_recorded",
        {
            "evidence_id": "observed-v5",
            "kind": "hardware_observation",
            "summary": "双状态灯按输入状态互斥切换",
            "verification_status": "verified",
            "verification_level": "V5",
            "source": "tool",
            "purpose": "acceptance",
            "hardware_verified": True,
        },
        revision,
    )
    revision += 1
    finished = run_cli(
        profile,
        "finish",
        "--outcome",
        "completed",
        "--expected-revision",
        str(revision),
    )
    assert finished["state"]["completed_courses"][0]["status"] == "completed"


def test_profile_updated_records_structured_hardware_and_toolchain_baselines(tmp_path):
    profile = tmp_path / "profile"
    init(profile)
    payload = {
        "hardware_baseline": {
            "mcu": "STM32F103C8Tx",
            "package": "LQFP48",
            "board": "第三方 Blue Pill",
            "board_revision": "待确认",
            "logic_voltage": "3.3V",
            "evidence_ids": [],
        },
        "toolchain_baseline": {
            "ide": "STM32CubeIDE",
            "ide_version": "1.19.0",
            "framework": "HAL",
            "firmware_package": "STM32CubeF1 1.8.6",
            "programmer": "ST-LINK/V2",
            "debug_interface": "SWD",
            "evidence_ids": [],
        },
    }

    updated = record(profile, "learning.profile_updated", payload, 1)
    assert updated["state"]["profile"]["name"] == "Kevin"
    assert updated["state"]["profile"]["hardware_baseline"]["package"] == "LQFP48"
    assert updated["state"]["profile"]["toolchain_baseline"]["ide_version"] == "1.19.0"

    rebuilt = run_cli(profile, "rebuild")
    assert rebuilt["state"]["profile"]["hardware_baseline"] == payload["hardware_baseline"]
    assert rebuilt["state"]["profile"]["toolchain_baseline"] == payload["toolchain_baseline"]


def test_existing_v1_ledger_and_snapshot_remain_readable(tmp_path):
    legacy = tmp_path / "legacy"
    shutil.copytree(ROOT / "Student_Profile", legacy)

    status = run_cli(legacy, "status")

    assert status["state"]["schema_version"] == 1
    assert status["state"]["revision"] >= 1
    assert set(status["resume_summary"]) == {
        "unfinished_homework",
        "due_reviews",
        "last_checkpoint",
        "phase",
        "next_action",
    }
