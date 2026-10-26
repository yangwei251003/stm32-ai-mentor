#!/usr/bin/env python3
"""Event-sourced local learning state for STM32 AI Mentor.

The JSONL event ledger is canonical. ``state.json`` and Markdown files are
materialized views and can be rebuilt at any time. Only the main mentor agent
should invoke mutating commands.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


# Codex often runs this script through Windows PowerShell, whose active OEM
# codepage may not be UTF-8. Make the machine-readable CLI contract explicit.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SCHEMA_VERSION = 1
LOCK_STALE_SECONDS = 60
DEFAULT_PROFILE = Path(__file__).resolve().parents[4] / "Student_Profile"
ALLOWED_EVENT_TYPES = {
    "learning.profile_initialized",
    "learning.profile_updated",
    "learning.course_begun",
    "learning.readiness_recorded",
    "learning.remediation_recorded",
    "learning.evidence_recorded",
    "learning.mastery_updated",
    "learning.milestone_updated",
    "learning.homework_assigned",
    "learning.homework_updated",
    "learning.misconception_recorded",
    "learning.unverified_conclusion_recorded",
    "learning.review_scheduled",
    "learning.review_completed",
    "learning.course_finished",
}
DIMENSIONS = {"theory", "practice", "debugging", "transfer"}
MASTERY_LABELS = {
    0: "未接触",
    1: "能识别",
    2: "可在指导下完成",
    3: "可独立完成并解释",
    4: "延迟后仍可迁移应用",
}
VERIFICATION_LEVELS = {"V0", "V1", "V2", "V3", "V4", "V5"}
FUNCTIONAL_ACCEPTANCE_KINDS = {
    "acceptance",
    "behavior_observation",
    "bus_communication",
    "functional_test",
    "hardware_measurement",
    "hardware_observation",
    "measurement",
    "photo",
    "serial_log",
    "usb_enumeration",
    "video",
}
LEGACY_V1_MILESTONE_CONTRACTS = {
    f"P{index:02d}": ["M1", "M2", "M3"] for index in range(1, 16)
}
SKILL_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = SKILL_ROOT / "references" / "projects" / "catalog.json"
DETAILED_PROJECTS_DIR = SKILL_ROOT / "references" / "projects" / "detailed"
HARDWARE_BASELINE_FIELDS = {
    "mcu",
    "package",
    "board",
    "board_revision",
    "logic_voltage",
    "evidence_ids",
}
TOOLCHAIN_BASELINE_FIELDS = {
    "ide",
    "ide_version",
    "framework",
    "firmware_package",
    "programmer",
    "programmer_firmware",
    "debug_interface",
    "cubemx_version",
    "compiler",
    "evidence_ids",
}


class StateError(Exception):
    def __init__(self, code: str, message: str, details: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details is not None:
            result["details"] = self.details
        return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        last_error: OSError | None = None
        for _ in range(200):
            try:
                os.replace(temporary, path)
                last_error = None
                break
            except OSError as exc:
                # Windows scanners/indexers can momentarily open the current
                # view without delete sharing. Retrying preserves atomicity.
                last_error = exc
                time.sleep(0.01)
        if last_error is not None:
            raise last_error
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def _write_lock(profile_dir: Path, timeout: float = 30.0) -> Iterator[None]:
    """Acquire a cross-process lock using atomic directory creation."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = profile_dir / ".write.lock"
    deadline = time.monotonic() + timeout
    token = uuid.uuid4().hex
    while True:
        try:
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "token": token, "created_at": _now()}),
                encoding="utf-8",
            )
            break
        except FileExistsError:
            _clear_abandoned_lock(lock_dir)
            if time.monotonic() >= deadline:
                raise StateError("lock_timeout", "学习档案正被另一个写入操作占用。")
            time.sleep(0.03)
        except PermissionError:
            # On Windows, creating a directory while another process is in the
            # final remove transition can briefly report ACCESS_DENIED instead
            # of ALREADY_EXISTS. Treat only this lock-path race as contention.
            if time.monotonic() >= deadline:
                raise StateError("lock_timeout", "学习档案正被另一个写入操作占用。")
            time.sleep(0.03)
    try:
        yield
    finally:
        # The directory itself grants exclusive ownership, so no successor can
        # replace it before this owner removes it. Windows virus scanners and
        # indexers may transiently hold the owner file; retry instead of
        # silently leaving a lock that blocks every later writer.
        released = False
        for _ in range(200):
            try:
                owner_path = lock_dir / "owner.json"
                owner_path.unlink(missing_ok=True)
                lock_dir.rmdir()
                released = True
                break
            except FileNotFoundError:
                released = True
                break
            except OSError:
                time.sleep(0.01)
        if not released:
            raise StateError("lock_release_failed", "学习档案写锁无法安全释放。")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return True
        # Access denied means that a protected process exists.
        return ctypes.windll.kernel32.GetLastError() == 5  # type: ignore[attr-defined]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clear_abandoned_lock(lock_dir: Path) -> None:
    """Recover a lock left behind after an interrupted writer."""
    try:
        owner_path = lock_dir / "owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        pid = int(owner.get("pid", 0))
        age_seconds = time.time() - owner_path.stat().st_mtime
        # Both facts are required: the owner process is gone and the lock has
        # remained untouched beyond the explicit stale threshold.
        abandoned = not _pid_alive(pid) and age_seconds >= LOCK_STALE_SECONDS
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        # Broken ownership evidence is not enough authority to delete a lock.
        return
    if not abandoned:
        return
    try:
        (lock_dir / "owner.json").unlink(missing_ok=True)
        lock_dir.rmdir()
    except OSError:
        # Another writer may already have recovered or replaced it.
        return


def _blank_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "last_event_id": None,
        "updated_at": None,
        "profile": {
            "student_id": "kevin",
            "name": "Kevin",
            "level": "STM32 入门",
            "learning_style": "项目驱动、重实践",
            "primary_mcu": "STM32F103C8Tx",
            "toolchain": "STM32CubeIDE 1.19.0 + HAL",
        },
        "memory_mode": "automatic_local",
        "extensions": {},
        "prestudy": {
            "project_id": None,
            "completed": False,
            "score": None,
            "total": 5,
            "passed": False,
            "attempts": [],
            "wrong_topics": [],
            "remediations": [],
        },
        "mastery": {
            dimension: {"level": 0, "label": MASTERY_LABELS[0], "evidence_ids": [], "updated_at": None}
            for dimension in sorted(DIMENSIONS)
        },
        "current_course": None,
        "completed_courses": [],
        "evidence": [],
        "unverified_conclusions": [],
        "misconceptions": [],
        "due_reviews": [],
        "homework": [],
        "resume_pointer": {
            "phase": "choose_course",
            "project_id": None,
            "milestone_id": None,
            "next_action": "选择第一节生活化 STM32 项目课",
        },
        "next_lesson_suggestion": "从设备运行状态灯开始，建立 GPIO 与调试基础。",
    }


def _required(payload: dict[str, Any], name: str, kind: type | tuple[type, ...]) -> Any:
    value = payload.get(name)
    if not isinstance(value, kind) or (isinstance(value, str) and not value.strip()):
        raise StateError("invalid_payload", f"字段 {name} 缺失或类型不正确。")
    return value


def _validated_evidence_ids(state: dict[str, Any], value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StateError("invalid_payload", "evidence_ids 必须是字符串数组。")
    known = {item["evidence_id"] for item in state["evidence"]}
    missing = [item for item in value if item not in known]
    if missing:
        raise StateError("unknown_evidence", "引用了不存在的证据。", missing)
    return list(dict.fromkeys(value))


def _ready_project_contract(project_id: str, title: str) -> dict[str, Any]:
    """Resolve a V1 classroom project against the ready detailed catalog."""
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateError("catalog_unavailable", "项目目录无法安全读取。", str(exc)) from exc
    projects = catalog.get("projects") if isinstance(catalog, dict) else None
    if not isinstance(projects, list):
        raise StateError("catalog_unavailable", "项目目录结构无效。")

    ready = [
        item
        for item in projects
        if isinstance(item, dict)
        and item.get("mode") == "detailed"
        and item.get("status") == "ready-for-class"
    ]
    detailed_files = sorted(DETAILED_PROJECTS_DIR.glob("P[0-9][0-9]-*.md"))
    if len(ready) > len(detailed_files):
        raise StateError("catalog_unavailable", "ready-for-class 项目缺少对应详细教案。")

    lesson_aliases = {f"P{index:02d}": item for index, item in enumerate(ready, 1)}
    by_id = {item.get("id"): item for item in projects if isinstance(item.get("id"), str)}
    project = lesson_aliases.get(project_id) or by_id.get(project_id)
    if project is None:
        raise StateError("unknown_project", f"项目不在目录中：{project_id}")
    if project.get("mode") != "detailed" or project.get("status") != "ready-for-class":
        raise StateError("project_not_ready", "V1 只能开始 ready-for-class 的精讲项目。")
    if title != project.get("title"):
        raise StateError(
            "project_title_mismatch",
            "项目标题与目录契约不一致。",
            {"expected": project.get("title"), "actual": title},
        )

    try:
        index = ready.index(project)
        detailed_path = detailed_files[index]
        content = detailed_path.read_text(encoding="utf-8")
    except (ValueError, IndexError, OSError, UnicodeDecodeError) as exc:
        raise StateError("catalog_unavailable", "项目详细教案无法安全读取。", str(exc)) from exc
    milestones = list(
        dict.fromkeys(re.findall(r"^\s*-\s+(M\d+)(?=[：:\s])", content, flags=re.MULTILINE))
    )
    if not milestones:
        raise StateError("catalog_unavailable", "项目详细教案未声明里程碑。")
    return {
        "catalog_project_id": project["id"],
        "catalog_status": project["status"],
        "detailed_lesson_id": f"P{index + 1:02d}",
        "required_milestone_ids": milestones,
    }


def _validated_begin_payload(
    project_id: str,
    title: str,
    required_milestone_ids: list[str],
) -> dict[str, Any]:
    contract = _ready_project_contract(project_id, title)
    expected = contract["required_milestone_ids"]
    if required_milestone_ids != expected:
        raise StateError(
            "milestone_contract_mismatch",
            "必做里程碑必须与详细教案完整且顺序一致。",
            {"expected": expected, "actual": required_milestone_ids},
        )
    return contract


def _validate_baseline(
    state: dict[str, Any], value: Any, allowed_fields: set[str], field_name: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise StateError("invalid_payload", f"{field_name} 必须是非空对象。")
    unknown = sorted(set(value) - allowed_fields)
    if unknown:
        raise StateError("invalid_payload", f"{field_name} 含未知字段。", unknown)
    normalized = copy.deepcopy(value)
    for key, item in normalized.items():
        if key == "evidence_ids":
            normalized[key] = _validated_evidence_ids(state, item)
        elif item is not None and (not isinstance(item, str) or not item.strip()):
            raise StateError("invalid_payload", f"{field_name}.{key} 必须是非空字符串或 null。")
    return normalized


def _qualifies_as_functional_acceptance(
    course: dict[str, Any], evidence: dict[str, Any]
) -> bool:
    if (
        evidence.get("project_id") != course["project_id"]
        or evidence.get("verification_status") != "verified"
        or evidence.get("purpose") != "acceptance"
        or evidence.get("kind") not in FUNCTIONAL_ACCEPTANCE_KINDS
    ):
        return False
    if course.get("catalog_status") == "ready-for-class":
        return (
            evidence.get("verification_level") == "V5"
            and evidence.get("hardware_verified") is True
            and evidence.get("source") != "reported_by_user"
        )
    return evidence.get("verification_level") in {"V4", "V5"}


def _event_shape(event: Any, line_number: int | None = None) -> None:
    where = f"第 {line_number} 行" if line_number else "事件"
    if not isinstance(event, dict):
        raise StateError("corrupt_event_log", f"{where}不是 JSON 对象。")
    required = {"schema_version", "event_id", "event_type", "timestamp", "revision", "payload"}
    missing = sorted(required - set(event))
    if missing:
        raise StateError("corrupt_event_log", f"{where}缺少字段。", missing)
    if event["schema_version"] != SCHEMA_VERSION:
        raise StateError("unsupported_schema", f"{where}使用不支持的 schema_version。")
    if not isinstance(event["event_id"], str) or not event["event_id"]:
        raise StateError("corrupt_event_log", f"{where}的 event_id 无效。")
    if not isinstance(event["timestamp"], str) or not event["timestamp"]:
        raise StateError("corrupt_event_log", f"{where}的 timestamp 无效。")
    if event["event_type"] not in ALLOWED_EVENT_TYPES:
        raise StateError("event_type_not_allowed", f"不允许的事件类型：{event['event_type']}")
    if not isinstance(event["revision"], int) or event["revision"] < 1:
        raise StateError("corrupt_event_log", f"{where}的 revision 无效。")
    if not isinstance(event["payload"], dict):
        raise StateError("corrupt_event_log", f"{where}的 payload 必须是对象。")


def _read_events(profile_dir: Path) -> list[dict[str, Any]]:
    path = profile_dir / "events" / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    raise StateError("corrupt_event_log", f"事件账本第 {line_number} 行为空。")
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StateError(
                        "corrupt_event_log", f"事件账本第 {line_number} 行 JSON 损坏。", str(exc)
                    ) from exc
                _event_shape(event, line_number)
                if event["revision"] != line_number:
                    raise StateError(
                        "corrupt_event_log",
                        f"事件账本第 {line_number} 行 revision 不连续。",
                    )
                if event["event_id"] in event_ids:
                    raise StateError("corrupt_event_log", f"事件账本第 {line_number} 行 event_id 重复。")
                event_ids.add(event["event_id"])
                key = event.get("idempotency_key")
                if key:
                    if not isinstance(key, str) or key in idempotency_keys:
                        raise StateError(
                            "corrupt_event_log", f"事件账本第 {line_number} 行幂等键无效或重复。"
                        )
                    idempotency_keys.add(key)
                events.append(event)
    except UnicodeDecodeError as exc:
        raise StateError("corrupt_event_log", "事件账本不是有效 UTF-8。", str(exc)) from exc
    return events


def _append_event(profile_dir: Path, event: dict[str, Any]) -> None:
    path = profile_dir / "events" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical(event) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _apply_event(
    state: dict[str, Any], event: dict[str, Any], *, replay_mode: bool = False
) -> dict[str, Any]:
    if event["revision"] != state["revision"] + 1:
        raise StateError("corrupt_event_log", "事件 revision 与前一状态不连续。")
    result = copy.deepcopy(state)
    payload = event["payload"]
    event_type = event["event_type"]
    timestamp = event["timestamp"]

    if event_type == "learning.profile_initialized":
        if state["revision"] != 0:
            raise StateError("corrupt_event_log", "初始化事件只能是第一条事件。")
        profile = payload.get("profile", {})
        if profile:
            if not isinstance(profile, dict):
                raise StateError("invalid_payload", "profile 必须是对象。")
            result["profile"].update(profile)
        result["memory_mode"] = payload.get("memory_mode", "automatic_local")

    elif event_type == "learning.profile_updated":
        allowed = {"hardware_baseline", "toolchain_baseline"}
        unknown = sorted(set(payload) - allowed)
        if unknown or not payload:
            raise StateError(
                "invalid_payload",
                "profile_updated 只接受硬件或工具链基线更新。",
                unknown or None,
            )
        if "hardware_baseline" in payload:
            baseline = _validate_baseline(
                result,
                payload["hardware_baseline"],
                HARDWARE_BASELINE_FIELDS,
                "hardware_baseline",
            )
            current = result["profile"].get("hardware_baseline", {})
            result["profile"]["hardware_baseline"] = {**current, **baseline}
            if "mcu" in baseline:
                result["profile"]["primary_mcu"] = baseline["mcu"]
        if "toolchain_baseline" in payload:
            baseline = _validate_baseline(
                result,
                payload["toolchain_baseline"],
                TOOLCHAIN_BASELINE_FIELDS,
                "toolchain_baseline",
            )
            current = result["profile"].get("toolchain_baseline", {})
            result["profile"]["toolchain_baseline"] = {**current, **baseline}

    elif event_type == "learning.course_begun":
        if result["current_course"] is not None:
            raise StateError("course_already_active", "已有一节课程尚未结束。")
        project_id = _required(payload, "project_id", str)
        title = _required(payload, "title", str)
        required_milestone_ids = payload.get("required_milestone_ids")
        legacy_missing_contract = required_milestone_ids is None
        if required_milestone_ids is None:
            if not replay_mode:
                raise StateError(
                    "invalid_payload",
                    "新课程事件必须显式声明 required_milestone_ids。",
                )
            # schema_version 1 originally allowed this field to be absent.
            # Replay must not consult mutable catalog or Markdown content.
            required_milestone_ids = copy.deepcopy(
                LEGACY_V1_MILESTONE_CONTRACTS.get(project_id, [])
            )
        if (
            not isinstance(required_milestone_ids, list)
            or (not required_milestone_ids and not legacy_missing_contract)
            or not all(isinstance(item, str) and item.strip() for item in required_milestone_ids)
            or len(set(required_milestone_ids)) != len(required_milestone_ids)
        ):
            raise StateError(
                "invalid_payload", "required_milestone_ids 必须是至少含一项且无重复的字符串数组。"
            )
        # Reducers must stay deterministic so a rebuilt snapshot is identical.
        session_id = _required(payload, "session_id", str)
        result["current_course"] = {
            "session_id": session_id,
            "project_id": project_id,
            "title": title,
            "status": "prestudy",
            "started_at": timestamp,
            "milestones": [],
            "required_milestone_ids": required_milestone_ids,
        }
        if legacy_missing_contract:
            result["current_course"].update(
                {
                    "legacy_schema1_missing_contract": True,
                    "legacy_contract_unknown": project_id
                    not in LEGACY_V1_MILESTONE_CONTRACTS,
                }
            )
            if project_id in LEGACY_V1_MILESTONE_CONTRACTS:
                result["current_course"]["detailed_lesson_id"] = project_id
        for key in ("catalog_project_id", "catalog_status", "detailed_lesson_id"):
            value = payload.get(key)
            if value is not None:
                result["current_course"][key] = value
        result["prestudy"] = {
            "project_id": project_id,
            "completed": False,
            "score": None,
            "total": 5,
            "passed": False,
            "attempts": [],
            "wrong_topics": [],
            "remediations": [],
        }
        result["resume_pointer"] = {
            "phase": "prestudy",
            "project_id": project_id,
            "milestone_id": None,
            "next_action": "阅读课堂预习手册并完成 5 道准备度小测",
        }

    elif event_type == "learning.readiness_recorded":
        if result["current_course"] is None:
            raise StateError("no_active_course", "没有进行中的课程。")
        if result["prestudy"]["passed"]:
            raise StateError("readiness_already_passed", "准备度已通过，无需重复记录。")
        previous_attempts = result["prestudy"]["attempts"]
        failed_attempts = sum(item["score"] < 4 for item in previous_attempts)
        remediations = result["prestudy"].get("remediations", [])
        question_set_id = payload.get("question_set_id")
        if failed_attempts:
            if len(remediations) < failed_attempts:
                raise StateError("remediation_required", "准备度未通过后必须先完成针对性微课。")
            expected_questions = remediations[-1]["new_question_set_id"]
            used_question_sets = {
                item.get("question_set_id")
                for item in previous_attempts
                if isinstance(item.get("question_set_id"), str)
            }
            if question_set_id in used_question_sets:
                raise StateError(
                    "fresh_questions_required",
                    "复测题集不得复用任何旧准备度题集。",
                )
            if question_set_id != expected_questions:
                raise StateError(
                    "fresh_questions_required",
                    "复测必须使用微课后声明的新题集。",
                    {"expected": expected_questions, "actual": question_set_id},
                )
        elif question_set_id is not None and (
            not isinstance(question_set_id, str) or not question_set_id.strip()
        ):
            raise StateError("invalid_payload", "question_set_id 必须是非空字符串。")
        score = _required(payload, "score", int)
        total = payload.get("total", 5)
        if isinstance(score, bool) or isinstance(total, bool) or total != 5 or not 0 <= score <= total:
            raise StateError("invalid_payload", "准备度小测必须是 0–5 分且总分为 5。")
        wrong_topics = payload.get("wrong_topics", [])
        if not isinstance(wrong_topics, list) or not all(isinstance(item, str) for item in wrong_topics):
            raise StateError("invalid_payload", "wrong_topics 必须是字符串数组。")
        attempt = {
            "score": score,
            "total": total,
            "wrong_topics": wrong_topics,
            "question_set_id": question_set_id,
            "recorded_at": timestamp,
        }
        result["prestudy"]["attempts"].append(attempt)
        result["prestudy"].update(
            {
                "completed": True,
                "score": score,
                "total": total,
                "passed": score >= 4,
                "wrong_topics": wrong_topics,
            }
        )
        if score >= 4:
            result["current_course"]["status"] = "in_class"
            result["resume_pointer"].update(
                {"phase": "in_class", "next_action": "从最小可运行里程碑开始动手实现"}
            )
        else:
            result["resume_pointer"].update(
                {
                    "phase": "remediation",
                    "next_action": "只补讲答错知识点，再完成针对性复测",
                }
            )

    elif event_type == "learning.remediation_recorded":
        if result["current_course"] is None:
            raise StateError("no_active_course", "没有进行中的课程。")
        failed_attempts = sum(item["score"] < 4 for item in result["prestudy"]["attempts"])
        if failed_attempts <= len(result["prestudy"].get("remediations", [])):
            raise StateError("remediation_not_due", "只有准备度未通过后才能记录对应微课。")
        links = payload.get("concept_links")
        if links is None:
            links = [
                {
                    "wrong_topic": _required(payload, "wrong_topic", str),
                    "concept": _required(payload, "concept", str),
                }
            ]
        if (
            not isinstance(links, list)
            or not links
            or not all(
                isinstance(item, dict)
                and isinstance(item.get("wrong_topic"), str)
                and bool(item["wrong_topic"].strip())
                and isinstance(item.get("concept"), str)
                and bool(item["concept"].strip())
                for item in links
            )
        ):
            raise StateError("invalid_payload", "concept_links 必须记录错题到概念的对应关系。")
        duration = _required(payload, "duration_minutes", int)
        if isinstance(duration, bool) or not 1 <= duration <= 30:
            raise StateError("invalid_payload", "补课时长必须是 1–30 分钟。")
        new_question_set_id = _required(payload, "new_question_set_id", str)
        used_question_sets = {
            item.get("question_set_id")
            for item in result["prestudy"]["attempts"]
            if isinstance(item.get("question_set_id"), str)
        }
        used_question_sets.update(
            item.get("new_question_set_id")
            for item in result["prestudy"].get("remediations", [])
            if isinstance(item.get("new_question_set_id"), str)
        )
        if new_question_set_id in used_question_sets:
            raise StateError(
                "fresh_questions_required",
                "补救后的新题集不得复用任何旧题集 ID。",
            )
        remediation = {
            "concept_links": links,
            "micro_lesson": _required(payload, "micro_lesson", str),
            "duration_minutes": duration,
            "new_question_set_id": new_question_set_id,
            "recorded_at": timestamp,
        }
        result["prestudy"].setdefault("remediations", []).append(remediation)
        result["resume_pointer"].update(
            {
                "phase": "remediation_retry",
                "next_action": f"完成新题集 {remediation['new_question_set_id']} 的针对性复测",
            }
        )

    elif event_type == "learning.evidence_recorded":
        evidence_id = _required(payload, "evidence_id", str)
        if any(item["evidence_id"] == evidence_id for item in result["evidence"]):
            raise StateError("duplicate_evidence", f"证据 ID 已存在：{evidence_id}")
        kind = _required(payload, "kind", str)
        summary = _required(payload, "summary", str)
        verification_status = payload.get("verification_status", "unverified")
        if verification_status not in {"verified", "unverified", "self_reported"}:
            raise StateError("invalid_payload", "verification_status 无效。")
        source = payload.get("source", "mentor_assessment")
        if source not in {"tool", "reported_by_user", "mentor_assessment"}:
            raise StateError("invalid_payload", "source 必须是 tool、reported_by_user 或 mentor_assessment。")
        limitations = payload.get("limitations", [])
        if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
            raise StateError("invalid_payload", "limitations 必须是字符串数组。")
        if source == "reported_by_user":
            verification_status = "self_reported"
            limitations = list(dict.fromkeys([*limitations, "not_independently_observed"]))
        purpose = payload.get("purpose")
        if purpose is None:
            purpose = "acceptance" if payload.get("acceptance") is True or kind == "acceptance" else "learning"
        if purpose not in {"learning", "acceptance", "debugging", "transfer"}:
            raise StateError("invalid_payload", "证据 purpose 无效。")
        verification_level = payload.get("verification_level")
        if verification_level is not None and verification_level not in VERIFICATION_LEVELS:
            raise StateError("invalid_payload", "verification_level 必须是 V0–V5。")
        hardware_verified = (
            source != "reported_by_user"
            and verification_level == "V5"
            and payload.get("hardware_verified", False) is True
        )
        result["evidence"].append(
            {
                "evidence_id": evidence_id,
                "kind": kind,
                "summary": summary,
                "verification_status": verification_status,
                "verification_level": verification_level,
                "source": source,
                "limitations": limitations,
                "hardware_verified": hardware_verified,
                "purpose": purpose,
                "project_id": payload.get("project_id")
                or (result["current_course"] or {}).get("project_id"),
                "artifact": payload.get("artifact"),
                "recorded_at": timestamp,
            }
        )

    elif event_type == "learning.mastery_updated":
        dimension = _required(payload, "dimension", str)
        if dimension not in DIMENSIONS:
            raise StateError("invalid_payload", f"未知掌握维度：{dimension}")
        level = _required(payload, "level", int)
        if isinstance(level, bool) or not 0 <= level <= 4:
            raise StateError("invalid_payload", "掌握度必须是 0–4 的整数。")
        previous = result["mastery"][dimension]["level"]
        evidence_ids = payload.get("evidence_ids", [])
        if "evidence_id" in payload:
            evidence_ids = [payload["evidence_id"], *evidence_ids]
        if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
            raise StateError("invalid_payload", "evidence_ids 必须是字符串数组。")
        evidence_by_id = {item["evidence_id"]: item for item in result["evidence"]}
        if level > previous:
            verified = [
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id in evidence_by_id
                and evidence_by_id[evidence_id]["verification_status"] == "verified"
            ]
            if not verified:
                raise StateError(
                    "evidence_required",
                    "掌握度晋级必须引用至少一条已验证证据。",
                )
        missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_by_id]
        if missing:
            raise StateError("unknown_evidence", "引用了不存在的证据。", missing)
        result["mastery"][dimension] = {
            "level": level,
            "label": MASTERY_LABELS[level],
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "updated_at": timestamp,
        }

    elif event_type == "learning.milestone_updated":
        course = result["current_course"]
        if course is None:
            raise StateError("no_active_course", "没有进行中的课程。")
        milestone_id = _required(payload, "milestone_id", str)
        status = _required(payload, "status", str)
        if status not in {"pending", "in_progress", "completed", "blocked"}:
            raise StateError("invalid_payload", "里程碑状态无效。")
        milestones = course["milestones"]
        existing = next((item for item in milestones if item["milestone_id"] == milestone_id), None)
        legacy_fact_replay = replay_mode and course.get("legacy_schema1_missing_contract")
        dependencies: list[str] = []
        if not legacy_fact_replay:
            if not result["prestudy"]["passed"]:
                raise StateError("readiness_gate", "准备度未达到 4/5，先进行针对性补课。")
            required_ids = course["required_milestone_ids"]
            if milestone_id not in required_ids:
                raise StateError("unknown_milestone", f"里程碑不在本课必做契约中：{milestone_id}")
            dependencies = required_ids[: required_ids.index(milestone_id)]
            completed_ids = {
                item["milestone_id"] for item in milestones if item["status"] == "completed"
            }
            missing_dependencies = [item for item in dependencies if item not in completed_ids]
            if missing_dependencies:
                raise StateError(
                    "milestone_dependency",
                    "必须先完成前置里程碑。",
                    missing_dependencies,
                )
            transitions = {
                "pending": {"in_progress", "blocked", "completed"},
                "in_progress": {"blocked", "completed"},
                "blocked": {"in_progress", "completed"},
                "completed": set(),
            }
            if existing and status not in transitions[existing["status"]]:
                raise StateError(
                    "invalid_milestone_transition",
                    f"不允许从 {existing['status']} 转为 {status}。",
                )
        evidence_ids = _validated_evidence_ids(result, payload.get("evidence_ids", []))
        value = {
            "milestone_id": milestone_id,
            "title": payload.get("title", milestone_id),
            "status": status,
            "depends_on": dependencies,
            "evidence_ids": evidence_ids,
            "updated_at": timestamp,
        }
        if existing:
            existing.update(value)
        else:
            milestones.append(value)
        result["resume_pointer"].update(
            {
                "phase": "in_class",
                "milestone_id": milestone_id,
                "next_action": payload.get("next_action", f"继续里程碑：{value['title']}"),
            }
        )

    elif event_type == "learning.homework_assigned":
        homework_id = _required(payload, "homework_id", str)
        if any(item["homework_id"] == homework_id for item in result["homework"]):
            raise StateError("duplicate_homework", f"作业 ID 已存在：{homework_id}")
        level = _required(payload, "level", str)
        if level not in {"required", "life_application", "optional_challenge", "reflection"}:
            raise StateError("invalid_payload", "作业级别无效。")
        project_id = _required(payload, "project_id", str)
        due_at = _required(payload, "due_at", str)
        if any(
            item["project_id"] == project_id and item["level"] == level
            for item in result["homework"]
        ):
            raise StateError("duplicate_homework_level", "同一项目的同一级作业只能有一项。")
        result["homework"].append(
            {
                "homework_id": homework_id,
                "level": level,
                "title": _required(payload, "title", str),
                "status": "assigned",
                "project_id": project_id,
                "due_at": due_at,
                "evidence_ids": [],
                "assigned_at": timestamp,
            }
        )

    elif event_type == "learning.homework_updated":
        homework_id = _required(payload, "homework_id", str)
        item = next((entry for entry in result["homework"] if entry["homework_id"] == homework_id), None)
        if item is None:
            raise StateError("unknown_homework", f"作业不存在：{homework_id}")
        status = _required(payload, "status", str)
        if status not in {"assigned", "submitted", "verified", "needs_revision"}:
            raise StateError("invalid_payload", "作业状态无效。")
        evidence_ids = _validated_evidence_ids(result, payload.get("evidence_ids", item["evidence_ids"]))
        item.update(
            {
                "status": status,
                "evidence_ids": evidence_ids,
                "feedback": payload.get("feedback"),
                "updated_at": timestamp,
            }
        )

    elif event_type == "learning.misconception_recorded":
        result["misconceptions"].append(
            {
                "topic": _required(payload, "topic", str),
                "description": _required(payload, "description", str),
                "correction": payload.get("correction"),
                "project_id": payload.get("project_id")
                or (result["current_course"] or {}).get("project_id"),
                "recorded_at": timestamp,
            }
        )

    elif event_type == "learning.unverified_conclusion_recorded":
        result["unverified_conclusions"].append(
            {
                "claim": _required(payload, "claim", str),
                "reason": _required(payload, "reason", str),
                "project_id": payload.get("project_id")
                or (result["current_course"] or {}).get("project_id"),
                "recorded_at": timestamp,
            }
        )

    elif event_type == "learning.review_scheduled":
        review_id = _required(payload, "review_id", str)
        if any(item["review_id"] == review_id for item in result["due_reviews"]):
            raise StateError("duplicate_review", f"复习项 ID 已存在：{review_id}")
        result["due_reviews"].append(
            {
                "review_id": review_id,
                "topic": _required(payload, "topic", str),
                "due_at": _required(payload, "due_at", str),
                "status": "due",
                "project_id": payload.get("project_id"),
                "created_at": timestamp,
            }
        )

    elif event_type == "learning.review_completed":
        review_id = _required(payload, "review_id", str)
        item = next((entry for entry in result["due_reviews"] if entry["review_id"] == review_id), None)
        if item is None:
            raise StateError("unknown_review", f"复习项不存在：{review_id}")
        item.update({"status": "completed", "completed_at": timestamp, "result": payload.get("result")})

    elif event_type == "learning.course_finished":
        course = result["current_course"]
        if course is None:
            raise StateError("no_active_course", "没有进行中的课程。")
        outcome = payload.get("outcome", "completed")
        if outcome not in {"completed", "paused", "cancelled"}:
            raise StateError("invalid_payload", "课程结果无效。")
        legacy_fact_replay = replay_mode and course.get("legacy_schema1_missing_contract")
        if outcome == "completed" and not legacy_fact_replay:
            missing_requirements: list[str] = []
            if not result["prestudy"]["passed"]:
                missing_requirements.append("readiness_4_of_5")
            completed_milestone_ids = {
                item["milestone_id"]
                for item in course["milestones"]
                if item["status"] == "completed"
            }
            for milestone_id in course["required_milestone_ids"]:
                if milestone_id not in completed_milestone_ids:
                    missing_requirements.append(f"milestone:{milestone_id}")
            if not any(
                _qualifies_as_functional_acceptance(course, item)
                for item in result["evidence"]
            ):
                missing_requirements.append("functional_acceptance_evidence")
            assigned_levels = {
                item["level"]
                for item in result["homework"]
                if item["project_id"] == course["project_id"]
            }
            required_levels = {
                "required",
                "life_application",
                "optional_challenge",
                "reflection",
            }
            for level in sorted(required_levels - assigned_levels):
                missing_requirements.append(f"homework:{level}")
            if missing_requirements:
                raise StateError(
                    "completion_gate",
                    "正式项目课尚未满足结课证据契约。",
                    missing_requirements,
                )
        completed = copy.deepcopy(course)
        completed.update(
            {
                "status": outcome,
                "finished_at": timestamp,
                "summary": payload.get("summary"),
            }
        )
        result["completed_courses"].append(completed)
        result["current_course"] = None
        completed_checkpoints = [
            item["milestone_id"] for item in course["milestones"] if item["status"] == "completed"
        ]
        result["resume_pointer"] = {
            "phase": "homework_review" if outcome == "completed" else "choose_course",
            "project_id": completed["project_id"],
            "milestone_id": completed_checkpoints[-1] if completed_checkpoints else None,
            "next_action": payload.get("next_action", "检查本课作业与到期复习项"),
        }
        result["next_lesson_suggestion"] = payload.get(
            "next_lesson_suggestion", "先完成生活应用作业，再根据薄弱点选择下一课。"
        )

    if result["current_course"] is not None and result["current_course"].get(
        "legacy_contract_unknown"
    ):
        result["resume_pointer"] = {
            "phase": "blocked_legacy_migration",
            "project_id": result["current_course"]["project_id"],
            "milestone_id": None,
            "next_action": "取消缺少契约的旧课程，再开始 ready-for-class 精讲项目",
        }

    result["revision"] = event["revision"]
    result["last_event_id"] = event["event_id"]
    result["updated_at"] = timestamp
    return result


def _materialize(events: list[dict[str, Any]]) -> dict[str, Any]:
    if events and events[0]["event_type"] != "learning.profile_initialized":
        raise StateError("corrupt_event_log", "事件账本必须从学习档案初始化事件开始。")
    state = _blank_state()
    for event in events:
        state = _apply_event(state, event, replay_mode=True)
    return state


def _load_snapshot(profile_dir: Path) -> dict[str, Any] | None:
    path = profile_dir / "state.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateError("snapshot_corrupt", "state.json 存在但无法安全读取。", str(exc)) from exc
    if not isinstance(value, dict):
        raise StateError("snapshot_corrupt", "state.json 必须是 JSON 对象。")
    extensions = value.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        raise StateError("snapshot_corrupt", "state.json 的 extensions 必须是对象。")
    return value


def _markdown_views(state: dict[str, Any]) -> dict[str, str]:
    profile = state["profile"]
    course = state["current_course"]
    course_text = (
        f"{course['project_id']} · {course['title']}（{course['status']}）" if course else "当前没有进行中的课程"
    )
    learning = f"""# {profile['name']} 的 STM32 学习状态

- 状态版本：{state['revision']}
- 当前课程：{course_text}
- 预习准备度：{state['prestudy']['score'] if state['prestudy']['score'] is not None else '未测'}/5
- 准备度门槛：{'已通过' if state['prestudy']['passed'] else '未通过'}
- 恢复位置：{state['resume_pointer']['next_action']}
- 下一课建议：{state['next_lesson_suggestion']}

## 未完成作业

"""
    pending = [item for item in state["homework"] if item["status"] not in {"verified"}]
    learning += "\n".join(f"- [{item['status']}] {item['title']}" for item in pending) or "- 暂无\n"
    learning += "\n"

    ability = "# 能力评估\n\n掌握度采用 0–4 级，只有可核查证据才能推动晋级。\n\n"
    for dimension in ("theory", "practice", "debugging", "transfer"):
        item = state["mastery"][dimension]
        ability += f"- {dimension}: {item['level']}/4（{item['label']}）\n"
    ability += "\n评价权重：理论 30%，实际实现 40%，调试 20%，复盘与迁移 10%。\n"

    weak = "# 薄弱点与待验证项\n\n## 常见误区\n\n"
    weak += "\n".join(
        f"- {item['topic']}：{item['description']}" for item in state["misconceptions"]
    ) or "- 暂无"
    weak += "\n\n## 未验证结论\n\n"
    weak += "\n".join(
        f"- {item['claim']}（{item['reason']}）" for item in state["unverified_conclusions"]
    ) or "- 暂无"
    weak += "\n"
    return {
        "learning_state.md": learning,
        "ability_assessment.md": ability,
        "weak_points.md": weak,
    }


def _write_views(profile_dir: Path, state: dict[str, Any]) -> None:
    _atomic_json(profile_dir / "state.json", state)
    for filename, content in _markdown_views(state).items():
        _atomic_text(profile_dir / filename, content)
    sessions = profile_dir / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    for course in state["completed_courses"]:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", course["session_id"])
        content = (
            f"# {course['title']}\n\n"
            f"- 项目：{course['project_id']}\n"
            f"- 开始：{course['started_at']}\n"
            f"- 结束：{course['finished_at']}\n"
            f"- 结果：{course['status']}\n"
            f"- 总结：{course.get('summary') or '未填写'}\n"
        )
        _atomic_text(sessions / f"{safe_id}.md", content)


def _manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "student_id": "kevin",
        "name": "Kevin",
        "memory_mode": "automatic_local",
        "canonical_ledger": "events/events.jsonl",
        "materialized_state": "state.json",
        "derived_views": ["learning_state.md", "ability_assessment.md", "weak_points.md"],
        "event_namespace": "learning.*",
    }


def _manifest_matches(profile_dir: Path) -> bool:
    path = profile_dir / "manifest.json"
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return actual == _manifest()


def _current_locked(
    profile_dir: Path, *, persist_recovery: bool = True
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    events = _read_events(profile_dir)
    if not events:
        raise StateError("not_initialized", "学习档案尚未初始化。")
    canonical_state = _materialize(events)
    snapshot = _load_snapshot(profile_dir)
    recovered = snapshot is None
    if snapshot is not None:
        snapshot_revision = snapshot.get("revision")
        if not isinstance(snapshot_revision, int):
            raise StateError("snapshot_corrupt", "state.json revision 无效。")
        if snapshot_revision > canonical_state["revision"]:
            raise StateError(
                "snapshot_ahead_of_ledger",
                "状态快照领先于事件账本，拒绝自动覆盖。",
                {"snapshot": snapshot_revision, "ledger": canonical_state["revision"]},
            )
        if snapshot_revision == canonical_state["revision"]:
            if snapshot.get("last_event_id") != canonical_state["last_event_id"]:
                raise StateError(
                    "snapshot_divergence",
                    "状态快照与同版本事件账本的末事件不一致，拒绝自动覆盖。",
                )
            snapshot_materialized = copy.deepcopy(snapshot)
            canonical_materialized = copy.deepcopy(canonical_state)
            snapshot_materialized.pop("extensions", None)
            canonical_materialized.pop("extensions", None)
            if snapshot_materialized != canonical_materialized:
                raise StateError(
                    "snapshot_divergence",
                    "同版本状态快照的物化字段与事件账本重放结果不一致，拒绝自动覆盖。",
                )
        else:
            recovered = True
        canonical_state["extensions"] = copy.deepcopy(snapshot["extensions"])
    recovered = recovered or not _manifest_matches(profile_dir)
    if recovered and persist_recovery:
        _atomic_json(profile_dir / "manifest.json", _manifest())
        _write_views(profile_dir, canonical_state)
    return canonical_state, events, recovered


def init_profile(profile_dir: Path) -> dict[str, Any]:
    with _write_lock(profile_dir):
        ledger = profile_dir / "events" / "events.jsonl"
        if ledger.exists() or (profile_dir / "state.json").exists():
            state, _, recovered = _current_locked(profile_dir)
            return {"created": False, "recovered": recovered, "state": state}
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "events").mkdir(exist_ok=True)
        (profile_dir / "sessions").mkdir(exist_ok=True)
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "event_type": "learning.profile_initialized",
            "timestamp": _now(),
            "revision": 1,
            "idempotency_key": "profile-init-kevin-v1",
            "payload": {"profile": _blank_state()["profile"], "memory_mode": "automatic_local"},
        }
        _append_event(profile_dir, event)
        state = _materialize([event])
        _atomic_json(profile_dir / "manifest.json", _manifest())
        _write_views(profile_dir, state)
        return {"created": True, "recovered": False, "state": state}


def get_status(profile_dir: Path) -> dict[str, Any]:
    with _write_lock(profile_dir):
        state, _, recovered = _current_locked(profile_dir)
        course = state["current_course"]
        milestones = course["milestones"] if course else []
        last_checkpoint = milestones[-1] if milestones else None
        last_completed = next(
            (item for item in reversed(milestones) if item.get("status") == "completed"),
            None,
        )
        current_milestone = next(
            (item for item in reversed(milestones) if item.get("status") != "completed"),
            None,
        )
        if course and current_milestone is None:
            completed_ids = {
                item["milestone_id"] for item in milestones if item.get("status") == "completed"
            }
            next_id = next(
                (
                    milestone_id
                    for milestone_id in course["required_milestone_ids"]
                    if milestone_id not in completed_ids
                ),
                None,
            )
            if next_id:
                current_milestone = {
                    "milestone_id": next_id,
                    "title": next_id,
                    "status": "pending",
                    "evidence_ids": [],
                }
        if course and last_checkpoint is None:
            last_checkpoint = {
                "milestone_id": None,
                "title": None,
                "status": "not_started",
                "evidence_ids": [],
            }
        if course is None:
            for completed_course in reversed(state["completed_courses"]):
                last_checkpoint = next(
                    (
                        item
                        for item in reversed(completed_course.get("milestones", []))
                        if item.get("status") == "completed"
                    ),
                    None,
                )
                if last_checkpoint is not None:
                    last_completed = last_checkpoint
                    break
            current_milestone = None
        if last_checkpoint is not None:
            last_checkpoint = copy.deepcopy(last_checkpoint)
            context_course = course
            if context_course is None:
                context_course = next(
                    (
                        item
                        for item in reversed(state["completed_courses"])
                        if any(
                            milestone.get("milestone_id") == last_checkpoint.get("milestone_id")
                            for milestone in item.get("milestones", [])
                        )
                    ),
                    None,
                )
            last_checkpoint.update(
                {
                    "project_id": (context_course or {}).get("project_id"),
                    "project_title": (context_course or {}).get("title"),
                    "session_id": (context_course or {}).get("session_id"),
                    "last_completed": copy.deepcopy(last_completed),
                    "current_milestone": copy.deepcopy(current_milestone),
                }
            )
        resume_summary = {
            "unfinished_homework": [
                {
                    "homework_id": item["homework_id"],
                    "title": item["title"],
                    "due_at": item["due_at"],
                    "status": item["status"],
                }
                for item in state["homework"]
                if item["status"] != "verified"
            ],
            "due_reviews": [item for item in state["due_reviews"] if item["status"] == "due"],
            "last_checkpoint": last_checkpoint,
            "phase": state["resume_pointer"]["phase"],
            "next_action": state["resume_pointer"]["next_action"],
        }
        return {"recovered": recovered, "resume_summary": resume_summary, "state": state}


def validate_profile(profile_dir: Path) -> dict[str, Any]:
    try:
        with _write_lock(profile_dir):
            state, events, recovered = _current_locked(profile_dir)
            if state["schema_version"] != SCHEMA_VERSION:
                raise StateError("invalid_state", "状态 schema_version 不受支持。")
            return {
                "valid": True,
                "event_count": len(events),
                "revision": state["revision"],
                "recovered": recovered,
            }
    except StateError as exc:
        result = exc.as_dict()
        result["valid"] = False
        return result


def record_event(
    profile_dir: Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise StateError("event_type_not_allowed", f"不允许的事件类型：{event_type}")
    if not isinstance(payload, dict):
        raise StateError("invalid_payload", "payload 必须是 JSON 对象。")
    with _write_lock(profile_dir):
        state, events, recovered = _current_locked(profile_dir, persist_recovery=False)
        course = state["current_course"]
        cancelling_unknown_legacy = (
            event_type == "learning.course_finished"
            and payload.get("outcome") == "cancelled"
        )
        if (
            course is not None
            and course.get("legacy_contract_unknown")
            and not cancelling_unknown_legacy
        ):
            raise StateError(
                "legacy_migration_required",
                "旧课程契约未知；只允许取消旧课程，再开始合法精讲项目。",
            )
        if event_type == "learning.course_begun":
            project_id = _required(payload, "project_id", str)
            title = _required(payload, "title", str)
            required_milestone_ids = payload.get("required_milestone_ids")
            if not isinstance(required_milestone_ids, list):
                raise StateError("invalid_payload", "required_milestone_ids 必须是字符串数组。")
            contract = _validated_begin_payload(project_id, title, required_milestone_ids)
            payload = {
                **payload,
                **{
                    key: value
                    for key, value in contract.items()
                    if key != "required_milestone_ids"
                },
            }
        if idempotency_key:
            match = next((event for event in events if event.get("idempotency_key") == idempotency_key), None)
            if match:
                if match["event_type"] != event_type or _canonical(match["payload"]) != _canonical(payload):
                    raise StateError("idempotency_conflict", "幂等键已被不同内容使用。")
                if recovered:
                    _atomic_json(profile_dir / "manifest.json", _manifest())
                    _write_views(profile_dir, state)
                return {"duplicate": True, "recovered": recovered, "event": match, "state": state}
        if expected_revision is None:
            raise StateError("expected_revision_required", "变更学习状态必须提供 expected_revision。")
        if expected_revision is not None and expected_revision != state["revision"]:
            raise StateError(
                "revision_conflict",
                f"期望 revision {expected_revision}，当前为 {state['revision']}。",
                {"expected": expected_revision, "actual": state["revision"]},
            )
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "event_type": event_type,
            "timestamp": _now(),
            "revision": state["revision"] + 1,
            "idempotency_key": idempotency_key,
            "payload": payload,
        }
        candidate = _apply_event(state, event)
        _append_event(profile_dir, event)
        if recovered:
            _atomic_json(profile_dir / "manifest.json", _manifest())
        _write_views(profile_dir, candidate)
        mastery_changes = {
            dimension: {
                "from": state["mastery"][dimension]["level"],
                "to": candidate["mastery"][dimension]["level"],
            }
            for dimension in sorted(DIMENSIONS)
            if state["mastery"][dimension]["level"]
            != candidate["mastery"][dimension]["level"]
        }
        progress_summary = {
            "mastery_changes": mastery_changes,
            "weak_points": [item["topic"] for item in candidate["misconceptions"][-3:]],
            "unfinished_homework": sum(
                item["status"] != "verified" for item in candidate["homework"]
            ),
            "next_action": candidate["resume_pointer"]["next_action"],
        }
        return {
            "duplicate": False,
            "recovered": recovered,
            "event": event,
            "progress_summary": progress_summary,
            "state": candidate,
        }


def begin_course(
    profile_dir: Path,
    project_id: str,
    title: str,
    *,
    required_milestone_ids: list[str],
    session_id: str | None = None,
    idempotency_key: str | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    contract = _validated_begin_payload(project_id, title, required_milestone_ids)
    if session_id is None:
        session_id = (
            uuid.uuid5(uuid.NAMESPACE_URL, f"stm32-ai-mentor:{idempotency_key}:{project_id}").hex
            if idempotency_key
            else uuid.uuid4().hex
        )
    payload = {
        "project_id": project_id,
        "title": title,
        "session_id": session_id,
        "required_milestone_ids": required_milestone_ids,
        **{key: value for key, value in contract.items() if key != "required_milestone_ids"},
    }
    return record_event(
        profile_dir,
        "learning.course_begun",
        payload,
        idempotency_key=idempotency_key,
        expected_revision=expected_revision,
    )


def finish_course(
    profile_dir: Path,
    outcome: str,
    summary: str | None = None,
    *,
    idempotency_key: str | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"outcome": outcome}
    if summary:
        payload["summary"] = summary
    return record_event(
        profile_dir,
        "learning.course_finished",
        payload,
        idempotency_key=idempotency_key,
        expected_revision=expected_revision,
    )


def rebuild_profile(profile_dir: Path) -> dict[str, Any]:
    with _write_lock(profile_dir):
        state, events, _ = _current_locked(profile_dir)
        _write_views(profile_dir, state)
        if not (profile_dir / "manifest.json").exists():
            _atomic_json(profile_dir / "manifest.json", _manifest())
        return {"rebuilt": True, "event_count": len(events), "state": state}


def _parse_payload(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateError("invalid_payload", "payload 不是有效 JSON。", str(exc)) from exc
    if not isinstance(value, dict):
        raise StateError("invalid_payload", "payload 必须是 JSON 对象。")
    return value


def _parse_string_list(raw: str, field_name: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateError("invalid_payload", f"{field_name} 不是有效 JSON 数组。", str(exc)) from exc
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise StateError("invalid_payload", f"{field_name} 必须是至少含一项且无重复的字符串数组。")
    return value


def _add_write_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--idempotency-key")
    parser.add_argument("--expected-revision", type=int)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="STM32 AI Mentor 学习状态工具")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="初始化 Kevin 的本地学习档案")
    subparsers.add_parser("status", help="显示状态；快照落后时自动从事件恢复")
    subparsers.add_parser("validate", help="验证事件账本与状态")

    begin = subparsers.add_parser("begin", help="开始项目课堂")
    begin.add_argument("--project-id", required=True)
    begin.add_argument("--title", required=True)
    begin.add_argument("--session-id")
    begin.add_argument("--required-milestone-ids", required=True)
    _add_write_options(begin)

    record = subparsers.add_parser("record", help="记录一个 learning.* 学习事件")
    record.add_argument("--event-type", required=True)
    record.add_argument("--payload", required=True)
    _add_write_options(record)

    finish = subparsers.add_parser("finish", help="结束当前项目课堂")
    finish.add_argument("--outcome", default="completed", choices=["completed", "paused", "cancelled"])
    finish.add_argument("--summary")
    _add_write_options(finish)
    subparsers.add_parser("rebuild", help="从事件账本重建全部物化状态")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    profile_dir = args.profile_dir.resolve()
    try:
        if args.command == "init":
            result = init_profile(profile_dir)
        elif args.command == "status":
            result = get_status(profile_dir)
        elif args.command == "validate":
            result = validate_profile(profile_dir)
            if not result["valid"]:
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
                return 2
        elif args.command == "begin":
            result = begin_course(
                profile_dir,
                args.project_id,
                args.title,
                required_milestone_ids=_parse_string_list(
                    args.required_milestone_ids, "required_milestone_ids"
                ),
                session_id=args.session_id,
                idempotency_key=args.idempotency_key,
                expected_revision=args.expected_revision,
            )
        elif args.command == "record":
            result = record_event(
                profile_dir,
                args.event_type,
                _parse_payload(args.payload),
                idempotency_key=args.idempotency_key,
                expected_revision=args.expected_revision,
            )
        elif args.command == "finish":
            result = finish_course(
                profile_dir,
                args.outcome,
                args.summary,
                idempotency_key=args.idempotency_key,
                expected_revision=args.expected_revision,
            )
        elif args.command == "rebuild":
            result = rebuild_profile(profile_dir)
        else:  # pragma: no cover
            raise StateError("unknown_command", args.command)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except StateError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    except OSError as exc:
        error = StateError("io_error", "读写学习档案失败。", str(exc))
        print(json.dumps(error.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
