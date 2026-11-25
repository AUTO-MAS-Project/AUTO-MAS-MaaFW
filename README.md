# AUTO-MAS-MaaFW

AUTO-MAS 的 MFW 积木仓库：把宿主里的通用 MaaFramework 引擎（原 `app/task/MaaFW`）拆成五个可以单独发版的 Python 包（两块是普通库，三块是 AUTO-MAS 插件），外加一个三个专项共用的库。通用 MFW、M9A、MSS 三个专项插件（各自的仓库 `AUTO-MAS-MaaFW-Adapter`、`AUTO-MAS-M9A-Adapter`、`AUTO-MAS-MSS-Adapter`）在它们之上运行。

现在是 0.2.0，目标是先能联调：主路径能装、能跑，已知问题见 [`docs/known-issues-0.2.0.md`](docs/known-issues-0.2.0.md)（0.1.0 时的清单留在 [`docs/known-issues-0.1.0.md`](docs/known-issues-0.1.0.md)）。0.2 要求宿主带托管生命周期钩子，也就是 MFW 已改为插件提供的那一版及以后。

## 六个包

| 目录 | 发行包 | 导入名 | 类型 | 做什么 |
| --- | --- | --- | --- | --- |
| `packages/auto-mas-maafw-interface` | `auto-mas-maafw-interface` | `maafw_interface` | 库 | 解析 `interface.json`、建运行计划、Win32 控制器匹配、日志打码 |
| `packages/auto-mas-maafw-native` | `auto-mas-maafw-native` | `maafw_native` | 库 | 识别项目自带的 MaaFramework 原生库版本与架构、`data/mfw` 目录布局 |
| `packages/auto-mas-maafw-agent-env` | `auto-mas-maafw-agent-env` | `maafw_agent_env` | 插件（服务 `maafw.agent_env.v1.*`） | 运行池与项目 agent 的 Python 环境 |
| `packages/auto-mas-maafw-runner` | `auto-mas-maafw-runner` | `maafw_runner` | 插件（服务 `maafw.runner.v1.*`） | 跑运行计划：worker 子进程、超时与打转保护、失败截图、运行前设置、设备与桌面游戏 |
| `packages/auto-mas-maafw-project-update` | `auto-mas-maafw-project-update` | `maafw_project_update` | 插件（服务 `maafw.project.v1.*`、`maafw.project_update.v1.*`） | 项目副本、视图、导入与更新、维护清理、`/api/scripts/maafw/*` 端点、托管属主登记 |
| `packages/auto-mas-maafw-adapter-kit` | `auto-mas-maafw-adapter-kit` | `maafw_adapter_kit` | 库（不进插件市场） | 三个专项共用、不属于任何积木的代码：托管属主入口、任务选项密码加解密、账号保存前准备、默认任务队列、配置恢复池 |

每个包有自己的 `pyproject.toml`、`README.md`、`CHANGELOG.md`，版本号只写在各自的 `pyproject.toml` 里，各自发版。

## 依赖关系

发行包之间的依赖（`pyproject.toml` 的 `dependencies`）：

```
maafw_interface   maafw_native          （库，互不依赖，只依赖 pydantic / json5 / packaging）
        ▲               ▲
        ├───────────────┤
        │       maafw_adapter_kit       （库，三个专项共用：只导入两块库，SDK 在函数体内取）
        │               ▲
 maafw_agent_env        │               （插件，依赖两块库）
     ▲       ▲          │
 maafw_runner   maafw_project_update    （插件，依赖两块库与 agent 环境）
     ▲       ▲          │
   maafw_adapter / m9a_adapter / mss_adapter（专项插件，另仓；依赖上面六个包）
```

运行时插件之间只经服务调用（每个操作一个服务名 `maafw.<族>.v1.<操作>`，契约见 [`docs/service-contract-0.3.md`](docs/service-contract-0.3.md)）：

- 运行 `requires` agent 环境的借还环境 5 个操作，项目更新 `requires` agent 环境的 15 个操作；agent 环境不 `requires` 任何服务。
- 三个专项 `requires` 运行、agent 环境、项目、项目更新的服务操作（三家共有 70 个，M9A 另加 `project_peek`，通用 MFW 另加外壳导入用的 4 个）；项目更新按专项登记的前缀现取它们的属主服务 `maafw.owner.<专项>.v1.*`。

- 插件对 `auto-mas-core`（插件 SDK，由宿主提供，不在 PyPI 上）写 `>=5.9.0b1,<6`。
- 包之间的依赖现在仍是 0.2.0 的写法（`>=0.2.0,<0.3`）。0.3.0 起改成：两块库与专项共用库被直接导入，写次版本上限（`>=0.3.0,<0.4`）；对三块服务插件只写下限（`>=0.3.0`），破坏性改动走新的 `v2` 操作。逐文件的改法见 [`docs/release-0.3.0.md`](docs/release-0.3.0.md)。
- 三方依赖（pydantic、psutil、numpy、maafw 等）由宿主提供，插件包不声明。
- 规则：插件之间不直接导入。任何插件的 `plugin.py` 和它在模块顶层的导入链里不出现别的插件包；三块服务插件的宿主侧、专项共用库和三个专项的源码里都不导入别的服务插件包（含函数体内与动态导入）。唯一的例外是运行积木的 worker 子进程：它不在宿主里、调不了服务，经门面 `maafw_agent_env.core.worker_api` 直接导入 agent 环境。
## 本地构建

需要 Python 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install build twine
.\.venv\Scripts\python.exe scripts\build_all.py          # 六个包的 wheel 和 sdist 都打到 dist\
.\.venv\Scripts\python.exe -m twine check --strict dist\*
```

只打一个包：`scripts\build_all.py auto-mas-maafw-runner --outdir dist\runner`。

不碰宿主的部分可以单独验导入（两块库、worker 侧的 `core/` 和专项共用库）：

```powershell
python -m venv .smoke
.\.smoke\Scripts\python.exe -m pip install --no-deps (Get-ChildItem dist\*.whl)
.\.smoke\Scripts\python.exe -m pip install pydantic json5 packaging
.\.smoke\Scripts\python.exe -I scripts\smoke_import.py maafw_interface maafw_native maafw_agent_env.core maafw_runner.core maafw_adapter_kit
```

插件类和 `host/` 下的模块在导入期要 SDK，而 SDK 自己在顶层导入宿主（`app`），所以只能在宿主环境里导入。本地联调的做法（把各包目录联接到联调宿主树的 `plugins\` 下）见拆分契约文档 §6。

## 发布

- CI（`.github/workflows/ci.yml`）：每次推送把六个包都构建一遍，跑 `twine check --strict`、检查发行包不带测试、单独导入不碰宿主的部分、跑两块库的单元测试。
- 发布（`.github/workflows/publish.yml`）：主分支上某个包 `pyproject.toml` 的版本号变了就发这个包；也可以打包级标签 `<发行包名>-v<版本>`（如 `auto-mas-maafw-runner-v0.1.1`）补发，或手动触发。走 PyPI Trusted Publishing，每个包一个发布环境：`pypi-interface`、`pypi-native`、`pypi-agent-env`、`pypi-runner`、`pypi-project-update`、`pypi-adapter-kit`。
- 保险：仓库变量 `PUBLISH_ENABLED` 不是 `true` 时只构建不上传。

## 其它目录

- `tests/`：两块库与宿主原件的等价对拍（要本地的宿主快照 `_src/`，不进 CI）。
- `scripts/`：构建、发布选包、导入检查，以及抽库时用过的对照脚本。
- `docs/notes/`：抽两块库时留下的过程文档（任务说明、进度、文件来源表、宿主切换清单）。

## 许可证

AGPL-3.0-or-later，见 [LICENSE](LICENSE)。
