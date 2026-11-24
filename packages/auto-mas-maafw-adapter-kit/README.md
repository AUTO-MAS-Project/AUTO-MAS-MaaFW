# auto-mas-maafw-adapter-kit

AUTO-MAS 的 MFW 专项共用库：通用 MFW（`maafw_adapter`）、M9A（`m9a_adapter`）、MSS（`mss_adapter`）三个专项都要用、但不属于任何一块积木的代码放在这里，不各抄一份。是库，不是插件，不进插件市场。

## 模块

按模块导入，包根不再导出任何名字。

| 模块 | 提供 |
| --- | --- |
| `maafw_adapter_kit.owner_entry` | 属主服务：`record_payload`（托管记录的 JSON 字典）、`ConfigOwner`、`OwnerServiceMixin`、`owner_provides(<插件 id>)`、`write_or_raise` |
| `maafw_adapter_kit.services` | 专项调三块服务插件：`ServiceSlot`、`ServiceClient`（`call` / `call_once` / `call_sync` / `call_threadsafe`）、`Reply` 与 `ServiceFailure`、`Operation`（长操作，被取消时按族收尾，`stop()` 同步）、`event_dispatcher`、`ProjectOpener` / `open_project`、`release_run_reservation`、操作名常量元组（`ADAPTER_REQUIRES` 等）、各请求构造函数 |
| `maafw_adapter_kit.project_texts` | 三句良性跳过原文与 `BENIGN_SKIPS`、`describe_open_failure` |
| `maafw_adapter_kit.attempt_ledger`、`run_record`、`run_report`、`run_messages`、`run_notices`、`run_verdict`、`signal_notice`、`proxy_quota`、`run_settings`、`telemetry_project`、`host_client`、`device_state` | 账号流程的记账、判定、文案、信号聚合、代理次数、运行设置与宿主 / 模拟器胶水，从运行积木搬来，口径不变 |
| `maafw_adapter_kit.option_secrets` | 任务选项里密码字段（PI `password: true`）的加解密：`prepare_user_task_snapshot`（保存前双写全局选项并加密）、`open_task_snapshot`（建计划前在内存里解密）、`seal_task_snapshot`、`DPAPI_SECRET_OPENER`、`MaaFWSecretError`、`SECRET_PREFIX`、`is_sealed_secret`；取账号快照原值的 `user_task_snapshot`、`script_task_snapshots` |
| `maafw_adapter_kit.user_update` | `prepare_user_update(script, user, *, data)`：账号保存前准备任务快照补丁（只做加密；专项自己的整理在调用前做） |
| `maafw_adapter_kit.default_snapshot` | `fill_default_task_snapshots`：空任务队列按项目默认（预设或默认勾选）写回；`prepare_user_read`、`initialize_user`、`is_empty_task_snapshot` |
| `maafw_adapter_kit.backup_archive` | 配置恢复池：账号字段侧车（`mas` 池）与项目 `config/`（`native` 池）的归档、恢复、预览；`read_overlay_values`、`archive_mas_runtime_backup`、`archive_native_backup` 等 |

## 依赖与导入

- 各模块顶层只导入 `auto-mas-maafw-interface` 与 `auto-mas-maafw-native`，离开宿主也能导入；不导入三块服务插件，跨插件的事都经 `services` 走服务调用。
- 宿主 SDK（`auto_mas_core`：日志、DPAPI、`Config`、公共归档模块、进程作用域、通知）在函数体内取（`signal_notice`、`telemetry_project` 照搬来前的样子，还有两处直接取宿主 `app`，等 SDK 补门面）；属主服务在函数体内取项目更新协议数据类（`maafw_project_update.host.owners` 的属主协议数据类）。真正调用时要在宿主里。
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

