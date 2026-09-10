"""Increment the application version in version.py.

Besides version.py this helper also:
  * renames the launcher script (launch_vX.Y.Z.py);
  * syncs version references in 打包命令.txt, README.md, README_EN.md,
    RELEASE.md and CONTRIBUTING.md.

The main application keeps the fixed name NetAssist.py (no version suffix) so it
can be imported as a module.

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

# 需要同步版本号引用的文件（打包命令 + 文档）
VERSION_REFERENCE_FILES = (
    "打包命令.txt",
    "README.md",
    "README_EN.md",
    "RELEASE.md",
    "CONTRIBUTING.md",
)


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


def rename_launcher_file(
    root: Path,
    current: tuple[int, int, int],
    updated: tuple[int, int, int],
) -> None:
    """重命名启动器脚本。

    主应用固定为 NetAssist.py（不含版本号），以便通过 import 引入；
    启动器仅作入口脚本，保留版本号以便区分发布产物。
    """
    current_launcher = versioned_filename("launch", current)
    updated_launcher = versioned_filename("launch", updated)

    launcher_path = root / current_launcher
    if not launcher_path.exists():
        raise FileNotFoundError(f"Expected launcher not found: {current_launcher}")
    if (root / updated_launcher).exists():
        raise FileExistsError(f"Target launcher already exists: {updated_launcher}")

    launcher_path.rename(root / updated_launcher)


def update_version_references(
    root: Path,
    current: tuple[int, int, int],
    updated: tuple[int, int, int],
) -> list[str]:
    """同步打包命令与文档中的版本号引用。

    仅替换带 v 前缀的版本号（NetAssist_v1.5.2 / launch_v1.5.2 / v1.5.2），
    避免误伤说明性示例里的裸版本号（如 `# 1.5.2 -> 1.5.3`）。
    """
    current_tag = "v" + ".".join(str(part) for part in current)
    updated_tag = "v" + ".".join(str(part) for part in updated)

    changed: list[str] = []
    for name in VERSION_REFERENCE_FILES:
        path = root / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if current_tag not in content:
            continue
        path.write_text(content.replace(current_tag, updated_tag), encoding="utf-8")
        changed.append(name)
    return changed


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
    rename_launcher_file(version_file.parent, current, updated)
    changed_files = update_version_references(version_file.parent, current, updated)
    version_file.write_text(updated_content, encoding="utf-8")
    print(f"Version updated: {'.'.join(map(str, current))} -> {new_value}")
    if changed_files:
        print(f"Version references synced: {', '.join(changed_files)}")


if __name__ == "__main__":
    main()
