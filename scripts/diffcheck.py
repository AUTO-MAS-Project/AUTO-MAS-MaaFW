"""按 MAPPING.md 的文件来源表统计搬运后的逐行差异。"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = ROOT / "docs" / "notes" / "MAPPING.md"
ROW = re.compile(r"^\|\s*\x60([^\x60]+)\x60\s*\|\s*\x60([^\x60]+)\x60(?:\s*\|.*)?$")
RANGE = re.compile(r"L(\d+)-L(\d+)")


def read_rows(mapping: Path) -> list[tuple[str, str]]:
    rows = []
    inside = False
    for line in mapping.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 文件来源"):
            inside = True
            continue
        if line.startswith("## "):
            inside = False
        if inside:
            match = ROW.match(line)
            if match and match.group(1) not in {"库文件", "文件"}:
                rows.append((match.group(1), match.group(2)))
    return rows


def source_spec(text: str) -> tuple[Path, list[tuple[int, int]]]:
    path_text, _, range_text = text.partition("#")
    path = ROOT / path_text
    ranges = []
    for item in range_text.split(","):
        match = RANGE.fullmatch(item)
        if match:
            ranges.append((int(match.group(1)), int(match.group(2))))
    return path, ranges


def old_lines(text: str) -> list[str]:
    path, ranges = source_spec(text)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not ranges:
        return lines
    selected: list[str] = []
    for start, end in ranges:
        selected.extend(lines[start - 1 : end])
    return selected


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    args = parser.parse_args()
    total_old = total_add = total_del = 0
    print("| 库文件 | 原件行数 | 增 | 删 | 状态 |")
    print("| --- | ---: | ---: | ---: | --- |")
    for library, source in read_rows(args.mapping):
        lp = ROOT / library
        sp, _ = source_spec(source)
        if not lp.is_file():
            print(f"| \x60{library}\x60 | - | - | - | 库文件尚未搬入 |")
            continue
        if not sp.is_file():
            print(f"| \x60{library}\x60 | - | - | - | 原件不存在 |")
            continue
        old = old_lines(source)
        new = lp.read_text(encoding="utf-8").splitlines(keepends=True)
        add = delete = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new).get_opcodes():
            if tag in {"replace", "insert"}:
                add += j2 - j1
            if tag in {"replace", "delete"}:
                delete += i2 - i1
        total_old += len(old)
        total_add += add
        total_del += delete
        print(f"| \x60{library}\x60 | {len(old)} | {add} | {delete} | 已比较 |")
    print(f"\n合计：原件 {total_old} 行，增 {total_add} 行，删 {total_del} 行。")


if __name__ == "__main__":
    main()
