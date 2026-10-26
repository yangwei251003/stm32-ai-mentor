import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EDA_ROOT = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts"
sys.path.insert(0, str(EDA_ROOT))

from eda_lab_mcp import EdaLabError, EdaLabMcp  # noqa: E402
from eda_lab_mcp.server import TOOL_NAMES, lab_from_environment  # noqa: E402


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, *, cwd, timeout):
        self.calls.append((command, cwd, timeout))
        if "--output" in command:
            output = Path(command[command.index("--output") + 1])
            if "gerbers" in command or "drill" in command:
                output.mkdir(parents=True, exist_ok=True)
                (output / ("mock.gbr" if "gerbers" in command else "mock.drl")).write_text(
                    "fixture\n", encoding="utf-8",
                )
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("fixture\n", encoding="utf-8")
        return {"returncode": 0, "stdout": "checked", "stderr": ""}


@pytest.fixture()
def design(tmp_path):
    root = tmp_path / "workspace" / "sensor-carrier"
    root.mkdir(parents=True)
    (root / "sensor-carrier.kicad_sch").write_text("(kicad_sch (version 20231120))\n", encoding="utf-8")
    (root / "sensor-carrier.kicad_pcb").write_text("(kicad_pcb (version 20240108))\n", encoding="utf-8")
    return root


@pytest.fixture()
def lab(design):
    return EdaLabMcp(
        workspace_roots=[design.parent], kicad_cli="fake-kicad-cli", runner=FakeRunner(),
        ipc_probe=lambda: {"binding_available": True, "binding_version": "test", "connected": False},
    )


def test_exact_narrow_tool_names_are_exposed(lab):
    assert set(lab.tools) == {
        "design_inspect", "design_snapshot", "schematic_apply_transaction", "pcb_apply_transaction",
        "erc_run", "drc_run", "parity_run", "render_run", "release_export",
    }
    assert set(TOOL_NAMES) == set(lab.tools)


def test_server_environment_is_fail_closed_and_uses_only_explicit_paths(design):
    with pytest.raises(EdaLabError, match="workspace"):
        lab_from_environment({})
    configured = lab_from_environment({
        "STM32_AI_MENTOR_EDA_WORKSPACES": str(design.parent),
        "KICAD_CLI": "fake-kicad-cli",
        "SHELL": "unsafe-and-ignored",
    })
    assert configured.workspace_roots == (design.parent.resolve(),)
    assert configured.kicad_cli == "fake-kicad-cli"


def test_external_policy_is_authoritative_over_project_workspace_environment(design, tmp_path):
    policy = tmp_path / "permissions.json"
    policy.write_text(json.dumps({
        "schema_version": 1,
        "workspace_roots": [str(design.parent)],
        "eda_lab": {"allowed_tools": list(TOOL_NAMES)},
    }), encoding="utf-8")
    configured = lab_from_environment({
        "STM32_AI_MENTOR_POLICY": str(policy),
        "STM32_AI_MENTOR_EDA_WORKSPACES": str(tmp_path / "must-not-win"),
        "KICAD_CLI": "fake-kicad-cli",
    })
    assert configured.workspace_roots == (design.parent.resolve(),)

    broken = json.loads(policy.read_text(encoding="utf-8"))
    broken["eda_lab"]["allowed_tools"].append("raw_shell")
    policy.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(EdaLabError, match="白名单"):
        lab_from_environment({"STM32_AI_MENTOR_POLICY": str(policy)})


def test_inspect_and_snapshot_are_limited_to_whitelisted_workspace(lab, design, tmp_path):
    inspected = lab.design_inspect({"design_dir": str(design)})
    assert inspected["ok"] is True
    assert inspected["files"]["schematic"]["name"] == "sensor-carrier.kicad_sch"

    receipt = lab.design_snapshot({"design_dir": str(design), "reason": "before wiring"})
    snapshot = Path(receipt["snapshot_path"])
    assert snapshot.is_file()
    assert receipt["hashes"]["sensor-carrier.kicad_pcb"] == hashlib.sha256(
        (design / "sensor-carrier.kicad_pcb").read_bytes()
    ).hexdigest()
    assert Path(receipt["backups"]["sensor-carrier.kicad_sch"]).read_bytes() == (
        design / "sensor-carrier.kicad_sch"
    ).read_bytes()

    with pytest.raises(EdaLabError, match="workspace"):
        lab.design_inspect({"design_dir": str(tmp_path)})


def test_transaction_only_replaces_design_file_and_records_before_after(lab, design):
    before = (design / "sensor-carrier.kicad_sch").read_bytes()
    receipt = lab.schematic_apply_transaction({
        "design_dir": str(design),
        "content": "(kicad_sch (version 20231120) (generator stm32-ai-mentor))\n",
        "reason": "add SHT3x connector",
    })
    assert receipt["ok"] is True
    assert receipt["before_hash"] == hashlib.sha256(before).hexdigest()
    assert receipt["after_hash"] == hashlib.sha256((design / "sensor-carrier.kicad_sch").read_bytes()).hexdigest()
    assert Path(receipt["snapshot_path"]).is_file()
    assert receipt["readback_match"] is True
    assert receipt["transaction_mode"] == "offline_atomic_file_replace"
    assert receipt["ipc_used"] is False

    with pytest.raises(EdaLabError, match="content"):
        lab.schematic_apply_transaction({"design_dir": str(design), "content": "not-kicad", "reason": "bad"})
    assert not (design / "escape.txt").exists()


def test_offline_transaction_stops_when_a_kicad_gui_ipc_session_is_active(design):
    guarded = EdaLabMcp(
        workspace_roots=[design.parent], kicad_cli="fake", runner=FakeRunner(),
        ipc_probe=lambda: {"binding_available": True, "binding_version": "0.7.1", "connected": True},
    )
    with pytest.raises(EdaLabError) as active:
        guarded.pcb_apply_transaction({
            "design_dir": str(design),
            "content": "(kicad_pcb (version 20240108) (generator stm32-ai-mentor))\n",
            "reason": "must not race the GUI",
        })
    assert active.value.code == "kicad_gui_active"


def test_cli_actions_are_fixed_argument_lists_and_release_has_complete_manifest(lab, design):
    erc = lab.erc_run({"design_dir": str(design)})
    drc = lab.drc_run({"design_dir": str(design)})
    parity = lab.parity_run({"design_dir": str(design)})
    render = lab.render_run({"design_dir": str(design)})
    release = lab.release_export({"design_dir": str(design), "release_id": "r1"})

    assert all(isinstance(part, str) for call in lab.runner.calls for part in call[0])
    assert erc["command"][1:3] == ["sch", "erc"]
    assert "--exit-code-violations" in erc["command"]
    assert drc["command"][1:3] == ["pcb", "drc"]
    assert "--exit-code-violations" in drc["command"]
    assert parity["command"][1:4] == ["pcb", "drc", "--schematic-parity"]
    assert "--exit-code-violations" in parity["command"]
    assert render["command"][1:3] == ["pcb", "render"]
    assert set(erc["tool_receipt"]) == {
        "receipt_id", "tool", "exit_code", "log_hash", "diagnostic_class",
        "tool_version", "timestamp", "artifact_hashes",
    }
    assert erc["tool_receipt"]["artifact_hashes"]
    assert set(release["manifest"]["outputs"]) == {"bom", "gerber", "drill", "pnp", "step", "render"}
    assert release["manifest"]["cloud_policy"] == "Flux is non-authoritative; local KiCad remains the release source."
    assert release["manifest"]["checks"]["erc"]["ok"] is True
    assert release["manifest"]["checks"]["drc"]["ok"] is True
    assert release["manifest"]["checks"]["parity"]["ok"] is True
    assert release["manifest"]["artifact_hashes"]
    assert release["manifest"]["exported_from_snapshot"] is True
    release_inputs = [Path(call[0][-1]) for call in lab.runner.calls if "release_export" not in call[0][0]]
    assert all(path != design / path.name for path in release_inputs[-9:])
    assert release["manifest"]["release_status"] == "automation_checked_draft"
    assert release["manifest"]["unresolved_items"]
    assert not any("shell" in " ".join(call[0]).lower() for call in lab.runner.calls)


def test_release_refuses_success_when_cli_reports_zero_but_artifacts_are_missing(design):
    def lying_runner(command, *, cwd, timeout):
        return {"returncode": 0, "stdout": "claimed success", "stderr": ""}

    untrusted = EdaLabMcp(
        workspace_roots=[design.parent], kicad_cli="fake-kicad-cli", runner=lying_runner,
    )
    with pytest.raises(EdaLabError, match="产物"):
        untrusted.release_export({"design_dir": str(design), "release_id": "r1"})


def test_missing_kicad_fails_closed_without_running(lab, design):
    lab.kicad_cli = None
    with pytest.raises(EdaLabError, match="KiCad"):
        lab.erc_run({"design_dir": str(design)})
    assert lab.runner.calls == []


def test_release_id_and_content_are_not_path_or_shell_injection(lab, design):
    with pytest.raises(EdaLabError, match="release_id"):
        lab.release_export({"design_dir": str(design), "release_id": "../bad"})
    with pytest.raises(EdaLabError, match="payload"):
        lab.erc_run({"design_dir": str(design), "arguments": ["; rm -rf"]})


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink support unavailable")
def test_metadata_reparse_point_cannot_escape_workspace(design, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    metadata = design / ".stm32-ai-mentor"
    try:
        metadata.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("current Windows account cannot create a directory symlink")
    guarded = EdaLabMcp(workspace_roots=[design.parent], kicad_cli="fake", runner=FakeRunner())

    with pytest.raises(EdaLabError, match="重解析|链接|workspace"):
        guarded.design_snapshot({"design_dir": str(design), "reason": "must stay inside"})
    assert list(outside.iterdir()) == []


def test_kicad_timeout_and_runner_crash_are_structured_failures(design):
    def timed_out(_command, *, cwd, timeout):
        raise subprocess.TimeoutExpired("kicad-cli", timeout)

    timed = EdaLabMcp(workspace_roots=[design.parent], kicad_cli="fake", runner=timed_out)
    with pytest.raises(EdaLabError) as timeout_error:
        timed.erc_run({"design_dir": str(design)})
    assert timeout_error.value.code == "kicad_timeout"

    def crashed(_command, *, cwd, timeout):
        raise OSError("process vanished")

    broken = EdaLabMcp(workspace_roots=[design.parent], kicad_cli="fake", runner=crashed)
    with pytest.raises(EdaLabError) as crash_error:
        broken.drc_run({"design_dir": str(design)})
    assert crash_error.value.code == "kicad_process_failed"

    def runtime_bug(_command, *, cwd, timeout):
        raise RuntimeError("adapter bug")

    failed = EdaLabMcp(workspace_roots=[design.parent], kicad_cli="fake", runner=runtime_bug)
    with pytest.raises(EdaLabError) as runtime_error:
        failed.parity_run({"design_dir": str(design)})
    assert runtime_error.value.code == "kicad_runner_failed"


def test_release_rejects_sources_changed_during_export(design):
    runner = FakeRunner()
    original_call = runner.__call__

    def mutating_runner(command, *, cwd, timeout):
        result = original_call(command, cwd=cwd, timeout=timeout)
        if "gerbers" in command:
            schematic = design / "sensor-carrier.kicad_sch"
            schematic.write_text(schematic.read_text(encoding="utf-8") + "\n; changed\n", encoding="utf-8")
        return result

    lab = EdaLabMcp(workspace_roots=[design.parent], kicad_cli="fake", runner=mutating_runner)
    with pytest.raises(EdaLabError) as changed:
        lab.release_export({"design_dir": str(design), "release_id": "r1"})
    assert changed.value.code == "release_source_changed"
