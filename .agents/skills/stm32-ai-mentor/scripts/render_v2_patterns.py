#!/usr/bin/env python3
"""Validate and render the structured V2 project-pattern reference blocks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LIBRARY = SCRIPT_DIR.parent / "references" / "projects" / "v2-detailed"
DEFAULT_MANIFEST = DEFAULT_LIBRARY / "patterns.json"
START_PREFIX = "<!-- V2_PATTERN_GENERATED:START sha256="
END_MARKER = "<!-- V2_PATTERN_GENERATED:END -->"
LEGACY_HEADING = "## Manifest 接线与资源来源"
WIRING_HEADING = "## 可覆写接线表"
BUDGET_HEADING = "## 资源预算"
WIRING_POINTER = "逐信号端点类型、电气约束、合法 AF 候选、组件与电源域的唯一可执行表，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份引脚表。"
BUDGET_POINTER = "MCU 信号数、Flash/RAM 区间、MCU/负载分域电流及估算依据，详见文末“Manifest 生成的可覆写工程区块”；此处不维护第二份数值预算。"


class ManifestValidationError(ValueError):
    """Raised when schema or engineering semantics reject a manifest."""


RANGE_SCHEMA = {
    "type": "object",
    "required": ["min", "max", "rationale"],
    "properties": {
        "min": {"type": "number"},
        "max": {"type": "number"},
        "rationale": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}
ESTIMATE_SCHEMA = {
    "type": "object",
    "required": ["min", "max", "rationale", "verification_status"],
    "properties": {
        "min": {"type": "number"},
        "max": {"type": "number"},
        "rationale": {"type": "string", "minLength": 20},
        "verification_status": {"const": "estimated"},
    },
    "additionalProperties": False,
}
COMPONENT_VALUE_SCHEMA = {
    "oneOf": [RANGE_SCHEMA, {"const": "unknown_requires_datasheet"}],
}
CANDIDATE_SCHEMA = {
    "type": "object",
    "required": ["pin", "af", "remap", "conditions"],
    "properties": {
        "pin": {"type": "string", "minLength": 2},
        "af": {"type": "string", "minLength": 1},
        "remap": {"type": "string", "minLength": 1},
        "conditions": {
            "type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1},
        },
    },
    "additionalProperties": False,
}
SIGNAL_SCHEMA = {
    "type": "object",
    "required": [
        "function", "endpoint_type", "direction", "electrical", "peripheral",
        "component_ref", "power_domain_ref",
    ],
    "properties": {
        "function": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]*$"},
        "endpoint_type": {
            "enum": ["mcu_signal", "module_signal", "bus_terminal", "power_terminal"],
        },
        "direction": {
            "enum": ["in", "out", "bidirectional", "passive", "power_in", "power_out", "return"],
        },
        "electrical": {"type": "string", "minLength": 8},
        "peripheral": {"type": "string", "minLength": 1},
        "candidate_pins": {"type": "array", "minItems": 1, "items": CANDIDATE_SCHEMA},
        "unknown": {"const": True},
        "confirmation_method": {"type": "string", "minLength": 20},
        "component_ref": {"type": "string", "minLength": 1},
        "power_domain_ref": {"type": "string", "minLength": 1},
        "component_port_ref": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "required_rail_voltage_v": RANGE_SCHEMA,
    },
    "allOf": [
        {
            "if": {"properties": {"endpoint_type": {"const": "mcu_signal"}}},
            "then": {"required": ["candidate_pins"], "not": {"required": ["unknown"]}},
            "else": {
                "required": ["unknown", "confirmation_method"],
                "not": {"required": ["candidate_pins"]},
            },
        },
        {
            "if": {"properties": {"endpoint_type": {"const": "power_terminal"}}},
            "then": {"required": ["component_port_ref", "required_rail_voltage_v"]},
        },
    ],
    "additionalProperties": False,
}
PATTERN_SCHEMA = {
    "type": "object",
    "required": [
        "project_id", "target", "hardware_verification", "components", "power_domains",
        "signals", "resource_budget",
    ],
    "properties": {
        "project_id": {"type": "string", "minLength": 1},
        "target": {
            "type": "object",
            "required": ["mcu", "package", "board", "preserved_debug_pins", "source"],
            "properties": {
                "mcu": {"const": "STM32F103C8Tx"},
                "package": {"const": "LQFP48"},
                "board": {"const": "unknown_requires_confirmation"},
                "preserved_debug_pins": {
                    "type": "array", "prefixItems": [{"const": "PA13"}, {"const": "PA14"}],
                    "minItems": 2, "maxItems": 2,
                },
                "source": {"type": "string", "minLength": 20},
            },
            "additionalProperties": False,
        },
        "hardware_verification": {"const": "not_tested_on_hardware"},
        "components": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "name", "supply_v", "logic_v", "current_ma", "supply_rails"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "name": {"type": "string", "minLength": 3},
                    "supply_v": COMPONENT_VALUE_SCHEMA,
                    "logic_v": COMPONENT_VALUE_SCHEMA,
                    "current_ma": COMPONENT_VALUE_SCHEMA,
                    "supply_rails": {
                        "type": "array", "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["id", "voltage_v", "current_ma", "current_role"],
                            "properties": {
                                "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                                "voltage_v": RANGE_SCHEMA,
                                "current_ma": RANGE_SCHEMA,
                                "current_role": {"enum": ["consumer", "pass_through", "source", "signal_load"]},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
        },
        "power_domains": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "id", "name", "voltage_v", "current_budget_ma", "intrinsic_current_ma",
                    "source_capacity_ma", "concurrency", "rationale", "verification_status",
                ],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "name": {"type": "string", "minLength": 3},
                    "voltage_v": RANGE_SCHEMA,
                    "current_budget_ma": RANGE_SCHEMA,
                    "intrinsic_current_ma": RANGE_SCHEMA,
                    "source_capacity_ma": RANGE_SCHEMA,
                    "concurrency": {
                        "type": "object",
                        "required": ["diversity_factor", "rationale"],
                        "properties": {
                            "diversity_factor": {"const": 1.0},
                            "rationale": {"type": "string", "minLength": 20},
                        },
                        "additionalProperties": False,
                    },
                    "rationale": {"type": "string", "minLength": 20},
                    "verification_status": {"const": "estimated"},
                },
                "additionalProperties": False,
            },
        },
        "signals": {"type": "array", "minItems": 1, "items": SIGNAL_SCHEMA},
        "resource_budget": {
            "type": "object",
            "required": ["flash_bytes", "ram_bytes", "mcu_current_ma", "load_current_ma"],
            "properties": {
                "flash_bytes": ESTIMATE_SCHEMA,
                "ram_bytes": ESTIMATE_SCHEMA,
                "mcu_current_ma": ESTIMATE_SCHEMA,
                "load_current_ma": ESTIMATE_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}
MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "patterns"],
    "properties": {
        "schema_version": {"const": 3},
        "patterns": {"type": "array", "minItems": 30, "maxItems": 30, "items": PATTERN_SCHEMA},
    },
    "additionalProperties": False,
}


VALID_PIN_AF = {
    "ADC1": {
        ("PA0", "ADC1_IN0", "none"), ("PA1", "ADC1_IN1", "none"),
        ("PA2", "ADC1_IN2", "none"), ("PA3", "ADC1_IN3", "none"),
        ("PA4", "ADC1_IN4", "none"), ("PA5", "ADC1_IN5", "none"),
        ("PA6", "ADC1_IN6", "none"), ("PA7", "ADC1_IN7", "none"),
        ("PB0", "ADC1_IN8", "none"), ("PB1", "ADC1_IN9", "none"),
    },
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
LQFP48_GPIO_PINS = {
    "PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7", "PA8", "PA9", "PA10",
    "PA11", "PA12", "PA15", "PB0", "PB1", "PB2", "PB3", "PB4", "PB5", "PB6", "PB7",
    "PB8", "PB9", "PB10", "PB11", "PB12", "PB13", "PB14", "PB15", "PC13", "PC14", "PC15",
    "PD0", "PD1",
}


def _schema_error(data: dict[str, Any]) -> str | None:
    errors = sorted(Draft202012Validator(MANIFEST_SCHEMA).iter_errors(data), key=lambda error: list(error.path))
    if not errors:
        return None
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "manifest"
    return f"schema error at {location}: {error.message}"


def _fail(message: str) -> None:
    raise ManifestValidationError(message)


def validate_manifest_data(data: dict[str, Any]) -> None:
    """Run JSON Schema plus MCU, reference, endpoint, and budget semantics."""
    schema_error = _schema_error(data)
    if schema_error:
        _fail(schema_error)

    project_ids = [pattern["project_id"] for pattern in data["patterns"]]
    if len(project_ids) != len(set(project_ids)):
        _fail("project_id values must be unique")

    for pattern in data["patterns"]:
        project_id = pattern["project_id"]
        component_by_id = {component["id"]: component for component in pattern["components"]}
        domain_by_id = {domain["id"]: domain for domain in pattern["power_domains"]}
        components = list(component_by_id)
        domains = list(domain_by_id)
        if len(components) != len(set(components)):
            _fail(f"{project_id}: component ids must be unique")
        if len(domains) != len(set(domains)):
            _fail(f"{project_id}: power-domain ids must be unique")

        component_refs = {signal["component_ref"] for signal in pattern["signals"]}
        domain_refs = {signal["power_domain_ref"] for signal in pattern["signals"]}
        if set(components) != component_refs:
            _fail(f"{project_id}: component references differ: declared={set(components)}, used={component_refs}")
        if set(domains) != domain_refs:
            _fail(f"{project_id}: power-domain references differ: declared={set(domains)}, used={domain_refs}")

        functions = [signal["function"] for signal in pattern["signals"]]
        if len(functions) != len(set(functions)):
            _fail(f"{project_id}: signal functions must be unique")
        if any(function.endswith(("_INPUT", "_OUTPUT", "_DEBUG")) for function in functions):
            _fail(f"{project_id}: generic INPUT/OUTPUT/DEBUG signal placeholder is forbidden")

        consumer_ports = {domain_id: set() for domain_id in domains}
        for signal in pattern["signals"]:
            function = signal["function"]
            endpoint_type = signal["endpoint_type"]
            peripheral = signal["peripheral"]
            if endpoint_type == "mcu_signal":
                for candidate in signal["candidate_pins"]:
                    candidate_key = (candidate["pin"], candidate["af"], candidate["remap"])
                    if candidate["pin"] in {"PA13", "PA14"}:
                        _fail(f"{project_id}/{function}: PA13/PA14 must remain SWD")
                    if peripheral in {"GPIO", "GPIO_EXTI"}:
                        expected_af = "GPIO_input" if signal["direction"] == "in" else "GPIO_output"
                        if candidate["pin"] not in LQFP48_GPIO_PINS or candidate["af"] != expected_af or candidate["remap"] != "none":
                            _fail(f"{project_id}/{function}: invalid GPIO candidate {candidate_key}")
                    elif peripheral not in VALID_PIN_AF or candidate_key not in VALID_PIN_AF[peripheral]:
                        _fail(f"{project_id}/{function}: illegal F103C8 LQFP48 pin/AF/remap {candidate_key} for {peripheral}")
            elif peripheral == "power" and endpoint_type != "power_terminal":
                _fail(f"{project_id}/{function}: power endpoint must be power_terminal")
            elif peripheral in {"RS485_bus", "RS485_termination", "RS485_bias", "CAN_bus", "CAN_termination", "INA219_shunt"} and endpoint_type != "bus_terminal":
                _fail(f"{project_id}/{function}: physical bus endpoint must be bus_terminal")

            if endpoint_type == "power_terminal":
                component = component_by_id[signal["component_ref"]]
                component_ports = {rail["id"]: rail for rail in component["supply_rails"]}
                port_id = signal["component_port_ref"]
                if port_id not in component_ports:
                    _fail(f"{project_id}/{function}: component port {port_id} is not declared by {component['id']}")
                component_port = component_ports[port_id]
                required_voltage = signal["required_rail_voltage_v"]
                allowed_voltage = component_port["voltage_v"]
                power_domain = domain_by_id[signal["power_domain_ref"]]
                domain_voltage = power_domain["voltage_v"]
                if not (
                    allowed_voltage["min"] <= required_voltage["min"]
                    and required_voltage["max"] <= allowed_voltage["max"]
                ):
                    _fail(
                        f"{project_id}/{function}: required rail voltage exceeds "
                        f"{component['id']}/{port_id} supply range"
                    )
                if not (
                    required_voltage["min"] <= domain_voltage["min"]
                    and domain_voltage["max"] <= required_voltage["max"]
                ):
                    _fail(f"{project_id}/{function}: domain can leave the terminal voltage requirement")
                if signal["direction"] != "return" and component_port["current_role"] == "consumer":
                    consumer_ports[power_domain["id"]].add((component["id"], port_id))

            if peripheral in {"I2C1_SCL", "I2C1_SDA"}:
                if signal["direction"] != "bidirectional" or "open-drain" not in signal["electrical"] or "pull-up" not in signal["electrical"]:
                    _fail(f"{project_id}/{function}: I2C requires bidirectional open-drain and an external pull-up")

        if "signal_count" in pattern:
            _fail(f"{project_id}: signal_count is derived from mcu_signal rows and must not be stored")
        budget = pattern["resource_budget"]
        for budget_name, estimate in budget.items():
            if estimate["min"] >= estimate["max"]:
                _fail(f"{project_id}/{budget_name}: estimate must be a non-zero range")
        if budget["flash_bytes"]["max"] - budget["flash_bytes"]["min"] < 1024:
            _fail(f"{project_id}: Flash range is implausibly precise")
        if budget["ram_bytes"]["max"] - budget["ram_bytes"]["min"] < 256:
            _fail(f"{project_id}: RAM range is implausibly precise")

        for component in pattern["components"]:
            for field in ("supply_v", "logic_v", "current_ma"):
                value = component[field]
                if isinstance(value, dict) and value["min"] > value["max"]:
                    _fail(f"{project_id}/{component['id']}/{field}: invalid range")
            rail_ids = [rail["id"] for rail in component["supply_rails"]]
            if len(rail_ids) != len(set(rail_ids)):
                _fail(f"{project_id}/{component['id']}: supply-rail ids must be unique")
            for rail in component["supply_rails"]:
                for field in ("voltage_v", "current_ma"):
                    value = rail[field]
                    if value["min"] > value["max"]:
                        _fail(f"{project_id}/{component['id']}/{rail['id']}/{field}: invalid range")
        for power_domain in pattern["power_domains"]:
            for field in ("voltage_v", "current_budget_ma", "intrinsic_current_ma", "source_capacity_ma"):
                value = power_domain[field]
                if value["min"] > value["max"]:
                    _fail(f"{project_id}/{power_domain['id']}/{field}: invalid range")
            connected_peak = sum(
                next(
                    rail["current_ma"]["max"]
                    for rail in component_by_id[component_id]["supply_rails"]
                    if rail["id"] == port_id
                )
                for component_id, port_id in consumer_ports[power_domain["id"]]
            )
            required_peak = (
                power_domain["intrinsic_current_ma"]["max"]
                + power_domain["concurrency"]["diversity_factor"] * connected_peak
            )
            if power_domain["current_budget_ma"]["max"] < required_peak:
                _fail(
                    f"{project_id}/{power_domain['id']}: current budget "
                    f"{power_domain['current_budget_ma']['max']} mA is below concurrent peak {required_peak} mA"
                )
            if power_domain["current_budget_ma"]["max"] > power_domain["source_capacity_ma"]["min"]:
                _fail(
                    f"{project_id}/{power_domain['id']}: rail budget exceeds the conservative source-capacity floor"
                )


def pattern_digest(pattern: dict[str, Any]) -> str:
    canonical = json.dumps(pattern, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _format_range(value: Any, unit: str) -> str:
    if value == "unknown_requires_datasheet":
        return "unknown_requires_datasheet"
    return f"{value['min']}-{value['max']} {unit}; {value['rationale']}"


def _candidate_text(signal: dict[str, Any]) -> str:
    if signal["endpoint_type"] != "mcu_signal":
        return f"unknown; confirm: {signal['confirmation_method']}"
    rendered = []
    for candidate in signal["candidate_pins"]:
        conditions = "; ".join(candidate["conditions"])
        rendered.append(f"{candidate['pin']} / {candidate['af']} / {candidate['remap']} / {conditions}")
    return "<br>".join(rendered)


def _supply_rail_text(component: dict[str, Any]) -> str:
    return "<br>".join(
        f"{rail['id']}: {_format_range(rail['voltage_v'], 'V')} / "
        f"{_format_range(rail['current_ma'], 'mA')} / {rail['current_role']}"
        for rail in component["supply_rails"]
    )


def _domain_consumer_peak(pattern: dict[str, Any], domain_id: str) -> float:
    components = {component["id"]: component for component in pattern["components"]}
    connected = set()
    for signal in pattern["signals"]:
        if (
            signal["endpoint_type"] == "power_terminal"
            and signal["direction"] != "return"
            and signal["power_domain_ref"] == domain_id
        ):
            component = components[signal["component_ref"]]
            rail = next(
                rail for rail in component["supply_rails"]
                if rail["id"] == signal["component_port_ref"]
            )
            if rail["current_role"] == "consumer":
                connected.add((component["id"], rail["id"]))
    return sum(
        next(
            rail["current_ma"]["max"]
            for rail in components[component_id]["supply_rails"]
            if rail["id"] == port_id
        )
        for component_id, port_id in connected
    )


def render_pattern_block(pattern: dict[str, Any]) -> str:
    """Render the complete generated section for one validated pattern."""
    digest = pattern_digest(pattern)
    lines = [
        f"{START_PREFIX}{digest} -->",
        "## Manifest 生成的可覆写工程区块",
        "",
        "单一来源：`patterns.json`。目标为 `STM32F103C8Tx LQFP48`，板卡版本未知；下表只列 MCU 合法候选能力，实施前必须根据板卡走线、复用冲突和组件数据手册覆写。`PA13/PA14` 始终保留给 SWD。**未实机（not_tested_on_hardware）**。",
        "",
        "### 组件规格边界",
        "",
        "| component_ref | 组件 | supply_v | logic_v | current_ma | supply_rails |",
        "|---|---|---|---|---|---|",
    ]
    for component in pattern["components"]:
        lines.append(
            "| " + " | ".join([
                _escape(component["id"]), _escape(component["name"]),
                _escape(_format_range(component["supply_v"], "V")),
                _escape(_format_range(component["logic_v"], "V")),
                _escape(_format_range(component["current_ma"], "mA")),
                _escape(_supply_rail_text(component)),
            ]) + " |"
        )

    lines.extend([
        "",
        "### 电源域",
        "",
        "| power_domain_ref | 电源域 | 电压 | intrinsic_current | concurrent consumer peak | 电流预算 | source_capacity | concurrency | 状态 |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for power_domain in pattern["power_domains"]:
        lines.append(
            "| " + " | ".join([
                _escape(power_domain["id"]), _escape(power_domain["name"]),
                _escape(_format_range(power_domain["voltage_v"], "V")),
                _escape(_format_range(power_domain["intrinsic_current_ma"], "mA")),
                f"{_domain_consumer_peak(pattern, power_domain['id'])} mA",
                _escape(_format_range(power_domain["current_budget_ma"], "mA")),
                _escape(_format_range(power_domain["source_capacity_ma"], "mA")),
                _escape(
                    f"diversity={power_domain['concurrency']['diversity_factor']}; "
                    f"{power_domain['concurrency']['rationale']}"
                ),
                power_domain["verification_status"],
            ]) + " |"
        )

    lines.extend([
        "",
        "### 逐信号契约",
        "",
        "| function | endpoint_type | direction | electrical | peripheral | candidate_pins / confirmation | component_ref | component_port_ref | required_rail_voltage | power_domain_ref |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])
    for signal in pattern["signals"]:
        lines.append(
            "| " + " | ".join([
                signal["function"], signal["endpoint_type"], signal["direction"],
                _escape(signal["electrical"]), signal["peripheral"], _escape(_candidate_text(signal)),
                signal["component_ref"], signal.get("component_port_ref", "-"),
                _escape(_format_range(signal["required_rail_voltage_v"], "V"))
                if "required_rail_voltage_v" in signal else "-",
                signal["power_domain_ref"],
            ]) + " |"
        )

    budget = pattern["resource_budget"]
    mcu_signal_count = sum(signal["endpoint_type"] == "mcu_signal" for signal in pattern["signals"])
    lines.extend([
        "",
        "### 资源预算（全部为 estimated）",
        "",
        "| 资源 | 估算范围 | rationale | verification_status |",
        "|---|---|---|---|",
        f"| MCU 信号数 | {mcu_signal_count} | 从 endpoint_type=mcu_signal 的逐信号行派生，不把 A/B、VCC/GND 或模块端子计入 | derived |",
    ])
    budget_labels = {
        "flash_bytes": ("Flash", "B"),
        "ram_bytes": ("RAM", "B"),
        "mcu_current_ma": ("MCU 电流", "mA"),
        "load_current_ma": ("负载电流", "mA"),
    }
    for key, (label, unit) in budget_labels.items():
        estimate = budget[key]
        lines.append(
            f"| {label} | {estimate['min']}-{estimate['max']} {unit} | {_escape(estimate['rationale'])} | {estimate['verification_status']} |"
        )
    lines.extend(["", END_MARKER])
    return "\n".join(lines)


def _replace_generated_block(markdown: str, block: str) -> str:
    markdown = _replace_section(markdown, WIRING_HEADING, WIRING_POINTER)
    markdown = _replace_section(markdown, BUDGET_HEADING, BUDGET_POINTER)
    if START_PREFIX in markdown:
        start = markdown.index(START_PREFIX)
        end = markdown.find(END_MARKER, start)
        if end < 0:
            raise ManifestValidationError("generated START marker has no END marker")
        end += len(END_MARKER)
        return markdown[:start].rstrip() + "\n\n" + block + markdown[end:]
    if LEGACY_HEADING in markdown:
        return markdown.split(LEGACY_HEADING, 1)[0].rstrip() + "\n\n" + block + "\n"
    return markdown.rstrip() + "\n\n" + block + "\n"


def _replace_section(markdown: str, heading: str, replacement: str) -> str:
    start = markdown.find(heading)
    if start < 0:
        raise ManifestValidationError(f"required Markdown section missing: {heading}")
    next_heading = markdown.find("\n## ", start + len(heading))
    if next_heading < 0:
        raise ManifestValidationError(f"required Markdown section has no following section: {heading}")
    normalized = f"{heading}\n\n{replacement}\n"
    return markdown[:start] + normalized + markdown[next_heading:]


def render_library(manifest_path: Path, library_path: Path, check: bool) -> int:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_data(data)
    expected_ids = {pattern["project_id"] for pattern in data["patterns"]}
    actual_ids = {path.stem for path in library_path.glob("*.md")}
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ManifestValidationError(f"Markdown/project mismatch: missing={missing}, extra={extra}")

    drifted = []
    for pattern in data["patterns"]:
        path = library_path / f"{pattern['project_id']}.md"
        current = path.read_text(encoding="utf-8")
        expected = _replace_generated_block(current, render_pattern_block(pattern))
        if current != expected:
            drifted.append(path.name)
            if not check:
                path.write_text(expected, encoding="utf-8")
    if drifted:
        verb = "drift" if check else "rendered"
        print(f"{verb}: " + ", ".join(drifted))
    return 1 if check and drifted else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return render_library(args.manifest, args.library, args.check)
    except (OSError, json.JSONDecodeError, ManifestValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
