#!/usr/bin/env python3
"""Fail-closed, independent event ledger for V3 competition work."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ADAPTERS = {"nuedc", "cpipc", "soc_china", "generic"}
SOURCE_TIERS = {"official", "organizer_authorized", "archived_official", "secondary"}
PURPOSES = {"rules", "prior_art", "technical", "format"}
FUTURE_SKEW_SECONDS = 300
EVENTS = {
    "competition.intake_recorded", "competition.rules_frozen", "competition.citation_recorded",
    "competition.ai_use_recorded", "competition.evidence_recorded", "competition.deliverable_recorded",
    "competition.submission_reported",
}


class CompetitionError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _obj(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CompetitionError("invalid_json", f"{label} 必须是 JSON 对象。") from exc
    if not isinstance(value, dict):
        raise CompetitionError("invalid_payload", f"{label} 必须是 JSON 对象。")
    return value


def _required(value: dict[str, Any], name: str, kind: type = str) -> Any:
    item = value.get(name)
    if not isinstance(item, kind) or (kind is str and not item.strip()):
        raise CompetitionError("invalid_payload", f"缺少或无效字段：{name}")
    return item


def _iso(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise CompetitionError("invalid_payload", f"{name} 必须为 ISO-8601 时间。")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CompetitionError("invalid_payload", f"{name} 必须为 ISO-8601 时间。") from exc
    if parsed.tzinfo is None:
        raise CompetitionError("invalid_payload", f"{name} 必须带时区。")
    return parsed


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _paths(root: Path, competition_id: str) -> tuple[Path, Path, Path]:
    if not competition_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in competition_id):
        raise CompetitionError("invalid_competition_id", "competition_id 只能包含字母、数字、下划线和连字符。")
    base = root / competition_id
    return base / "events.jsonl", base / "snapshot.json", base / ".lock"


def _atomic_json(path: Path, value: Any) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _lock(path: Path) -> None:
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise CompetitionError("active_lock", "竞赛账本正被另一个操作使用；为保护账本已停止。") from exc
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(json.dumps({"pid": os.getpid(), "created_at": _now()}, ensure_ascii=False))


def _unlock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _initial(competition_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1, "competition_id": competition_id, "revision": 0, "created_at": None,
        "updated_at": None, "intake": None, "ruleset": None, "rules_fresh": False, "warnings": [],
        "citations": [], "ai_use": [], "evidence": [], "deliverables": [], "submissions": [],
    }


def _fresh(rules: dict[str, Any]) -> bool:
    retrieved = _iso(rules.get("retrieved_at"), "retrieved_at")
    return (datetime.now(timezone.utc) - retrieved.astimezone(timezone.utc)).total_seconds() <= 7 * 24 * 3600


def _reject_future(value: Any, name: str) -> None:
    if _iso(value, name).astimezone(timezone.utc).timestamp() > datetime.now(timezone.utc).timestamp() + FUTURE_SKEW_SECONDS:
        raise CompetitionError("future_timestamp", f"{name} 超出允许的未来时钟偏差。")


def _warnings(state: dict[str, Any]) -> None:
    warnings: list[str] = []
    rules = state["ruleset"]
    state["rules_fresh"] = bool(rules and _fresh(rules))
    if rules:
        if not state["rules_fresh"]:
            warnings.append("rules_stale")
        if rules.get("source_tier") != "official" or rules.get("availability") == "unreachable":
            warnings.append("rules_source_degraded")
    state["warnings"] = warnings


def _validate_intake(value: dict[str, Any]) -> None:
    for name in ("competition_name", "adapter", "edition", "track", "deadline"):
        _required(value, name)
    if value["adapter"] not in ADAPTERS:
        raise CompetitionError("unknown_adapter", "adapter 必须是 nuedc、cpipc、soc_china 或 generic。")
    _iso(value["deadline"], "deadline")
    if not isinstance(value.get("team"), dict):
        raise CompetitionError("invalid_payload", "team 必须是对象。")


def _validate_rules(value: dict[str, Any]) -> None:
    for name in ("ruleset_id", "competition_name", "adapter", "edition", "track", "source_url", "source_tier", "retrieved_at", "rule_hash", "ai_use_policy"):
        _required(value, name)
    if value["adapter"] not in ADAPTERS or value["source_tier"] not in SOURCE_TIERS:
        raise CompetitionError("invalid_payload", "adapter 或 source_tier 无效。")
    _iso(value["retrieved_at"], "retrieved_at")
    _reject_future(value["retrieved_at"], "retrieved_at")
    if len(value["rule_hash"]) != 64 or any(char not in "0123456789abcdef" for char in value["rule_hash"].lower()):
        raise CompetitionError("invalid_payload", "rule_hash 必须是 SHA-256 十六进制摘要。")
    if value["ai_use_policy"] not in {"disclose", "prohibit", "unknown"}:
        raise CompetitionError("invalid_payload", "ai_use_policy 必须为 disclose、prohibit 或 unknown。")


def _find(items: list[dict[str, Any]], field: str, value: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get(field) == value), None)


def _string_list(value: Any, name: str, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value) or (nonempty and not value):
        raise CompetitionError("invalid_payload", f"{name} 必须是{'非空' if nonempty else ''}字符串数组。")
    return value


def _validate_deliverable(value: dict[str, Any]) -> None:
    for name in ("deliverable_id", "kind", "status", "ruleset_hash"):
        _required(value, name)
    if value["status"] not in {"outline", "draft", "draft_complete", "ready", "invalidated"}:
        raise CompetitionError("invalid_payload", "Deliverable status 无效。")
    if value["status"] != "draft_complete":
        return
    for name in ("citation_ids", "prior_art_citation_ids", "student_decision_ids", "raw_evidence_ids"):
        _string_list(value.get(name), name, nonempty=True)
    if not isinstance(value.get("claim_evidence"), dict) or not value["claim_evidence"]:
        raise CompetitionError("invalid_payload", "draft_complete 必须有 claim_evidence。")
    contribution_map = value.get("contribution_map")
    if not isinstance(contribution_map, dict) or not contribution_map or not all(isinstance(key, str) and key and isinstance(item, str) and item for key, item in contribution_map.items()):
        raise CompetitionError("invalid_payload", "draft_complete 必须有非空 contribution_map。")
    if not isinstance(value.get("anonymity_checked"), bool) or not isinstance(value.get("contains_identity"), bool):
        raise CompetitionError("invalid_payload", "draft_complete 必须有匿名检查布尔值。")


def _apply(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(state)
    kind, payload = event["event_type"], event["payload"]
    if kind == "competition.intake_recorded":
        _validate_intake(payload)
        if result["intake"] is not None:
            raise CompetitionError("intake_already_recorded", "CompetitionIntake 已被冻结，不能静默覆盖。")
        result["intake"] = copy.deepcopy(payload)
    elif kind == "competition.rules_frozen":
        _validate_rules(payload)
        if not result["intake"]:
            raise CompetitionError("intake_required", "冻结 RuleSet 前必须先记录 CompetitionIntake。")
        if any(payload[field] != result["intake"][field] for field in ("competition_name", "adapter", "edition", "track")):
            raise CompetitionError("competition_identity_mismatch", "RuleSet 的赛事、届次、赛道和 adapter 必须与 CompetitionIntake 一致。")
        previous = result["ruleset"]
        result["ruleset"] = copy.deepcopy(payload)
        if previous and previous["rule_hash"] != payload["rule_hash"]:
            for deliverable in result["deliverables"]:
                if deliverable.get("status") != "submitted" and deliverable.get("ruleset_hash") != payload["rule_hash"]:
                    deliverable["status"] = "invalidated"
                    deliverable.setdefault("invalidations", []).append("rules_updated")
    elif kind == "competition.citation_recorded":
        for name in ("citation_id", "title", "url", "source_tier", "retrieved_at", "purpose"):
            _required(payload, name)
        if payload["source_tier"] not in SOURCE_TIERS:
            raise CompetitionError("invalid_payload", "Citation source_tier 无效。")
        _iso(payload["retrieved_at"], "retrieved_at")
        _reject_future(payload["retrieved_at"], "retrieved_at")
        if payload["purpose"] not in PURPOSES:
            raise CompetitionError("invalid_payload", "Citation purpose 无效。")
        if _find(result["citations"], "citation_id", payload["citation_id"]):
            raise CompetitionError("duplicate_citation", "Citation ID 已存在。")
        result["citations"].append(copy.deepcopy(payload))
    elif kind == "competition.ai_use_recorded":
        for name in ("use_id", "tool", "purpose"):
            _required(payload, name)
        if not isinstance(payload.get("disclosed"), bool) or not isinstance(payload.get("student_reviewed"), bool):
            raise CompetitionError("invalid_payload", "AIUse.disclosed/student_reviewed 必须是布尔值。")
        if _find(result["ai_use"], "use_id", payload["use_id"]):
            raise CompetitionError("duplicate_ai_use", "AIUse ID 已存在。")
        result["ai_use"].append(copy.deepcopy(payload))
    elif kind == "competition.evidence_recorded":
        for name in ("evidence_id", "kind", "summary", "source", "verification_status"):
            _required(payload, name)
        if payload["source"] not in {"tool", "reported_by_user", "document", "inference"}:
            raise CompetitionError("invalid_payload", "证据 source 无效。")
        if payload["verification_status"] not in {"verified", "reported", "unverified"}:
            raise CompetitionError("invalid_payload", "证据 verification_status 无效。")
        if payload["source"] == "tool" and payload["verification_status"] == "verified" and payload["kind"] in {"raw_measurement", "measurement", "innovation_experiment"}:
            raise CompetitionError("tool_hardware_evidence_unverified", "工具不能把硬件实测或创新实验记录为 verified。")
        if payload["kind"] in {"raw_measurement", "innovation_experiment"}:
            _required(payload, "raw_artifact_hash")
            if len(payload["raw_artifact_hash"]) != 64:
                raise CompetitionError("invalid_payload", "原始证据必须携带 SHA-256 摘要。")
        if _find(result["evidence"], "evidence_id", payload["evidence_id"]):
            raise CompetitionError("duplicate_evidence", "证据 ID 已存在。")
        result["evidence"].append(copy.deepcopy(payload))
    elif kind == "competition.deliverable_recorded":
        _validate_deliverable(payload)
        existing = _find(result["deliverables"], "deliverable_id", payload["deliverable_id"])
        if existing:
            result["deliverables"][result["deliverables"].index(existing)] = copy.deepcopy(payload)
        else:
            result["deliverables"].append(copy.deepcopy(payload))
    elif kind == "competition.submission_reported":
        deliverable_id = _required(payload, "deliverable_id")
        if payload.get("source") != "reported_by_user":
            raise CompetitionError("submission_must_be_reported_by_user", "提交只能记录为 reported_by_user，不能由工具或导师声称完成。")
        _required(payload, "receipt")
        deliverable = _find(result["deliverables"], "deliverable_id", deliverable_id)
        if not deliverable:
            raise CompetitionError("unknown_deliverable", "提交引用了不存在的 Deliverable。")
        gate = _preflight(result, deliverable)
        if not gate["ok"]:
            raise CompetitionError("submission_preflight_failed", "提交前检查未通过。", gate["blocking_reasons"])
        deliverable["status"] = "submitted"
        result["submissions"].append({**copy.deepcopy(payload), "reported_at": event["occurred_at"]})
    else:
        raise CompetitionError("unsupported_event", f"不支持的事件类型：{kind}")
    result["revision"] = event["revision"]
    result["created_at"] = result["created_at"] or event["occurred_at"]
    result["updated_at"] = event["occurred_at"]
    _warnings(result)
    return result


def _read_events(events_path: Path, competition_id: str) -> list[dict[str, Any]]:
    if not events_path.exists():
        raise CompetitionError("competition_not_found", "竞赛账本不存在。")
    events = []
    for index, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CompetitionError("ledger_corrupt", f"events.jsonl 第 {index} 行不是有效 JSON。") from exc
        if not isinstance(event, dict) or event.get("revision") != index or event.get("event_type") not in EVENTS:
            raise CompetitionError("ledger_corrupt", f"events.jsonl 第 {index} 行违反事件顺序或类型。")
        if event.get("competition_id") != competition_id or not isinstance(event.get("payload"), dict):
            raise CompetitionError("ledger_corrupt", f"events.jsonl 第 {index} 行归属或载荷无效。")
        events.append(event)
    return events


def _materialize(events_path: Path, competition_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = _initial(competition_id)
    events = _read_events(events_path, competition_id)
    for event in events:
        state = _apply(state, event)
    return state, events


def _snapshot_status(snapshot_path: Path, state: dict[str, Any], events: list[dict[str, Any]], competition_id: str) -> str:
    """Return ok/behind/missing/divergence without ever trusting a snapshot."""
    if not snapshot_path.exists():
        return "missing"
    try:
        saved = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CompetitionError("snapshot_corrupt", "snapshot.json 不是有效 JSON。") from exc
    saved_revision = saved.get("revision") if isinstance(saved, dict) else None
    if not isinstance(saved_revision, int) or saved_revision < 0 or saved_revision > len(events):
        return "divergence"
    expected = _initial(competition_id)
    for event in events[:saved_revision]:
        expected = _apply(expected, event)
    if saved != expected:
        return "divergence"
    return "ok" if saved_revision == state["revision"] else "behind"


def _load(root: Path, competition_id: str, check_snapshot: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]], Path, Path, Path]:
    events_path, snapshot_path, lock_path = _paths(root, competition_id)
    state, events = _materialize(events_path, competition_id)
    if check_snapshot:
        status = _snapshot_status(snapshot_path, state, events, competition_id)
        if status == "missing":
            raise CompetitionError("snapshot_missing", "快照缺失；请先运行 rebuild。")
        if status == "behind":
            raise CompetitionError("snapshot_behind", "快照落后于事件账本；请先运行 rebuild。")
        if status == "divergence":
            raise CompetitionError("snapshot_divergence", "快照与事件账本不一致；已 fail-closed，未写入。")
    return state, events, events_path, snapshot_path, lock_path


def _preflight(state: dict[str, Any], deliverable: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    rules = state.get("ruleset")
    if not rules:
        reasons.append("rules_missing")
    else:
        intake = state.get("intake") or {}
        if any(rules.get(field) != intake.get(field) for field in ("competition_name", "adapter", "edition", "track")):
            reasons.append("competition_identity_mismatch")
        if not state["rules_fresh"]:
            reasons.append("rules_stale")
        if rules.get("source_tier") != "official" or rules.get("availability") == "unreachable":
            reasons.append("official_rules_required")
        policy = rules.get("ai_use_policy")
        if policy == "disclose" and not state["ai_use"]:
            reasons.append("ai_use_disclosure_missing")
        if policy == "disclose" and any(not item.get("disclosed") for item in state["ai_use"]):
            reasons.append("ai_use_disclosure_missing")
        if policy == "prohibit" and state["ai_use"]:
            reasons.append("ai_use_prohibited")
        if policy == "unknown":
            reasons.append("ai_use_policy_unknown")
        if rules.get("anonymity_required") and (not deliverable.get("anonymity_checked") or deliverable.get("contains_identity")):
            reasons.append("anonymity_violation")
        if deliverable.get("ruleset_hash") != rules.get("rule_hash"):
            reasons.append("ruleset_outdated")
    citations = {item["citation_id"]: item for item in state["citations"]}
    if not any(item.get("purpose") == "prior_art" for item in state["citations"]):
        reasons.append("prior_art_missing")
    if not deliverable.get("citation_ids"):
        reasons.append("citation_missing")
    if any(item not in citations for item in deliverable.get("citation_ids", [])):
        reasons.append("unknown_citation")
    prior_refs = deliverable.get("prior_art_citation_ids", [])
    if not prior_refs or any(item not in citations or citations[item].get("purpose") != "prior_art" for item in prior_refs):
        reasons.append("prior_art_reference_missing")
    if not deliverable.get("ruleset_id") or rules and deliverable.get("ruleset_id") != rules.get("ruleset_id"):
        reasons.append("ruleset_reference_missing")
    evidence = {item["evidence_id"]: item for item in state["evidence"]}
    claims = deliverable.get("claim_evidence", {})
    for ids in claims.values():
        if not isinstance(ids, list) or any(not isinstance(item, str) or item not in evidence for item in ids):
            reasons.append("unknown_evidence")
            break
    decisions = deliverable.get("student_decision_ids", [])
    if not decisions or any(evidence.get(item, {}).get("kind") != "student_decision" or evidence.get(item, {}).get("source") != "reported_by_user" for item in decisions):
        reasons.append("student_decision_missing")
    raw = deliverable.get("raw_evidence_ids", [])
    if not raw or any(evidence.get(item, {}).get("kind") != "raw_measurement" or evidence.get(item, {}).get("source") != "reported_by_user" or not evidence.get(item, {}).get("raw_artifact_hash") for item in raw):
        reasons.append("raw_evidence_missing")
    if not isinstance(deliverable.get("contribution_map"), dict) or not deliverable["contribution_map"]:
        reasons.append("contribution_map_missing")
    innovation = claims.get("innovation", [])
    if not innovation or not any(evidence.get(item, {}).get("kind") == "innovation_experiment" and evidence.get(item, {}).get("source") == "reported_by_user" and evidence.get(item, {}).get("verification_status") == "verified" and evidence.get(item, {}).get("raw_artifact_hash") for item in innovation):
        reasons.append("innovation_evidence_missing")
    measurements = claims.get("measurement", [])
    if not measurements or not any(evidence.get(item, {}).get("kind") in {"measurement", "raw_measurement"} and evidence.get(item, {}).get("source") == "reported_by_user" and evidence.get(item, {}).get("verification_status") == "verified" and evidence.get(item, {}).get("raw_artifact_hash") for item in measurements):
        reasons.append("measurement_evidence_missing")
    if deliverable.get("fabricated_claim") is True or "fabricated" in claims:
        reasons.append("fabricated_claim")
    if deliverable.get("status") == "invalidated":
        reasons.append("deliverable_invalidated")
    return {"ok": not reasons, "blocking_reasons": sorted(set(reasons)), "warnings": state["warnings"], "deliverable_id": deliverable["deliverable_id"]}


def _append(root: Path, competition_id: str, event_type: str, payload: dict[str, Any], expected_revision: int | None, key: str) -> dict[str, Any]:
    state, events, events_path, snapshot_path, lock_path = _load(root, competition_id)
    if not key:
        raise CompetitionError("idempotency_key_required", "每个写入都必须有 idempotency_key。")
    existing = next((event for event in events if event.get("idempotency_key") == key), None)
    if existing:
        if existing.get("event_type") != event_type or _hash(existing.get("payload")) != _hash(payload):
            raise CompetitionError("idempotency_conflict", "同一 idempotency_key 对应了不同事件或载荷；已 fail-closed。")
        return {"state": state, "idempotent": True, "event_id": existing["event_id"]}
    if expected_revision is None or expected_revision != state["revision"]:
        raise CompetitionError("revision_conflict", "expected_revision 与当前 revision 不一致。", {"actual_revision": state["revision"]})
    _lock(lock_path)
    try:
        # Re-read only after acquiring the lock so concurrent writers cannot append from a stale state.
        state, events, events_path, snapshot_path, _ = _load(root, competition_id)
        if expected_revision != state["revision"]:
            raise CompetitionError("revision_conflict", "锁定后 revision 已变化。", {"actual_revision": state["revision"]})
        event = {"event_id": _hash([competition_id, event_type, payload, key]), "competition_id": competition_id,
                 "event_type": event_type, "payload": payload, "idempotency_key": key, "revision": state["revision"] + 1,
                 "occurred_at": _now()}
        next_state = _apply(state, event)
        with events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _atomic_json(snapshot_path, next_state)
        return {"state": next_state, "idempotent": False, "event_id": event["event_id"]}
    finally:
        _unlock(lock_path)


def _init(root: Path, competition_id: str, intake: dict[str, Any], key: str) -> dict[str, Any]:
    events_path, snapshot_path, lock_path = _paths(root, competition_id)
    if events_path.exists() or snapshot_path.exists():
        state, events, *_ = _load(root, competition_id)
        existing = next((event for event in events if event.get("idempotency_key") == key), None)
        if existing:
            if existing.get("event_type") != "competition.intake_recorded" or _hash(existing.get("payload")) != _hash(intake):
                raise CompetitionError("idempotency_conflict", "同一 idempotency_key 对应了不同 intake；已 fail-closed。")
            return {"state": state, "idempotent": True, "event_id": existing["event_id"]}
        raise CompetitionError("competition_exists", "竞赛账本已经存在；请使用 record。")
    if not key:
        raise CompetitionError("idempotency_key_required", "init 必须有 idempotency_key。")
    _validate_intake(intake)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    _lock(lock_path)
    try:
        if events_path.exists() or snapshot_path.exists():
            raise CompetitionError("competition_exists", "竞赛账本已经存在。")
        event = {"event_id": _hash([competition_id, "competition.intake_recorded", intake, key]), "competition_id": competition_id,
                 "event_type": "competition.intake_recorded", "payload": intake, "idempotency_key": key, "revision": 1, "occurred_at": _now()}
        state = _apply(_initial(competition_id), event)
        events_path.write_text(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        _atomic_json(snapshot_path, state)
        return {"state": state, "idempotent": False, "event_id": event["event_id"]}
    finally:
        _unlock(lock_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", "--competitions-dir", dest="competitions_dir", default="Competitions")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "validate", "rebuild", "preflight"):
        part = sub.add_parser(name); part.add_argument("--competition-id", required=True)
        if name == "preflight": part.add_argument("--deliverable-id", required=True)
    init = sub.add_parser("init"); init.add_argument("--competition-id", required=True); init.add_argument("--intake", "--payload-json", dest="intake", required=True); init.add_argument("--idempotency-key", required=True)
    record = sub.add_parser("record"); record.add_argument("--competition-id", required=True); record.add_argument("--event-type", required=True, choices=sorted(EVENTS)); record.add_argument("--payload", "--payload-json", dest="payload", required=True); record.add_argument("--expected-revision", required=True, type=int); record.add_argument("--idempotency-key", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = Path(args.competitions_dir)
    try:
        if args.command == "init": output = _init(root, args.competition_id, _obj(args.intake, "intake"), args.idempotency_key)
        elif args.command == "record": output = _append(root, args.competition_id, args.event_type, _obj(args.payload, "payload"), args.expected_revision, args.idempotency_key)
        else:
            if args.command == "rebuild":
                events_path, snapshot, _ = _paths(root, args.competition_id)
                state, events = _materialize(events_path, args.competition_id)
                status = _snapshot_status(snapshot, state, events, args.competition_id)
                if status == "divergence":
                    raise CompetitionError("snapshot_divergence", "快照与事件账本不一致；已 fail-closed，未写入。")
                _atomic_json(snapshot, state); output = {"state": state, "rebuilt": True, "recovered_snapshot": status in {"behind", "missing"}}
            else:
                state, _, _, snapshot, _ = _load(root, args.competition_id)
                if args.command == "preflight":
                    deliverable = _find(state["deliverables"], "deliverable_id", args.deliverable_id)
                    if not deliverable: raise CompetitionError("unknown_deliverable", "Deliverable 不存在。")
                    output = _preflight(state, deliverable)
                else: output = {"state": state, "valid": True}
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except CompetitionError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "message": exc.message, "details": exc.details}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:  # keep the machine contract valid even for unexpected faults
        print(json.dumps({"ok": False, "error": "internal_error", "message": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
