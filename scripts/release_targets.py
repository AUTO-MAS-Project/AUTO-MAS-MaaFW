"""算出这次要发布哪些包（发布工作流用）。

三种触发：

- 推到 main：比较推送前后每个包 ``pyproject.toml`` 里的版本号，变了的发布。推送前的提交取不到
  （新分支、强推后丢失）时，按「全部有变化」处理；PyPI 上已有的版本由上传步骤跳过。
- 包级标签 ``<发行包名>-v<版本>``：只发这一个包，标签里的版本必须等于 ``pyproject.toml``。
- 手动触发：给出包名和版本，版本必须等于 ``pyproject.toml``。

结果写进 ``$GITHUB_OUTPUT``：``targets`` 是 JSON 数组，每项 ``{"dist", "env", "version"}``；
``has_targets`` 是 ``true`` / ``false``。本地调试时不设 ``GITHUB_OUTPUT``，结果打到标准输出。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 发行包名 → 发布环境名（pypi-<导入名去掉 maafw_ 前缀>）。顺序即发布顺序。
ENVIRONMENTS = {
    "auto-mas-maafw-native": "pypi-native",
    "auto-mas-maafw-interface": "pypi-interface",
    "auto-mas-maafw-agent-env": "pypi-agent-env",
    "auto-mas-maafw-runner": "pypi-runner",
    "auto-mas-maafw-project-update": "pypi-project-update",
}
ZERO_SHA = "0" * 40


def _version_at(ref: str | None, dist: str) -> str | None:
    path = f"packages/{dist}/pyproject.toml"
    if ref is None:
        text = (ROOT / path).read_text(encoding="utf-8")
    else:
        result = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            return None
        text = result.stdout
    return str(tomllib.loads(text)["project"]["version"])


def _ref_exists(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


def resolve(event: str, ref: str, before: str, package: str, version: str) -> list[dict[str, str]]:
    current = {dist: _version_at(None, dist) or "" for dist in ENVIRONMENTS}
    picked: list[str] = []

    if event == "workflow_dispatch":
        if package not in ENVIRONMENTS:
            raise SystemExit(f"不认识的包：{package}")
        if version != current[package]:
            raise SystemExit(f"{package} 的版本是 {current[package]}，与输入的 {version} 不一致")
        picked = [package]
    elif ref.startswith("refs/tags/"):
        tag = ref.removeprefix("refs/tags/")
        for dist in ENVIRONMENTS:
            if tag.startswith(f"{dist}-v"):
                tag_version = tag.removeprefix(f"{dist}-v")
                if tag_version != current[dist]:
                    raise SystemExit(f"标签 {tag} 与 {dist} 的版本 {current[dist]} 不一致")
                picked = [dist]
                break
        else:
            raise SystemExit(f"标签 {tag} 不对应任何包")
    elif ref == "refs/heads/main":
        if not before or before == ZERO_SHA or not _ref_exists(before):
            picked = list(ENVIRONMENTS)
        else:
            picked = [
                dist for dist in ENVIRONMENTS if _version_at(before, dist) != current[dist]
            ]
    return [
        {"dist": dist, "env": ENVIRONMENTS[dist], "version": current[dist]}
        for dist in ENVIRONMENTS
        if dist in picked
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event-name", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--before-sha", default="")
    parser.add_argument("--package", default="")
    parser.add_argument("--version", default="")
    args = parser.parse_args()

    targets = resolve(args.event_name, args.ref, args.before_sha, args.package, args.version)
    lines = [
        f"targets={json.dumps(targets, ensure_ascii=False)}",
        f"has_targets={'true' if targets else 'false'}",
        f"dists={' '.join(item['dist'] for item in targets)}",
    ]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
