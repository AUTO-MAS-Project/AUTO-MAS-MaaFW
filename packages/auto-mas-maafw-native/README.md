# auto-mas-maafw-native

MaaFramework 原生库识别库，从 AUTO-MAS 宿主的 MFW 引擎原样搬出：只读项目目录里的 DLL、dist-info、requirements，识别项目自带的 MaaFramework 原生库版本和架构。运行时只依赖 packaging。不依赖 `auto-mas-maafw-interface`。

## 对外接口

按子模块导入，各子模块的 `__all__` 与宿主原件相同，包根不导出东西。没有私有名改成公开名。

| 模块 | 提供 |
| --- | --- |
| `maafw_native.architecture` | `host_architecture`、`supported_architecture_target`、`ArchitectureTarget` 和架构错误类型 |
| `maafw_native.layout` | `data/mfw`、`.payloads`、`.pycache` 等目录布局常量 |
| `maafw_native.offline_dependencies` | 离线依赖文件识别 |
| `maafw_native.pe` | `detect_pe_architecture`、`pe_imported_dlls` |
| `maafw_native.project_runtime` | 项目原生库路径、版本、架构、依赖与加载探测 |
| `maafw_native.requirement` | 项目 maafw requirement 解析 |
| `maafw_native.requirements_file` | requirements 文件解析 |
| `maafw_native.versions` | 版本规范化、requirement 解析、`MaaFWBindingError` |

## 开发

在仓库根 `D:\MAS\code\blocks` 运行。`uv` 不在 PATH 时用 `D:\MAS\code\main\environment\python\Scripts\uv.exe`。

```powershell
uv venv .venv-dev --python 3.12
uv pip install --python .venv-dev\Scripts\python.exe -e packages\auto-mas-maafw-native -e packages\auto-mas-maafw-interface pytest build ruff
.\.venv-dev\Scripts\python.exe -m pytest packages\auto-mas-maafw-native\tests -q -p no:cacheprovider --basetemp "$env:TEMP\blk-pytest"
```

只开发本包时 `-e packages\auto-mas-maafw-interface` 可以不装。测试里的 PE 架构用例取 `D:\MAS\test\walkref` 里真实项目的 `MaaFramework.dll`。等价对拍的环境怎么建见 `packages\auto-mas-maafw-interface\README.md`「等价对拍」。

## 打包

```powershell
.\.venv-dev\Scripts\python.exe scripts\build_all.py
```

两个包的 wheel 和 sdist 写进 `dist\`。只装 wheel 的验收命令见 `packages\auto-mas-maafw-interface\README.md`「打包」。
