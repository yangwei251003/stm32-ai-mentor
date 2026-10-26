import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts" / "competition_tool.py"


def run_cli(directory: Path, *args: str, ok: bool = True):
    result = subprocess.run(
        [sys.executable, str(TOOL), "--store", str(directory), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    data = json.loads(result.stdout)
    assert (result.returncode == 0) is ok, result.stderr or data
    return data


def intake():
    return {
        "competition_name": "全国大学生电子设计竞赛",
        "adapter": "nuedc",
        "edition": "2026",
        "track": "undergraduate-A",
        "team": {"members": 3, "school": "示例大学"},
        "deadline": "2026-09-30T12:00:00+08:00",
        "constraints": ["仅使用已登记器件"],
    }


def record(directory, revision, event_type, payload, key="record", ok=True):
    return run_cli(
        directory,
        "record",
        "--competition-id",
        "demo",
        "--event-type",
        event_type,
        "--payload",
        json.dumps(payload, ensure_ascii=False),
        "--expected-revision",
        str(revision),
        "--idempotency-key",
        key,
        ok=ok,
    )


def fresh_rules(**overrides):
    rules = {
        "ruleset_id": "nuedc-2026-v1",
        "adapter": "nuedc",
        "edition": "2026",
        "competition_name": "全国大学生电子设计竞赛",
        "track": "undergraduate-A",
        "source_url": "https://official.example/rules",
        "source_tier": "official",
        "retrieved_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "rule_hash": "a" * 64,
        "ai_use_policy": "disclose",
        "anonymity_required": True,
    }
    rules.update(overrides)
    return rules


def initialize(directory):
    return run_cli(
        directory,
        "init",
        "--competition-id",
        "demo",
        "--intake",
        json.dumps(intake(), ensure_ascii=False),
        "--idempotency-key",
        "init-demo",
    )


def test_independent_ledger_rebuild_idempotency_and_divergence_fail_closed(tmp_path):
    root = tmp_path / "Competitions"
    started = initialize(root)
    assert started["state"]["revision"] == 1
    assert (root / "demo" / "events.jsonl").exists()
    assert (root / "demo" / "snapshot.json").exists()

    same = initialize(root)
    assert same["idempotent"] is True
    assert same["state"]["revision"] == 1

    saved = record(root, 1, "competition.rules_frozen", fresh_rules(), "freeze")
    assert saved["state"]["ruleset"]["source_tier"] == "official"
    rebuilt = run_cli(root, "rebuild", "--competition-id", "demo")
    assert rebuilt["state"] == saved["state"]

    snapshot = root / "demo" / "snapshot.json"
    bad = json.loads(snapshot.read_text(encoding="utf-8"))
    bad["revision"] = 99
    snapshot.write_text(json.dumps(bad), encoding="utf-8")
    invalid = run_cli(root, "validate", "--competition-id", "demo", ok=False)
    assert invalid["error"] == "snapshot_divergence"


def test_rules_freshness_update_invalidation_and_unreachable_downgrade(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    record(root, 1, "competition.rules_frozen", fresh_rules(), "freeze")
    record(root, 2, "competition.deliverable_recorded", {
        "deliverable_id": "paper", "kind": "paper", "status": "draft",
        "ruleset_hash": "a" * 64, "ruleset_id": "nuedc-2026-v1", "claim_evidence": {}, "citation_ids": [],
    }, "paper")
    updated = record(root, 3, "competition.rules_frozen", fresh_rules(rule_hash="b" * 64), "refresh")
    assert updated["state"]["deliverables"][0]["status"] == "invalidated"
    assert "rules_updated" in updated["state"]["deliverables"][0]["invalidations"]

    stale = record(root, 4, "competition.rules_frozen", fresh_rules(
        ruleset_id="old", retrieved_at=(datetime.now(timezone.utc) - timedelta(days=8)).isoformat(), source_tier="archived_official",
        rule_hash="c" * 64, availability="unreachable"), "old")
    assert stale["state"]["rules_fresh"] is False
    assert "rules_stale" in stale["state"]["warnings"]
    assert "rules_source_degraded" in stale["state"]["warnings"]


def test_snapshot_lag_is_recoverable_but_divergence_is_not(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    record(root, 1, "competition.rules_frozen", fresh_rules(), "freeze")
    snapshot = root / "demo" / "snapshot.json"
    saved = json.loads(snapshot.read_text(encoding="utf-8"))
    saved["revision"] = 1
    saved["ruleset"] = None
    saved["rules_fresh"] = False
    saved["warnings"] = []
    saved["updated_at"] = saved["created_at"]
    snapshot.write_text(json.dumps(saved), encoding="utf-8")
    behind = run_cli(root, "validate", "--competition-id", "demo", ok=False)
    assert behind["error"] == "snapshot_behind"
    recovered = run_cli(root, "rebuild", "--competition-id", "demo")
    assert recovered["recovered_snapshot"] is True


def test_active_lock_fails_closed_without_appending_an_event(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    ledger = root / "demo" / "events.jsonl"
    (root / "demo" / ".lock").write_text('{"pid": 0}', encoding="utf-8")
    blocked = record(root, 1, "competition.rules_frozen", fresh_rules(), "freeze", ok=False)
    assert blocked["error"] == "active_lock"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_integrity_and_submission_gate(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    record(root, 1, "competition.rules_frozen", fresh_rules(), "freeze")
    record(root, 2, "competition.citation_recorded", {
        "citation_id": "prior-1", "title": "已有方案", "url": "https://official.example/prior",
        "source_tier": "official", "retrieved_at": datetime.now(timezone.utc).isoformat(), "purpose": "prior_art",
    }, "citation")
    record(root, 3, "competition.evidence_recorded", {
        "evidence_id": "innovation-1", "kind": "innovation_experiment", "summary": "差异实验记录",
        "source": "reported_by_user", "verification_status": "verified", "raw_artifact_hash": "a" * 64,
    }, "innov")
    record(root, 4, "competition.evidence_recorded", {
        "evidence_id": "measure-1", "kind": "raw_measurement", "summary": "实测波形和数据",
        "source": "reported_by_user", "verification_status": "verified", "raw_artifact_hash": "b" * 64,
    }, "measure")
    record(root, 5, "competition.evidence_recorded", {
        "evidence_id": "decision-1", "kind": "student_decision", "summary": "学生选择差分方案",
        "source": "reported_by_user", "verification_status": "reported",
    }, "decision")
    record(root, 6, "competition.ai_use_recorded", {
        "use_id": "ai-1", "tool": "LLM", "purpose": "语句润色", "disclosed": True, "student_reviewed": True,
    }, "ai")
    record(root, 7, "competition.deliverable_recorded", {
        "deliverable_id": "report", "kind": "paper", "status": "draft_complete", "ruleset_hash": "a" * 64,
        "ruleset_id": "nuedc-2026-v1", "citation_ids": ["prior-1"], "prior_art_citation_ids": ["prior-1"],
        "student_decision_ids": ["decision-1"], "raw_evidence_ids": ["measure-1"], "contribution_map": {"student-1": "architecture and measurement"},
        "claim_evidence": {
            "innovation": ["innovation-1"], "measurement": ["measure-1"],
        },
        "anonymity_checked": True, "contains_identity": False,
    }, "report")
    preflight = run_cli(root, "preflight", "--competition-id", "demo", "--deliverable-id", "report")
    assert preflight["ok"] is True

    rejected = record(root, 8, "competition.submission_reported", {
        "deliverable_id": "report", "source": "tool", "receipt": "R-1",
    }, "bad-submit", ok=False)
    assert rejected["error"] == "submission_must_be_reported_by_user"
    submitted = record(root, 8, "competition.submission_reported", {
        "deliverable_id": "report", "source": "reported_by_user", "receipt": "R-1",
    }, "submit")
    assert submitted["state"]["submissions"][0]["receipt"] == "R-1"


def test_unbacked_claim_anonymity_and_missing_ai_disclosure_block_preflight(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    record(root, 1, "competition.rules_frozen", fresh_rules(ai_use_policy="disclose"), "freeze")
    record(root, 2, "competition.deliverable_recorded", {
        "deliverable_id": "bad", "kind": "paper", "status": "draft_complete", "ruleset_hash": "a" * 64,
        "ruleset_id": "nuedc-2026-v1", "citation_ids": ["invented"], "prior_art_citation_ids": ["invented"], "student_decision_ids": ["invented"], "raw_evidence_ids": ["invented"], "contribution_map": {"student": "unknown"}, "claim_evidence": {"innovation": ["invented"]},
        "anonymity_checked": False, "contains_identity": True,
    }, "bad")
    preflight = run_cli(root, "preflight", "--competition-id", "demo", "--deliverable-id", "bad")
    assert preflight["ok"] is False
    assert {"unknown_evidence", "anonymity_violation", "ai_use_disclosure_missing", "prior_art_missing", "measurement_evidence_missing", "student_decision_missing", "raw_evidence_missing"} <= set(preflight["blocking_reasons"])


def test_complete_draft_rejects_tool_only_claims_and_missing_student_traceability(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    record(root, 1, "competition.rules_frozen", fresh_rules(), "freeze")
    record(root, 2, "competition.citation_recorded", {
        "citation_id": "prior", "title": "前案", "url": "https://example.test/prior", "source_tier": "official",
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "purpose": "prior_art",
    }, "prior")
    record(root, 3, "competition.evidence_recorded", {"evidence_id": "tool-i", "kind": "innovation_experiment", "summary": "工具输出", "source": "tool", "verification_status": "unverified", "raw_artifact_hash": "c" * 64}, "tool-i")
    record(root, 4, "competition.evidence_recorded", {"evidence_id": "tool-m", "kind": "measurement", "summary": "工具输出", "source": "tool", "verification_status": "unverified"}, "tool-m")
    record(root, 5, "competition.ai_use_recorded", {"use_id": "ai", "tool": "LLM", "purpose": "draft", "disclosed": True, "student_reviewed": True}, "ai")
    record(root, 6, "competition.deliverable_recorded", {
        "deliverable_id": "bad-trace", "kind": "paper", "status": "draft_complete", "ruleset_hash": "a" * 64, "ruleset_id": "nuedc-2026-v1",
        "citation_ids": ["prior"], "prior_art_citation_ids": ["prior"], "student_decision_ids": ["tool-i"], "raw_evidence_ids": ["tool-m"], "contribution_map": {"student": "claimed"},
        "claim_evidence": {"innovation": ["tool-i"], "measurement": ["tool-m"]}, "anonymity_checked": True, "contains_identity": False,
    }, "bad-trace")
    gate = run_cli(root, "preflight", "--competition-id", "demo", "--deliverable-id", "bad-trace")
    assert {"innovation_evidence_missing", "measurement_evidence_missing", "student_decision_missing", "raw_evidence_missing"} <= set(gate["blocking_reasons"])


def test_ruleset_identity_idempotency_and_future_clock_are_fail_closed(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    mismatch = record(root, 1, "competition.rules_frozen", fresh_rules(edition="2025"), "wrong-edition", ok=False)
    assert mismatch["error"] == "competition_identity_mismatch"
    future = record(root, 1, "competition.rules_frozen", fresh_rules(retrieved_at=(datetime.now(timezone.utc) + timedelta(minutes=6)).isoformat()), "future", ok=False)
    assert future["error"] == "future_timestamp"
    record(root, 1, "competition.rules_frozen", fresh_rules(), "same")
    conflict = record(root, 2, "competition.citation_recorded", {"citation_id": "x", "title": "x", "url": "https://x", "source_tier": "official", "retrieved_at": datetime.now(timezone.utc).isoformat(), "purpose": "prior_art"}, "same", ok=False)
    assert conflict["error"] == "idempotency_conflict"


def test_tool_cannot_record_verified_hardware_measurement_or_innovation(tmp_path):
    root = tmp_path / "Competitions"
    initialize(root)
    rejected = record(root, 1, "competition.evidence_recorded", {"evidence_id": "tool-measure", "kind": "raw_measurement", "summary": "tool says measured", "source": "tool", "verification_status": "verified", "raw_artifact_hash": "a" * 64}, "tool-measure", ok=False)
    assert rejected["error"] == "tool_hardware_evidence_unverified"
