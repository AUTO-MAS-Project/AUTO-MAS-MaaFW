# 0.3.0 发版清单

积木仓六个包、三个专项（通用 MFW、M9A、MSS）和宿主下限一起升到服务化之后的第一版 0.3.0。这份清单给人照着做：每一步写了在哪个目录跑什么命令、看到什么算过。设计依据是 AUTO-MAS 工作区《MFW 服务化实施方案》§8（版本与依赖范围）与工作单 W11、W12、WH；契约本身见 [`service-contract-0.3.md`](service-contract-0.3.md)。

**改版本号、改依赖范围、推送、打标签、发 PyPI，每一步都要用户先点头。** 本清单写于 2026-11-25，对照的是积木仓 `cx/svc-close-20261124`、三个专项仓 `cx/svc-close-20261124`、宿主 `cx/mfw-host-20261124` 当时的文件；下面「现在」一栏的行号以那时为准，动手前用每节给的 `git grep` 再核一遍。

本清单里的本机路径：积木仓 `D:\MAS\code\blocks`，专项仓 `D:\MAS\code\adapters\{maafw,m9a,mss}`，对拍仓 `D:\MAS\code\par2`，uv 是 `D:\MAS\code\main\environment\python\Scripts\uv.exe`（全局没有 uv）。下面用 `$uv` 指它：

```powershell
$uv = 'D:\MAS\code\main\environment\python\Scripts\uv.exe'
```

## 0. 已知约束（先读）

1. **不能发成 0.2.x。** 0.2.0 的三个专项写的是 `auto-mas-maafw-*>=0.2.0,<0.3`，而且直接导入三块服务插件的模块（例如 `maafw_runner.host.run_verdict`、`maafw_runner.host.host_client`、`maafw_runner.core.runner.service`，0.2.0 之后都已删掉，共 12 个文件）。积木若发 0.2.1，装着 0.2.0 专项的用户会被升到它、专项加载失败。0.3.0 落在旧专项的范围之外，pip / uv 解不出「0.2 专项 + 0.3 积木」，旧组合自洽。
2. **一族一起到 0.3.0。** 包间接口全换了（插件之间只经服务调用、0.2 的分发式整名 `maafw.runner.v1` / `maafw.agent_env.v1` / `maafw.project.v1` 已删），0.3 的专项配 0.2 的积木同样不行。
3. **0.3.0 是第一个带 `contract.py` 的版本**，兼容核对脚本这一版只能 `--self` 自检；从 0.3.1 起每次发版对上一版跑（§2.4）。
4. **不要在活目录里构建。** `packages\auto-mas-maafw-adapter-kit`、`packages\auto-mas-maafw-interface`、`packages\auto-mas-maafw-native` 下各有一个没被 git 跟踪的过期 `build\lib`；直接从源码目录打 wheel（`--wheel` 单打、或从源码目录直接 `bdist_wheel`）时 setuptools 会沿用它：interface 那份里还留着已删的 `maafw_interface\worker_protocol.py`，会被打进 wheel（2026-11-25 在临时拷贝里实测复现过）。**发版时必须从干净导出（`git archive`）构建，或先清掉这三个 `build` 目录。** CI 与发布工作流是新检出、不受影响；`scripts\build_all.py` 和 `uv build` 不带 `--wheel` 时都是先打 sdist 再从 sdist 打 wheel，也不受影响。
5. **发布有先后。** 新版本在镜像上可见约需 10 分钟（已知问题第 49 条）。顺序：interface、native → adapter-kit、agent-env → runner、project-update → 三个专项 → 宿主（WH 那一版）。上一批在 PyPI 上可安装之后再发下一批。
6. **宿主侧前提。** 0.3 专项的收尾步骤都是服务调用，宿主要带「先封入口、停完任务再封服务注册表」那一路改动（实施方案 WS），否则退出时关游戏、恢复分辨率做不到；宿主的三个专项最低版本（WH）要等三个专项 0.3.0 在 PyPI 上可装之后再随宿主发。
7. **已装 0.2 全家的宿主只升一个专项**会撞已知问题第 47 条（宿主装插件时把别的已装插件钉在当前版本），宿主那边在修。
8. **发布前置**：本地联调（W13，用本地 wheel 做「无联接存量升级演练」）与真机（W14）都过了才发 PyPI（实施方案 §6.2、§7.4、§7.5）。

## 1. 发版前置

- [ ] 用户同意实施方案 §8 的版本与依赖范围。
- [ ] 积木仓的 `cx/svc-close-20261124` 已并进 `main`（发布工作流只在 `main` 上跑，标签也必须打在 `main` 上），三个专项仓的同名分支已并进 `master`。怎么并另行决定，本清单不含。
- [ ] 各仓工作区干净：

```powershell
foreach ($r in 'D:\MAS\code\blocks','D:\MAS\code\adapters\maafw','D:\MAS\code\adapters\m9a','D:\MAS\code\adapters\mss') {
  "$r $(git -C $r rev-parse --abbrev-ref HEAD) $(git -C $r rev-parse --short HEAD) 改动=$((git -C $r status --porcelain).Count)"
}
```

## 2. 发版前检查（改版本号之前跑一遍，改完、提交后再跑一遍）

### 2.1 五条导入守卫（结果都必须是 0）

```powershell
# G-ADP：三个专项仓各跑一次
foreach ($r in 'maafw','m9a','mss') {
  Set-Location "D:\MAS\code\adapters\$r"
  "G-ADP $r = " + (Select-String -Path (Get-ChildItem src -Recurse -Filter *.py).FullName `
    -Pattern '^\s*(from|import)\s+maafw_(runner|project_update|agent_env)\b', 'import_module\(\s*[''"]maafw_(runner|project_update|agent_env)' |
    Measure-Object).Count
}
# 其余四条在积木仓根
Set-Location D:\MAS\code\blocks
"G-KIT = " + (Select-String -Path (Get-ChildItem packages\auto-mas-maafw-adapter-kit\src -Recurse -Filter *.py).FullName -Pattern '^\s*(from|import)\s+maafw_(runner|project_update|agent_env)\b' | Measure-Object).Count
"G-PU = " + (Select-String -Path (Get-ChildItem packages\auto-mas-maafw-project-update\src -Recurse -Filter *.py).FullName -Pattern '^\s*(from|import)\s+maafw_(agent_env|runner)\b' | Measure-Object).Count
"G-RUN-HOST = " + (Select-String -Path (Get-ChildItem packages\auto-mas-maafw-runner\src\maafw_runner\host -Recurse -Filter *.py).FullName -Pattern '^\s*(from|import)\s+maafw_(agent_env|project_update)\b', 'import_module\(' | Measure-Object).Count
"G-RUN-CORE = " + (Select-String -Path (Get-ChildItem packages\auto-mas-maafw-runner\src\maafw_runner\core -Recurse -Filter *.py).FullName -Pattern '^\s*(from|import)\s+maafw_agent_env(?!\.core\.worker_api\b)' | Measure-Object).Count
```

2026-11-25 在积木 `198793c`、专项 `5e64f2c` / `3e9ddb0` / `f7dbbd1` 上实跑，七个数都是 0。这几条同时写成了各仓的本地 AST 守卫测试，随 §2.2 一起跑。

### 2.2 九个包的本地测试

本地测试只留本机（被 git 忽略、不在发行包里），解释器是本机为它们建的临时 venv，跑法记在 `D:\MAS\code\cx1\out\baseline-local-tests.md`；现成的脚本 `%TEMP%\cx1h\run-local.ps1` 把九个包按记录的解释器与环境变量（专项测试要 `PYTHONPATH` 指积木仓六个 `packages\*\src`、`AUTO_MAS_HOST_SOURCE` 指宿主源码导出）各跑一遍，每个用独立的 `--basetemp`：

```powershell
pwsh -NoProfile -File $env:TEMP\cx1h\run-local.ps1 -Tag rel030-pre          # 九个都跑
pwsh -NoProfile -File $env:TEMP\cx1h\run-local.ps1 -Tag rel030-pre -Only runner,interface   # 只跑几个
Get-Content $env:TEMP\cx1h\rel030-pre\summary.txt
```

`%TEMP%` 里的这两个脚本（`run-local.ps1`、§2.3 的 `run-parity.ps1`）被清掉时，照 `baseline-local-tests.md` 与对拍仓 `DIFF_L2.md` 里记的解释器、环境变量和命令逐个跑，效果相同。

算过：每行 `exit=0`、没有 failed / error。积木六个包 2026-11-25 的基线：runner 51 passed、project-update 123 passed、agent-env 114 passed、adapter-kit 89 passed、interface 68 passed 8 skipped、native 10 passed 10 skipped。三个专项以最近一次记录为准。

### 2.3 对拍

在对拍仓按它自己的做法跑：先把 `D:\MAS\code\par2\work\now` 换成这次要发的那组提交的导出（宿主、积木、三个专项；做法与 `harness\golden\BASELINE.json` 的记法见对拍仓的 `DIFF_L2.md`），再三种驱动各跑一遍、金样逐字节比：

```powershell
pwsh -NoProfile -File $env:TEMP\cx1h\run-parity.ps1 -Tag rel030-par
pwsh -NoProfile -File $env:TEMP\cx1h\run-parity.ps1 -Tag rel030-par-s -Seed 31337
Get-Content $env:TEMP\cx1h\rel030-par\summary.txt
```

算过：manager、l2、service 三行 `exit=0` 且通过数与基线相同（第四轮后是 manager 115、l2 125、service 148），`bytes` 那行「金样 113 份，逐字节不同或缺 0 份」；两个种子都一样。

### 2.4 服务契约兼容核对

在积木仓根：

```powershell
Set-Location D:\MAS\code\blocks
.\.venv-dev\Scripts\python.exe -I scripts\contract_compat.py --self          # 0.3.0：只自检
# 0.3.1 起：对上一发行版
.\.venv-dev\Scripts\python.exe -I scripts\contract_compat.py --base auto-mas-maafw-agent-env-v0.3.0 `
  --base runner=auto-mas-maafw-runner-v0.3.0 --base project_update=auto-mas-maafw-project-update-v0.3.0
```

算过：`结论：通过`、退出码 0。退出码 1 是有不兼容（按列出的条目改，或者那个改动本来就该走 `v2`）；3 是基线里没有 `contract.py`（对 0.2.0 跑就是这样，无从比较）。没有发行标签时不给 `--base` 会报错退出，用提交号作基线也行（`--base <提交>`）。2026-11-25 在 `198793c` 上：`--self` 与 `--base HEAD` 都通过（取样 203 份，覆盖共用库 `requires` 的 75 个服务名）；`--base f0bd57b`（0.2.0 的发版提交）三块都「无从比较」。

### 2.5 构建与发行包核对（不在活目录里构建）

```powershell
Set-Location D:\MAS\code\blocks
$ref = git rev-parse --short HEAD
$work = Join-Path $env:TEMP "rel030-$ref"            # 新目录，不要复用
New-Item -ItemType Directory $work | Out-Null
git archive --format=tar HEAD -o "$work\src.tar"
New-Item -ItemType Directory "$work\src" | Out-Null
tar -xf "$work\src.tar" -C "$work\src"
foreach ($p in 'auto-mas-maafw-interface','auto-mas-maafw-native','auto-mas-maafw-adapter-kit','auto-mas-maafw-agent-env','auto-mas-maafw-runner','auto-mas-maafw-project-update') {
  & $uv build "$work\src\packages\$p" --out-dir "$work\dist\$p" --python .\.venv-dev\Scripts\python.exe
}
.\.venv-dev\Scripts\python.exe -I scripts\check_dists.py "$work\dist" --ref $ref --list > "$work\check_dists.txt"
Get-Content "$work\check_dists.txt" | Select-String -NotMatch '^    '
```

算过：`check_dists.py` 结论「通过」（每个 wheel 不带测试与构建残留、包内文件与该提交 `src` 下已跟踪的文件逐个相同、`Requires-Dist` / `Version` / `Requires-Python` 与 `pyproject.toml` 一致；sdist 同样核过）。`check_dists.txt` 里留着每个 wheel 的文件清单。再用一个干净 venv 只装这六个 wheel 验导入：

```powershell
& $uv venv "$work\smoke" --python .\.venv-dev\Scripts\python.exe
& $uv pip install --python "$work\smoke\Scripts\python.exe" --no-deps (Get-ChildItem "$work\dist" -Recurse -Filter *.whl).FullName
& $uv pip install --python "$work\smoke\Scripts\python.exe" "pydantic==2.11.7" "json5==0.14.0" packaging psutil
Push-Location $work
& "$work\smoke\Scripts\python.exe" -I D:\MAS\code\blocks\scripts\smoke_import.py maafw_interface maafw_native maafw_adapter_kit
Pop-Location
```

算过：「失败 0 个，带出的宿主模块：无」。`maafw_agent_env.core`、`maafw_runner.core` 还要 maafw 等三方包（CI 装的是 `maafw==5.16.1` 一组），本地没装时只有 `maafw_runner.core.runner.runner`、`.worker` 两个模块因 `No module named 'maa'` 失败，CI 上全量验。

专项的 wheel（W12）：在各专项仓同样 `git archive` 后 `& $uv build <导出目录> --out-dir <目录>`，再看依赖元数据（Requires-Dist 里的范围会写成 `<0.4,>=0.3.0` 这种顺序）：

```powershell
D:\MAS\code\blocks\.venv-dev\Scripts\python.exe -c "import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); n=[x for x in z.namelist() if x.endswith('.dist-info/METADATA')][0]; print('\n'.join(l for l in z.read(n).decode().splitlines() if l.startswith(('Name','Version','Requires-Dist'))))" <专项 wheel 路径>
```

算过：与 §3.2 的「改成」一栏逐条相同。

## 3. 改版本号与依赖范围

依赖范围的口径（实施方案 §8）：两块库与专项共用库被直接导入，写 `>=0.3.0,<0.4`；对三块服务插件只写下限 `>=0.3.0`（无上限，破坏性改动走 `v2` 操作）；`auto-mas-core>=5.9.0b1,<6` 与 pydantic / json5 / packaging 不动。

### 3.1 积木仓（`D:\MAS\code\blocks`）

核对现值：

```powershell
git grep -n -E '^version = |auto-mas-maafw-[a-z-]+(>=|<)' -- 'packages/*/pyproject.toml'
git grep -n -E '^(PACKAGE_)?VERSION = ' -- 'packages/*/src/*/plugin.py'
```

| 文件 | 行 | 现在 | 改成 |
| --- | --- | --- | --- |
| `packages/auto-mas-maafw-interface/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| `packages/auto-mas-maafw-native/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| `packages/auto-mas-maafw-adapter-kit/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| 同上 | 17 | `"auto-mas-maafw-interface>=0.2.0,<0.3",` | `"auto-mas-maafw-interface>=0.3.0,<0.4",` |
| 同上 | 18 | `"auto-mas-maafw-native>=0.2.0,<0.3",` | `"auto-mas-maafw-native>=0.3.0,<0.4",` |
| `packages/auto-mas-maafw-agent-env/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| 同上 | 17 | `"auto-mas-maafw-interface>=0.2.0,<0.3",` | `"auto-mas-maafw-interface>=0.3.0,<0.4",` |
| 同上 | 18 | `"auto-mas-maafw-native>=0.2.0,<0.3",` | `"auto-mas-maafw-native>=0.3.0,<0.4",` |
| `packages/auto-mas-maafw-agent-env/src/maafw_agent_env/plugin.py` | 21 | `VERSION = "0.2.0"` | `VERSION = "0.3.0"`（`version` 操作原样返回它） |
| `packages/auto-mas-maafw-runner/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| 同上 | 15 | `# worker 直接导入两块库和 agent 环境积木（拆分文档 §2.1、§4），按次版本写上限。` | 改成说明新口径：两块库按次版本写上限；agent 环境只写下限（worker 经 `maafw_agent_env.core.worker_api` 门面导入，门面带 `worker_api` 版本） |
| 同上 | 19 | `"auto-mas-maafw-interface>=0.2.0,<0.3",` | `"auto-mas-maafw-interface>=0.3.0,<0.4",` |
| 同上 | 20 | `"auto-mas-maafw-native>=0.2.0,<0.3",` | `"auto-mas-maafw-native>=0.3.0,<0.4",` |
| 同上 | 21 | `"auto-mas-maafw-agent-env>=0.2.0,<0.3",` | `"auto-mas-maafw-agent-env>=0.3.0",` |
| `packages/auto-mas-maafw-runner/src/maafw_runner/plugin.py` | 24 | `PACKAGE_VERSION = "0.2.0"` | `PACKAGE_VERSION = "0.3.0"` |
| `packages/auto-mas-maafw-project-update/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| 同上 | 17 | `"auto-mas-maafw-interface>=0.2.0,<0.3",` | `"auto-mas-maafw-interface>=0.3.0,<0.4",` |
| 同上 | 18 | `"auto-mas-maafw-native>=0.2.0,<0.3",` | `"auto-mas-maafw-native>=0.3.0,<0.4",` |
| 同上 | 19 | `"auto-mas-maafw-agent-env>=0.2.0,<0.3",` | `"auto-mas-maafw-agent-env>=0.3.0",` |
| `packages/auto-mas-maafw-project-update/src/maafw_project_update/plugin.py` | 26 | `PACKAGE_VERSION = "0.2.0"` | `PACKAGE_VERSION = "0.3.0"` |
| `README.md` | 5 | 「现在是 0.2.0，……0.2 要求宿主带托管生命周期钩子……」 | 写成 0.3.0：插件之间只经服务调用、要求带 WS 那一路改动的宿主；已知问题文档按需新开 `docs/known-issues-0.3.0.md` |
| `README.md` | 43 | 「包之间的依赖现在仍是 0.2.0 的写法……0.3.0 起改成……」 | 只留 0.3.0 的口径 |

interface、native 的依赖（pydantic、json5、packaging 与 `test` extra）不变；共用库已经不依赖项目更新（0.2.0 时依赖过），不用再删。

### 3.2 三个专项仓

核对现值（各仓根）：`git grep -n -E '^version = |auto-mas-maafw-[a-z-]+(>=|<)|^#' -- pyproject.toml`。三个专项的源码里没有版本号常量。

| 文件 | 行 | 现在 | 改成 |
| --- | --- | --- | --- |
| `adapters/maafw/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| 同上 | 18 | `# 直接 import 两块库、专项共用库和三块服务插件（跨插件越界见 README），因此都写次版本上限。` | 改成新口径：直接导入两块库与共用库、写次版本上限；三块服务插件只经服务调用、只写下限 |
| 同上 | 23 | `"auto-mas-maafw-interface>=0.2.0,<0.3",` | `"auto-mas-maafw-interface>=0.3.0,<0.4",` |
| 同上 | 24 | `"auto-mas-maafw-native>=0.2.0,<0.3",` | `"auto-mas-maafw-native>=0.3.0,<0.4",` |
| 同上 | 25 | `"auto-mas-maafw-adapter-kit>=0.2.0,<0.3",` | `"auto-mas-maafw-adapter-kit>=0.3.0,<0.4",` |
| 同上 | 26 | `"auto-mas-maafw-agent-env>=0.2.0,<0.3",` | `"auto-mas-maafw-agent-env>=0.3.0",` |
| 同上 | 27 | `"auto-mas-maafw-runner>=0.2.0,<0.3",` | `"auto-mas-maafw-runner>=0.3.0",` |
| 同上 | 28 | `"auto-mas-maafw-project-update>=0.2.0,<0.3",` | `"auto-mas-maafw-project-update>=0.3.0",` |
| `adapters/m9a/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| 同上 | 16 | `# 0.1.0 直接 import 三块积木（拆分契约 §3.2 越界 S1），所以积木也写次版本上限。` | 同通用 MFW 第 18 行的新口径 |
| 同上 | 21 | `"auto-mas-maafw-interface>=0.2.0,<0.3",` | `"auto-mas-maafw-interface>=0.3.0,<0.4",` |
| 同上 | 22 | `"auto-mas-maafw-native>=0.2.0,<0.3",` | `"auto-mas-maafw-native>=0.3.0,<0.4",` |
| 同上 | 23 | `"auto-mas-maafw-agent-env>=0.2.0,<0.3",` | `"auto-mas-maafw-agent-env>=0.3.0",` |
| 同上 | 24 | `"auto-mas-maafw-runner>=0.2.0,<0.3",` | `"auto-mas-maafw-runner>=0.3.0",` |
| 同上 | 25 | `"auto-mas-maafw-project-update>=0.2.0,<0.3",` | `"auto-mas-maafw-project-update>=0.3.0",` |
| 同上 | 26 | `"auto-mas-maafw-adapter-kit>=0.2.0,<0.3",` | `"auto-mas-maafw-adapter-kit>=0.3.0,<0.4",` |
| `adapters/mss/pyproject.toml` | 7 | `version = "0.2.0"` | `version = "0.3.0"` |
| 同上 | 18 | `# 直接 import 三块积木插件与专项共用库的模块（越界清单见 README），所以对积木也写次版本上限。` | 同通用 MFW 第 18 行的新口径 |
| 同上 | 23 | `"auto-mas-maafw-interface>=0.2.0,<0.3",` | `"auto-mas-maafw-interface>=0.3.0,<0.4",` |
| 同上 | 24 | `"auto-mas-maafw-native>=0.2.0,<0.3",` | `"auto-mas-maafw-native>=0.3.0,<0.4",` |
| 同上 | 25 | `"auto-mas-maafw-agent-env>=0.2.0,<0.3",` | `"auto-mas-maafw-agent-env>=0.3.0",` |
| 同上 | 26 | `"auto-mas-maafw-runner>=0.2.0,<0.3",` | `"auto-mas-maafw-runner>=0.3.0",` |
| 同上 | 27 | `"auto-mas-maafw-project-update>=0.2.0,<0.3",` | `"auto-mas-maafw-project-update>=0.3.0",` |
| 同上 | 28 | `"auto-mas-maafw-adapter-kit>=0.2.0,<0.3",` | `"auto-mas-maafw-adapter-kit>=0.3.0,<0.4",` |

三个专项 README 里讲越界导入、版本上限的段落一并照现状看一遍（W12 的范围）。

### 3.3 宿主下限（WH，宿主仓指定的树）

`app/core/config/plugin_upgrade.py`（存量自动装与「版本过低」提示用它）：

| 行 | 现在 | 改成 |
| --- | --- | --- |
| 44 | `# 0.2 起专项要求宿主带托管生命周期钩子；0.1.x 在本宿主上不是受支持的组合。` | 补一句 0.3 起专项只经服务调三块服务插件，0.2.x 与本宿主上的 0.3 服务插件不是受支持的组合 |
| 45 | `"maafw_adapter": Version("0.2.0"),` | `"maafw_adapter": Version("0.3.0"),` |
| 46 | `"m9a_adapter": Version("0.2.0"),` | `"m9a_adapter": Version("0.3.0"),` |
| 47 | `"mss_adapter": Version("0.2.0"),` | `"mss_adapter": Version("0.3.0"),` |
| 38 | `"MaaEndConfig": "auto-mas-maafw-interface>=0.2.0",` | **不动**（MaaEnd 只要解析库的下限） |

核对：宿主树根 `git grep -n -E 'MINIMUM_ADAPTER_VERSIONS|Version\("0\.' -- app/core/config/plugin_upgrade.py`；改完跑宿主相关测试（`tests\core\test_plugin_startup_upgrade.py`、`tests\core\test_plugin_market.py`、`tests\core\test_plugin_config_upgrade.py`，宿主测试的 `--basetemp` 路径总长不超过 47 个字符）。

## 4. CHANGELOG 落版

照 0.2.0 发版提交（`f0bd57b`）的做法：把每个包「## 未发布」这一行改成版本标题，标题写法跟着该文件已有的样式，不另留空的「未发布」段：

| 文件 | 行 | 改成 |
| --- | --- | --- |
| `packages/auto-mas-maafw-adapter-kit/CHANGELOG.md` | 3 | `## [0.3.0] - <发布日期>` |
| `packages/auto-mas-maafw-agent-env/CHANGELOG.md` | 3 | `## [0.3.0] - <发布日期>` |
| `packages/auto-mas-maafw-runner/CHANGELOG.md` | 3 | `## [0.3.0] - <发布日期>` |
| `packages/auto-mas-maafw-project-update/CHANGELOG.md` | 3 | `## [0.3.0] - <发布日期>` |
| `packages/auto-mas-maafw-interface/CHANGELOG.md` | 3 | `## 0.3.0` |
| `packages/auto-mas-maafw-native/CHANGELOG.md` | 3 | `## 0.3.0` |
| `adapters/maafw/CHANGELOG.md` | 3 | `## 0.3.0` |
| `adapters/m9a/CHANGELOG.md` | 3 | `## 0.3.0` |
| `adapters/mss/CHANGELOG.md` | 3 | `## [0.3.0] - <发布日期>` |

落版时把「未发布」里「要配合积木仓带这些模块的下一版」「要配合共用库带这个参数的下一版」这类话改成具体版本（0.3.0）；每个积木包的段落开头补一句「服务化后的第一版：插件之间只经服务调用，0.2 的分发式服务名已删（契约见积木仓 `docs/service-contract-0.3.md`）」。日期按本地日期。

## 5. 构建与发布

### 5.1 积木仓

发布工作流 `.github/workflows/publish.yml`：推到 `main` 时，`pyproject.toml` 版本号变了的包就构建、`twine check --strict`、经 Trusted Publishing 上传（仓库变量 `PUBLISH_ENABLED` 必须是 `true`，否则只构建不上传；已存在的版本跳过）。一次推送里改了几个就按 `scripts/release_targets.py` 的顺序（native、interface、agent-env、runner、project-update、adapter-kit）一个一个发，中间不等镜像。为了满足 §0 第 5 条的批次，把 §3.1 与 §4 的改动按批分三个提交、分三次推：

1. 第一批：interface、native 的版本号与 CHANGELOG。推 `main` → 等工作流绿、两个包在 PyPI 上可装。
2. 第二批：adapter-kit、agent-env 的版本号、依赖范围、`plugin.py` 常量与 CHANGELOG。同上。
3. 第三批：runner、project-update 的版本号、依赖范围、`plugin.py` 常量、CHANGELOG，加 `README.md` 两处。同上。

每批推之前在本地跑 §2.5（构建与核对）；全部推完后再跑一次 §2.1–§2.4。查某个版本在不在镜像上（能解出来就是可装了）：

```powershell
"auto-mas-maafw-interface==0.3.0" | & $uv pip compile - --no-deps --no-cache --python-version 3.12
```

打发行标签（下次 `contract_compat.py` 不给 `--base` 时就用它们作基线）：在各包的发版提交上打 `<发行包名>-v0.3.0`。推这种标签也会触发发布工作流（`skip-existing`，不会重复上传；标签必须在 `main` 上）。只在本地打、不推也行，推不推由用户定。

### 5.2 三个专项仓

六个积木包都能从 PyPI 装到 0.3.0 之后：§3.2 与 §4 的改动提交、并进 `master`，在发版提交上打 `v0.3.0` 推上去（各仓 `.github/workflows/publish.yml` 校验标签必须等于 `pyproject.toml` 的版本）。三个仓互不依赖，可以同时发。

### 5.3 宿主

三个专项 0.3.0 都能从 PyPI 装到之后，§3.3 的 WH 改动随宿主正常流程合入、发版。

## 6. 发布后检查

- [ ] 九个包 0.3.0 都能从 PyPI 解出来（§5.1 那条命令，把包名逐个换掉）。
- [ ] 从 PyPI 装六个积木包做一次干净导入：

```powershell
$work = Join-Path $env:TEMP 'rel030-pypi'            # 新目录
& $uv venv "$work" --python D:\MAS\code\blocks\.venv-dev\Scripts\python.exe
& $uv pip install --python "$work\Scripts\python.exe" --no-deps --no-cache auto-mas-maafw-interface==0.3.0 auto-mas-maafw-native==0.3.0 auto-mas-maafw-adapter-kit==0.3.0 auto-mas-maafw-agent-env==0.3.0 auto-mas-maafw-runner==0.3.0 auto-mas-maafw-project-update==0.3.0
& $uv pip install --python "$work\Scripts\python.exe" "pydantic==2.11.7" "json5==0.14.0" packaging psutil
Push-Location $env:TEMP
& "$work\Scripts\python.exe" -I D:\MAS\code\blocks\scripts\smoke_import.py maafw_interface maafw_native maafw_adapter_kit
Pop-Location
```

- [ ] 在发版提交上再跑一次 §2.1 五条导入守卫、§2.2 九个包本地测试、§2.3 对拍、§2.4 `contract_compat.py --self`（打了标签的话再 `--base <标签>` 跑一次，应当通过）。
- [ ] 宿主 WH 版本上：已装 0.2.0 全家的运行目录起后端，三个专项被升到 0.3.0 全家、「版本过低」提示按 0.3.0 出（实施方案 §7.4 存量升级演练；W13 用本地 wheel 做过一次，这里换成 PyPI 上的包复核）。
