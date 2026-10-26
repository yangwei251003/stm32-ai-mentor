from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "stm32-ai-mentor"


def test_single_entry_routes_to_dormant_sidecars_without_extra_public_skills():
    metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "allow_implicit_invocation: true" in metadata
    assert "intent_router.py" in skill_text
    assert "project-workflow.md" in skill_text
    assert "competition-workflow.md" in skill_text
    assert not (ROOT / ".agents" / "skills" / "stm32-project-builder").exists()
    assert not (ROOT / ".agents" / "skills" / "stm32-competition-mentor").exists()


def test_specialist_agent_configuration_matches_the_approved_model_split():
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
    expected = {
        "firmware_engineer": ("gpt-5.6-sol", "high"),
        "hardware_engineer": ("gpt-5.6-terra", "high"),
        "learning_assessor": ("gpt-5.6-luna", "medium"),
        "state_integrity": ("gpt-5.6-sol", "high"),
        "competition_researcher": ("gpt-5.6-terra", "high"),
        "red_team_reviewer": ("gpt-5.5", "high"),
    }
    assert config["agents"]["max_threads"] >= 4
    for name, (model, effort) in expected.items():
        assert name in config["agents"]
        agent = tomllib.loads((ROOT / ".codex" / "agents" / f"{name}.toml").read_text(encoding="utf-8"))
        assert agent["model"] == model
        assert agent["model_reasoning_effort"] == effort
        assert agent["sandbox_mode"] == "read-only"
        assert "Student_Profile" in agent["developer_instructions"]


def test_v2_v3_sidecars_are_documented_as_enabled_and_independently_recoverable():
    extensions = (SKILL / "references" / "pedagogy" / "extensions.md").read_text(encoding="utf-8")
    assert "尚未启用" not in extensions
    assert "Projects/<project_id>" in extensions
    assert "Competitions/<competition_id>" in extensions
    assert "不做跨账本双写" in extensions
    assert "每次烧录" in extensions
    assert "7 天" in extensions


def test_workspace_instructions_expose_sidecar_preflight_without_marketing_in_class():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "project_tool.py" in readme
    assert "competition_tool.py" in readme
    assert "V3 > V2 > V1" in agents
    assert "Projects/<project_id>" in agents
    assert "Competitions/<competition_id>" in agents
    assert "不得主动" in agents
