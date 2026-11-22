"""构建仓库里五个包的 wheel 和 sdist。

用法::

    python scripts/build_all.py                       # 五个包都打到 dist/
    python scripts/build_all.py auto-mas-maafw-runner --outdir dist/runner   # 只打指定的包

不带 ``--wheel`` / ``--sdist``：``python -m build`` 先打 sdist，再从解开的 sdist 打 wheel。
同时给这两个参数时 wheel 直接从源码目录打，setuptools 会沿用包目录下残留的 ``build/lib``，
已经删掉的文件（如 ``worker_protocol.py``）会被悄悄打进 wheel。

打之前先删掉输出目录里同名包的旧产物，免得 ``twine check dist/*`` 和发布带上旧版本。
需要 ``build``（``pip install build``）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
# 按依赖顺序：两块库在前，agent 环境在运行和项目更新之前
PACKAGES = (
    "auto-mas-maafw-native",
    "auto-mas-maafw-interface",
    "auto-mas-maafw-agent-env",
    "auto-mas-maafw-runner",
    "auto-mas-maafw-project-update",
)


def _clear_old(outdir: Path, name: str) -> None:
    prefix = name.replace("-", "_") + "-"
    for path in outdir.glob(prefix + "*"):
        if path.is_file() and path.suffix in {".whl", ".gz"}:
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("packages", nargs="*", help="发行包名，不给就全部")
    parser.add_argument("--outdir", type=Path, default=DIST)
    args = parser.parse_args()

    names = args.packages or list(PACKAGES)
    unknown = [name for name in names if name not in PACKAGES]
    if unknown:
        raise SystemExit(f"不认识的包：{', '.join(unknown)}；可选：{', '.join(PACKAGES)}")

    outdir: Path = args.outdir if args.outdir.is_absolute() else ROOT / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    for name in names:
        _clear_old(outdir, name)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                str(ROOT / "packages" / name),
                "--outdir",
                str(outdir),
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    main()
