from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_forbidden_layout_overrides() -> int:
    path = ROOT / "arch_distribution_dialog.py"
    text = read_text(path)

    forbidden = [
        "gData.setColumnStretch(",
        "gData.setColumnMinimumWidth(",
        "comboStudyArea.setMinimumWidth(",
        "listTopoLayers.setMinimumWidth(",
        "listHeritageLayers.setMinimumWidth(",
        "ld1u.setWordWrap(",
        "ld1u.setMaximumWidth(",
    ]

    errors = 0
    for token in forbidden:
        if token in text:
            fail(f"Forbidden layout override found in arch_distribution_dialog.py: {token}")
            errors += 1
    if errors == 0:
        ok("No forbidden runtime layout overrides found")
    return errors


def check_ui_baseline_exists() -> int:
    required = [
        ROOT / "1.0.1" / "arch_distribution_dialog_base.ui",
        ROOT / "1.0.1" / "arch_distribution_dialog.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        for p in missing:
            fail(f"Missing baseline file: {p}")
        return len(missing)
    ok("1.0.1 baseline files exist")
    return 0


def check_version_sync() -> int:
    metadata_text = read_text(ROOT / "metadata.txt")
    readme_text = read_text(ROOT / "README.md")

    m = re.search(r"^version=(\d+\.\d+\.\d+)\s*$", metadata_text, flags=re.MULTILINE)
    if not m:
        fail("metadata.txt does not contain version=MAJOR.MINOR.PATCH")
        return 1
    version = m.group(1)

    required_snippets = [
        f"Version: `{version}`",
        f"version = {{{version}}}",
    ]

    errors = 0
    for snippet in required_snippets:
        if snippet not in readme_text:
            fail(f"README.md missing version snippet: {snippet}")
            errors += 1
    if errors == 0:
        ok(f"Version synced between metadata.txt and README.md ({version})")
    return errors


def main() -> int:
    errors = 0
    errors += check_forbidden_layout_overrides()
    errors += check_ui_baseline_exists()
    errors += check_version_sync()

    if errors:
        print(f"\nGuardrail check failed with {errors} issue(s).")
        return 1
    print("\nGuardrail check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
