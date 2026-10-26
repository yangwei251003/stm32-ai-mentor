import json
from pathlib import Path
import jsonschema


ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references"


def test_competition_workflow_documents_independent_ledger_and_integrity_gates():
    text = (REF / "competition" / "competition-workflow.md").read_text(encoding="utf-8")
    for phrase in ("CompetitionIntake", "规则冻结", "7 天", "来源层级", "匿名", "AI", "reported_by_user", "回执", "competition_tool.py"):
        assert phrase in text
    assert "Competitions/<competition_id>" in text
    assert "不做跨账本双写" in text


def test_official_adapters_and_schemas_are_present_without_copying_rules():
    adapters = json.loads((REF / "competition" / "adapters.json").read_text(encoding="utf-8"))
    assert {"nuedc", "cpipc", "soc_china", "generic"} <= set(adapters["adapters"])
    assert adapters["adapters"]["nuedc"]["official_name"] == "全国大学生电子设计竞赛"
    assert adapters["adapters"]["cpipc"]["official_name"] == "中国研究生电子设计竞赛"
    assert adapters["adapters"]["soc_china"]["official_name"] == "全国大学生嵌入式芯片与系统设计竞赛"
    assert "完整规则原文" not in (REF / "competition" / "adapters.json").read_text(encoding="utf-8")
    for adapter in ("nuedc", "cpipc", "soc_china"):
        source = adapters["adapters"][adapter]["official_home"]
        assert source["url"].startswith("http")
        assert source["source_tier"] == "official"
        assert source["retrieved_at"] == "2026-08-21"
        assert adapters["adapters"][adapter]["official_award_cases"]["availability"] == "unavailable"

    schema = json.loads((REF / "schemas" / "competition.schema.json").read_text(encoding="utf-8"))
    assert {"CompetitionIntake", "RuleSet", "Citation", "AIUse", "Deliverable"} <= set(schema["$defs"])
    for name in ("competition-intake", "competition-ruleset", "competition-citation", "competition-ai-use", "competition-deliverable"):
        assert "$ref" in json.loads((REF / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert {"track", "team"} <= set(schema["$defs"]["CompetitionIntake"]["required"])
    assert {"competition_name", "edition", "track"} <= set(schema["$defs"]["RuleSet"]["required"])


def test_deliverable_schema_allows_minimal_draft_but_requires_traceability_for_complete_work():
    schema = json.loads((REF / "schemas" / "competition.schema.json").read_text(encoding="utf-8"))["$defs"]["Deliverable"]
    draft = {"deliverable_id": "d", "kind": "paper", "status": "draft", "ruleset_hash": "a" * 64}
    jsonschema.Draft202012Validator(schema).validate(draft)
    with __import__("pytest").raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate({**draft, "status": "draft_complete"})
    complete = {**draft, "status": "draft_complete", "ruleset_id": "r", "citation_ids": ["c"], "prior_art_citation_ids": ["p"], "student_decision_ids": ["d1"], "raw_evidence_ids": ["e1"], "contribution_map": {"student": "test"}, "claim_evidence": {"measurement": ["e1"]}, "anonymity_checked": True, "contains_identity": False}
    jsonschema.Draft202012Validator(schema).validate(complete)


def test_adapter_urls_are_bound_to_verified_sources_and_generic_has_none():
    adapters = json.loads((REF / "competition" / "adapters.json").read_text(encoding="utf-8"))["adapters"]
    assert adapters["nuedc"]["official_home"]["url"] == "https://nuedc.xjtu.edu.cn/"
    assert adapters["cpipc"]["official_home"]["url"] == "https://cpipc.acge.org.cn/cw/hp/6"
    assert adapters["soc_china"]["official_home"]["url"] == "https://www.socchina.net/home"
    assert "official_home" not in adapters["generic"]
