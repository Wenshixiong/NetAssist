"""Increment the application version in version.py.

Examples:
    python bump_version.py             # 1.5.0 -> 1.5.1
    python bump_version.py --minor     # 1.5.1 -> 1.6.0
    python bump_version.py --major     # 1.6.0 -> 2.0.0
    python bump_version.py --set 2.1.0
"""

import argparse
import re
from pathlib import Path


VERSION_PATTERN = re.compile(r'^(VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(")$', re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update the NetAssist application version.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--major", action="store_true", help="Increment the major version.")
    group.add_argument("--minor", action="store_true", help="Increment the minor version.")
    group.add_argument("--set", metavar="X.Y.Z", help="Set an explicit semantic version.")
    return parser.parse_args()


def next_version(current: tuple[int, int, int], args: argparse.Namespace) -> tuple[int, int, int]:
    major, minor, patch = current
    if args.set:
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", args.set)
        if not match:
            raise ValueError("--set must use semantic version format X.Y.Z")
        return tuple(int(part) for part in match.groups())
    if args.major:
        return major + 1, 0, 0
    if args.minor:
        return major, minor + 1, 0
    return major, minor, patch + 1


def versioned_filename(prefix: str, version: tuple[int, int, int]) -> str:
    return f"{prefix}_v{'.'.join(str(part) for part in version)}.py"


def rename_application_files(
    root: Path,
    current: tuple[int, int, int],
    updated: tuple[int, int, int],
) -> None:
    current_module = versioned_filename("NetAssist", current)
    updated_module = versioned_filename("NetAssist", updated)
    current_launcher = versioned_filename("launch", current)
    updated_launcher = versioned_filename("launch", updated)

    module_path = root / current_module
    launcher_path = root / current_launcher
    if not module_path.exists() or not launcher_path.exists():
        raise FileNotFoundError(
            f"Expected versioned files not found: {current_module}, {current_launcher}"
        )
    if (root / updated_module).exists() or (root / updated_launcher).exists():
        raise FileExistsError(f"Target versioned files already exist: {updated_module}, {updated_launcher}")

    launcher_content = launcher_path.read_text(encoding="utf-8")
    launcher_content = launcher_content.replace(
        f"NetAssist_v{'.'.join(str(part) for part in current)}",
        f"NetAssist_v{'.'.join(str(part) for part in updated)}",
    )
    launcher_path.write_text(launcher_content, encoding="utf-8")
    module_path.rename(root / updated_module)
    launcher_path.rename(root / updated_launcher)


def main() -> None:
    args = parse_args()
    version_file = Path(__file__).with_name("version.py")
    content = version_file.read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(content)
    if not match:
        raise RuntimeError(f"Could not find a semantic VERSION in {version_file}")

    current = tuple(int(match.group(index)) for index in (2, 3, 4))
    updated = next_version(current, args)
    new_value = ".".join(str(part) for part in updated)
    updated_content = VERSION_PATTERN.sub(
        lambda found: f'{found.group(1)}{new_value}{found.group(5)}',
        content,
        count=1,
    )
    rename_application_files(version_file.parent, current, updated)
    version_file.write_text(updated_content, encoding="utf-8")
    print(f"Version updated: {'.'.join(map(str, current))} -> {new_value}")


if __name__ == "__main__":
    main()
