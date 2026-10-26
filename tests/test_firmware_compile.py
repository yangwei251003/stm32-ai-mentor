from pathlib import Path
import os
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / ".tmp-stm32cube" / "STM32CubeF1-v1.8.7"
SMOKE = ROOT / "tests" / "firmware_smoke"
IDE_PLUGINS = Path(r"C:\ST\STM32CubeIDE_1.19.0\STM32CubeIDE\plugins")


def find_gcc():
    if not IDE_PLUGINS.exists():
        return None
    return next(IDE_PLUGINS.rglob("arm-none-eabi-gcc.exe"), None)


def test_official_cube_f1_tag_is_pinned():
    if not PACK.exists():
        pytest.skip("temporary STM32CubeF1 verification pack is not present")
    completed = subprocess.run(
        ["git", "-C", str(PACK), "describe", "--tags", "--always"],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    assert completed.stdout.strip() == "v1.8.7"


def test_lesson_hal_api_smoke_compiles_with_cubeide_gcc(tmp_path):
    gcc = find_gcc()
    if gcc is None or not PACK.exists():
        pytest.skip("CubeIDE GCC or temporary STM32CubeF1 pack is unavailable")
    includes = [
        SMOKE,
        PACK / "Drivers" / "CMSIS" / "Include",
        PACK / "Drivers" / "CMSIS" / "Device" / "ST" / "STM32F1xx" / "Include",
        PACK / "Drivers" / "STM32F1xx_HAL_Driver" / "Inc",
        PACK / "Drivers" / "STM32F1xx_HAL_Driver" / "Inc" / "Legacy",
    ]
    command = [
        str(gcc), "-c", "-std=c11", "-mcpu=cortex-m3", "-mthumb",
        "-DSTM32F103xB", "-DUSE_HAL_DRIVER", "-Wall", "-Wextra", "-Werror",
        str(SMOKE / "stm32f103_hal_smoke.c"), "-o", str(tmp_path / "hal-smoke.o"),
    ]
    for include in includes:
        command.extend(["-I", str(include)])
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, env=env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (tmp_path / "hal-smoke.o").is_file()
