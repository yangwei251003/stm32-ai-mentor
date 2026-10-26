"""Narrow, fail-closed KiCad execution surface for STM32 AI Mentor."""

from .service import EdaLabError, EdaLabMcp, detect_kicad_cli, inspect_kicad_ipc

__all__ = ["EdaLabError", "EdaLabMcp", "detect_kicad_cli", "inspect_kicad_ipc"]
