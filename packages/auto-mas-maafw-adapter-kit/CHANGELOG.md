- 删除旧 BuiltinConfigOwner，属主统一走 ConfigOwner 服务。`r`n# 更新日志

## 未发布

- 从运行积木整份搬来专项账号流程用的那组模块：`attempt_ledger`、`run_record`、`run_report`、`run_messages`、`run_notices`、`run_verdict`、`signal_notice`、`proxy_quota`、`run_settings`、`telemetry_project`、`host_client`，另从 `device_config` 切出 `device_state`（`MaaFWAdbDeviceState`、`choose_game_package`、`optional_int`）。文案、判定与记账口径一字不动；只是改读解析库的 `run_events` 与信号常量，记账的附件收运行结果里的字典，`judge_attempt` 认运行服务的失败 code（`run_timeout`、`pretask_failed`），`host_client` 的事件出口改成收字典的回调，`format_user_log_line` 多一个可选的事件时刻 `at`。运行积木里的原模块照旧可用。
- 新模块 `services`（专项调三块服务插件的那一层：服务槽、客户端、结果与异常、长操作与同步停止、事件分派、打开项目与交回运行预约两个助手、操作名常量元组、各请求构造函数）与 `project_texts`（三句良性跳过原文与打开项目失败的那句话）。
- `owner_entry` 加属主服务的新形：`record_payload`（托管记录转成只含 JSON 值的字典，导入时间出 ISO 字符串）、`ConfigOwner`、`OwnerServiceMixin`、`owner_provides`、`write_or_raise`；旧的属主对象入口已删除。
- `services.open_request` 多一个可选的 `round_started_at`（这一轮开始的时刻，过边界出 ISO 字符串）：原先打开项目的会话请求里就带着它，项目更新收尾清原生日志备份要用；不传就不带。
- `services.release_run_reservation` 停止分支开运行前设置的退出确认时带 `after_scope=true`：快照照旧当场拍，运行服务先等作用域收尾再等确认退出（原先的先后）；不认这个字段的旧运行服务照旧当场开始等。
- `services.release_run_reservation` 停止分支带着修复作业时，作用域保留的那个后台任务先跟住修复作业到结束（它还发的日志照样交给 `on_repair_event`）再 `run_release`，交回也在这个任务里做（原来就是在这个任务里 `await shield(核对任务)` 之后才放）。
- `default_snapshot`、`option_secrets` 算视图目录、判视图健康改读两块库（`maafw_native.layout.view_dir`、`maafw_interface.interface.loader.has_interface_file`，与项目更新同一算法），不再在函数体内导入项目更新。新依赖 `auto-mas-maafw-native`。

## [0.2.0] - 2026-11-22

- 首次独立：三个专项（通用 MFW、M9A、MSS）共用的五个模块从 `auto-mas-maafw-project-update` 的 `glue/` 搬来，行为不变：`owner_entry`、`option_secrets`、`user_update`、`default_snapshot`、`backup_archive`。
- 和搬来前的差别只在导入：宿主 SDK 与项目更新插件都改在函数体内取，离开宿主也能导入；`backup_archive` 不再依赖宿主先导入过公共归档模块；属主协议版本写成字面值 1（与项目更新 0.1.0 的 `OWNER_PROTOCOL` 相同）。
- `BuiltinConfigOwner.list_managed` 判断托管是否完整加载改读宿主的 `managed_configs_loaded()`（有托管因所属插件不可用而旁挂时为假；旧宿主退回 `script_config_loaded_intact`），同宿主迁移分支 506598b1a。


