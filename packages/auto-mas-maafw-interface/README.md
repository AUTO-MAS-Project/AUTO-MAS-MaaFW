# auto-mas-maafw-interface

MaaFramework ProjectInterface（`interface.json`）的解析与运行计划库，从 AUTO-MAS 宿主的 MFW 引擎原样搬出。运行时只依赖 pydantic、json5。

## 对外接口

按子模块导入；包根只惰性导出 `MaaFWInterfaceService`，`import maafw_interface.log_redact` 不会连带加载 pydantic、json5。

| 模块 | 提供 |
| --- | --- |
| `maafw_interface.interface` | `load_interface_model`、`load_interface_model_cached`、`MaaFWInterfaceService`、interface 模型、快照归一化函数（`interface/__init__.py` 的 `__all__`）；子模块 `loader`、`models`、`preview`、`task_config`、`plan_rules`、`agent_command`、`agent_entry`、`password_values`、`host_path`、`service` |
| `maafw_interface.runner` | 惰性导出计划模型与 `build_maafw_run_plan`、`MaaFWRunPlanError`；子模块 `run_plan`（建计划、选控制器与资源、默认快照）、`task_selection`（展开任务快照）、`plan_transforms`（周期与重试）、`pipeline_override`、`hotkey`、`models` |
| `maafw_interface.controller_win32` | `MaaFWWin32ControllerService`、`MaaFWWin32Window`、`MaaFWWindowMatch`；`service.controller_has_window_rules` |
| `maafw_interface.embedded_labels` | `Labels`、`Translate`、`mxu_option_values`（宿主原私有名 `_Labels`、`_mxu_option_values`） |
| `maafw_interface.log_redact` | `DETAIL_LOG_PREFIX`、`HOME_TOKEN`、`mask_home_path` 等 |

和宿主原代码不同的地方（其余一律照搬）：

- `build_maafw_run_plan(..., client_version="")`、`build_arranged_plan(..., client_version="")`：AUTO-MAS 客户端版本由调用方传入，写进 `piEnv["PI_CLIENT_VERSION"]`；库不去找宿主的 `res/version.json`。
- `MaaFWWin32ControllerService.match_controller_windows(controller, list_windows=None)`：第二个参数是返回窗口列表的函数，只在控制器有窗口规则时才调用；需要扫描却没传时抛 `RuntimeError`。库不自己扫描窗口。

`interface.loader` 在工作目录下用 `data/cache/maafw_interface_loader` 做磁盘缓存。`PI_CLIENT_MAAFW_VERSION` 与预览里的 `emulatorExtras` 是对已安装 maafw 的可选探测，没装就是空。

## 开发

以下命令都在仓库根 `D:\MAS\code\blocks` 运行。`uv` 不在 PATH 时用 `D:\MAS\code\main\environment\python\Scripts\uv.exe`。

```powershell
uv venv .venv-dev --python 3.12
uv pip install --python .venv-dev\Scripts\python.exe -e packages\auto-mas-maafw-native -e packages\auto-mas-maafw-interface pytest build ruff
.\.venv-dev\Scripts\python.exe -m pytest packages\auto-mas-maafw-interface\tests -q -p no:cacheprovider --basetemp "$env:TEMP\blk-pytest"
.\.venv-dev\Scripts\python.exe -m ruff check .
.\.venv-dev\Scripts\python.exe -m ruff format --check .
```

`--basetemp` 指到自己能写的目录：默认的 `%TEMP%\pytest-of-<用户>` 若是管理员终端建的，非提权会话写不进去。

### 等价对拍（`tests\test_equivalence.py`）

拿宿主快照里的原函数和本库的同名函数对 `D:\MAS\test\walkref` 的六个项目逐字节比较。要一个能跑宿主代码的环境 `.venv-eqhost`（由 `_src` 的 `uv.lock` 建出）和 `_src\res\version.json`：

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.venv-eqhost"
Push-Location _src; uv sync --frozen --group dev; Pop-Location
Remove-Item Env:UV_PROJECT_ENVIRONMENT
New-Item -ItemType Directory -Force _src\res | Out-Null
cmd /c "git -C D:\MAS\code\main show 048993fca:res/version.json > _src\res\version.json"
.\.venv-dev\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp "$env:TEMP\blk-pytest"
```

用 `cmd /c` 重定向是为了按原字节写出（PowerShell 管道会改换行和编码），写完 `git hash-object _src\res\version.json` 应为 `be7df643153350027ed930edc33a75aa577fc5d0`。`_src` 是迁移分支 `048993fca` 的 `app/`、`tests/`、`pyproject.toml`、`uv.lock` 导出（只读素材，不进版本库）。宿主解释器放在别处时用环境变量 `MAAFW_EQ_HOST_PYTHON` 指定。不带参数在仓库根跑 `python -m pytest` 会按 `pytest.ini` 收三处测试（两个包的 `tests` 和根 `tests`）。

## 打包

```powershell
.\.venv-dev\Scripts\python.exe scripts\build_all.py
```

两个包的 wheel 和 sdist 写进 `dist\`。只装 wheel 验收：

```powershell
uv venv "$env:TEMP\blk-wheels" --python 3.12
uv pip install --python "$env:TEMP\blk-wheels\Scripts\python.exe" (Get-ChildItem dist\*.whl).FullName pytest
Push-Location $env:TEMP
& "$env:TEMP\blk-wheels\Scripts\python.exe" -m pytest D:\MAS\code\blocks\packages\auto-mas-maafw-native\tests D:\MAS\code\blocks\packages\auto-mas-maafw-interface\tests -q -p no:cacheprovider --rootdir $env:TEMP --basetemp "$env:TEMP\blk-pytest"
Pop-Location
```

在仓库外跑，保证导入到的是 site-packages 里的那份；导入守卫测试扫的也是已安装的包。
