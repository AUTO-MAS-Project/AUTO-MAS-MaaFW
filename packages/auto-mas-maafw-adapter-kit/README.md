# auto-mas-maafw-adapter-kit

AUTO-MAS 的 MFW 专项共用库：通用 MFW（`maafw_adapter`）、M9A（`m9a_adapter`）、MSS（`mss_adapter`）三个专项都要用、但不属于任何一块积木的代码放在这里，不各抄一份。是库，不是插件，不进插件市场。

## 模块

按模块导入，包根不再导出任何名字。

| 模块 | 提供 |
| --- | --- |
| `maafw_adapter_kit.owner_entry` | `BuiltinConfigOwner`：专项在项目更新登记的托管属主入口（按确切类型认领托管、读写项目记录、导入锁），可带 `plan_rules`、`project_mismatch` |
| `maafw_adapter_kit.option_secrets` | 任务选项里密码字段（PI `password: true`）的加解密：`prepare_user_task_snapshot`（保存前双写全局选项并加密）、`open_task_snapshot`（建计划前在内存里解密）、`seal_task_snapshot`、`DPAPI_SECRET_OPENER`、`MaaFWSecretError`、`SECRET_PREFIX`、`is_sealed_secret`；取账号快照原值的 `user_task_snapshot`、`script_task_snapshots` |
| `maafw_adapter_kit.user_update` | `prepare_user_update(script, user, *, data)`：账号保存前准备任务快照补丁（只做加密；专项自己的整理在调用前做） |
| `maafw_adapter_kit.default_snapshot` | `fill_default_task_snapshots`：空任务队列按项目默认（预设或默认勾选）写回；`prepare_user_read`、`initialize_user`、`is_empty_task_snapshot` |
| `maafw_adapter_kit.backup_archive` | 配置恢复池：账号字段侧车（`mas` 池）与项目 `config/`（`native` 池）的归档、恢复、预览；`read_overlay_values`、`archive_mas_runtime_backup`、`archive_native_backup` 等 |

## 依赖与导入

- 各模块顶层只导入 `auto-mas-maafw-interface`，离开宿主也能导入。
- 宿主 SDK（`auto_mas_core`：日志、DPAPI、`Config`、公共归档模块）和项目更新插件（`maafw_project_update.host.owners` 的属主协议数据类、`host.embedded_project` 的视图路径）都在函数体内取，所以真正调用时要在宿主里，且项目更新已装。
- `auto-mas-core` 由宿主提供，不在 PyPI 上；和插件包一样写 `>=5.9.0b1,<6`。

## 开发

以下命令都在仓库根运行，`uv` 不在 PATH 时用 `D:\MAS\code\main\environment\python\Scripts\uv.exe`。只验导入（不需要宿主）：

```powershell
python scripts\build_all.py auto-mas-maafw-interface auto-mas-maafw-native auto-mas-maafw-adapter-kit --outdir dist\kit
python -m venv .smoke
.\.smoke\Scripts\python.exe -m pip install --no-deps (Get-ChildItem dist\kit\*.whl)
.\.smoke\Scripts\python.exe -m pip install pydantic json5 packaging
.\.smoke\Scripts\python.exe -I scripts\smoke_import.py maafw_adapter_kit
```

单元测试只留本地（`tests/` 不提交，也不进发行包）。

## 许可证

AGPL-3.0-or-later，见 [LICENSE](LICENSE)。
