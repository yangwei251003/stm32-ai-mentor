import json
from collections import Counter
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "projects" / "catalog.json"
REQUIRED = {
    "life_problem", "expected_result", "knowledge", "prerequisites",
    "prestudy_focus", "core_components", "cost_band", "estimated_time",
    "difficulty", "safety_level", "safety_gate", "observable_acceptance",
    "applicable_chips", "verification_level", "validation_note", "references",
}

def load():
    with CATALOG.open(encoding="utf-8") as f:
        return json.load(f)

def test_catalog_has_exact_distribution_and_stable_ids():
    data = load()
    projects = data["projects"]
    assert len(projects) == 100
    assert len({p["id"] for p in projects}) == 100
    counts = Counter(p["category"] for p in projects)
    assert counts == Counter({
        "smart_home": 20, "environment": 15, "measurement": 15,
        "mobility": 15, "industrial": 15, "energy_safety": 10, "innovation": 10,
    })
    assert sum(p["mode"] == "detailed" for p in projects) == 30
    assert sum(p["mode"] == "catalog-only" for p in projects) == 70

def test_every_entry_has_landing_and_safety_contract():
    data = load()
    for project in data["projects"]:
        missing = REQUIRED - project.keys()
        assert not missing, (project["id"], missing)
        for key in ("life_problem", "expected_result", "safety_gate", "validation_note"):
            assert project[key].strip()
        assert "STM32F103C8Tx" in project["applicable_chips"]
        assert project["mode"] in {"detailed", "catalog-only"}
        if project["mode"] == "catalog-only":
            assert project["status"] == "catalog-only"
            assert "不得" in project["validation_note"] or "未补齐" in project["validation_note"]

def test_detailed_projects_match_v1_mainline():
    expected = [
        "device_status_light", "doorbell_button_nightlight",
        "traffic_light_state_machine", "breathing_nightlight_buzzer",
        "smart_appliance_uart_console", "automatic_desk_lamp",
        "adc_dma_data_logger", "desktop_temp_humidity_station",
        "spi_flash_settings", "rtc_low_power_logger",
        "ultrasonic_parking_servo", "smart_fan_pid", "can_vehicle_node",
        "usb_cdc_sensor_meter", "freertos_environment_panel",
    ]
    data = load()
    assert [p["id"] for p in data["projects"][:15]] == expected
    assert all(p["mode"] == "detailed" for p in data["projects"][:15])
    assert all(p["status"] == "ready-for-class" for p in data["projects"][:15])


def test_v2_detailed_projects_are_backed_by_a_pattern_file():
    data = load()
    library = CATALOG.parent / "v2-detailed"
    detailed = [p for p in data["projects"] if p["mode"] == "detailed"]
    assert len(detailed) == 30
    assert all(p["status"] == "ready-for-class" for p in detailed[:15])
    assert all(p["status"] == "v2-pattern-ready" for p in detailed[15:])
    assert all((library / f"{p['id']}.md").is_file() for p in detailed)


def test_catalog_has_no_generic_practice_project_landing_copy():
    for project in load()["projects"]:
        assert "实践项目" not in project["title"]
        assert "实践项目" not in project["life_problem"]
        assert "实践项目" not in project["expected_result"]

def test_prerequisites_are_references_or_explicit_none():
    data = load()
    ids = {p["id"] for p in data["projects"]}
    curriculum_ids = {
        "S0-gpio-basics", "S1-digital-io", "S2-time-state", "S3-analog-acquisition",
        "S4-sensor-storage", "S5-motion-control", "S6-communications", "S7-system-integration",
    }
    for project in data["projects"]:
        for ref in project["prerequisites"]:
            assert ref == "无" or ref in curriculum_ids or ref in ids, (project["id"], ref)


def test_every_declared_reference_resolves_inside_skill_references():
    data = load()
    references_root = CATALOG.parent.parent
    for project in data["projects"]:
        for ref in project["references"]:
            target = references_root / ref
            assert target.is_file(), (project["id"], ref)


def test_every_project_matches_machine_readable_schema():
    data = load()
    schema_path = CATALOG.parent.parent / "schemas" / "project.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for project in data["projects"]:
        errors = sorted(validator.iter_errors(project), key=lambda item: list(item.path))
        assert not errors, (project["id"], [error.message for error in errors])
