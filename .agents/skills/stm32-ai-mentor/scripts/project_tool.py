#!/usr/bin/env python3
"""Independent event-sourced V2 project sidecar for STM32 AI Mentor.

The ledger below ``Projects/<project_id>/events`` is canonical.  This tool
never writes ``Student_Profile`` and never invokes a programmer or flasher.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SCHEMA_VERSION = 1
LOCK_STALE_SECONDS = 60
DEFAULT_PROJECTS = Path(__file__).resolve().parents[4] / "Projects"
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
LEVELS = ("V0", "V1", "V2", "V3", "V4", "V5")
CORE_STAGES = (
    "requirements", "design", "resources", "hardware_plan",
    "implementation", "build", "hardware_acceptance",
)
ALLOWED_EVENT_TYPES = {
    "generation.project_initialized",
    "generation.intake_updated",
    "generation.requirements_updated",
    "generation.target_updated",
    "generation.safety_updated",
    "generation.resources_updated",
    "generation.procurement_updated",
    "generation.baseline_updated",
    "generation.evidence_recorded",
    "generation.increment_recorded",
    "generation.stage_recorded",
    "generation.checkpoint_recorded",
    "generation.flash_confirmed",
    "generation.flash_recorded",
    "generation.execution_run_recorded",
    "generation.design_release_recorded",
    "generation.release_recorded",
}
EXECUTION_ACTIONS = {
    "environment.inspect", "project.inspect", "cubemx.generate_staged", "build.run",
    "artifact.inspect", "test.host", "probe.list", "target.identify", "serial.list",
    "serial.capture", "flash.plan", "flash.execute", "target.reset", "test.target",
    "job.status", "job.cancel",
}
UNSAFE_TERMS = (
    "市电", "高压", "mains", "high voltage", "无保护锂电", "unprotected lithium",
    "医疗诊断", "medical diagnosis", "生命安全关键", "safety-critical", "大功率电机",
)
UNKNOWN_TERMS = ("unknown", "tbd", "待确认", "待核对", "未知", "不确定")
BUILD_OR_FLASH_KINDS = {
    "build_result", "build_success", "build_successful",
    "compile_result", "compile_success", "compile_successful",
    "link_result", "link_success", "link_successful",
    "flash_result", "flash_success", "flash_successful",
    "program_result", "program_success", "program_successful",
}
BUILD_EVIDENCE_KINDS = {
    "build_result", "build_success", "build_successful",
    "compile_result", "compile_success", "compile_successful",
    "link_result", "link_success", "link_successful",
}
EVIDENCE_KINDS = {
    "authoritative_document", "document_review", "design_review", "configuration_review",
    "resource_report", "resource_map", "logic_test", "host_test", "runtime_log",
    "measurement", "acceptance_test", "hardware_observation", "hardware_measurement",
    *BUILD_OR_FLASH_KINDS,
}
EVIDENCE_SOURCES = {
    "authoritative_document", "tool", "instrument", "mentor_observed",
    "reported_by_user", "imported_reference", "instrument_capture", "verified_hardware_tool",
}
INDEPENDENT_HARDWARE_SOURCES = {"instrument_capture", "verified_hardware_tool"}
OBSERVATION_KINDS = {
    "logic_test", "host_test", "runtime_log", "measurement",
    "hardware_observation", "hardware_measurement", "acceptance_test",
}
STAGE_EVIDENCE_KINDS = {
    "requirements": {"authoritative_document", "document_review", "acceptance_test"},
    "design": {"design_review", "configuration_review", "document_review"},
    "resources": {"resource_report", "resource_map", "configuration_review"},
    "hardware_plan": {"design_review", "configuration_review", "resource_report", "resource_map"},
    "implementation": {"logic_test", "host_test", "runtime_log", "configuration_review"},
    "build": BUILD_EVIDENCE_KINDS,
    "hardware_acceptance": {"hardware_observation", "hardware_measurement", "acceptance_test"},
}
VALID_F103_LQFP48_PINS = {
    *(f"PA{i}" for i in range(16)), *(f"PB{i}" for i in range(16)),
    "PC13", "PC14", "PC15", "PD0", "PD1",
}
F103_AF_PINS = {
    "USB": {"PA11", "PA12"},
    "USART1": {"PA9", "PA10", "PB6", "PB7"},
    "USART2": {"PA2", "PA3"},
    "USART3": {"PB10", "PB11"},
    "I2C1": {"PB6", "PB7", "PB8", "PB9"},
    "I2C2": {"PB10", "PB11"},
    "SPI1": {"PA4", "PA5", "PA6", "PA7", "PA15", "PB3", "PB4", "PB5"},
    "SPI2": {"PB12", "PB13", "PB14", "PB15"},
    "CAN": {"PA11", "PA12", "PB8", "PB9"},
    "TIM1": {"PA8", "PA9", "PA10", "PA11", "PB13", "PB14", "PB15"},
    "TIM2": {"PA0", "PA1", "PA2", "PA3", "PA15", "PB3", "PB10", "PB11"},
    "TIM3": {"PA6", "PA7", "PB0", "PB1", "PB4", "PB5"},
    "TIM4": {"PB6", "PB7", "PB8", "PB9"},
}
F103_SIGNAL_CAPABILITIES: dict[str, tuple[set[str], str]] = {
    "GPIO_INPUT": (VALID_F103_LQFP48_PINS, "GPIO"),
    "GPIO_OUTPUT": (VALID_F103_LQFP48_PINS, "GPIO"),
    "USB_DM": ({"PA11"}, "USB"), "USB_DP": ({"PA12"}, "USB"),
    "USART1_TX": ({"PA9"}, "USART1"), "USART1_RX": ({"PA10"}, "USART1"),
    "USART2_TX": ({"PA2"}, "USART2"), "USART2_RX": ({"PA3"}, "USART2"),
    "USART3_TX": ({"PB10"}, "USART3"), "USART3_RX": ({"PB11"}, "USART3"),
    "I2C1_SCL": ({"PB6"}, "I2C1"), "I2C1_SDA": ({"PB7"}, "I2C1"),
    "I2C2_SCL": ({"PB10"}, "I2C2"), "I2C2_SDA": ({"PB11"}, "I2C2"),
    "SPI1_NSS": ({"PA4"}, "SPI1"), "SPI1_SCK": ({"PA5"}, "SPI1"),
    "SPI1_MISO": ({"PA6"}, "SPI1"), "SPI1_MOSI": ({"PA7"}, "SPI1"),
    "SPI2_NSS": ({"PB12"}, "SPI2"), "SPI2_SCK": ({"PB13"}, "SPI2"),
    "SPI2_MISO": ({"PB14"}, "SPI2"), "SPI2_MOSI": ({"PB15"}, "SPI2"),
    "TIM1_CH1": ({"PA8"}, "TIM1"), "TIM1_CH2": ({"PA9"}, "TIM1"),
    "TIM1_CH3": ({"PA10"}, "TIM1"), "TIM1_CH4": ({"PA11"}, "TIM1"),
    "TIM2_CH1": ({"PA0"}, "TIM2"), "TIM2_CH2": ({"PA1"}, "TIM2"),
    "TIM2_CH3": ({"PA2"}, "TIM2"), "TIM2_CH4": ({"PA3"}, "TIM2"),
    "TIM3_CH1": ({"PA6"}, "TIM3"), "TIM3_CH2": ({"PA7"}, "TIM3"),
    "TIM3_CH3": ({"PB0"}, "TIM3"), "TIM3_CH4": ({"PB1"}, "TIM3"),
    "TIM4_CH1": ({"PB6"}, "TIM4"), "TIM4_CH2": ({"PB7"}, "TIM4"),
    "TIM4_CH3": ({"PB8"}, "TIM4"), "TIM4_CH4": ({"PB9"}, "TIM4"),
    **{f"ADC1_IN{i}": ({f"PA{i}"}, "ANALOG") for i in range(8)},
    "ADC1_IN8": ({"PB0"}, "ANALOG"), "ADC1_IN9": ({"PB1"}, "ANALOG"),
}
DMA_FUNCTIONS = {
    "DMA1_CH1": {"ADC1"},
    "DMA1_CH2": {"SPI1_RX", "USART3_TX", "TIM1_CH1"},
    "DMA1_CH3": {"SPI1_TX", "USART3_RX", "TIM1_CH2"},
    "DMA1_CH4": {"USART1_TX", "I2C2_TX", "SPI2_RX", "TIM1_CH4"},
    "DMA1_CH5": {"USART1_RX", "I2C2_RX", "SPI2_TX", "TIM1_UP"},
    "DMA1_CH6": {"USART2_RX", "I2C1_TX", "TIM3_CH1"},
    "DMA1_CH7": {"USART2_TX", "I2C1_RX", "TIM2_CH2", "TIM4_UP"},
}
IRQ_FUNCTIONS = {
    **{f"EXTI{i}": {f"GPIO_EXTI{i}"} for i in range(5)},
    "EXTI9_5": {"GPIO_EXTI5_9"}, "EXTI15_10": {"GPIO_EXTI10_15"},
    "USART1": {"USART1"}, "USART2": {"USART2"}, "USART3": {"USART3"},
    "USB_LP_CAN1_RX0": {"USB", "CAN1_RX0"}, "USB_HP_CAN1_TX": {"USB", "CAN1_TX"},
    **{f"DMA1_CH{i}": {f"DMA1_CH{i}"} for i in range(1, 8)},
    **{f"TIM{i}": {f"TIM{i}"} for i in range(1, 5)},
}
VALID_IRQS = {
    *(f"EXTI{i}" for i in range(5)), "EXTI9_5", "EXTI15_10",
    "USART1", "USART2", "USART3", "USB_LP_CAN1_RX0", "USB_HP_CAN1_TX",
    *(f"DMA1_CH{i}" for i in range(1, 8)),
    *(f"TIM{i}" for i in range(1, 5)),
}


class ProjectError(Exception):
    def __init__(self, code: str, message: str, details: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details is not None:
            result["details"] = self.details
        return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_hash(event: dict[str, Any]) -> str:
    value = copy.deepcopy(event)
    value.pop("event_hash", None)
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        last_error: OSError | None = None
        for _ in range(200):
            try:
                os.replace(temporary, path)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.01)
        if last_error is not None:
            raise last_error
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # type: ignore[attr-defined]
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return True
        return ctypes.windll.kernel32.GetLastError() == 5  # type: ignore[attr-defined]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clear_abandoned_lock(lock_dir: Path) -> None:
    try:
        owner_path = lock_dir / "owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        pid = int(owner.get("pid", 0))
        old_enough = time.time() - owner_path.stat().st_mtime >= LOCK_STALE_SECONDS
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return
    if _pid_alive(pid) or not old_enough:
        return
    try:
        owner_path.unlink(missing_ok=True)
        lock_dir.rmdir()
    except OSError:
        return


@contextmanager
def _write_lock(project_dir: Path, timeout: float = 30.0) -> Iterator[None]:
    project_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = project_dir / ".write.lock"
    deadline = time.monotonic() + timeout
    token = uuid.uuid4().hex
    while True:
        try:
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "token": token, "created_at": _now()}), encoding="utf-8"
            )
            break
        except FileExistsError:
            _clear_abandoned_lock(lock_dir)
            if time.monotonic() >= deadline:
                raise ProjectError("lock_timeout", "项目正被另一个写入操作占用。")
            time.sleep(0.03)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise ProjectError("lock_timeout", "项目正被另一个写入操作占用。")
            time.sleep(0.03)
    try:
        yield
    finally:
        released = False
        for _ in range(200):
            try:
                (lock_dir / "owner.json").unlink(missing_ok=True)
                lock_dir.rmdir()
                released = True
                break
            except FileNotFoundError:
                released = True
                break
            except OSError:
                time.sleep(0.01)
        if not released:
            raise ProjectError("lock_release_failed", "项目写锁无法安全释放。")


def _project_dir(projects_dir: Path, project_id: str) -> Path:
    if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
        raise ProjectError("invalid_project_id", "project_id 仅允许小写字母、数字、连字符和下划线。")
    root = projects_dir.resolve()
    result = (root / project_id).resolve()
    if result.parent != root:
        raise ProjectError("invalid_project_id", "project_id 不能越过 Projects 根目录。")
    return result


def _required(payload: dict[str, Any], name: str, kind: type | tuple[type, ...]) -> Any:
    value = payload.get(name)
    if not isinstance(value, kind) or (isinstance(value, str) and not value.strip()):
        raise ProjectError("invalid_payload", f"字段 {name} 缺失或类型不正确。")
    return value


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ProjectError("invalid_payload", f"{field} 必须是字符串数组。")
    if len(set(value)) != len(value):
        raise ProjectError("invalid_payload", f"{field} 不能包含重复项。")
    return list(value)


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise ProjectError("invalid_payload", f"{field} 必须是 64 位 SHA-256 十六进制摘要。")
    return value.lower()


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in _flatten_text(key) + _flatten_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _flatten_text(item)]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    return []


def _safety_violations(
    value: Any,
    *,
    safety_context: dict[str, Any] | None = None,
    resources_context: dict[str, Any] | None = None,
) -> list[str]:
    normalized_chunks = [
        unicodedata.normalize("NFKC", item).casefold()
        for item in _flatten_text(value)
    ]
    text = " ".join(normalized_chunks)
    separated = re.sub(r"[-_‐‑‒–—―/\\\s]+", " ", text)
    compact = re.sub(r"[-_‐‑‒–—―/\\\s]+", "", text)
    violations = [f"prohibited:{term}" for term in UNSAFE_TERMS if term.casefold() in text]
    ultrasonic = "hcsr04" in compact or "ultrasonic" in compact or "超声" in text
    echo = "echo" in compact or "回波" in text
    endpoint = "gpio" in compact or "io口" in compact or bool(re.search(r"\bp[a-g]\d{1,2}\b", separated))
    mcu_wiring = endpoint or any(token in compact for token in ("stm32", "mcu", "接线", "引脚", "wiring", "pin"))
    direct = any(
        token in compact for token in (
            "直连", "直接接", "直接连", "直接相连", "直接连接", "直通", "directconnect", "connectdirect",
        )
    ) or "direct connection" in text
    motor = any(token in compact for token in ("motor", "电机", "马达"))

    def plain_connection_between(left: str, right: str, bridge_terms: tuple[str, ...]) -> bool:
        connector = r"(?:接|连接|相连|连到|接到|接入)"
        for chunk in normalized_chunks:
            candidate = re.sub(r"[-_‐‑‒–—―/\\\s]+", "", chunk)
            for first, second in ((left, right), (right, left)):
                match = re.search(
                    rf"(?:{first})(?P<path>.{{0,48}}?){connector}(?P<tail>.{{0,48}}?)(?:{second})",
                    candidate,
                )
                if match and not any(
                    bridge in match.group("path") + match.group("tail")
                    for bridge in bridge_terms
                ):
                    return True
        return False

    echo_plain_direct = plain_connection_between(
        r"(?:hcsr04|echo|回波|超声)",
        r"(?:gpio|io口|p[a-g]\d{1,2}|stm32|mcu)",
        ("分压", "电平转换", "转换器", "levelshifter", "divider"),
    )
    motor_plain_direct = plain_connection_between(
        r"(?:motor|电机|马达)",
        r"(?:gpio|io口|p[a-g]\d{1,2}|stm32|mcu)",
        ("驱动", "driver", "h桥", "hbridge", "tb6612", "l298"),
    )
    safety = safety_context if safety_context is not None else (
        value.get("safety", {}) if isinstance(value, dict) else {}
    )
    resources = resources_context if resources_context is not None else (
        value.get("resources", {}) if isinstance(value, dict) else {}
    )
    if (ultrasonic or echo) and mcu_wiring:
        interface = safety.get("echo_interface") if isinstance(safety, dict) else None
        valid_interface = isinstance(interface, dict)
        if valid_interface:
            output_v = interface.get("module_output_v")
            mcu_max_v = interface.get("mcu_max_v")
            method = interface.get("method")
            resistor_values = interface.get("resistor_values")
            source = interface.get("source")
            valid_interface = (
                isinstance(output_v, (int, float)) and not isinstance(output_v, bool) and output_v > 0
                and isinstance(mcu_max_v, (int, float)) and not isinstance(mcu_max_v, bool)
                and 0 < mcu_max_v <= 3.6
                and method in {"divider", "level_shifter"}
                and (
                    isinstance(resistor_values, dict) and bool(resistor_values)
                    and all(
                        isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount > 0
                        for amount in resistor_values.values()
                    )
                    or _meaningful_text(source)
                )
            )
        if not valid_interface:
            violations.append("echo_interface_required")
        if direct or echo_plain_direct:
            violations.append("echo_direct_mcu_connection")
    if motor and mcu_wiring:
        driver = safety.get("motor_driver") if isinstance(safety, dict) else None
        valid_driver = isinstance(driver, dict) and (
            _meaningful_text(driver.get("driver_model"))
            and _meaningful_text(driver.get("supply_domain"))
            and driver.get("separate_from_gpio") is True
            and isinstance(driver.get("peak_current_ma"), (int, float))
            and not isinstance(driver.get("peak_current_ma"), bool)
            and driver["peak_current_ma"] > 0
            and _meaningful_text(driver.get("stop_method"))
        )
        components = resources.get("components", []) if isinstance(resources, dict) else []
        driver_model = driver.get("driver_model", "") if isinstance(driver, dict) else ""
        inventory_has_driver = any(
            isinstance(component, dict)
            and _meaningful_text(component.get("name"))
            and _meaningful_text(component.get("model"))
            and (
                "driver" in unicodedata.normalize("NFKC", component["name"]).casefold()
                or "驱动" in component["name"]
            )
            and unicodedata.normalize("NFKC", component["model"]).casefold()
            == unicodedata.normalize("NFKC", str(driver_model)).casefold()
            for component in components
        )
        if not valid_driver:
            violations.append("motor_driver_required")
        elif not inventory_has_driver:
            violations.append("motor_driver_missing_from_inventory")
        if direct or motor_plain_direct:
            violations.append("motor_direct_gpio_connection")
    # Retain direct legacy variants as fail-closed detection even when a payload
    # omits the rest of the project intake context.
    if (ultrasonic or echo) and endpoint and (direct or echo_plain_direct):
        violations.append("echo_direct_mcu_connection")
    if endpoint and motor and (direct or motor_plain_direct):
        violations.append("gpio_direct_motor")
    return list(dict.fromkeys(violations))


def _target_signature(intake: dict[str, Any]) -> str:
    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in sorted(value.items())}
        return re.sub(r"\s+", " ", str(value).strip()).casefold()

    target = intake["exact_target"]
    normalized: dict[str, Any] = {
        field: normalize(target[field])
        for field in ("mcu", "package", "board", "board_revision", "toolchain")
    }
    identity = intake.get("hardware_identity")
    if isinstance(identity, dict):
        normalized["board_evidence_hash"] = normalize(identity["board_evidence_hash"])
        normalized["flash_capacity_bytes"] = identity["flash_capacity_bytes"]
    return hashlib.sha256(_canonical(normalized).encode("utf-8")).hexdigest()


def _meaningful_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = unicodedata.normalize("NFKC", value).strip()
    return bool(normalized and any(character.isalnum() for character in normalized)) and not any(
        term in normalized.casefold() for term in UNKNOWN_TERMS
    )


def _toolchain_complete(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"ide", "firmware_package", "compiler", "programmer"}:
        return False
    for field in ("ide", "firmware_package", "compiler"):
        item = value.get(field)
        if not isinstance(item, dict) or set(item) != {"name", "version"}:
            return False
        if not _meaningful_text(item.get("name")) or not _meaningful_text(item.get("version")):
            return False
    programmer = value.get("programmer")
    if not isinstance(programmer, dict) or set(programmer) - {"name", "version"} or "name" not in programmer:
        return False
    return _meaningful_text(programmer.get("name")) and (
        "version" not in programmer or _meaningful_text(programmer.get("version"))
    )


def _normalise_toolchain(value: Any) -> dict[str, Any]:
    if not _toolchain_complete(value):
        raise ProjectError(
            "invalid_intake",
            "exact_target.toolchain 必须分别给出 IDE、固件包、编译器和烧录器的名称/版本结构。",
        )
    return copy.deepcopy(value)


def _strict_object(value: Any, field: str, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectError("invalid_intake", f"{field} 必须是对象。")
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        raise ProjectError(
            "invalid_intake", f"{field} 字段不完整或包含未授权字段。", {"missing": missing, "extra": extra},
        )
    return copy.deepcopy(value)


def _meaningful_required(value: Any, field: str) -> str:
    if not _meaningful_text(value):
        raise ProjectError("invalid_intake", f"{field} 必须是非占位文本。")
    return unicodedata.normalize("NFKC", value).strip()


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProjectError("invalid_intake", f"{field} 必须是正整数。")
    return value


def _normalise_intake_extensions(result: dict[str, Any]) -> None:
    if "hardware_identity" in result:
        identity = _strict_object(
            result["hardware_identity"], "hardware_identity",
            {
                "mcu", "package", "board", "board_revision", "board_evidence_hash",
                "flash_capacity_bytes", "photo_refs", "datasheet_refs",
            },
        )
        for field in ("mcu", "package", "board", "board_revision"):
            identity[field] = _meaningful_required(identity[field], f"hardware_identity.{field}")
        identity["photo_refs"] = _string_list(identity["photo_refs"], "hardware_identity.photo_refs", allow_empty=False)
        identity["datasheet_refs"] = _string_list(identity["datasheet_refs"], "hardware_identity.datasheet_refs", allow_empty=False)
        if not isinstance(identity["board_evidence_hash"], str) or not HASH_RE.fullmatch(identity["board_evidence_hash"]):
            raise ProjectError("invalid_intake", "hardware_identity.board_evidence_hash 必须是 64 位 SHA-256 摘要。")
        identity["board_evidence_hash"] = identity["board_evidence_hash"].lower()
        capacity = _positive_int(identity["flash_capacity_bytes"], "hardware_identity.flash_capacity_bytes")
        if not 1024 <= capacity <= 2 * 1024 * 1024:
            raise ProjectError(
                "invalid_intake", "hardware_identity.flash_capacity_bytes 必须在 1 KiB 到 2 MiB 之间。",
            )
        identity["flash_capacity_bytes"] = capacity
        result["hardware_identity"] = identity

    if "execution_profile" in result:
        profile = _strict_object(
            result["execution_profile"], "execution_profile",
            {"toolchain", "build_system", "probe", "serial", "allowed_actions"},
        )
        profile["toolchain"] = _meaningful_required(profile["toolchain"], "execution_profile.toolchain")
        profile["build_system"] = _meaningful_required(profile["build_system"], "execution_profile.build_system")
        probe = _strict_object(profile["probe"], "execution_profile.probe", {"kind", "serial"})
        probe["kind"] = _meaningful_required(probe["kind"], "execution_profile.probe.kind")
        probe["serial"] = _meaningful_required(probe["serial"], "execution_profile.probe.serial")
        serial = _strict_object(profile["serial"], "execution_profile.serial", {"identity", "baudrate"})
        serial["identity"] = _meaningful_required(serial["identity"], "execution_profile.serial.identity")
        serial["baudrate"] = _positive_int(serial["baudrate"], "execution_profile.serial.baudrate")
        actions = _string_list(profile["allowed_actions"], "execution_profile.allowed_actions", allow_empty=False)
        unsupported = sorted(set(actions) - EXECUTION_ACTIONS)
        if unsupported:
            raise ProjectError("invalid_intake", "execution_profile.allowed_actions 包含未授权动作。", unsupported)
        profile.update({"probe": probe, "serial": serial, "allowed_actions": actions})
        result["execution_profile"] = profile

    if "test_contract" in result:
        contract = _strict_object(
            result["test_contract"], "test_contract",
            {"startup_timeout_ms", "serial_protocol", "assertions", "measurement_tolerance", "timeout_ms"},
        )
        contract["startup_timeout_ms"] = _positive_int(contract["startup_timeout_ms"], "test_contract.startup_timeout_ms")
        contract["timeout_ms"] = _positive_int(contract["timeout_ms"], "test_contract.timeout_ms")
        contract["serial_protocol"] = _meaningful_required(contract["serial_protocol"], "test_contract.serial_protocol")
        assertions = contract["assertions"]
        if not isinstance(assertions, list) or not assertions:
            raise ProjectError("invalid_intake", "test_contract.assertions 必须是非空对象数组。")
        normalized_assertions: list[dict[str, str]] = []
        assertion_ids: set[str] = set()
        for index, assertion in enumerate(assertions):
            item = _strict_object(assertion, f"test_contract.assertions[{index}]", {"assertion_id", "expression"})
            assertion_id = _meaningful_required(item["assertion_id"], f"test_contract.assertions[{index}].assertion_id")
            if assertion_id in assertion_ids:
                raise ProjectError("invalid_intake", "test_contract assertion_id 不能重复。")
            assertion_ids.add(assertion_id)
            normalized_assertions.append({
                "assertion_id": assertion_id,
                "expression": _meaningful_required(item["expression"], f"test_contract.assertions[{index}].expression"),
            })
        tolerance = contract["measurement_tolerance"]
        if not isinstance(tolerance, dict) or not tolerance:
            raise ProjectError("invalid_intake", "test_contract.measurement_tolerance 必须是非空对象。")
        normalized_tolerance: dict[str, float | int] = {}
        for name, amount in tolerance.items():
            if not _meaningful_text(name) or not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
                raise ProjectError("invalid_intake", "measurement_tolerance 必须由非负数值组成。")
            normalized_tolerance[name] = amount
        contract.update({"assertions": normalized_assertions, "measurement_tolerance": normalized_tolerance})
        result["test_contract"] = contract

    if "eda_profile" in result:
        profile = _strict_object(
            result["eda_profile"], "eda_profile",
            {"board_outline", "layer_count", "design_rules", "manufacturer", "assembly", "mechanical_constraints"},
        )
        outline = _strict_object(profile["board_outline"], "eda_profile.board_outline", {"width_mm", "height_mm"})
        if any(
            not isinstance(outline[field], (int, float)) or isinstance(outline[field], bool) or outline[field] <= 0
            for field in ("width_mm", "height_mm")
        ):
            raise ProjectError("invalid_intake", "eda_profile.board_outline 尺寸必须为正数。")
        if profile["layer_count"] not in {2, 4, 6, 8}:
            raise ProjectError("invalid_intake", "eda_profile.layer_count 只支持 2、4、6、8 层。")
        rules = profile["design_rules"]
        if not isinstance(rules, dict) or not rules or any(
            not _meaningful_text(name) or not isinstance(amount, (int, float))
            or isinstance(amount, bool) or amount <= 0 for name, amount in rules.items()
        ):
            raise ProjectError("invalid_intake", "eda_profile.design_rules 必须是正数规则对象。")
        profile["manufacturer"] = _meaningful_required(profile["manufacturer"], "eda_profile.manufacturer")
        profile["assembly"] = _meaningful_required(profile["assembly"], "eda_profile.assembly")
        profile["mechanical_constraints"] = _string_list(
            profile["mechanical_constraints"], "eda_profile.mechanical_constraints"
        )
        profile.update({"board_outline": outline, "design_rules": copy.deepcopy(rules)})
        result["eda_profile"] = profile

    if "cloud_policy" in result:
        policy = _strict_object(
            result["cloud_policy"], "cloud_policy",
            {"flux_upload_allowed", "authoritative_source", "approved_data_classes"},
        )
        if not isinstance(policy["flux_upload_allowed"], bool):
            raise ProjectError("invalid_intake", "cloud_policy.flux_upload_allowed 必须是布尔值。")
        if policy["authoritative_source"] != "kicad":
            raise ProjectError("invalid_intake", "cloud_policy.authoritative_source 必须为 kicad。")
        policy["approved_data_classes"] = _string_list(
            policy["approved_data_classes"], "cloud_policy.approved_data_classes"
        )
        result["cloud_policy"] = policy


def _normalise_resources(value: Any) -> dict[str, Any]:
    if value is None:
        return {"components": [], "budget": None, "time_limit": None}
    if not isinstance(value, dict):
        raise ProjectError("invalid_intake", "resources 必须是对象。")
    components = value.get("components", [])
    if not isinstance(components, list):
        raise ProjectError("invalid_intake", "resources.components 必须是对象数组。")
    normalized_components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise ProjectError("invalid_intake", "resources.components 不能使用字符串占位。")
        component_id = component.get("component_id")
        name = component.get("name")
        model = component.get("model")
        quantity = component.get("quantity")
        if not all(_meaningful_text(item) for item in (component_id, name, model)):
            raise ProjectError("invalid_intake", "component_id/name/model 必须是非占位文本。")
        if component_id in seen or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ProjectError("invalid_intake", "component_id 必须唯一且 quantity 必须为正整数。")
        seen.add(component_id)
        normalized_components.append({
            "component_id": component_id.strip(), "name": name.strip(),
            "model": model.strip(), "quantity": quantity,
        })
    budget = value.get("budget")
    if budget is not None:
        if not isinstance(budget, dict) or set(budget) != {"amount", "currency"}:
            raise ProjectError("invalid_intake", "resources.budget 必须包含 amount 和 currency。")
        if isinstance(budget.get("amount"), bool) or not isinstance(budget.get("amount"), (int, float)) or budget["amount"] <= 0:
            raise ProjectError("invalid_intake", "resources.budget.amount 必须大于 0。")
        if not _meaningful_text(budget.get("currency")):
            raise ProjectError("invalid_intake", "resources.budget.currency 必须是非占位文本。")
        budget = {"amount": budget["amount"], "currency": budget["currency"].strip().upper()}
    time_limit = value.get("time_limit")
    if time_limit is not None:
        if not isinstance(time_limit, dict) or set(time_limit) != {"hours", "deadline"}:
            raise ProjectError("invalid_intake", "resources.time_limit 必须包含 hours 和 deadline。")
        if isinstance(time_limit.get("hours"), bool) or not isinstance(time_limit.get("hours"), (int, float)) or time_limit["hours"] <= 0:
            raise ProjectError("invalid_intake", "resources.time_limit.hours 必须大于 0。")
        if not _meaningful_text(time_limit.get("deadline")):
            raise ProjectError("invalid_intake", "resources.time_limit.deadline 必须是非占位文本。")
        time_limit = {"hours": time_limit["hours"], "deadline": time_limit["deadline"].strip()}
    return {"components": normalized_components, "budget": budget, "time_limit": time_limit}


def _normalise_procurement(value: Any) -> dict[str, Any] | None:
    """Normalize the pre-purchase decision record without claiming physical ownership."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProjectError("invalid_intake", "procurement 必须是对象。")
    inventory_status = value.get("inventory_status", "existing_or_unspecified")
    if inventory_status not in {"none_owned", "partial", "ready", "existing_or_unspecified"}:
        raise ProjectError("invalid_intake", "procurement.inventory_status 枚举无效。")
    requirements_confirmation = value.get("requirements_confirmation", "pending")
    selection_confirmation = value.get("selection_confirmation", "pending")
    shopping_list_confirmation = value.get("shopping_list_confirmation", "pending")
    for field, status in (
        ("requirements_confirmation", requirements_confirmation),
        ("selection_confirmation", selection_confirmation),
        ("shopping_list_confirmation", shopping_list_confirmation),
    ):
        if status not in {"pending", "confirmed"}:
            raise ProjectError("invalid_intake", f"procurement.{field} 必须是 pending 或 confirmed。")

    raw_options = value.get("solution_options", [])
    if not isinstance(raw_options, list) or len(raw_options) > 3:
        raise ProjectError("invalid_intake", "procurement.solution_options 必须是最多 3 项的数组。")
    options: list[dict[str, Any]] = []
    option_ids: set[str] = set()
    for raw in raw_options:
        if not isinstance(raw, dict):
            raise ProjectError("invalid_intake", "solution_options 每项必须是对象。")
        option_id = _meaningful_required(raw.get("option_id"), "procurement.solution_options.option_id")
        if option_id in option_ids:
            raise ProjectError("invalid_intake", "solution_options.option_id 必须唯一。")
        option_ids.add(option_id)
        total = raw.get("estimated_total")
        if total is not None:
            if not isinstance(total, dict) or set(total) != {"amount", "currency"}:
                raise ProjectError("invalid_intake", "solution_options.estimated_total 必须包含 amount/currency。")
            if isinstance(total.get("amount"), bool) or not isinstance(total.get("amount"), (int, float)) or total["amount"] <= 0:
                raise ProjectError("invalid_intake", "solution_options.estimated_total.amount 必须大于 0。")
            total = {
                "amount": total["amount"],
                "currency": _meaningful_required(total.get("currency"), "estimated_total.currency").upper(),
            }
        recommended = raw.get("recommended", False)
        if not isinstance(recommended, bool):
            raise ProjectError("invalid_intake", "solution_options.recommended 必须是布尔值。")
        options.append({
            "option_id": option_id,
            "name": _meaningful_required(raw.get("name"), "procurement.solution_options.name"),
            "positioning": _meaningful_required(raw.get("positioning"), "procurement.solution_options.positioning"),
            "pros": _string_list(raw.get("pros", []), "procurement.solution_options.pros", allow_empty=False),
            "cons": _string_list(raw.get("cons", []), "procurement.solution_options.cons", allow_empty=False),
            "estimated_total": total,
            "recommended": recommended,
            "recommendation_reason": _meaningful_required(
                raw.get("recommendation_reason"), "procurement.solution_options.recommendation_reason"
            ),
        })
    if options and sum(1 for option in options if option["recommended"]) != 1:
        raise ProjectError("invalid_intake", "存在候选方案时必须且只能标记一个 Recommended。")

    selected_option_id = value.get("selected_option_id")
    if selected_option_id is not None:
        selected_option_id = _meaningful_required(selected_option_id, "procurement.selected_option_id")
        if selected_option_id not in option_ids:
            raise ProjectError("invalid_intake", "selected_option_id 必须引用已有方案。")
    if selection_confirmation == "confirmed" and selected_option_id is None:
        raise ProjectError("invalid_intake", "确认方案前必须提供 selected_option_id。")

    raw_items = value.get("shopping_list", [])
    if not isinstance(raw_items, list):
        raise ProjectError("invalid_intake", "procurement.shopping_list 必须是对象数组。")
    items: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ProjectError("invalid_intake", "shopping_list 每项必须是对象。")
        item_id = _meaningful_required(raw.get("item_id"), "procurement.shopping_list.item_id")
        if item_id in item_ids:
            raise ProjectError("invalid_intake", "shopping_list.item_id 必须唯一。")
        item_ids.add(item_id)
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ProjectError("invalid_intake", "shopping_list.quantity 必须为正整数。")
        priority = raw.get("priority")
        if priority not in {"required", "recommended", "optional"}:
            raise ProjectError("invalid_intake", "shopping_list.priority 枚举无效。")
        purchase_batch = raw.get("purchase_batch")
        if purchase_batch not in {"now", "after_prototype"}:
            raise ProjectError("invalid_intake", "shopping_list.purchase_batch 枚举无效。")
        purchase_status = raw.get("purchase_status", "planned")
        if purchase_status not in {"planned", "ordered", "received", "verified", "mismatch"}:
            raise ProjectError("invalid_intake", "shopping_list.purchase_status 枚举无效。")
        items.append({
            "item_id": item_id,
            "category": _meaningful_required(raw.get("category"), "procurement.shopping_list.category"),
            "exact_model": _meaningful_required(raw.get("exact_model"), "procurement.shopping_list.exact_model"),
            "quantity": quantity,
            "priority": priority,
            "purchase_batch": purchase_batch,
            "selection_reason": _meaningful_required(
                raw.get("selection_reason"), "procurement.shopping_list.selection_reason"
            ),
            "critical_specs": _string_list(
                raw.get("critical_specs", []), "procurement.shopping_list.critical_specs", allow_empty=False
            ),
            "allowed_substitutes": _string_list(
                raw.get("allowed_substitutes", []), "procurement.shopping_list.allowed_substitutes"
            ),
            "avoid": _string_list(raw.get("avoid", []), "procurement.shopping_list.avoid"),
            "purchase_status": purchase_status,
            "source_refs": _string_list(raw.get("source_refs", []), "procurement.shopping_list.source_refs"),
        })
    if shopping_list_confirmation == "confirmed" and not items:
        raise ProjectError("invalid_intake", "确认购物清单前必须至少有一项物料。")
    return {
        "inventory_status": inventory_status,
        "requirements_confirmation": requirements_confirmation,
        "solution_options": options,
        "selected_option_id": selected_option_id,
        "selection_confirmation": selection_confirmation,
        "shopping_list": items,
        "shopping_list_confirmation": shopping_list_confirmation,
    }


def _normalise_resource_plan(value: Any, target: dict[str, Any]) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ProjectError("invalid_intake", "resource_plan 必须是对象。")
    result = copy.deepcopy(value)
    for field in ("pins", "dma", "irqs"):
        result.setdefault(field, [])
        if not isinstance(result[field], list) or not all(isinstance(item, dict) for item in result[field]):
            raise ProjectError("invalid_intake", f"resource_plan.{field} 必须是对象数组。")
    result.setdefault("clocks", {})
    result.setdefault("flash_bytes", None)
    result.setdefault("ram_bytes", None)
    result.setdefault("power", {"rails": [], "loads": []})
    if not isinstance(result["clocks"], dict) or not isinstance(result["power"], dict):
        raise ProjectError("invalid_intake", "resource_plan clocks/power 必须是对象。")
    if any(isinstance(item, bool) or not isinstance(item, (int, float, str)) for item in result["clocks"].values()):
        raise ProjectError("invalid_intake", "resource_plan.clocks 的值必须是数字或字符串。")
    power = result["power"]
    power.setdefault("rails", [])
    power.setdefault("loads", [])
    if not all(isinstance(power[field], list) and all(isinstance(item, dict) for item in power[field]) for field in ("rails", "loads")):
        raise ProjectError("invalid_intake", "resource_plan.power rails/loads 必须是对象数组。")
    for pin in result["pins"]:
        for field in ("pin", "signal", "function", "alternate_function"):
            if not isinstance(pin.get(field), str) or not pin[field].strip():
                raise ProjectError("invalid_intake", f"resource_plan.pins.{field} 必须是字符串。")
            pin[field] = pin[field].strip().upper()
            if field != "pin" and not _meaningful_text(pin[field]):
                raise ProjectError("invalid_intake", f"resource_plan.pins.{field} 不能是占位值。")
        if pin["pin"] == "UNKNOWN":
            continue
        if "STM32F103C8" in str(target.get("mcu", "")).upper() and pin["pin"] not in VALID_F103_LQFP48_PINS:
            raise ProjectError("invalid_intake", f"{pin['pin']} 不是 STM32F103C8 LQFP48 可用 GPIO。")
        capability = F103_SIGNAL_CAPABILITIES.get(pin["signal"])
        if capability is None:
            raise ProjectError("invalid_intake", f"不支持或不明确的 signal：{pin['signal']}")
        legal_pins, required_af = capability
        if pin["pin"] not in legal_pins or pin["alternate_function"] != required_af:
            raise ProjectError(
                "invalid_intake", f"{pin['signal']} 不支持 {pin['pin']}/{pin['alternate_function']}。"
            )
    for item, id_field, label in (
        (result["dma"], "channel", "dma"), (result["irqs"], "irq", "irqs")
    ):
        for entry in item:
            if not isinstance(entry.get(id_field), str) or not isinstance(entry.get("function"), str):
                raise ProjectError("invalid_intake", f"resource_plan.{label} 字段类型无效。")
            entry[id_field] = entry[id_field].strip().upper()
            entry["function"] = entry["function"].strip().upper()
            if not entry[id_field] or not entry["function"] or any(
                term in entry[id_field].casefold() or term in entry["function"].casefold()
                for term in UNKNOWN_TERMS
            ) or any(term in entry["function"] for term in ("IMPOSSIBLE", "INVALID")):
                raise ProjectError("invalid_intake", f"resource_plan.{label} 不允许空值或 unknown。")
            if id_field == "channel" and not re.fullmatch(r"DMA1_CH[1-7]", entry[id_field]):
                raise ProjectError("invalid_intake", f"非法 DMA channel：{entry[id_field]}")
            if id_field == "irq" and entry[id_field] not in VALID_IRQS:
                raise ProjectError("invalid_intake", f"非法 IRQ：{entry[id_field]}")
            allowed = DMA_FUNCTIONS.get(entry[id_field]) if id_field == "channel" else IRQ_FUNCTIONS.get(entry[id_field])
            if allowed is None or entry["function"] not in allowed:
                raise ProjectError(
                    "invalid_intake", f"{entry[id_field]} 与 function {entry['function']} 不相容。"
                )
    clocks = result["clocks"]
    for field, maximum in (
        ("sysclk_hz", 72_000_000), ("hclk_hz", 72_000_000),
        ("pclk1_hz", 36_000_000), ("pclk2_hz", 72_000_000),
    ):
        amount = clocks.get(field)
        if amount is not None and (
            isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0 or amount > maximum
        ):
            raise ProjectError("invalid_intake", f"resource_plan.clocks.{field} 超出 STM32F103 范围。")
    if isinstance(clocks.get("hclk_hz"), (int, float)) and isinstance(clocks.get("sysclk_hz"), (int, float)):
        if clocks["hclk_hz"] > clocks["sysclk_hz"]:
            raise ProjectError("invalid_intake", "HCLK 不能高于 SYSCLK。")
    if isinstance(clocks.get("hclk_hz"), (int, float)):
        for field in ("pclk1_hz", "pclk2_hz"):
            if isinstance(clocks.get(field), (int, float)) and clocks[field] > clocks["hclk_hz"]:
                raise ProjectError("invalid_intake", f"{field.upper()} 不能高于 HCLK。")
    for field in ("flash_bytes", "ram_bytes"):
        amount = result[field]
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int) or amount < 0):
            raise ProjectError("invalid_intake", f"resource_plan.{field} 必须是非负整数。")
    return result


def _resource_blockers(intake: dict[str, Any]) -> list[str]:
    plan = intake["resource_plan"]
    blockers: list[str] = []
    for items, field, prefix in (
        (plan["pins"], "pin", "pin_conflict"),
        (plan["dma"], "channel", "dma_conflict"),
        (plan["irqs"], "irq", "irq_conflict"),
    ):
        seen: set[str] = set()
        for item in items:
            identifier = item[field]
            if identifier in seen:
                blockers.append(f"{prefix}:{identifier}")
            seen.add(identifier)
    af_seen: set[str] = set()
    for item in plan["pins"]:
        alternate = item["alternate_function"]
        signal = item["function"]
        if alternate not in {"GPIO", "ANALOG"} and signal in af_seen:
            blockers.append(f"af_conflict:{signal}")
        if alternate not in {"GPIO", "ANALOG"}:
            af_seen.add(signal)
    usb_used = any("USB" in item["function"] or "USB" in item["alternate_function"] for item in plan["pins"])
    if usb_used and plan["clocks"].get("usb_hz") != 48_000_000:
        blockers.append("usb_clock_not_48mhz")
    for field in ("sysclk_hz", "hclk_hz", "pclk1_hz", "pclk2_hz"):
        if not isinstance(plan["clocks"].get(field), (int, float)) or isinstance(plan["clocks"].get(field), bool):
            blockers.append(f"clock_unknown:{field}")
    if any(item["pin"] == "UNKNOWN" for item in plan["pins"]):
        blockers.append("pin_unknown")
    if "STM32F103C8" in intake["exact_target"]["mcu"].upper():
        if plan.get("flash_bytes") is not None and plan["flash_bytes"] > 64 * 1024:
            blockers.append("flash_over_budget")
        if plan.get("ram_bytes") is not None and plan["ram_bytes"] > 20 * 1024:
            blockers.append("ram_over_budget")
    rails: dict[str, dict[str, Any]] = {}
    for rail in plan["power"]["rails"]:
        name = rail.get("name")
        if not isinstance(name, str) or not name.strip():
            blockers.append("power_rail_unknown")
            continue
        name = name.strip().upper()
        if name in rails:
            blockers.append(f"power_rail_conflict:{name}")
        rails[name] = rail
        for field in ("voltage", "max_current_ma"):
            if isinstance(rail.get(field), bool) or not isinstance(rail.get(field), (int, float)) or rail[field] <= 0:
                blockers.append(f"power_rail_unknown:{name}:{field}")
    totals: dict[str, float] = {}
    for load in plan["power"]["loads"]:
        rail_name = str(load.get("rail", "")).strip().upper()
        if not rail_name or rail_name not in rails:
            blockers.append(f"power_load_unknown:{rail_name or 'rail'}")
            continue
        for field in ("voltage", "current_ma"):
            if isinstance(load.get(field), bool) or not isinstance(load.get(field), (int, float)) or load[field] < 0:
                blockers.append(f"power_load_unknown:{load.get('name', 'load')}:{field}")
        if isinstance(load.get("current_ma"), (int, float)) and not isinstance(load.get("current_ma"), bool):
            totals[rail_name] = totals.get(rail_name, 0.0) + float(load["current_ma"])
        if isinstance(load.get("voltage"), (int, float)) and isinstance(rails[rail_name].get("voltage"), (int, float)):
            if abs(float(load["voltage"]) - float(rails[rail_name]["voltage"])) > 0.1:
                blockers.append(f"power_voltage_mismatch:{rail_name}")
    for rail_name, total in totals.items():
        capacity = rails[rail_name].get("max_current_ma")
        if isinstance(capacity, (int, float)) and total > float(capacity):
            blockers.append(f"power_insufficient:{rail_name}")
    if not plan["power"]["rails"]:
        blockers.append("power_rails_unknown")
    if not plan["power"]["loads"]:
        blockers.append("power_loads_unknown")
    if plan.get("flash_bytes") is None:
        blockers.append("flash_bytes_unknown")
    if plan.get("ram_bytes") is None:
        blockers.append("ram_bytes_unknown")
    return list(dict.fromkeys(blockers))


def _normalise_requirements(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectError("invalid_intake", "requirements 必须是可追踪需求数组。")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value, 1):
        if isinstance(item, str) and item.strip():
            item = {"requirement_id": f"R{index}", "text": item, "acceptance_ids": []}
        if not isinstance(item, dict):
            raise ProjectError("invalid_intake", "每项 requirement 必须是对象。")
        requirement_id = item.get("requirement_id")
        text = item.get("text")
        if not isinstance(requirement_id, str) or not requirement_id or requirement_id in seen:
            raise ProjectError("invalid_intake", "requirement_id 缺失或重复。")
        if not isinstance(text, str) or not text.strip():
            raise ProjectError("invalid_intake", "需求 text 不能为空。")
        acceptance_ids = _string_list(item.get("acceptance_ids", []), "acceptance_ids")
        if not acceptance_ids:
            raise ProjectError("invalid_intake", "每条需求必须引用至少一个 acceptance_id。")
        seen.add(requirement_id)
        result.append({"requirement_id": requirement_id, "text": text, "acceptance_ids": acceptance_ids})
    return result


def _normalise_acceptance(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectError("invalid_intake", "acceptance_criteria 必须是可观察验收数组。")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value, 1):
        if isinstance(item, str) and item.strip():
            item = {"acceptance_id": f"A{index}", "text": item, "requires_hardware": False}
        if not isinstance(item, dict):
            raise ProjectError("invalid_intake", "每项 acceptance criterion 必须是对象。")
        acceptance_id = item.get("acceptance_id")
        text = item.get("text")
        if not isinstance(acceptance_id, str) or not acceptance_id or acceptance_id in seen:
            raise ProjectError("invalid_intake", "acceptance_id 缺失或重复。")
        if not isinstance(text, str) or not text.strip():
            raise ProjectError("invalid_intake", "验收 text 不能为空。")
        requires_hardware = item.get("requires_hardware", False)
        if not isinstance(requires_hardware, bool):
            raise ProjectError("invalid_intake", "requires_hardware 只能是布尔值。")
        seen.add(acceptance_id)
        metric = item.get("metric")
        operator = item.get("operator")
        threshold = item.get("threshold")
        unit = item.get("unit")
        window = item.get("window")
        observation_method = item.get("observation_method")
        if metric is not None and (not isinstance(metric, str) or not metric.strip()):
            raise ProjectError("invalid_intake", "acceptance.metric 必须是非空字符串。")
        if operator is not None and operator not in {"eq", "ne", "lt", "lte", "gt", "gte", "between"}:
            raise ProjectError("invalid_intake", "acceptance.operator 枚举无效。")
        if threshold is not None:
            numeric = isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
            ranged = (
                isinstance(threshold, dict)
                and any(field in threshold for field in ("min", "max"))
                and all(
                    isinstance(threshold[field], (int, float)) and not isinstance(threshold[field], bool)
                    for field in threshold if field in {"min", "max"}
                )
            )
            if not numeric and not ranged:
                raise ProjectError("invalid_intake", "acceptance.threshold 必须是数字或 min/max 范围。")
            if ranged and "min" in threshold and "max" in threshold and threshold["min"] > threshold["max"]:
                raise ProjectError("invalid_intake", "acceptance.threshold min 不能大于 max。")
        if unit is not None and (not isinstance(unit, str) or not unit.strip()):
            raise ProjectError("invalid_intake", "acceptance.unit 必须是非空字符串。")
        if window is not None:
            valid_window = (
                isinstance(window, dict)
                and (
                    (
                        isinstance(window.get("samples"), int)
                        and not isinstance(window.get("samples"), bool)
                        and window["samples"] > 0
                    )
                    or (
                        isinstance(window.get("duration"), (int, float))
                        and not isinstance(window.get("duration"), bool)
                        and window["duration"] > 0
                        and _meaningful_text(window.get("unit"))
                    )
                )
            )
            if not valid_window:
                raise ProjectError("invalid_intake", "window 必须包含正数 samples 或 duration+unit。")
        if observation_method is not None and observation_method not in {
            "instrument", "serial_log", "logic_test", "visual_observation", "bus_capture", "host_test"
        }:
            raise ProjectError("invalid_intake", "observation_method 枚举无效。")
        result.append({
            "acceptance_id": acceptance_id,
            "text": text,
            "requires_hardware": requires_hardware,
            "metric": metric.strip() if isinstance(metric, str) else None,
            "operator": operator,
            "threshold": copy.deepcopy(threshold),
            "unit": unit.strip() if isinstance(unit, str) else None,
            "window": copy.deepcopy(window),
            "observation_method": observation_method,
        })
    return result


def _validate_intake(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectError("invalid_intake", "ProjectIntake 必须是 JSON 对象。")
    result = copy.deepcopy(value)
    goal = result.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ProjectError("invalid_intake", "goal 不能为空。")
    unsafe = _safety_violations(value)
    if unsafe:
        raise ProjectError("blocked_safety", "项目输入触发不可覆盖的安全边界。", unsafe)
    _normalise_intake_extensions(result)
    result["requirements"] = _normalise_requirements(result.get("requirements"))
    result["acceptance_criteria"] = _normalise_acceptance(result.get("acceptance_criteria"))
    acceptance_ids = {item["acceptance_id"] for item in result["acceptance_criteria"]}
    bad_refs = sorted({ref for item in result["requirements"] for ref in item["acceptance_ids"] if ref not in acceptance_ids})
    if bad_refs:
        raise ProjectError("invalid_intake", "需求引用了不存在的验收项。", bad_refs)
    target = result.get("exact_target", {})
    if not isinstance(target, dict):
        raise ProjectError("invalid_intake", "exact_target 必须是对象。")
    provided_target_fields = set(target)
    derived_unknown_fields = set(result.get("_unknown_target_fields", []))
    for field in ("mcu", "package", "board", "board_revision", "toolchain"):
        target.setdefault(field, "unknown")
        if field == "toolchain" and isinstance(target[field], dict):
            target[field] = _normalise_toolchain(target[field])
            continue
        if field == "toolchain" and field in provided_target_fields and field not in derived_unknown_fields:
            raise ProjectError("invalid_intake", "exact_target.toolchain 只接受结构化对象。")
        if not isinstance(target[field], str) or not target[field].strip():
            raise ProjectError("invalid_intake", f"exact_target.{field} 必须是字符串或受支持结构。")
        normalized_target = unicodedata.normalize("NFKC", target[field]).strip()
        if field in provided_target_fields and field not in derived_unknown_fields and (
            not any(character.isalnum() for character in normalized_target)
            or any(term in normalized_target.casefold() for term in UNKNOWN_TERMS)
        ):
            raise ProjectError("invalid_intake", f"exact_target.{field} 不能是 unknown、TBD 或纯标点。")
        target[field] = normalized_target
    result["_unknown_target_fields"] = sorted(
        derived_unknown_fields | ({"mcu", "package", "board", "board_revision", "toolchain"} - provided_target_fields)
    )
    resources = _normalise_resources(result.get("resources"))
    procurement = _normalise_procurement(result.get("procurement"))
    result["resource_plan"] = _normalise_resource_plan(result.get("resource_plan"), target)
    safety = result.get("safety", {"status": "pending"})
    if not isinstance(safety, dict) or safety.get("status", "pending") not in {"pending", "passed", "blocked"}:
        raise ProjectError("invalid_intake", "safety.status 必须是 pending、passed 或 blocked。")
    safety.setdefault("status", "pending")
    safety["gates"] = _string_list(safety.get("gates", []), "safety.gates")
    safety["blocked_reasons"] = _string_list(safety.get("blocked_reasons", []), "safety.blocked_reasons")
    questions = _string_list(result.get("clarification_questions", []), "clarification_questions")
    result["exact_target"] = target
    identity = result.get("hardware_identity")
    if isinstance(identity, dict):
        for field in ("mcu", "package", "board", "board_revision"):
            if identity[field].casefold() != str(target[field]).casefold():
                raise ProjectError(
                    "invalid_intake",
                    f"hardware_identity.{field} 必须与 exact_target.{field} 完全对应。",
                )
    result["resources"] = resources
    if procurement is not None:
        if procurement["requirements_confirmation"] == "confirmed" and (
            not result["requirements"] or not result["acceptance_criteria"]
        ):
            raise ProjectError("invalid_intake", "确认需求说明前必须存在需求与验收标准。")
        result["procurement"] = procurement
    else:
        result.pop("procurement", None)
    result["safety"] = safety
    procurement_next_action = None
    zero_hardware = procurement is not None and procurement["inventory_status"] == "none_owned"
    if not questions and zero_hardware:
        if not result["requirements"] or not result["acceptance_criteria"]:
            questions.append("请补充使用场景、主要功能和怎样才算成功；技术型号由导师提案。")
        elif procurement["requirements_confirmation"] != "confirmed":
            questions.append("请确认 AI 整理的需求说明是否准确，或指出要修改的内容？")
        elif len(procurement["solution_options"]) < 2:
            procurement_next_action = "AI 根据已确认需求生成 2–3 套硬件方案卡并标出推荐项"
        elif procurement["selection_confirmation"] != "confirmed":
            questions.append("请从方案卡中选择一项，或直接确认 Recommended 方案？")
        elif not procurement["shopping_list"]:
            procurement_next_action = "AI 为已确认方案生成完整分批购物清单"
        elif procurement["shopping_list_confirmation"] != "confirmed":
            questions.append("请确认购物清单、总价范围和允许替代件后再自行购买？")
        else:
            procurement_next_action = "AI 把已确认购物清单冻结为精确目标与选中 BOM"
    if not questions and not zero_hardware:
        if (
            not result["requirements"] or not result["acceptance_criteria"]
            or any(
                any(item.get(field) is None for field in (
                    "metric", "operator", "threshold", "unit", "window", "observation_method"
                ))
                for item in result["acceptance_criteria"]
            )
        ):
            questions.append("请明确可追踪需求及对应的可观察验收标准？")
        if (
            any(any(term in str(target[field]).lower() for term in UNKNOWN_TERMS) for field in target)
            or not _toolchain_complete(target.get("toolchain"))
        ):
            questions.append("请确认 MCU、封装、板卡版本和本机工具链的精确目标？")
        if (
            not resources.get("components") or not resources.get("budget")
            or not resources.get("time_limit") or safety["status"] != "passed" or not safety["gates"]
            or _resource_blockers(result)
        ):
            questions.append("请补齐已有器件、预算、期限，并确认适用的低压安全门？")
        questions = questions[:3]
    if len(questions) > 3:
        raise ProjectError("invalid_intake", "一次最多提出 3 个澄清问题。")
    requested_stages = _string_list(result.get("required_stages", list(CORE_STAGES)), "required_stages", allow_empty=False)
    required_stages = list(CORE_STAGES) + [item for item in requested_stages if item not in CORE_STAGES]
    next_action = "回答上述澄清问题并冻结 ProjectIntake" if questions else (
        procurement_next_action or result.get("next_action") or "冻结项目 baseline"
    )
    if not isinstance(next_action, str) or not next_action.strip():
        raise ProjectError("invalid_intake", "必须提供且只能提供一个 next_action 字符串。")
    result["clarification_questions"] = questions
    result["required_stages"] = required_stages
    result["next_action"] = next_action
    return result


def _intake_blockers(intake: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not intake["requirements"]:
        blockers.append("requirements")
    if not intake["acceptance_criteria"]:
        blockers.append("acceptance_criteria")
    for criterion in intake["acceptance_criteria"]:
        required_fields = ("metric", "operator", "threshold", "unit", "window", "observation_method")
        if any(criterion.get(field) is None for field in required_fields):
            blockers.append(f"acceptance_structure:{criterion['acceptance_id']}")
    for field in ("mcu", "package", "board", "board_revision", "toolchain"):
        value = intake["exact_target"].get(field, "")
        text = _canonical(value) if isinstance(value, dict) else str(value)
        if not text.strip() or any(term in text.casefold() for term in UNKNOWN_TERMS):
            blockers.append(f"exact_target:{field}")
    if not _toolchain_complete(intake["exact_target"].get("toolchain")):
        blockers.append("exact_target:toolchain")
    resources = intake["resources"]
    for field in ("components", "budget", "time_limit"):
        if not resources.get(field):
            blockers.append(f"resources:{field}")
    procurement = intake.get("procurement")
    if isinstance(procurement, dict) and procurement.get("inventory_status") == "none_owned":
        if procurement.get("requirements_confirmation") != "confirmed":
            blockers.append("procurement:requirements_confirmation")
        if len(procurement.get("solution_options", [])) < 2:
            blockers.append("procurement:solution_options")
        if procurement.get("selection_confirmation") != "confirmed":
            blockers.append("procurement:selection_confirmation")
        if not procurement.get("shopping_list"):
            blockers.append("procurement:shopping_list")
        if procurement.get("shopping_list_confirmation") != "confirmed":
            blockers.append("procurement:shopping_list_confirmation")
    if intake["safety"].get("status") != "passed" or intake["safety"].get("blocked_reasons"):
        blockers.append("safety")
    if not intake["safety"].get("gates"):
        blockers.append("safety:gates")
    if intake.get("clarification_questions"):
        blockers.append("clarification_questions")
    blockers.extend(_resource_blockers(intake))
    return list(dict.fromkeys(blockers))


def _blank_state(project_id: str, intake: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "revision": 0,
        "last_event_id": None,
        "updated_at": None,
        "intake": copy.deepcopy(intake),
        "target_signature": _target_signature(intake),
        "intake_blockers": _intake_blockers(intake),
        "resource_blockers": _resource_blockers(intake),
        "baseline": None,
        "baseline_history": [],
        "stages": {},
        "evidence": [],
        "increments": [],
        "checkpoints": [],
        "flash_confirmations": [],
        "flash_records": [],
        "execution_runs": [],
        "design_releases": [],
        "release": {"status": "draft"},
        "known_not_verified": [],
        "next_action": intake["next_action"],
    }


def _event_shape(event: Any, line_number: int) -> None:
    if not isinstance(event, dict):
        raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行不是对象。")
    required = {
        "schema_version", "event_id", "event_type", "timestamp", "revision", "payload",
        "project_id", "previous_event_hash", "event_hash",
    }
    missing = sorted(required - set(event))
    if missing:
        raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行缺少字段。", missing)
    if event["schema_version"] != SCHEMA_VERSION:
        raise ProjectError("unsupported_schema", "事件 schema_version 不受支持。")
    if event["event_type"] not in ALLOWED_EVENT_TYPES:
        raise ProjectError("event_type_not_allowed", f"不允许的事件类型：{event['event_type']}")
    if not isinstance(event["payload"], dict) or not isinstance(event["event_id"], str):
        raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行结构无效。")
    if event["revision"] != line_number or not isinstance(event["timestamp"], str):
        raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行 revision 或时间无效。")
    if not HASH_RE.fullmatch(str(event["event_hash"])) or event["event_hash"] != _event_hash(event):
        raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行哈希校验失败。")


def _read_events(project_dir: Path, project_id: str) -> list[dict[str, Any]]:
    path = project_dir / "events" / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    keys: set[str] = set()
    event_ids: set[str] = set()
    previous: str | None = None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行为空。")
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行 JSON 损坏。", str(exc)) from exc
                _event_shape(event, line_number)
                if event["project_id"] != project_id or event["previous_event_hash"] != previous:
                    raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行项目或哈希链不连续。")
                if event["event_id"] in event_ids:
                    raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行 event_id 重复。")
                event_ids.add(event["event_id"])
                key = event.get("idempotency_key")
                if key is not None:
                    if not isinstance(key, str) or not IDEMPOTENCY_RE.fullmatch(key) or key in keys:
                        raise ProjectError("corrupt_event_log", f"事件账本第 {line_number} 行幂等键无效。")
                    keys.add(key)
                previous = event["event_hash"]
                events.append(event)
    except UnicodeDecodeError as exc:
        raise ProjectError("corrupt_event_log", "事件账本不是有效 UTF-8。", str(exc)) from exc
    return events


def _append_event(project_dir: Path, event: dict[str, Any]) -> None:
    path = project_dir / "events" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _find_evidence(state: dict[str, Any], evidence_id: str) -> dict[str, Any] | None:
    return next((item for item in state["evidence"] if item["evidence_id"] == evidence_id), None)


def _normalise_evidence(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    evidence_id = _required(payload, "evidence_id", str)
    if _find_evidence(state, evidence_id):
        raise ProjectError("duplicate_evidence", "evidence_id 已存在。")
    kind = _required(payload, "kind", str).strip()
    if kind not in EVIDENCE_KINDS:
        raise ProjectError("invalid_payload", "kind 不在允许的 Evidence 枚举中。")
    summary = _required(payload, "summary", str)
    level = _required(payload, "verification_level", str).strip()
    if level not in LEVELS:
        raise ProjectError("invalid_payload", "verification_level 必须为 V0–V5。")
    source = _required(payload, "source", str).strip()
    if source not in EVIDENCE_SOURCES:
        raise ProjectError("invalid_payload", "source 不在允许的 Evidence 枚举中。")
    status = payload.get("verification_status", "unverified")
    if not isinstance(status, str):
        raise ProjectError("invalid_payload", "verification_status 必须是字符串枚举。")
    status = status.strip()
    if status not in {"unverified", "verified", "self_reported"}:
        raise ProjectError("invalid_payload", "verification_status 无效。")
    baseline_hash = _hash(payload.get("baseline_hash"), "baseline_hash")
    supplied_artifact_hash = payload.get("artifact_hash")
    artifact_hash = _hash(supplied_artifact_hash, "artifact_hash") if supplied_artifact_hash is not None else None
    acceptance_ids = _string_list(payload.get("acceptance_ids", []), "acceptance_ids")
    known_acceptance = {item["acceptance_id"] for item in state["intake"]["acceptance_criteria"]}
    missing = [item for item in acceptance_ids if item not in known_acceptance]
    if missing:
        raise ProjectError("unknown_acceptance", "证据引用了未知验收项。", missing)
    limitations = _string_list(payload.get("limitations", []), "limitations")
    hardware_verified = payload.get("hardware_verified", False)
    if not isinstance(hardware_verified, bool):
        raise ProjectError("invalid_payload", "hardware_verified 只能是布尔值。")
    if kind in BUILD_OR_FLASH_KINDS:
        if LEVELS.index(level) > LEVELS.index("V2"):
            level = "V2"
        hardware_verified = False
        acceptance_ids = []
        if "build_or_flash_does_not_prove_function" not in limitations:
            limitations.append("build_or_flash_does_not_prove_function")
    if source == "reported_by_user":
        status = "self_reported"
        hardware_verified = False
        if "not_independently_observed" not in limitations:
            limitations.append("not_independently_observed")
    if level != "V5":
        hardware_verified = False
    excluded_acceptance_sources = {"imported_reference", "tool", "reported_by_user"}
    if source in excluded_acceptance_sources:
        hardware_verified = False
        acceptance_ids = []
    provenance: dict[str, Any] = {}
    if hardware_verified:
        if source not in INDEPENDENT_HARDWARE_SOURCES or kind not in {
            "hardware_observation", "hardware_measurement", "measurement", "acceptance_test"
        }:
            raise ProjectError("invalid_payload", "hardware_verified 仅允许独立硬件采集来源与实物证据类型。")
        if status != "verified" or not state["baseline"] or baseline_hash != state["baseline"]["baseline_hash"]:
            raise ProjectError("invalid_payload", "hardware_verified 必须绑定 current baseline 且已核验。")
        target_signature = _hash(payload.get("target_signature"), "target_signature")
        if target_signature != state["target_signature"]:
            raise ProjectError("target_signature_mismatch", "V5 实物证据 target signature 不匹配。")
        artifact_hash = _hash(payload.get("artifact_hash"), "artifact_hash")
        raw_evidence_hash = _hash(payload.get("raw_evidence_hash"), "raw_evidence_hash")
        operator = _required(payload, "operator", str).strip()
        evidence_timestamp = _required(payload, "timestamp", str).strip()
        try:
            parsed_timestamp = datetime.fromisoformat(evidence_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProjectError("invalid_payload", "V5 evidence timestamp 必须是 ISO-8601。") from exc
        if parsed_timestamp.tzinfo is None:
            raise ProjectError("invalid_payload", "V5 evidence timestamp 必须带时区。")
        reproduction = payload.get("reproduction")
        if not isinstance(reproduction, dict):
            raise ProjectError("invalid_payload", "V5 evidence reproduction 必须是对象。")
        steps = _string_list(reproduction.get("steps", []), "reproduction.steps", allow_empty=False)
        reproduction_result = reproduction.get("result")
        if not isinstance(reproduction_result, str) or not reproduction_result.strip():
            raise ProjectError("invalid_payload", "reproduction.result 必须是非空字符串。")
        provenance = {
            "target_signature": target_signature,
            "artifact_hash": artifact_hash,
            "raw_evidence_hash": raw_evidence_hash,
            "operator": operator,
            "timestamp": evidence_timestamp,
            "reproduction": {"steps": steps, "result": reproduction_result.strip()},
        }
    result = {
        "evidence_id": evidence_id,
        "kind": kind,
        "summary": summary,
        "verification_level": level,
        "verification_status": status,
        "source": source,
        "baseline_hash": baseline_hash,
        "acceptance_ids": acceptance_ids,
        "hardware_verified": hardware_verified,
        "limitations": limitations,
        "status": "current",
    }
    result.update(provenance)
    if artifact_hash is not None:
        result["artifact_hash"] = artifact_hash
    return result


def _next_stage_action(state: dict[str, Any]) -> str:
    for stage_id in state["intake"]["required_stages"]:
        if state["stages"].get(stage_id, {}).get("status") != "passed":
            return f"完成阶段 {stage_id} 的可验证检查点"
    return "运行 release 阶段门检查"


def _refresh_derived(state: dict[str, Any]) -> None:
    state["target_signature"] = _target_signature(state["intake"])
    state["resource_blockers"] = _resource_blockers(state["intake"])
    state["intake_blockers"] = _intake_blockers(state["intake"])


def _invalidate_flash_confirmations(state: dict[str, Any], reason: str) -> None:
    for confirmation in state["flash_confirmations"]:
        if not confirmation["consumed"] and confirmation.get("status") == "current":
            confirmation["status"] = "invalidated"
            confirmation["invalidated_by"] = reason


def _invalidate_baseline(state: dict[str, Any], reason: str) -> None:
    prior = state.get("baseline")
    state["baseline"] = None
    if prior is None:
        return
    for evidence in state["evidence"]:
        if evidence["status"] == "current":
            evidence["status"] = "stale"
            evidence["invalidated_by"] = reason
    for stage in state["stages"].values():
        if stage["status"] == "passed":
            stage["status"] = "stale"
            stage["invalidated_by"] = reason
    for increment in state["increments"]:
        if increment.get("status") == "current":
            increment["status"] = "stale"
            increment["invalidated_by"] = reason
    for run in state.get("execution_runs", []):
        if run.get("status") == "current":
            run["status"] = "stale"
            run["invalidated_by"] = reason
    for design_release in state.get("design_releases", []):
        if design_release.get("status") != "stale":
            design_release["status"] = "stale"
            design_release["invalidated_by"] = reason
    _invalidate_flash_confirmations(state, reason)
    state["release"] = {"status": "draft"}


def _release_blockers(state: dict[str, Any]) -> list[str]:
    blockers: list[str] = list(state.get("intake_blockers", []))
    intake = state["intake"]
    if not intake["requirements"]:
        blockers.append("requirements")
    if not intake["acceptance_criteria"]:
        blockers.append("acceptance_criteria")
    for field in ("mcu", "package", "board", "board_revision", "toolchain"):
        value = str(intake["exact_target"].get(field, ""))
        if not value.strip() or any(term in value.lower() for term in UNKNOWN_TERMS):
            blockers.append(f"exact_target:{field}")
    resources = intake["resources"]
    for field in ("components", "budget", "time_limit"):
        if not resources.get(field):
            blockers.append(f"resources:{field}")
    safety = intake["safety"]
    if safety.get("status") != "passed" or safety.get("blocked_reasons"):
        blockers.append("safety")
    if not safety.get("gates"):
        blockers.append("safety:gates")
    if intake.get("clarification_questions"):
        blockers.append("clarification_questions")
    baseline = state.get("baseline")
    if not baseline:
        blockers.append("baseline")
    baseline_hash = baseline.get("baseline_hash") if baseline else None
    for stage_id in intake["required_stages"]:
        stage = state["stages"].get(stage_id)
        if not stage or stage.get("status") != "passed" or stage.get("baseline_hash") != baseline_hash:
            blockers.append(f"stage:{stage_id}")
    for criterion in intake["acceptance_criteria"]:
        matches = [
            evidence for evidence in state["evidence"]
            if evidence.get("status") == "current"
            and evidence.get("baseline_hash") == baseline_hash
            and evidence.get("verification_status") == "verified"
            and evidence.get("source") != "reported_by_user"
            and criterion["acceptance_id"] in evidence.get("acceptance_ids", [])
        ]
        if criterion.get("requires_hardware"):
            matches = [item for item in matches if item.get("verification_level") == "V5" and item.get("hardware_verified")]
        if not matches:
            blockers.append(f"acceptance:{criterion['acceptance_id']}")
    if state.get("known_not_verified"):
        blockers.append("known_not_verified")
    current_increments = [item for item in state.get("increments", []) if item.get("status") == "current"]
    if not current_increments:
        blockers.append("increments")
    for increment in current_increments:
        if not increment.get("complete"):
            blockers.append(f"increment:{increment['increment_id']}")
    return list(dict.fromkeys(blockers))


def _event_contract_object(
    value: Any,
    *,
    code: str,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectError(code, f"{field} 必须是对象。")
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        raise ProjectError(code, f"{field} 字段不完整或包含正文/路径等非摘要字段。", {"missing": missing, "extra": extra})
    return copy.deepcopy(value)


def _event_hash_map(value: Any, *, code: str, field: str, allow_empty: bool = False) -> dict[str, str]:
    if not isinstance(value, dict) or (not allow_empty and not value):
        raise ProjectError(code, f"{field} 必须是非空 SHA-256 映射。")
    result: dict[str, str] = {}
    for name, digest in value.items():
        if not _meaningful_text(name):
            raise ProjectError(code, f"{field} 的名称必须是非占位文本。")
        try:
            result[name] = _hash(digest, f"{field}.{name}")
        except ProjectError as exc:
            raise ProjectError(code, exc.message) from exc
    return result


def _normalise_execution_run(state: dict[str, Any], payload: dict[str, Any], timestamp: str) -> dict[str, Any]:
    required = {
        "run_id", "baseline_hash", "target_signature", "target_identity_hash", "execution_plan_hash",
        "tool_receipt_hashes", "artifact_hashes", "result",
    }
    value = _event_contract_object(payload, code="invalid_execution_run", field="execution run", required=required)
    run_id = value["run_id"]
    if not _meaningful_text(run_id):
        raise ProjectError("invalid_execution_run", "run_id 必须是非占位文本。")
    if any(item["run_id"] == run_id for item in state.get("execution_runs", [])):
        raise ProjectError("duplicate_execution_run", "run_id 已存在。")
    try:
        baseline_hash = _hash(value["baseline_hash"], "baseline_hash")
        target_signature = _hash(value["target_signature"], "target_signature")
        target_identity_hash = _hash(value["target_identity_hash"], "target_identity_hash")
        execution_plan_hash = _hash(value["execution_plan_hash"], "execution_plan_hash")
        receipt_hashes = [_hash(item, "tool_receipt_hashes") for item in _string_list(
            value["tool_receipt_hashes"], "tool_receipt_hashes", allow_empty=False
        )]
    except ProjectError as exc:
        raise ProjectError("invalid_execution_run", exc.message) from exc
    if len(set(receipt_hashes)) != len(receipt_hashes):
        raise ProjectError("invalid_execution_run", "tool_receipt_hashes 不能包含重复项。")
    if not state.get("baseline") or state["baseline"]["baseline_hash"] != baseline_hash:
        raise ProjectError("baseline_mismatch", "execution run 未绑定当前 baseline。")
    if target_signature != state["target_signature"]:
        raise ProjectError("target_signature_mismatch", "execution run 未绑定当前 target signature。")
    if value["result"] not in {"passed", "failed", "partial", "cancelled"}:
        raise ProjectError("invalid_execution_run", "execution run result 枚举无效。")
    return {
        "run_id": run_id.strip(),
        "baseline_hash": baseline_hash,
        "target_signature": target_signature,
        "target_identity_hash": target_identity_hash,
        "execution_plan_hash": execution_plan_hash,
        "tool_receipt_hashes": receipt_hashes,
        "artifact_hashes": _event_hash_map(value["artifact_hashes"], code="invalid_execution_run", field="artifact_hashes"),
        "result": value["result"],
        "status": "current",
        "recorded_at": timestamp,
    }


def _normalise_design_release(state: dict[str, Any], payload: dict[str, Any], timestamp: str) -> dict[str, Any]:
    required = {
        "design_release_id", "baseline_hash", "target_signature", "design_release_hash", "schematic_hash",
        "pcb_hash", "erc_report_hash", "drc_report_hash", "parity_report_hash", "bom_hash", "render_hash",
        "cam_hashes", "status",
    }
    value = _event_contract_object(payload, code="invalid_design_release", field="design release", required=required)
    release_id = value["design_release_id"]
    if not _meaningful_text(release_id):
        raise ProjectError("invalid_design_release", "design_release_id 必须是非占位文本。")
    if any(item["design_release_id"] == release_id for item in state.get("design_releases", [])):
        raise ProjectError("duplicate_design_release", "design_release_id 已存在。")
    try:
        hashes = {
            field: _hash(value[field], field)
            for field in (
                "baseline_hash", "target_signature", "design_release_hash", "schematic_hash", "pcb_hash",
                "erc_report_hash", "drc_report_hash", "parity_report_hash", "bom_hash", "render_hash",
            )
        }
    except ProjectError as exc:
        raise ProjectError("invalid_design_release", exc.message) from exc
    if not state.get("baseline") or state["baseline"]["baseline_hash"] != hashes["baseline_hash"]:
        raise ProjectError("baseline_mismatch", "design release 未绑定当前 baseline。")
    if hashes["target_signature"] != state["target_signature"]:
        raise ProjectError("target_signature_mismatch", "design release 未绑定当前 target signature。")
    if value["status"] not in {"draft", "reviewed", "released"}:
        raise ProjectError("invalid_design_release", "design release status 枚举无效。")
    cam = _event_contract_object(
        value["cam_hashes"], code="invalid_design_release", field="cam_hashes",
        required={"gerber", "drill", "pnp", "step"},
        optional={"layers", "dfm_report", "unresolved_issues"},
    )
    return {
        "design_release_id": release_id.strip(),
        **hashes,
        "cam_hashes": _event_hash_map(cam, code="invalid_design_release", field="cam_hashes"),
        "status": value["status"],
        "recorded_at": timestamp,
    }


def _apply_event(state: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    event_type = event["event_type"]
    timestamp = event["timestamp"]
    if state is None:
        if event_type != "generation.project_initialized" or event["revision"] != 1:
            raise ProjectError("corrupt_event_log", "第一条事件必须是 project_initialized。")
        intake = _validate_intake(payload.get("intake"))
        result = _blank_state(event["project_id"], intake)
    else:
        if event["revision"] != state["revision"] + 1:
            raise ProjectError("corrupt_event_log", "事件 revision 与前一状态不连续。")
        result = copy.deepcopy(state)
        if event_type == "generation.project_initialized":
            raise ProjectError("corrupt_event_log", "project_initialized 只能是第一条事件。")
        if event_type == "generation.intake_updated":
            result["intake"] = _validate_intake(payload.get("intake"))
            result["next_action"] = result["intake"]["next_action"]
            _invalidate_baseline(result, "intake_updated")
            _refresh_derived(result)
        elif event_type == "generation.requirements_updated":
            result["intake"]["requirements"] = _normalise_requirements(payload.get("requirements"))
            result["intake"]["acceptance_criteria"] = _normalise_acceptance(payload.get("acceptance_criteria"))
            known = {item["acceptance_id"] for item in result["intake"]["acceptance_criteria"]}
            missing = sorted({ref for item in result["intake"]["requirements"] for ref in item["acceptance_ids"] if ref not in known})
            if missing:
                raise ProjectError("invalid_payload", "需求引用了未知验收项。", missing)
            _invalidate_baseline(result, "requirements_updated")
            _refresh_derived(result)
        elif event_type == "generation.target_updated":
            target = payload.get("exact_target")
            candidate = copy.deepcopy(result["intake"])
            candidate["exact_target"] = target
            if "hardware_identity" in payload:
                candidate["hardware_identity"] = payload["hardware_identity"]
            candidate.pop("_unknown_target_fields", None)
            result["intake"] = _validate_intake(candidate)
            _invalidate_baseline(result, "target_updated")
            _refresh_derived(result)
        elif event_type == "generation.safety_updated":
            candidate = copy.deepcopy(result["intake"])
            candidate["safety"] = payload.get("safety")
            result["intake"] = _validate_intake(candidate)
            _invalidate_baseline(result, "safety_updated")
            _refresh_derived(result)
        elif event_type == "generation.resources_updated":
            candidate = copy.deepcopy(result["intake"])
            candidate["resources"] = payload.get("resources")
            result["intake"] = _validate_intake(candidate)
            _invalidate_baseline(result, "resources_updated")
            _refresh_derived(result)
        elif event_type == "generation.procurement_updated":
            candidate = copy.deepcopy(result["intake"])
            candidate["procurement"] = payload.get("procurement")
            result["intake"] = _validate_intake(candidate)
            _invalidate_baseline(result, "procurement_updated")
            _refresh_derived(result)
        elif event_type == "generation.baseline_updated":
            intake_blockers = result.get("intake_blockers", _intake_blockers(result["intake"]))
            if intake_blockers:
                resource = [item for item in intake_blockers if item in result.get("resource_blockers", [])]
                non_resource = [
                    item for item in intake_blockers
                    if item not in resource and not (resource and item == "clarification_questions")
                ]
                if non_resource:
                    raise ProjectError("intake_gate", "ProjectIntake 尚未冻结，不能创建 baseline。", intake_blockers)
                raise ProjectError("resource_gate", "资源计划存在冲突或未知项，不能冻结 baseline。", resource)
            baseline_id = _required(payload, "baseline_id", str)
            baseline_hash = _hash(payload.get("baseline_hash"), "baseline_hash")
            reused = next((item for item in result["baseline_history"] if item["baseline_id"] == baseline_id), None)
            if reused and reused["baseline_hash"] != baseline_hash:
                raise ProjectError("immutable_id_conflict", "baseline_id 已绑定不同哈希，不能重用。")
            prior_hash = result["baseline"]["baseline_hash"] if result["baseline"] else None
            result["baseline"] = {
                "baseline_id": baseline_id,
                "baseline_hash": baseline_hash,
                "note": payload.get("note"),
                "updated_at": timestamp,
            }
            if reused is None:
                result["baseline_history"].append(copy.deepcopy(result["baseline"]))
            if prior_hash != baseline_hash:
                for evidence in result["evidence"]:
                    if evidence.get("baseline_hash") != baseline_hash and evidence["status"] == "current":
                        evidence["status"] = "stale"
                        evidence["invalidated_by_baseline"] = baseline_hash
                for stage in result["stages"].values():
                    if stage.get("baseline_hash") != baseline_hash and stage["status"] == "passed":
                        stage["status"] = "stale"
                        stage["invalidated_by_baseline"] = baseline_hash
                for increment in result["increments"]:
                    if increment.get("baseline_hash") != baseline_hash and increment.get("status") == "current":
                        increment["status"] = "stale"
                        increment["invalidated_by_baseline"] = baseline_hash
                for run in result.get("execution_runs", []):
                    if run.get("baseline_hash") != baseline_hash and run.get("status") == "current":
                        run["status"] = "stale"
                        run["invalidated_by_baseline"] = baseline_hash
                for design_release in result.get("design_releases", []):
                    if design_release.get("baseline_hash") != baseline_hash and design_release.get("status") != "stale":
                        design_release["status"] = "stale"
                        design_release["invalidated_by_baseline"] = baseline_hash
                _invalidate_flash_confirmations(result, "baseline_updated")
                result["release"] = {"status": "draft"}
        elif event_type == "generation.evidence_recorded":
            evidence = _normalise_evidence(result, payload)
            if not result["baseline"] or evidence["baseline_hash"] != result["baseline"]["baseline_hash"]:
                evidence["status"] = "stale"
                evidence["limitations"].append("not_bound_to_current_baseline")
            evidence["recorded_at"] = timestamp
            result["evidence"].append(evidence)
        elif event_type == "generation.stage_recorded":
            stage_id = _required(payload, "stage_id", str)
            status = _required(payload, "status", str)
            if status not in {"pending", "in_progress", "blocked", "passed"}:
                raise ProjectError("invalid_payload", "stage status 无效。")
            baseline_hash = _hash(payload.get("baseline_hash"), "baseline_hash")
            if not result["baseline"] or baseline_hash != result["baseline"]["baseline_hash"]:
                raise ProjectError("baseline_mismatch", "阶段结果未绑定当前 baseline。")
            evidence_ids = _string_list(payload.get("evidence_ids", []), "evidence_ids")
            evidence = [_find_evidence(result, item) for item in evidence_ids]
            missing = [item for item, found in zip(evidence_ids, evidence) if found is None]
            if missing:
                raise ProjectError("unknown_evidence", "阶段引用了不存在的证据。", missing)
            execution_run_ids = _string_list(payload.get("execution_run_ids", []), "execution_run_ids")
            known_runs = {item["run_id"]: item for item in result.get("execution_runs", [])}
            missing_runs = [item for item in execution_run_ids if item not in known_runs]
            if missing_runs:
                raise ProjectError("unknown_execution_run", "阶段引用了不存在的 execution run。", missing_runs)
            stale_runs = [
                item for item in execution_run_ids
                if known_runs[item].get("status") != "current" or known_runs[item].get("baseline_hash") != baseline_hash
            ]
            if stale_runs:
                raise ProjectError("stale_execution_run", "阶段只能引用当前 baseline 的 execution run。", stale_runs)
            design_release_ids = _string_list(payload.get("design_release_ids", []), "design_release_ids")
            known_design_releases = {
                item["design_release_id"]: item for item in result.get("design_releases", [])
            }
            missing_design_releases = [item for item in design_release_ids if item not in known_design_releases]
            if missing_design_releases:
                raise ProjectError(
                    "unknown_design_release", "阶段引用了不存在的 design release。", missing_design_releases,
                )
            stale_design_releases = [
                item for item in design_release_ids
                if known_design_releases[item].get("status") == "stale"
                or known_design_releases[item].get("baseline_hash") != baseline_hash
            ]
            if stale_design_releases:
                raise ProjectError("stale_design_release", "阶段只能引用当前 baseline 的 design release。", stale_design_releases)
            if status == "passed":
                if stage_id in {"design", "resources", "hardware_plan", "implementation"} and result["intake_blockers"]:
                    raise ProjectError("intake_gate", "输入未冻结，不能通过设计、资源、硬件或实现阶段。", result["intake_blockers"])
                if stage_id in {"resources", "hardware_plan"} and result["resource_blockers"]:
                    raise ProjectError("resource_gate", "资源冲突阻止该阶段通过。", result["resource_blockers"])
                required = result["intake"]["required_stages"]
                if stage_id in required:
                    prior = required[: required.index(stage_id)]
                    incomplete = [item for item in prior if result["stages"].get(item, {}).get("status") != "passed"]
                    if incomplete:
                        raise ProjectError("stage_order", "前置阶段尚未通过。", incomplete)
                bad = [item["evidence_id"] for item in evidence if item and (item["status"] != "current" or item["baseline_hash"] != baseline_hash or item["verification_status"] == "unverified")]
                if bad:
                    raise ProjectError("stage_evidence_gate", "阶段证据无效、过期或未核验。", bad)
                if not evidence_ids:
                    raise ProjectError("stage_evidence_gate", "passed 阶段至少需要一条证据。")
                allowed_kinds = STAGE_EVIDENCE_KINDS.get(stage_id)
                if allowed_kinds is not None:
                    incompatible = [item["evidence_id"] for item in evidence if item and item["kind"] not in allowed_kinds]
                    if incompatible:
                        raise ProjectError("incompatible_evidence", "证据类型与阶段不相容，不能跨阶段复用。", incompatible)
                if stage_id in {"implementation", "build"}:
                    current_increments = [item for item in result["increments"] if item.get("status") == "current"]
                    incomplete_increments = [item["increment_id"] for item in current_increments if not item.get("complete")]
                    if not current_increments or incomplete_increments:
                        raise ProjectError("increment_gate", "implementation/build 需要可构建、已观察且可回滚的增量。", incomplete_increments or ["missing_increment"])
                if stage_id == "hardware_acceptance" and not any(
                    item and item["verification_level"] == "V5" and item["hardware_verified"]
                    and item["verification_status"] == "verified" and item["source"] != "reported_by_user"
                    for item in evidence
                ):
                    raise ProjectError("hardware_evidence_required", "硬件验收需要独立 V5 实物证据；构建或烧录结果不够。")
            stage = {
                "stage_id": stage_id,
                "status": status,
                "baseline_hash": baseline_hash,
                "evidence_ids": evidence_ids,
                "outputs": _string_list(payload.get("outputs", []), "outputs"),
                "known_not_verified": _string_list(payload.get("known_not_verified", []), "known_not_verified"),
                "increment_ids": [
                    item["increment_id"] for item in result["increments"] if item.get("status") == "current"
                ] if stage_id in {"implementation", "build"} else [],
                "execution_run_ids": execution_run_ids,
                "design_release_ids": design_release_ids,
                "recorded_at": timestamp,
            }
            result["stages"][stage_id] = stage
            result["checkpoints"].append(copy.deepcopy(stage))
            result["known_not_verified"] = list(dict.fromkeys(
                item for saved in result["stages"].values() if saved["status"] in {"passed", "in_progress"}
                for item in saved.get("known_not_verified", [])
            ))
            result["next_action"] = _next_stage_action(result)
        elif event_type == "generation.increment_recorded":
            increment_id = _required(payload, "increment_id", str).strip()
            if any(item["increment_id"] == increment_id for item in result["increments"]):
                raise ProjectError("duplicate_increment", "increment_id 已存在。")
            baseline_hash = _hash(payload.get("baseline_hash"), "baseline_hash")
            if not result["baseline"] or baseline_hash != result["baseline"]["baseline_hash"]:
                raise ProjectError("baseline_mismatch", "增量未绑定当前 baseline。")
            buildable = payload.get("buildable")
            if not isinstance(buildable, bool) or buildable is not True:
                raise ProjectError("invalid_increment", "increment.buildable 必须明确为 true。")
            build_evidence_id = _required(payload, "build_evidence_id", str)
            expected_observation = payload.get("expected_observation")
            if not isinstance(expected_observation, str) or not expected_observation.strip():
                raise ProjectError("invalid_increment", "expected_observation 必须是非空字符串。")
            actual_observation = payload.get("actual_observation")
            if not isinstance(actual_observation, dict):
                raise ProjectError("invalid_increment", "actual_observation 必须是结构化对象。")
            for field in ("expected", "observed", "evidence_id"):
                if not isinstance(actual_observation.get(field), str) or not actual_observation[field].strip():
                    raise ProjectError("invalid_increment", f"actual_observation.{field} 必须是非空字符串。")
            if actual_observation.get("result") not in {"passed", "failed", "partial"}:
                raise ProjectError("invalid_increment", "actual_observation.result 枚举无效。")
            if actual_observation["expected"].strip() != expected_observation.strip():
                raise ProjectError("invalid_increment", "actual_observation.expected 必须与 expected_observation 一致。")
            observation_evidence_id = actual_observation["evidence_id"].strip()
            rollback = payload.get("rollback")
            if not isinstance(rollback, dict) or rollback.get("supported") is not True:
                raise ProjectError("invalid_increment", "rollback 必须是结构化对象。")
            rollback_steps = rollback.get("steps")
            if not isinstance(rollback_steps, list) or not rollback_steps or not all(
                isinstance(step, dict) for step in rollback_steps
            ):
                raise ProjectError("invalid_increment", "rollback.steps 必须是非空枚举对象数组。")
            allowed_hashes = {
                item["baseline_hash"] for item in result.get("baseline_history", [])
                if isinstance(item.get("baseline_hash"), str)
            }
            allowed_hashes.add(baseline_hash)
            allowed_hashes.update(
                item["artifact_hash"] for item in result["evidence"]
                if isinstance(item.get("artifact_hash"), str)
            )
            normalized_steps: list[dict[str, Any]] = []
            for step in rollback_steps:
                action = step.get("action")
                if action not in {"restore_artifact", "restore_config", "rebuild_and_test", "request_reflash"}:
                    raise ProjectError("invalid_increment", "rollback step action 枚举无效。")
                normalized_step = {"action": action}
                if "artifact_hash" in step:
                    try:
                        referenced_hash = _hash(step.get("artifact_hash"), "rollback.steps.artifact_hash")
                    except ProjectError as exc:
                        raise ProjectError("invalid_increment", exc.message) from exc
                    if referenced_hash not in allowed_hashes:
                        raise ProjectError("invalid_increment", "rollback hash 必须引用账本中的 baseline 或 evidence artifact。")
                    normalized_step["artifact_hash"] = referenced_hash
                if "ref" in step:
                    if not _meaningful_text(step.get("ref")):
                        raise ProjectError("invalid_increment", "rollback.steps.ref 必须是非占位引用。")
                    normalized_step["ref"] = step["ref"].strip()
                if len(normalized_step) == 1:
                    raise ProjectError("invalid_increment", "每个 rollback step 必须包含 artifact_hash 或 ref。")
                if action in {"restore_artifact", "request_reflash"} and "artifact_hash" not in normalized_step:
                    raise ProjectError("invalid_increment", f"{action} 必须绑定 artifact_hash。")
                normalized_steps.append(normalized_step)
            verification_action = rollback.get("verification_action")
            if not isinstance(verification_action, dict) or verification_action.get("action") not in {
                "rebuild_and_test", "logic_test", "runtime_check", "hardware_observation"
            }:
                raise ProjectError("invalid_increment", "rollback.verification_action 必须是受支持的结构化动作。")
            verification_evidence_id = verification_action.get("evidence_id")
            if not isinstance(verification_evidence_id, str) or not verification_evidence_id.strip():
                raise ProjectError("invalid_increment", "rollback.verification_action.evidence_id 必须引用证据。")
            verification_evidence = _find_evidence(result, verification_evidence_id.strip())
            if not verification_evidence or verification_evidence.get("status") != "current" or verification_evidence.get("verification_status") != "verified":
                raise ProjectError("invalid_increment", "rollback verification evidence 必须是当前已核验证据。")
            build_evidence = _find_evidence(result, build_evidence_id)
            observation_evidence = _find_evidence(result, observation_evidence_id)
            if not build_evidence or build_evidence["kind"] not in BUILD_EVIDENCE_KINDS or build_evidence["verification_status"] != "verified" or build_evidence["status"] != "current":
                raise ProjectError("invalid_increment", "build_evidence_id 必须引用当前已核验构建证据。")
            if (
                not observation_evidence or observation_evidence["kind"] not in OBSERVATION_KINDS
                or not (
                    observation_evidence["source"] == "tool"
                    and observation_evidence["kind"] in {"logic_test", "host_test", "runtime_log"}
                    or observation_evidence["source"] in {
                        "instrument", "instrument_capture", "verified_hardware_tool"
                    }
                    and observation_evidence["kind"] in {
                        "measurement", "hardware_observation", "hardware_measurement", "acceptance_test"
                    }
                )
                or observation_evidence["verification_status"] != "verified"
                or observation_evidence["status"] != "current"
                or observation_evidence["baseline_hash"] != baseline_hash
            ):
                raise ProjectError("invalid_increment", "observation_evidence_id 必须引用当前已核验观察证据。")
            result["increments"].append({
                "increment_id": increment_id,
                "baseline_hash": baseline_hash,
                "buildable": True,
                "build_evidence_id": build_evidence_id,
                "expected_observation": expected_observation.strip(),
                "actual_observation": {
                    "expected": actual_observation["expected"].strip(),
                    "observed": actual_observation["observed"].strip(),
                    "result": actual_observation["result"],
                    "evidence_id": observation_evidence_id,
                },
                "rollback": {
                    "supported": True,
                    "steps": normalized_steps,
                    "verification_action": {
                        "action": verification_action["action"],
                        "evidence_id": verification_evidence_id.strip(),
                    },
                },
                "complete": actual_observation["result"] == "passed",
                "status": "current",
                "recorded_at": timestamp,
            })
        elif event_type == "generation.checkpoint_recorded":
            checkpoint = copy.deepcopy(payload)
            checkpoint["recorded_at"] = timestamp
            result["checkpoints"].append(checkpoint)
            action = payload.get("next_action")
            if action is not None:
                if not isinstance(action, str) or not action.strip():
                    raise ProjectError("invalid_payload", "next_action 必须是一个非空字符串。")
                result["next_action"] = action
        elif event_type == "generation.flash_confirmed":
            identity = result["intake"].get("hardware_identity")
            if not isinstance(identity, dict):
                raise ProjectError(
                    "hardware_identity_required",
                    "烧录确认前必须补齐硬件护照、板卡证据 SHA-256 和精确 Flash 容量。",
                )
            confirmation_id = _required(payload, "confirmation_id", str)
            if not payload.get("explicit") is True:
                raise ProjectError("explicit_confirmation_required", "每次烧录前都需要一次明确确认。")
            if any(item["confirmation_id"] == confirmation_id for item in result["flash_confirmations"]):
                raise ProjectError("duplicate_confirmation", "confirmation_id 已存在。")
            baseline_hash = _hash(payload.get("baseline_hash"), "baseline_hash")
            artifact_hash = _hash(payload.get("artifact_hash"), "artifact_hash")
            if not result["baseline"] or result["baseline"]["baseline_hash"] != baseline_hash:
                raise ProjectError("baseline_mismatch", "烧录确认未绑定当前 baseline。")
            signature = _hash(payload.get("target_signature"), "target_signature")
            if signature != result["target_signature"]:
                raise ProjectError("target_signature_mismatch", "烧录确认未绑定当前规范化 target signature。")
            result["flash_confirmations"].append({
                "confirmation_id": confirmation_id, "explicit": True, "target_signature": signature,
                "baseline_hash": baseline_hash, "artifact_hash": artifact_hash, "confirmed_at": timestamp,
                "consumed": False, "status": "current",
            })
        elif event_type == "generation.flash_recorded":
            confirmation_id = _required(payload, "confirmation_id", str)
            confirmation = next((item for item in result["flash_confirmations"] if item["confirmation_id"] == confirmation_id), None)
            if confirmation is None:
                raise ProjectError("flash_confirmation_required", "未找到本次烧录的一次性确认。")
            if confirmation["consumed"]:
                raise ProjectError("flash_confirmation_consumed", "该烧录确认已使用，不能复用。")
            if confirmation.get("status") != "current":
                raise ProjectError("flash_confirmation_invalidated", "该烧录确认已因 target 或 baseline 变化而作废。")
            if not result["baseline"]:
                raise ProjectError("baseline_mismatch", "无 current baseline，禁止记录烧录。")
            binding = {
                "target_signature": _hash(payload.get("target_signature"), "target_signature"),
                "baseline_hash": _hash(payload.get("baseline_hash"), "baseline_hash"),
                "artifact_hash": _hash(payload.get("artifact_hash"), "artifact_hash"),
            }
            if any(binding[field] != confirmation[field] for field in binding):
                raise ProjectError("flash_confirmation_mismatch", "烧录目标、baseline 或 artifact 与确认记录不一致。")
            confirmation["consumed"] = True
            confirmation["status"] = "consumed"
            confirmation["consumed_at"] = timestamp
            result["flash_records"].append({
                "confirmation_id": confirmation_id, **binding, "result": payload.get("result", "unknown"),
                "recorded_at": timestamp, "hardware_verified": False,
                "limitation": "烧录结果不等于功能性硬件验收；project_tool 不执行自动烧录。",
            })
        elif event_type == "generation.execution_run_recorded":
            result["execution_runs"].append(_normalise_execution_run(result, payload, timestamp))
        elif event_type == "generation.design_release_recorded":
            result["design_releases"].append(_normalise_design_release(result, payload, timestamp))
        elif event_type == "generation.release_recorded":
            if result["release"].get("status") == "released":
                raise ProjectError("already_released", "项目已经 release；请更新 baseline 后再创建新 release。")
            blockers = _release_blockers(result)
            if blockers:
                raise ProjectError("release_gate", "项目尚未通过 release 阶段门。", blockers)
            release_artifact_hash = _hash(payload.get("artifact_hash"), "artifact_hash")
            artifact_blockers = [
                f"acceptance_artifact:{criterion['acceptance_id']}"
                for criterion in result["intake"]["acceptance_criteria"]
                if criterion.get("requires_hardware") and not any(
                    evidence.get("hardware_verified")
                    and criterion["acceptance_id"] in evidence.get("acceptance_ids", [])
                    and evidence.get("artifact_hash") == release_artifact_hash
                    and evidence.get("baseline_hash") == result["baseline"]["baseline_hash"]
                    for evidence in result["evidence"]
                )
            ]
            if artifact_blockers:
                raise ProjectError("release_gate", "V5 证据未绑定本次 release artifact。", artifact_blockers)
            result["release"] = {
                "status": "released",
                "release_id": _required(payload, "release_id", str),
                "artifact_hash": release_artifact_hash,
                "baseline_hash": result["baseline"]["baseline_hash"],
                "released_at": timestamp,
            }

    result["revision"] = event["revision"]
    result["last_event_id"] = event["event_id"]
    result["updated_at"] = timestamp
    return result


def _materialize(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] | None = None
    for event in events:
        state = _apply_event(state, event)
    if state is None:
        raise ProjectError("not_initialized", "项目尚未初始化。")
    return state


def _manifest(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "canonical_ledger": "events/events.jsonl",
        "materialized_state": "state.json",
        "event_namespace": "generation.*",
        "auto_flash": False,
    }


def _manifest_matches(project_dir: Path, project_id: str) -> bool:
    try:
        return json.loads((project_dir / "manifest.json").read_text(encoding="utf-8")) == _manifest(project_id)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _load_snapshot(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / "state.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectError("snapshot_corrupt", "state.json 损坏或不是有效 UTF-8 JSON。", str(exc)) from exc
    if not isinstance(value, dict):
        raise ProjectError("snapshot_corrupt", "state.json 必须是对象。")
    return value


def _current_locked(project_dir: Path, project_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    events = _read_events(project_dir, project_id)
    if not events:
        raise ProjectError("not_initialized", "项目尚未初始化。")
    canonical = _materialize(events)
    snapshot = _load_snapshot(project_dir)
    recovered = snapshot is None
    if snapshot is not None:
        revision = snapshot.get("revision")
        if not isinstance(revision, int):
            raise ProjectError("snapshot_corrupt", "state.json revision 无效。")
        if revision > canonical["revision"]:
            raise ProjectError("snapshot_ahead_of_ledger", "快照领先于项目事件账本，拒绝覆盖。", {"snapshot": revision, "ledger": canonical["revision"]})
        if revision == canonical["revision"] and snapshot != canonical:
            raise ProjectError("snapshot_divergence", "同 revision 快照与项目账本重放结果不同，拒绝覆盖。")
        if revision < canonical["revision"]:
            recovered = True
    if not _manifest_matches(project_dir, project_id):
        recovered = True
    if recovered:
        _atomic_json(project_dir / "manifest.json", _manifest(project_id))
        _atomic_json(project_dir / "state.json", canonical)
    return canonical, events, recovered


def _new_event(project_id: str, event_type: str, payload: dict[str, Any], revision: int, previous_hash: str | None, idempotency_key: str | None) -> dict[str, Any]:
    event = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "timestamp": _now(),
        "revision": revision,
        "idempotency_key": idempotency_key,
        "previous_event_hash": previous_hash,
        "payload": payload,
    }
    event["event_hash"] = _event_hash(event)
    return event


def init_project(
    projects_dir: Path,
    project_id: str,
    intake: dict[str, Any],
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    project_dir = _project_dir(projects_dir, project_id)
    normalised = _validate_intake(intake)
    with _write_lock(project_dir):
        ledger = project_dir / "events" / "events.jsonl"
        if ledger.exists() or (project_dir / "state.json").exists():
            state, _, recovered = _current_locked(project_dir, project_id)
            if state["intake"] != normalised:
                raise ProjectError("already_initialized", "项目已用不同 intake 初始化；请使用 intake_updated 事件。")
            return {"created": False, "recovered": recovered, "state": state, "resume_summary": _resume(state)}
        init_key = idempotency_key or f"project-init:{project_id}"
        if not IDEMPOTENCY_RE.fullmatch(init_key):
            raise ProjectError("invalid_idempotency_key", "init 幂等键必须是 1–128 位规范字符串。")
        event = _new_event(
            project_id, "generation.project_initialized", {"intake": normalised}, 1, None,
            init_key,
        )
        candidate = _apply_event(None, event)
        _append_event(project_dir, event)
        _atomic_json(project_dir / "manifest.json", _manifest(project_id))
        _atomic_json(project_dir / "state.json", candidate)
        return {"created": True, "recovered": False, "event": event, "state": candidate, "resume_summary": _resume(candidate)}


def _resume(state: dict[str, Any]) -> dict[str, Any]:
    questions = list(state["intake"].get("clarification_questions", []))[:3]
    return {
        "project_id": state["project_id"],
        "revision": state["revision"],
        "last_checkpoint": state["checkpoints"][-1] if state["checkpoints"] else None,
        "release_status": state["release"]["status"],
        "questions": questions,
        "next_action": state["next_action"],
    }


def get_status(projects_dir: Path, project_id: str) -> dict[str, Any]:
    project_dir = _project_dir(projects_dir, project_id)
    with _write_lock(project_dir):
        state, _, recovered = _current_locked(project_dir, project_id)
        return {"recovered": recovered, "resume_summary": _resume(state), "release_blockers": _release_blockers(state), "state": state}


def validate_project(projects_dir: Path, project_id: str) -> dict[str, Any]:
    try:
        project_dir = _project_dir(projects_dir, project_id)
        with _write_lock(project_dir):
            state, events, recovered = _current_locked(project_dir, project_id)
            return {"valid": True, "project_id": project_id, "event_count": len(events), "revision": state["revision"], "recovered": recovered}
    except ProjectError as exc:
        result = exc.as_dict()
        result["valid"] = False
        return result


def record_event(projects_dir: Path, project_id: str, event_type: str, payload: dict[str, Any], *, idempotency_key: str | None = None, expected_revision: int | None = None) -> dict[str, Any]:
    if event_type not in ALLOWED_EVENT_TYPES or event_type == "generation.project_initialized":
        raise ProjectError("event_type_not_allowed", f"不允许的事件类型：{event_type}")
    if not isinstance(payload, dict):
        raise ProjectError("invalid_payload", "payload 必须是 JSON 对象。")
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_RE.fullmatch(idempotency_key):
        raise ProjectError("invalid_idempotency_key", "写命令必须提供 1–128 位规范幂等键。")
    project_dir = _project_dir(projects_dir, project_id)
    with _write_lock(project_dir):
        state, events, recovered = _current_locked(project_dir, project_id)
        safety = _safety_violations(
            payload,
            safety_context=state["intake"]["safety"],
            resources_context=state["intake"]["resources"],
        )
        if safety:
            raise ProjectError("blocked_safety", "payload 触发不可覆盖的安全边界。", safety)
        if idempotency_key:
            match = next((event for event in events if event.get("idempotency_key") == idempotency_key), None)
            if match:
                if match["event_type"] != event_type or _canonical(match["payload"]) != _canonical(payload):
                    raise ProjectError("idempotency_conflict", "幂等键已被不同内容使用。")
                return {"duplicate": True, "recovered": recovered, "event": match, "state": state, "resume_summary": _resume(state)}
        if expected_revision is None:
            raise ProjectError("expected_revision_required", "变更项目状态必须提供 expected_revision。")
        if expected_revision != state["revision"]:
            raise ProjectError("revision_conflict", f"期望 revision {expected_revision}，当前为 {state['revision']}。", {"expected": expected_revision, "actual": state["revision"]})
        event = _new_event(project_id, event_type, payload, state["revision"] + 1, events[-1]["event_hash"], idempotency_key)
        candidate = _apply_event(state, event)
        _append_event(project_dir, event)
        _atomic_json(project_dir / "state.json", candidate)
        return {"duplicate": False, "recovered": recovered, "event": event, "state": candidate, "resume_summary": _resume(candidate)}


def rebuild_project(projects_dir: Path, project_id: str) -> dict[str, Any]:
    project_dir = _project_dir(projects_dir, project_id)
    with _write_lock(project_dir):
        state, events, _ = _current_locked(project_dir, project_id)
        _atomic_json(project_dir / "manifest.json", _manifest(project_id))
        _atomic_json(project_dir / "state.json", state)
        return {"rebuilt": True, "event_count": len(events), "state": state, "resume_summary": _resume(state)}


def checkpoint_project(projects_dir: Path, project_id: str, stage_id: str, status: str, evidence_ids: list[str], outputs: list[str], known_not_verified: list[str], baseline_hash: str, *, idempotency_key: str | None = None, expected_revision: int | None = None) -> dict[str, Any]:
    return record_event(
        projects_dir, project_id, "generation.stage_recorded",
        {"stage_id": stage_id, "status": status, "evidence_ids": evidence_ids, "outputs": outputs, "known_not_verified": known_not_verified, "baseline_hash": baseline_hash},
        idempotency_key=idempotency_key, expected_revision=expected_revision,
    )


def release_project(projects_dir: Path, project_id: str, release_id: str, artifact_hash: str, *, idempotency_key: str | None = None, expected_revision: int | None = None) -> dict[str, Any]:
    return record_event(
        projects_dir, project_id, "generation.release_recorded",
        {"release_id": release_id, "artifact_hash": artifact_hash},
        idempotency_key=idempotency_key, expected_revision=expected_revision,
    )


def _parse_object(raw: str, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectError("invalid_payload", f"{name} 不是有效 JSON。", str(exc)) from exc
    if not isinstance(value, dict):
        raise ProjectError("invalid_payload", f"{name} 必须是 JSON 对象。")
    return value


def _parse_list(raw: str, name: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectError("invalid_payload", f"{name} 不是有效 JSON。", str(exc)) from exc
    return _string_list(value, name)


def _write_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--idempotency-key")
    parser.add_argument("--expected-revision", type=int)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="STM32 AI Mentor V2 项目侧车工具（不会自动烧录）")
    parser.add_argument("--projects-dir", "--store", dest="projects_dir", type=Path, default=DEFAULT_PROJECTS)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--project-id", required=True)
    init_payload = init.add_mutually_exclusive_group(required=True)
    init_payload.add_argument("--intake")
    init_payload.add_argument("--payload-json", dest="intake")
    _write_options(init)
    for command in ("status", "validate", "rebuild"):
        item = sub.add_parser(command)
        item.add_argument("--project-id", required=True)
    record = sub.add_parser("record")
    record.add_argument("--project-id", required=True)
    record.add_argument("--event-type", required=True)
    record_payload = record.add_mutually_exclusive_group(required=True)
    record_payload.add_argument("--payload")
    record_payload.add_argument("--payload-json", dest="payload")
    _write_options(record)
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--project-id", required=True)
    checkpoint.add_argument("--stage-id")
    checkpoint.add_argument("--status", choices=["pending", "in_progress", "blocked", "passed"])
    checkpoint.add_argument("--evidence-ids", default="[]")
    checkpoint.add_argument("--outputs", default="[]")
    checkpoint.add_argument("--known-not-verified", default="[]")
    checkpoint.add_argument("--baseline-hash")
    checkpoint.add_argument("--payload-json")
    _write_options(checkpoint)
    release = sub.add_parser("release")
    release.add_argument("--project-id", required=True)
    release.add_argument("--release-id", default="release-1")
    release.add_argument("--artifact-hash", default="0" * 64)
    release.add_argument("--payload-json")
    _write_options(release)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    projects_dir = args.projects_dir.resolve()
    try:
        if args.command == "init":
            if args.expected_revision not in (None, 0):
                raise ProjectError("revision_conflict", "初始化项目的 expected_revision 必须为 0。")
            if args.idempotency_key is not None and not IDEMPOTENCY_RE.fullmatch(args.idempotency_key):
                raise ProjectError("invalid_idempotency_key", "显式 init 幂等键必须是 1–128 位规范字符串。")
            result = init_project(
                projects_dir, args.project_id, _parse_object(args.intake, "intake"),
                idempotency_key=args.idempotency_key,
            )
        elif args.command == "status":
            result = get_status(projects_dir, args.project_id)
        elif args.command == "validate":
            result = validate_project(projects_dir, args.project_id)
            if not result["valid"]:
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
                return 2
        elif args.command == "record":
            result = record_event(projects_dir, args.project_id, args.event_type, _parse_object(args.payload, "payload"), idempotency_key=args.idempotency_key, expected_revision=args.expected_revision)
        elif args.command == "rebuild":
            result = rebuild_project(projects_dir, args.project_id)
        elif args.command == "checkpoint":
            checkpoint_payload = _parse_object(args.payload_json, "payload") if args.payload_json else None
            result = checkpoint_project(
                projects_dir, args.project_id,
                checkpoint_payload.get("stage_id") if checkpoint_payload else args.stage_id,
                checkpoint_payload.get("status") if checkpoint_payload else args.status,
                _string_list(checkpoint_payload.get("evidence_ids", []), "evidence_ids") if checkpoint_payload else _parse_list(args.evidence_ids, "evidence_ids"),
                _string_list(checkpoint_payload.get("outputs", []), "outputs") if checkpoint_payload else _parse_list(args.outputs, "outputs"),
                _string_list(checkpoint_payload.get("known_not_verified", []), "known_not_verified") if checkpoint_payload else _parse_list(args.known_not_verified, "known_not_verified"),
                checkpoint_payload.get("baseline_hash") if checkpoint_payload else args.baseline_hash,
                idempotency_key=args.idempotency_key, expected_revision=args.expected_revision,
            )
        elif args.command == "release":
            release_payload = _parse_object(args.payload_json, "payload") if args.payload_json else None
            result = release_project(
                projects_dir, args.project_id,
                release_payload.get("release_id", args.release_id) if release_payload else args.release_id,
                release_payload.get("artifact_hash", args.artifact_hash) if release_payload else args.artifact_hash,
                idempotency_key=args.idempotency_key, expected_revision=args.expected_revision,
            )
        else:  # pragma: no cover
            raise ProjectError("unknown_command", args.command)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ProjectError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    except OSError as exc:
        print(json.dumps(ProjectError("io_error", "读写项目状态失败。", str(exc)).as_dict(), ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
