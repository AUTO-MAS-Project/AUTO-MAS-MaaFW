"""发版前核对打出来的 wheel 与 sdist：不带测试与构建残留、包内文件与源码一致、依赖元数据与 pyproject 一致。

用法（在积木仓根跑；解释器要有 ``packaging``，例如仓库根的 ``.venv-dev``）::

    python scripts/check_dists.py <放 wheel / sdist 的目录> [--ref HEAD] [--list]

``<目录>`` 下递归找六个包的 ``*.whl`` 与 ``*.tar.gz``（``scripts/build_all.py`` 或 ``uv build`` 的产物都行），
每个包必须恰好一个 wheel、一个 sdist。对照的是 git 引用 ``--ref``（缺省 ``HEAD``）里已跟踪的文件，
所以要从同一个引用的干净导出（``git archive``）构建，再拿这个引用来比；活目录里没被跟踪的
``build/lib`` 残留会被 setuptools 悄悄打进 wheel（已删的模块又回来了），本脚本按「wheel 里多出了源码
没有的文件」报出来。

核对：

1. wheel：不带 ``tests/``、``test_*.py``、``conftest.py``；不带 ``__pycache__``、``*.pyc``、``*.egg-info``、
   ``build/`` 之类构建残留；``*.dist-info`` 以外的文件与 ``packages/<包>/src`` 下已跟踪的文件**逐个相同**
   （文件集合与内容都比）。
2. wheel 元数据：``Name``、``Version``、``Requires-Python`` 与 ``pyproject.toml`` 相同；``Requires-Dist`` 与
   ``[project] dependencies``（无 extra）、``[project.optional-dependencies]``（带 extra）逐条相同。
3. sdist：不带构建残留；``src`` 下已跟踪的文件都在、内容相同，``src`` 下除 setuptools 生成的
   ``*.egg-info`` 外没有多余文件；三块服务插件与共用库的 sdist 不带测试（两块库的 sdist 按惯例带已提交的测试）。

``--list`` 另把每个 wheel 的文件清单打出来。退出码：0 通过；1 有问题；2 用法错误。
"""

from __future__ import annotations

import argparse
import email.parser
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "auto-mas-maafw-interface",
    "auto-mas-maafw-native",
    "auto-mas-maafw-adapter-kit",
    "auto-mas-maafw-agent-env",
    "auto-mas-maafw-runner",
    "auto-mas-maafw-project-update",
)
#: sdist 按惯例带已提交测试的两块库
SDIST_TESTS_ALLOWED = {"auto-mas-maafw-interface", "auto-mas-maafw-native"}
RESIDUE_PARTS = {"__pycache__", "build", ".pytest_cache", ".ruff_cache", ".tmp"}
RESIDUE_SUFFIXES = (".pyc", ".pyo", ".orig", ".rej", "~")


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout


def _git_bytes(ref: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:{path}"],
        capture_output=True,
        check=True,
    ).stdout


def _normalize(data: bytes) -> bytes:
    """比内容时不管换行（``.gitattributes`` 是 ``eol=lf``，Windows 上导出与构建都可能是 LF）。"""

    return data.replace(b"\r\n", b"\n")


def _tracked_src(ref: str, dist: str) -> dict[str, bytes]:
    """``packages/<包>/src`` 下已跟踪的文件：相对 ``src`` 的路径 → 内容。"""

    prefix = f"packages/{dist}/src/"
    names = _git("ls-tree", "-r", "--name-only", ref, "--", prefix).split("\n")
    return {
        name[len(prefix) :]: _normalize(_git_bytes(ref, name))
        for name in names
        if name.startswith(prefix)
    }


def _pyproject(ref: str, dist: str) -> dict:
    return tomllib.loads(
        _git_bytes(ref, f"packages/{dist}/pyproject.toml").decode("utf-8")
    )


def _is_test(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return "tests" in parts or name.startswith("test_") or name == "conftest.py"


def _is_residue(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if any(part in RESIDUE_PARTS for part in parts[:-1]):
        return True
    if any(part.endswith(".egg-info") for part in parts):
        return True
    return path.endswith(RESIDUE_SUFFIXES)


def _req_key(text: str) -> tuple[str, str, str, str]:
    req = Requirement(text)
    return (
        canonicalize_name(req.name),
        ",".join(sorted(str(spec) for spec in req.specifier)),
        ",".join(sorted(req.extras)),
        str(req.marker or ""),
    )


def _expected_requires(project: dict) -> set[tuple[str, str, str, str]]:
    expected = {_req_key(item) for item in project.get("dependencies", [])}
    for extra, items in (project.get("optional-dependencies") or {}).items():
        for item in items:
            req = Requirement(item)
            marker = f'extra == "{extra}"'
            if req.marker is not None:
                marker = f"({req.marker}) and {marker}"
            text = f"{req.name}{''.join(f'[{e}]' for e in sorted(req.extras))}{req.specifier}; {marker}"
            expected.add(_req_key(text))
    return expected


def check_wheel(dist: str, wheel: Path, ref: str, show: bool) -> list[str]:
    problems: list[str] = []
    project = _pyproject(ref, dist)["project"]
    tracked = _tracked_src(ref, dist)
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        payload = [name for name in names if ".dist-info/" not in name]
        info_dir = {name.split("/", 1)[0] for name in names if ".dist-info/" in name}
        if show:
            print(f"  {wheel.name}（{len(names)} 个文件）：")
            for name in sorted(names):
                print(f"    {name}")
        for name in payload:
            if _is_test(name):
                problems.append(f"{wheel.name} 带了测试：{name}")
            if _is_residue(name):
                problems.append(f"{wheel.name} 带了构建残留：{name}")
        extra = sorted(set(payload) - set(tracked))
        missing = sorted(set(tracked) - set(payload))
        for name in extra:
            problems.append(f"{wheel.name} 里多了源码（{ref}）没有的文件：{name}")
        for name in missing:
            problems.append(f"{wheel.name} 里少了源码有的文件：{name}")
        for name in sorted(set(payload) & set(tracked)):
            if _normalize(archive.read(name)) != tracked[name]:
                problems.append(f"{wheel.name} 里 {name} 的内容与源码（{ref}）不同")
        if len(info_dir) != 1:
            problems.append(
                f"{wheel.name} 的 dist-info 目录不是一个：{sorted(info_dir)}"
            )
            return problems
        metadata = email.parser.Parser().parsestr(
            archive.read(f"{next(iter(info_dir))}/METADATA").decode("utf-8")
        )
    if canonicalize_name(metadata["Name"]) != canonicalize_name(project["name"]):
        problems.append(f"{wheel.name} 的 Name {metadata['Name']} ≠ {project['name']}")
    if metadata["Version"] != project["version"]:
        problems.append(
            f"{wheel.name} 的 Version {metadata['Version']} ≠ {project['version']}"
        )
    if SpecifierSet(metadata["Requires-Python"] or "") != SpecifierSet(
        project.get("requires-python", "")
    ):
        problems.append(
            f"{wheel.name} 的 Requires-Python {metadata['Requires-Python']} ≠ {project.get('requires-python')}"
        )
    got = {_req_key(item) for item in metadata.get_all("Requires-Dist") or []}
    want = _expected_requires(project)
    for item in sorted(got - want):
        problems.append(f"{wheel.name} 的 Requires-Dist 多了：{item}")
    for item in sorted(want - got):
        problems.append(f"{wheel.name} 的 Requires-Dist 少了：{item}")
    return problems


def check_sdist(dist: str, sdist: Path, ref: str) -> list[str]:
    problems: list[str] = []
    tracked = _tracked_src(ref, dist)
    with tarfile.open(sdist) as archive:
        members = [m for m in archive.getmembers() if m.isfile()]
        top = {PurePosixPath(m.name).parts[0] for m in members}
        if len(top) != 1:
            return [f"{sdist.name} 顶层目录不是一个：{sorted(top)}"]
        root = next(iter(top))
        files: dict[str, tarfile.TarInfo] = {
            str(PurePosixPath(*PurePosixPath(m.name).parts[1:])): m for m in members
        }
        for name in files:
            if _is_residue(name) and not (
                name.startswith("src/") and ".egg-info/" in name
            ):
                problems.append(f"{sdist.name} 带了构建残留：{root}/{name}")
            if dist not in SDIST_TESTS_ALLOWED and _is_test(name):
                problems.append(f"{sdist.name} 带了测试：{root}/{name}")
        src = {
            name[len("src/") :]: member
            for name, member in files.items()
            if name.startswith("src/") and ".egg-info/" not in name
        }
        for name in sorted(set(src) - set(tracked)):
            problems.append(
                f"{sdist.name} 的 src 里多了源码（{ref}）没有的文件：{name}"
            )
        for name in sorted(set(tracked) - set(src)):
            problems.append(f"{sdist.name} 的 src 里少了源码有的文件：{name}")
        for name in sorted(set(src) & set(tracked)):
            handle = archive.extractfile(src[name])
            data = b"" if handle is None else handle.read()
            if _normalize(data) != tracked[name]:
                problems.append(f"{sdist.name} 里 src/{name} 的内容与源码（{ref}）不同")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist_dir", type=Path, help="放 wheel / sdist 的目录（递归找）")
    parser.add_argument("--ref", default="HEAD", help="对照的 git 引用（缺省 HEAD）")
    parser.add_argument("--list", action="store_true", help="打出每个 wheel 的文件清单")
    args = parser.parse_args(argv)
    if not args.dist_dir.is_dir():
        print(f"不是目录：{args.dist_dir}", file=sys.stderr)
        return 2

    problems: list[str] = []
    for dist in PACKAGES:
        stem = dist.replace("-", "_")
        wheels = sorted(args.dist_dir.rglob(f"{stem}-*.whl"))
        sdists = sorted(args.dist_dir.rglob(f"{stem}-*.tar.gz"))
        print(f"{dist}：wheel {len(wheels)} 个，sdist {len(sdists)} 个")
        if len(wheels) != 1 or len(sdists) != 1:
            problems.append(
                f"{dist}：要恰好一个 wheel、一个 sdist（找到 {len(wheels)} / {len(sdists)}）"
            )
            continue
        found = check_wheel(dist, wheels[0], args.ref, args.list) + check_sdist(
            dist, sdists[0], args.ref
        )
        print(f"  {'通过' if not found else f'{len(found)} 处问题'}")
        problems.extend(found)
    if problems:
        print(f"有问题（{len(problems)}）：")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("结论：通过")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
