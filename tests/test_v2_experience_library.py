"""Semantic and drift guardrails for the V2 project-pattern library."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROJECT_REFS = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "projects"
CATALOG = PROJECT_REFS / "catalog.json"
LIBRARY = PROJECT_REFS / "v2-detailed"
MANIFEST = LIBRARY / "patterns.json"
RENDERER = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts" / "render_v2_patterns.py"

FIXED_V2_IDS = {
    "smart_home-001", "environment-016", "environment-017", "measurement-029",
    "mobility-041", "mobility-042", "mobility-043", "industrial-054", "industrial-055",
    "energy_safety-066", "energy_safety-067", "energy_safety-068", "innovation-076",
    "innovation-077", "innovation-078",
}
FIXED_TITLES = {
    "smart_home-001": "门窗状态与离家提醒", "environment-016": "土壤湿度自动灌溉",
    "environment-017": "空气质量与通风", "measurement-029": "低压直流电压电流功率记录",
    "mobility-041": "循迹测速智能车", "mobility-042": "超声避障配送车",
    "mobility-043": "舵机机械臂分拣", "industrial-054": "Modbus RTU",
    "industrial-055": "RS485多节点", "energy_safety-066": "低压直流用电计量",
    "energy_safety-067": "低压掉电提醒", "energy_safety-068": "低压过流过压告警",
    "innovation-076": "智能温室", "innovation-077": "模块化环境巡检",
    "innovation-078": "多传感器智能车",
}
REQUIRED_SECTIONS = {
    "需求基线", "方案与 ADR", "BOM 与替代", "可覆写接线表", "CubeMX", "资源预算",
    "可构建增量契约", "测试与故障树", "回滚", "安全门", "C0", "C1", "C2", "C3", "C4", "发布清单",
}

# Hand-checked from ST DS5319 Rev 20, Table 5, for STM32F103C8Tx LQFP48.
# The fixture is intentionally independent from the renderer implementation.
LEGAL_PIN_AF = {
    "ADC1": {
        ("PA0", "ADC1_IN0", "none"), ("PA1", "ADC1_IN1", "none"),
        ("PA2", "ADC1_IN2", "none"), ("PA3", "ADC1_IN3", "none"),
        ("PA4", "ADC1_IN4", "none"), ("PA5", "ADC1_IN5", "none"),
        ("PA6", "ADC1_IN6", "none"), ("PA7", "ADC1_IN7", "none"),
        ("PB0", "ADC1_IN8", "none"), ("PB1", "ADC1_IN9", "none"),
    },
    "ADC1_IN0": {("PA0", "ADC1_IN0", "none")},
    "ADC1_IN1": {("PA1", "ADC1_IN1", "none")},
    "ADC1_IN2": {("PA2", "ADC1_IN2", "none")},
    "ADC1_IN3": {("PA3", "ADC1_IN3", "none")},
    "ADC1_IN4": {("PA4", "ADC1_IN4", "none")},
    "ADC1_IN5": {("PA5", "ADC1_IN5", "none")},
    "ADC1_IN6": {("PA6", "ADC1_IN6", "none")},
    "ADC1_IN7": {("PA7", "ADC1_IN7", "none")},
    "ADC1_IN8": {("PB0", "ADC1_IN8", "none")},
    "ADC1_IN9": {("PB1", "ADC1_IN9", "none")},
    "USART1_TX": {
        ("PA9", "USART1_TX", "none"),
        ("PB6", "USART1_TX", "AFIO_MAPR_USART1_REMAP=1"),
    },
    "USART1_RX": {
        ("PA10", "USART1_RX", "none"),
        ("PB7", "USART1_RX", "AFIO_MAPR_USART1_REMAP=1"),
    },
    "I2C1_SCL": {
        ("PB6", "I2C1_SCL", "none"),
        ("PB8", "I2C1_SCL", "AFIO_MAPR_I2C1_REMAP=1"),
    },
    "I2C1_SDA": {
        ("PB7", "I2C1_SDA", "none"),
        ("PB9", "I2C1_SDA", "AFIO_MAPR_I2C1_REMAP=1"),
    },
    "SPI1_NSS": {
        ("PA4", "SPI1_NSS", "none"),
        ("PA15", "SPI1_NSS", "AFIO_MAPR_SPI1_REMAP=1; JTAG disabled, SWD kept"),
    },
    "SPI1_SCK": {
        ("PA5", "SPI1_SCK", "none"),
        ("PB3", "SPI1_SCK", "AFIO_MAPR_SPI1_REMAP=1; JTAG disabled, SWD kept"),
    },
    "SPI1_MISO": {
        ("PA6", "SPI1_MISO", "none"),
        ("PB4", "SPI1_MISO", "AFIO_MAPR_SPI1_REMAP=1; JTAG disabled, SWD kept"),
    },
    "SPI1_MOSI": {
        ("PA7", "SPI1_MOSI", "none"),
        ("PB5", "SPI1_MOSI", "AFIO_MAPR_SPI1_REMAP=1; JTAG disabled, SWD kept"),
    },
    "TIM2_CH1": {
        ("PA0", "TIM2_CH1", "none"),
        ("PA15", "TIM2_CH1", "AFIO_MAPR_TIM2_REMAP=partial1/full; JTAG disabled, SWD kept"),
    },
    "TIM2_CH2": {
        ("PA1", "TIM2_CH2", "none/partial2"),
        ("PB3", "TIM2_CH2", "AFIO_MAPR_TIM2_REMAP=partial1/full; JTAG disabled, SWD kept"),
    },
    "TIM3_CH1": {
        ("PA6", "TIM3_CH1", "none"),
        ("PB4", "TIM3_CH1", "AFIO_MAPR_TIM3_REMAP=partial; JTAG disabled, SWD kept"),
    },
    "TIM3_CH2": {
        ("PA7", "TIM3_CH2", "none"),
        ("PB5", "TIM3_CH2", "AFIO_MAPR_TIM3_REMAP=partial"),
    },
    "TIM3_CH3": {("PB0", "TIM3_CH3", "none/partial")},
    "TIM3_CH4": {("PB1", "TIM3_CH4", "none/partial")},
    "CAN_RX": {
        ("PA11", "CAN_RX", "AFIO_MAPR_CAN_REMAP=00"),
        ("PB8", "CAN_RX", "AFIO_MAPR_CAN_REMAP=10"),
        ("PD0", "CAN_RX", "AFIO_MAPR_CAN_REMAP=11; HSE unavailable"),
    },
    "CAN_TX": {
        ("PA12", "CAN_TX", "AFIO_MAPR_CAN_REMAP=00"),
        ("PB9", "CAN_TX", "AFIO_MAPR_CAN_REMAP=10"),
        ("PD1", "CAN_TX", "AFIO_MAPR_CAN_REMAP=11; HSE unavailable"),
    },
    "USB_DM": {("PA11", "USB_DM", "fixed")},
    "USB_DP": {("PA12", "USB_DP", "fixed")},
}

PROJECT_SIGNAL_MINIMUMS = {
    "industrial-054": {"RS485_TX", "RS485_RX", "RS485_DE", "RS485_RE", "RS485_A", "RS485_B"},
    "industrial-055": {"NODE_TX", "NODE_RX", "NODE_DE", "NODE_RE", "BUS_A", "BUS_B"},
    "measurement-029": {
        "INA219_SCL", "INA219_SDA", "INA219_VCC", "INA219_GND", "SHUNT_IN_PLUS", "SHUNT_IN_MINUS",
    },
    "mobility-041": {
        "LINE_L", "LINE_M", "LINE_R", "ENC_L", "ENC_R", "MOTOR_L_PWM", "MOTOR_R_PWM",
        "MOTOR_AIN1", "MOTOR_AIN2", "MOTOR_BIN1", "MOTOR_BIN2", "MOTOR_STBY", "TB6612_VCC",
        "MOTOR_VM", "MOTOR_GND", "MOTOR_AO1", "MOTOR_AO2", "MOTOR_BO1", "MOTOR_BO2",
        "LINE_VCC", "LINE_GND", "ENCODER_VCC", "ENCODER_GND",
    },
    "mobility-042": {
        "ULTRA_TRIG", "ULTRA_ECHO", "MOTOR_L_PWM", "MOTOR_R_PWM", "MOTOR_AIN1", "MOTOR_AIN2",
        "MOTOR_BIN1", "MOTOR_BIN2", "MOTOR_STBY", "TB6612_VCC", "MOTOR_VM", "MOTOR_GND",
        "MOTOR_AO1", "MOTOR_AO2", "MOTOR_BO1", "MOTOR_BO2", "ULTRA_VCC", "ULTRA_GND",
    },
    "mobility-043": {
        "SERVO_1_PWM", "SERVO_2_PWM", "CLASSIFY_IN", "LIMIT_HOME", "LIMIT_END", "SERVO_5V",
        "SERVO_GND", "CLASSIFIER_VCC", "CLASSIFIER_GND",
    },
    "innovation-078": {
        "LINE_L", "LINE_M", "LINE_R", "ULTRA_TRIG", "ULTRA_ECHO", "LIGHT_ADC", "MOTOR_L_PWM",
        "MOTOR_R_PWM", "MOTOR_AIN1", "MOTOR_AIN2", "MOTOR_BIN1", "MOTOR_BIN2", "MOTOR_STBY",
        "TB6612_VCC", "MOTOR_VM", "MOTOR_GND", "MOTOR_AO1", "MOTOR_AO2", "MOTOR_BO1", "MOTOR_BO2",
        "LINE_VCC", "LINE_GND", "ULTRA_VCC", "ULTRA_GND", "LIGHT_VCC", "LIGHT_GND",
    },
}
SIMPLE_PROJECT_FIXTURES = {
    "device_status_light": {"STATUS_LED", "USER_BUTTON", "CONSOLE_TX", "CONSOLE_RX"},
    "traffic_light_state_machine": {"RED_LED", "YELLOW_LED", "GREEN_LED", "MODE_BUTTON"},
    "automatic_desk_lamp": {"LIGHT_ADC", "LAMP_PWM", "MANUAL_BUTTON"},
    "spi_flash_settings": {"FLASH_NSS", "FLASH_SCK", "FLASH_MISO", "FLASH_MOSI"},
    "can_vehicle_node": {"CAN_RX", "CAN_TX", "CAN_H", "CAN_L"},
    "smart_home-001": {"DOOR_REED", "AWAY_BUTTON", "REMINDER_BUZZER", "STATUS_LED"},
    "energy_safety-067": {"SUPPLY_ADC", "POWER_GOOD", "HOLDUP_ENABLE", "ALARM_BUZZER"},
}


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def load_renderer():
    spec = importlib.util.spec_from_file_location("render_v2_patterns", RENDERER)
    assert spec and spec.loader, RENDERER
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pattern_map(data: dict | None = None) -> dict[str, dict]:
    data = data or load_manifest()
    return {item["project_id"]: item for item in data["patterns"]}


def all_signals(data: dict | None = None):
    for pattern in (data or load_manifest())["patterns"]:
        for signal in pattern["signals"]:
            yield pattern, signal


def test_catalog_counts_ids_and_deep_files_remain_stable():
    """Dropping a fixed project or changing the 100/30/70 split is a release break."""
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["projects"]
    detailed = [project for project in catalog if project["mode"] == "detailed"]
    catalog_only = [project for project in catalog if project["mode"] == "catalog-only"]
    assert (len(catalog), len(detailed), len(catalog_only)) == (100, 30, 70)
    assert {project["id"] for project in detailed[15:]} == FIXED_V2_IDS
    assert {project["id"]: project["title"] for project in detailed[15:]} == FIXED_TITLES
    assert {path.stem for path in LIBRARY.glob("*.md")} == {project["id"] for project in detailed}


def test_signals_have_typed_endpoints_and_overridable_candidates():
    """A/B, VCC/GND, or generic three-row placeholders must not look like MCU GPIO."""
    data = load_manifest()
    assert data["schema_version"] == 3
    assert len(data["patterns"]) == 30
    allowed_types = {"mcu_signal", "module_signal", "bus_terminal", "power_terminal"}
    for pattern, signal in all_signals(data):
        assert signal["endpoint_type"] in allowed_types
        assert signal["direction"] and signal["electrical"] and signal["peripheral"]
        assert signal["component_ref"] and signal["power_domain_ref"]
        assert not signal["function"].endswith(("_INPUT", "_OUTPUT", "_DEBUG")), pattern["project_id"]
        if signal["endpoint_type"] == "mcu_signal":
            assert signal["candidate_pins"], (pattern["project_id"], signal["function"])
            assert "unknown" not in signal
            for candidate in signal["candidate_pins"]:
                assert set(candidate) == {"pin", "af", "remap", "conditions"}
                assert candidate["conditions"]
        else:
            assert signal.get("unknown") is True
            assert signal.get("confirmation_method")
            assert "candidate_pins" not in signal


def test_terminal_boundaries_are_not_disguised_as_gpio():
    """Transceiver bus and module power terminals must stay outside the MCU pin namespace."""
    patterns = pattern_map()
    expected = {
        "industrial-054": {"RS485_A": "bus_terminal", "RS485_B": "bus_terminal", "RS485_VCC": "power_terminal", "RS485_GND": "power_terminal"},
        "industrial-055": {"BUS_A": "bus_terminal", "BUS_B": "bus_terminal", "NODE_VCC": "power_terminal", "NODE_GND": "power_terminal"},
        "measurement-029": {"INA219_VCC": "power_terminal", "INA219_GND": "power_terminal", "SHUNT_IN_PLUS": "bus_terminal", "SHUNT_IN_MINUS": "bus_terminal"},
        "mobility-041": {"TB6612_VCC": "power_terminal", "MOTOR_AO1": "module_signal", "MOTOR_AO2": "module_signal", "MOTOR_BO1": "module_signal", "MOTOR_BO2": "module_signal"},
        "innovation-078": {"TB6612_VCC": "power_terminal", "ULTRA_VCC": "power_terminal", "LIGHT_VCC": "power_terminal"},
    }
    for project_id, fixture in expected.items():
        actual = {signal["function"]: signal["endpoint_type"] for signal in patterns[project_id]["signals"]}
        assert {name: actual[name] for name in fixture} == fixture


def test_candidate_pin_peripheral_pairs_match_f103c8_lqfp48_fixture():
    """An invalid pin/AF pair cannot be made acceptable by a conditional note."""
    for pattern, signal in all_signals():
        if signal["endpoint_type"] != "mcu_signal":
            continue
        peripheral = signal["peripheral"]
        if peripheral in {"GPIO", "GPIO_EXTI"}:
            for candidate in signal["candidate_pins"]:
                assert candidate["af"] in {"GPIO_input", "GPIO_output"}
                assert candidate["remap"] == "none"
            continue
        assert peripheral in LEGAL_PIN_AF, (pattern["project_id"], signal["function"], peripheral)
        for candidate in signal["candidate_pins"]:
            key = (candidate["pin"], candidate["af"], candidate["remap"])
            assert key in LEGAL_PIN_AF[peripheral], (pattern["project_id"], signal["function"], key)


def test_i2c_is_open_drain_bidirectional_and_swd_is_preserved():
    """I2C push-pull rows or reuse of PA13/PA14 would produce unsafe wiring guidance."""
    for pattern, signal in all_signals():
        if signal["peripheral"] in {"I2C1_SCL", "I2C1_SDA"}:
            assert signal["direction"] == "bidirectional"
            assert "open-drain" in signal["electrical"]
            assert "pull-up" in signal["electrical"]
        for candidate in signal.get("candidate_pins", []):
            assert candidate["pin"] not in {"PA13", "PA14"}, (pattern["project_id"], signal["function"])


def test_each_pattern_has_a_collision_free_candidate_pin_assignment():
    """A set of individually legal rows is still unusable if no distinct-pin assignment exists."""
    for pattern in load_manifest()["patterns"]:
        signals = [signal for signal in pattern["signals"] if signal["endpoint_type"] == "mcu_signal"]
        pin_to_signal: dict[str, int] = {}

        def assign(signal_index: int, visited: set[str]) -> bool:
            for candidate in signals[signal_index]["candidate_pins"]:
                pin = candidate["pin"]
                if pin in visited:
                    continue
                visited.add(pin)
                if pin not in pin_to_signal or assign(pin_to_signal[pin], visited):
                    pin_to_signal[pin] = signal_index
                    return True
            return False

        assigned = sum(assign(index, set()) for index in range(len(signals)))
        assert assigned == len(signals), (pattern["project_id"], assigned, len(signals))


def test_all_projects_have_specific_signals_and_complex_minimums():
    """Seven simple categories and the complex projects cannot collapse to INPUT/OUTPUT/DEBUG."""
    patterns = pattern_map()
    for project_id, required in {**PROJECT_SIGNAL_MINIMUMS, **SIMPLE_PROJECT_FIXTURES}.items():
        functions = {signal["function"] for signal in patterns[project_id]["signals"]}
        assert required <= functions, (project_id, required - functions)


def test_components_and_power_domains_are_ranged_and_referenced():
    """Unused placeholder components or dangling signal/domain references must fail validation."""
    for pattern in load_manifest()["patterns"]:
        components = {component["id"]: component for component in pattern["components"]}
        domains = {domain["id"]: domain for domain in pattern["power_domains"]}
        component_refs = {signal["component_ref"] for signal in pattern["signals"]}
        domain_refs = {signal["power_domain_ref"] for signal in pattern["signals"]}
        assert set(components) == component_refs, pattern["project_id"]
        assert set(domains) == domain_refs, pattern["project_id"]
        for component in components.values():
            for field in ("supply_v", "logic_v", "current_ma"):
                value = component[field]
                assert value == "unknown_requires_datasheet" or (
                    isinstance(value, dict) and value["min"] <= value["max"] and value["rationale"]
                ), (pattern["project_id"], component["id"], field)
        for domain in domains.values():
            assert domain["verification_status"] == "estimated"
            assert domain["voltage_v"]["min"] <= domain["voltage_v"]["max"]
            assert domain["current_budget_ma"]["min"] <= domain["current_budget_ma"]["max"]
            assert domain["rationale"]


def test_power_terminal_voltage_and_domain_current_closure():
    """Every powered port must fit its rail, and every rail must conservatively cover concurrent peak current."""
    for pattern in load_manifest()["patterns"]:
        components = {component["id"]: component for component in pattern["components"]}
        domains = {domain["id"]: domain for domain in pattern["power_domains"]}
        connected_consumers: dict[str, set[tuple[str, str]]] = {domain_id: set() for domain_id in domains}

        for component in components.values():
            rails = component["supply_rails"]
            assert rails, (pattern["project_id"], component["id"])
            assert len({rail["id"] for rail in rails}) == len(rails)

        for signal in pattern["signals"]:
            if signal["endpoint_type"] != "power_terminal":
                continue
            component = components[signal["component_ref"]]
            rail = next(rail for rail in component["supply_rails"] if rail["id"] == signal["component_port_ref"])
            domain = domains[signal["power_domain_ref"]]
            required = signal["required_rail_voltage_v"]
            allowed = rail["voltage_v"]
            assert allowed["min"] <= required["min"] <= required["max"] <= allowed["max"]
            assert required["min"] <= domain["voltage_v"]["min"] <= domain["voltage_v"]["max"] <= required["max"]
            if signal["direction"] != "return" and rail["current_role"] == "consumer":
                connected_consumers[domain["id"]].add((component["id"], rail["id"]))

        for domain_id, domain in domains.items():
            concurrency = domain["concurrency"]
            assert concurrency["diversity_factor"] == 1.0
            assert len(concurrency["rationale"]) >= 20
            connected_peak = sum(
                next(
                    rail["current_ma"]["max"]
                    for rail in components[component_id]["supply_rails"]
                    if rail["id"] == port_id
                )
                for component_id, port_id in connected_consumers[domain_id]
            )
            required_peak = domain["intrinsic_current_ma"]["max"] + connected_peak
            assert domain["current_budget_ma"]["max"] >= required_peak, (pattern["project_id"], domain_id, required_peak)
            assert domain["source_capacity_ma"]["min"] >= domain["current_budget_ma"]["max"]
            assert domain["verification_status"] == "estimated"


def test_motor_sensor_and_actuator_rails_are_not_wide_aggregate_domains():
    """5 V ultrasonic, motor logic, motor VM, servo, and pump rails must remain independently checkable."""
    patterns = pattern_map()
    expected_domains = {
        "mobility-041": {"mcu_3v3", "sensor_3v3", "motor_logic_3v3", "motor_vm"},
        "mobility-042": {"mcu_3v3", "ultra_5v", "motor_logic_3v3", "motor_vm"},
        "mobility-043": {"mcu_3v3", "sensor_3v3", "servo_5v"},
        "environment-016": {"mcu_3v3", "sensor_3v3", "pump_5v"},
        "innovation-076": {"mcu_3v3", "sensor_3v3", "pump_5v", "fan_load"},
        "innovation-078": {"mcu_3v3", "sensor_3v3", "ultra_5v", "motor_logic_3v3", "motor_vm"},
    }
    for project_id, required in expected_domains.items():
        actual = {domain["id"] for domain in patterns[project_id]["power_domains"]}
        assert required <= actual, (project_id, required - actual)
    for project_id in ("mobility-042", "innovation-078"):
        item = patterns[project_id]
        ultra = next(signal for signal in item["signals"] if signal["function"] == "ULTRA_VCC")
        assert ultra["power_domain_ref"] == "ultra_5v"
        domain = next(domain for domain in item["power_domains"] if domain["id"] == "ultra_5v")
        assert domain["voltage_v"] == {"min": 4.75, "max": 5.25, "rationale": domain["voltage_v"]["rationale"]}


def test_echo_level_shift_and_independent_load_domains_are_explicit():
    """A 5 V Echo or motor/servo/pump load may not be hidden in the MCU 3.3 V domain."""
    patterns = pattern_map()
    for project_id in ("ultrasonic_parking_servo", "mobility-042", "innovation-078"):
        echo = next(signal for signal in patterns[project_id]["signals"] if signal["function"] == "ULTRA_ECHO")
        assert "5 V" in echo["electrical"]
        assert any(token in echo["electrical"] for token in ("divider", "level shifter"))
    load_domains = {
        "mobility-041": "motor_vm",
        "mobility-042": "motor_vm",
        "mobility-043": "servo_5v",
        "environment-016": "pump_5v",
        "innovation-076": "pump_5v",
        "innovation-078": "motor_vm",
    }
    for project_id, domain_id in load_domains.items():
        domains = {domain["id"] for domain in patterns[project_id]["power_domains"]}
        assert domain_id in domains and domain_id != "mcu_3v3"


def test_resource_budgets_are_estimated_ranges_with_project_rationales():
    """One-byte precision or a mechanical shared budget sequence must fail review."""
    rationale_sets = set()
    for pattern in load_manifest()["patterns"]:
        budget = pattern["resource_budget"]
        assert "signal_count" not in pattern
        for name in ("flash_bytes", "ram_bytes", "mcu_current_ma", "load_current_ma"):
            estimate = budget[name]
            assert estimate["verification_status"] == "estimated"
            assert estimate["min"] < estimate["max"], (pattern["project_id"], name)
            assert len(estimate["rationale"]) >= 20, (pattern["project_id"], name)
        assert budget["flash_bytes"]["max"] - budget["flash_bytes"]["min"] >= 1024
        assert budget["ram_bytes"]["max"] - budget["ram_bytes"]["min"] >= 256
        rationale_sets.add(tuple(budget[name]["rationale"] for name in budget))
    assert len(rationale_sets) >= 25


def test_manifest_passes_jsonschema_and_custom_semantic_validation():
    """The production validator is the gate used by both rendering and --check."""
    renderer = load_renderer()
    renderer.validate_manifest_data(load_manifest())


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_pin_af", "one_byte_flash", "unused_component", "terminal_as_gpio",
        "ultra_rail_12v", "required_range_exceeds_component", "underrated_domain_current",
    ],
)
def test_semantic_mutations_are_rejected(mutation: str):
    """Realistic corruptions must be killed before they can reach Markdown."""
    renderer = load_renderer()
    data = copy.deepcopy(load_manifest())
    patterns = pattern_map(data)
    if mutation == "wrong_pin_af":
        signal = next(signal for _, signal in all_signals(data) if signal["peripheral"] == "USART1_TX")
        signal["candidate_pins"][0] = {
            "pin": "PA0", "af": "USART1_TX", "remap": "none", "conditions": ["invalid fixture"],
        }
    elif mutation == "one_byte_flash":
        patterns["device_status_light"]["resource_budget"]["flash_bytes"] = {
            "min": 1, "max": 1, "rationale": "deliberately false one-byte image budget", "verification_status": "estimated",
        }
    elif mutation == "unused_component":
        patterns["device_status_light"]["components"].append({
            "id": "unused", "name": "unused placeholder", "supply_v": "unknown_requires_datasheet",
            "logic_v": "unknown_requires_datasheet", "current_ma": "unknown_requires_datasheet",
        })
    elif mutation == "terminal_as_gpio":
        signal = next(signal for signal in patterns["industrial-054"]["signals"] if signal["function"] == "RS485_A")
        signal["endpoint_type"] = "mcu_signal"
    elif mutation == "ultra_rail_12v":
        signal = next(signal for signal in patterns["mobility-042"]["signals"] if signal["function"] == "ULTRA_VCC")
        domain = next(domain for domain in patterns["mobility-042"]["power_domains"] if domain["id"] == signal["power_domain_ref"])
        domain["voltage_v"]["max"] = 12.0
    elif mutation == "required_range_exceeds_component":
        signal = next(signal for signal in patterns["mobility-042"]["signals"] if signal["function"] == "ULTRA_VCC")
        signal["required_rail_voltage_v"]["max"] = 12.0
    else:
        signal = next(signal for signal in patterns["industrial-054"]["signals"] if signal["function"] == "RS485_VCC")
        domain = next(domain for domain in patterns["industrial-054"]["power_domains"] if domain["id"] == signal["power_domain_ref"])
        domain["current_budget_ma"]["min"] = 0
        domain["current_budget_ma"]["max"] = 1
    with pytest.raises(renderer.ManifestValidationError):
        renderer.validate_manifest_data(data)


def test_renderer_check_detects_and_repairs_markdown_drift(tmp_path: Path):
    """Generated blocks must be reproducible from patterns.json and --check must detect edits."""
    renderer = load_renderer()
    renderer.validate_manifest_data(load_manifest())
    copied_library = tmp_path / "v2-detailed"
    shutil.copytree(LIBRARY, copied_library)
    command = [
        sys.executable, str(RENDERER), "--manifest", str(copied_library / "patterns.json"),
        "--library", str(copied_library),
    ]
    assert subprocess.run([*command, "--check"], capture_output=True, text=True).returncode == 0
    target = copied_library / "industrial-054.md"
    target.write_text(target.read_text(encoding="utf-8").replace("RS485_A", "BROKEN_A", 1), encoding="utf-8")
    failed = subprocess.run([*command, "--check"], capture_output=True, text=True)
    assert failed.returncode == 1 and "industrial-054.md" in failed.stdout
    assert subprocess.run(command, capture_output=True, text=True).returncode == 0
    assert subprocess.run([*command, "--check"], capture_output=True, text=True).returncode == 0


def test_markdown_blocks_match_manifest_hash_and_derived_mcu_signal_count():
    """Markdown signal rows, hash, and signal count must be renderer output, never hand-maintained copies."""
    renderer = load_renderer()
    for pattern in load_manifest()["patterns"]:
        markdown = (LIBRARY / f"{pattern['project_id']}.md").read_text(encoding="utf-8")
        expected = renderer.render_pattern_block(pattern)
        assert expected in markdown, pattern["project_id"]
        digest = re.search(r"V2_PATTERN_GENERATED:START sha256=([0-9a-f]{64})", expected)
        assert digest and digest.group(1) == renderer.pattern_digest(pattern)
        mcu_count = sum(signal["endpoint_type"] == "mcu_signal" for signal in pattern["signals"])
        assert f"| MCU 信号数 | {mcu_count} |" in expected


def test_renderer_exposes_port_voltage_and_current_closure():
    """Rendered engineering tables must expose the same port and rail closure used by validation."""
    renderer = load_renderer()
    for project_id in ("industrial-054", "measurement-029", "mobility-041", "mobility-042", "innovation-078"):
        pattern = pattern_map()[project_id]
        block = renderer.render_pattern_block(pattern)
        assert "component_port_ref" in block
        assert "required_rail_voltage" in block
        assert "source_capacity" in block
        assert "concurrent consumer peak" in block
        assert all(domain["id"] in block for domain in pattern["power_domains"])


def test_human_shell_does_not_duplicate_generated_wiring_or_budget_tables():
    """A stale hand-maintained table must not contradict the manifest-generated source of truth."""
    for path in LIBRARY.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        wiring = text.split("## 可覆写接线表", 1)[1].split("## ", 1)[0]
        budget = text.split("## 资源预算", 1)[1].split("## ", 1)[0]
        assert "Manifest 生成的可覆写工程区块" in wiring
        assert "Manifest 生成的可覆写工程区块" in budget
        assert "| Flash |" not in budget and "PA0/PA1/PA8" not in wiring


def test_human_authored_pattern_shells_keep_engineering_and_honesty_gates():
    """Rendering the structured block must not erase the staged V2 engineering shell."""
    bodies = set()
    for path in LIBRARY.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        for section in REQUIRED_SECTIONS:
            assert section in text, (path.name, section)
        for token in ("时钟", "DMA", "IRQ", "Flash", "RAM", "未实机"):
            assert token in text, (path.name, token)
        body = "\n".join(line for line in text.splitlines() if not line.startswith(("# ", "稳定项目 ID")))
        bodies.add(body)
    assert len(bodies) == 30
