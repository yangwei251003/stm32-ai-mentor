from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "stm32-ai-mentor"


def test_repository_scaffold_and_user_directories_are_preserved():
    required = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / ".gitignore",
        SKILL / "SKILL.md",
        SKILL / "agents" / "openai.yaml",
        ROOT / ".codex" / "config.toml",
        ROOT / "Student_Profile",
        ROOT / "docs" / "research",
    ]
    assert all(path.exists() for path in required)
    assert (ROOT / ".playwright-mcp").is_dir()
    assert (ROOT / "%USERPROFILE%").is_dir()
    # Public release may be a Git checkout; original private-workspace rule does not apply.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "--profile-dir Student_Profile status" in readme
    assert "--profile-dir Student_Profile validate" in agents
    assert "--root Student_Profile" not in readme + agents


def test_skill_frontmatter_is_focused_and_routes_progressively():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match
    frontmatter = match.group(1)
    assert "name: stm32-ai-mentor" in frontmatter
    assert "description:" in frontmatter
    assert "$stm32-ai-mentor" not in frontmatter
    assert "Do not load the entire catalog" in text
    assert "scripts/state_tool.py" in text
    assert "4/5" in text
    assert "learning.*" in text


def test_openai_yaml_and_project_agent_models_are_declared():
    metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert 'default_prompt: "Use $stm32-ai-mentor' in metadata
    assert "allow_implicit_invocation: true" in metadata

    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert config["agents"]["max_threads"] == 6
    expected = {
        "firmware_engineer": ("gpt-5.6-sol", "high"),
        "hardware_engineer": ("gpt-5.6-terra", "high"),
        "learning_assessor": ("gpt-5.6-luna", "medium"),
        "state_integrity": ("gpt-5.6-sol", "high"),
        "competition_researcher": ("gpt-5.6-terra", "high"),
        "red_team_reviewer": ("gpt-5.5", "high"),
    }
    for name, (model, effort) in expected.items():
        agent = tomllib.loads((ROOT / ".codex" / "agents" / f"{name}.toml").read_text(encoding="utf-8"))
        assert agent["model"] == model
        assert agent["model_reasoning_effort"] == effort
        assert agent["sandbox_mode"] == "read-only"
        assert "Student_Profile" in agent["developer_instructions"]
        if name == "firmware_engineer":
            assert "blocked_by_missing_input" in agent["developer_instructions"]
            assert "clean rebuild" in agent["developer_instructions"]


def test_core_specs_roles_and_research_records_exist():
    core = [
        SKILL / "references" / "pedagogy" / "skill-specification.md",
        SKILL / "references" / "roles" / "mentor.md",
        SKILL / "references" / "roles" / "hardware-engineer.md",
        SKILL / "references" / "roles" / "firmware-engineer.md",
        SKILL / "references" / "roles" / "learning-assessor.md",
        SKILL / "references" / "curriculum" / "S0-S7_knowledge_graph.md",
        SKILL / "references" / "projects" / "catalog.json",
    ]
    assert all(path.exists() and path.stat().st_size > 200 for path in core)
    research = sorted((ROOT / "docs" / "research").glob("*.md"))
    assert len(research) >= 6
    combined = "\n".join(path.read_text(encoding="utf-8") for path in research)
    for term in ("STM32Cube", "Open edX", "Aider", "许可证", "V2", "V3"):
        assert term in combined


def test_classroom_contract_contains_all_fixed_gates():
    text = (SKILL / "references" / "pedagogy" / "classroom-contract.md").read_text(encoding="utf-8")
    for term in (
        "10–15 分钟", "必须记住", "五道准备度题", "4/5", "60–90 分钟",
        "兴趣导入", "必要理论", "分阶段动手", "验收与迁移",
        "必做", "生活应用", "选做挑战", "复盘", "30%", "40%", "20%", "10%",
    ):
        assert term in text


def test_scope_and_safety_invariants_are_documented():
    facts = (SKILL / "references" / "pedagogy" / "stm32-facts-and-safety.md").read_text(encoding="utf-8")
    for term in (
        "64 KB", "20 KB", "72 MHz", "无 FPU", "无 DAC", "Blue Pill", "第三方",
        "市电", "大功率电机", "锂电池", "V5", "CAN", "USB", "低功耗",
    ):
        assert term in facts
    extensions = (SKILL / "references" / "pedagogy" / "extensions.md").read_text(encoding="utf-8")
    assert "stm32-project-builder" in extensions
    assert "stm32-competition-mentor" in extensions
    assert "V1 仅写 `learning.*`" in extensions


def test_truncated_build_logs_remain_hypotheses_until_more_evidence():
    role = (SKILL / "references" / "roles" / "firmware-engineer.md").read_text(encoding="utf-8")
    for term in ("blocked_by_missing_input", "第一条未截断", "hypothesis", "root cause", "clean build", "V2"):
        assert term in role


def test_zero_hardware_procurement_flow_is_discoverable_and_complete():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    procurement_path = SKILL / "references" / "generation" / "procurement-workflow.md"
    assert procurement_path.name in skill
    procurement = procurement_path.read_text(encoding="utf-8")
    for term in (
        "采购前候选护照", "到货后实物护照", "2–3 个", "Recommended",
        "ST-Link", "USB-UART", "万用表", "面包板", "结构件", "建议备件",
        "不能承诺库存", "不能支持确定接线", "不能支持确定接线、PCB 发布、烧录",
    ):
        assert term in procurement
