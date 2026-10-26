from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "stm32-ai-mentor"


def test_skill_progressively_loads_execution_and_eda_workflows():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "references/generation/execution-workflow.md" in skill
    assert "references/generation/eda-workflow.md" in skill
    assert "写好并烧录测试" in skill
    assert "普通课堂" in skill and "不得主动" in skill
    assert "主 agent" in skill.lower()
    assert "每次烧录" in skill


def test_project_config_cannot_define_or_auto_start_mcp_executables():
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert "mcp_servers" not in config
    source = (ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "command =" not in source
    assert "args =" not in source
    assert "cwd =" not in source
    assert set(config["agents"]) >= {
        "max_threads", "firmware_engineer", "hardware_engineer", "learning_assessor",
        "state_integrity", "competition_researcher", "red_team_reviewer",
    }


def test_guarded_runtime_installer_is_part_of_the_skill_not_the_auto_started_surface():
    installer = SKILL / "scripts" / "install_execution_runtime.py"
    source = installer.read_text(encoding="utf-8")
    assert installer.is_file()
    assert "verified-files.json" in source
    assert "permission policy" in source
    assert "tool lock" in source
    assert "install_execution_runtime.py" not in (
        ROOT / ".codex" / "config.toml"
    ).read_text(encoding="utf-8")


def test_guarded_runtime_refuses_tampered_installed_server(tmp_path):
    sys.path.insert(0, str(SKILL / "scripts"))
    from install_execution_runtime import install_runtime  # noqa: PLC0415
    from eda_lab_mcp.server import TOOL_NAMES as EDA_TOOLS  # noqa: PLC0415
    from stm32_lab_mcp.server import TOOL_NAMES as STM32_TOOLS  # noqa: PLC0415

    policy = tmp_path / "permissions.json"
    policy.write_text(json.dumps({
        "schema_version": 1,
        "workspace_roots": [str(ROOT)],
        "stm32_lab": {"allowed_tools": list(STM32_TOOLS), "board_profiles": {}},
        "eda_lab": {"allowed_tools": list(EDA_TOOLS)},
    }), encoding="utf-8")
    fake_tool = tmp_path / "tool.exe"
    fake_tool.write_bytes(b"fixture")
    executable = Path(sys.executable).resolve()
    tool_lock = tmp_path / "tools.json"
    tool_lock.write_text(json.dumps({
        "installed": {
            "python": {"version": "test", "path": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()},
            "cmake": {"version": "test", "path": str(fake_tool), "sha256": hashlib.sha256(fake_tool.read_bytes()).hexdigest()},
            "stm32_cube_programmer": {"version": "test", "path": str(fake_tool), "sha256": hashlib.sha256(fake_tool.read_bytes()).hexdigest()},
            "kicad_cli": {"version": "test", "path": str(fake_tool), "sha256": hashlib.sha256(fake_tool.read_bytes()).hexdigest()},
        }
    }), encoding="utf-8")
    runtime = tmp_path / "runtime"
    install_runtime(workspace=ROOT, runtime_root=runtime, policy=policy, tool_lock=tool_lock)
    launcher = runtime / "current" / "stm32_lab_server.py"
    clean = subprocess.run(
        [sys.executable, str(launcher)], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=10, check=False,
    )
    assert clean.returncode == 0

    installed_core = runtime / "current" / "stm32_lab_mcp" / "core.py"
    installed_core.write_text(installed_core.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    denied = subprocess.run(
        [sys.executable, str(launcher)], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=10, check=False,
    )
    assert denied.returncode != 0
    assert "integrity check failed" in (denied.stdout + denied.stderr)


def test_toolchain_lock_is_reproducible_and_does_not_replace_existing_ide():
    lock_path = SKILL / "references" / "generation" / "toolchain-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["installation_strategy"] == "side_by_side"
    assert lock["preserve_existing"]["STM32CubeIDE"] == "1.19.0"
    assert lock["tools"]["STM32CubeMX"]["version"] == "6.18.1"
    assert lock["tools"]["STM32CubeCLT"]["version"] == "1.22.0"
    assert lock["tools"]["STM32CubeProgrammer"]["version"] == "2.23.0"
    assert lock["tools"]["STM32CubeF1"]["version"] == "1.8.6"
    assert lock["tools"]["KiCad"]["version"].startswith("10.")
    assert lock["tools"]["KiCadPythonIPC"]["version"] == "0.7.1"
    assert lock["policy"]["automatic_uninstall"] is False
    assert lock["policy"]["accept_vendor_licenses_automatically"] is False


def test_readme_explains_real_execution_without_claiming_full_hardware_autonomy():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for term in (
        "stm32-lab-mcp",
        "eda-lab-mcp",
        "构建成功不等于功能通过",
        "单次确认",
        "KiCad",
        "Flux",
        "温湿度",
    ):
        assert term in readme
    assert "100% 一次成功" not in readme
