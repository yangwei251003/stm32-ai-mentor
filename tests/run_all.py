"""Run the complete deterministic V1 validation suite from any working directory."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")],
        cwd=ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
