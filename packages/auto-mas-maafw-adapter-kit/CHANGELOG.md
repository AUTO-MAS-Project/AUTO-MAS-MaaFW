# 更新日志

## [0.2.0] - 2026-11-22

- 首次独立：三个专项（通用 MFW、M9A、MSS）共用的五个模块从 `auto-mas-maafw-project-update` 的 `glue/` 搬来，行为不变：`owner_entry`、`option_secrets`、`user_update`、`default_snapshot`、`backup_archive`。
- 和搬来前的差别只在导入：宿主 SDK 与项目更新插件都改在函数体内取，离开宿主也能导入；`backup_archive` 不再依赖宿主先导入过公共归档模块；`BuiltinConfigOwner.owner_protocol` 写成字面值 1（与项目更新 0.1.0 的 `OWNER_PROTOCOL` 相同）。
- `BuiltinConfigOwner.list_managed` 判断托管是否完整加载改读宿主的 `managed_configs_loaded()`（有托管因所属插件不可用而旁挂时为假；旧宿主退回 `script_config_loaded_intact`），同宿主迁移分支 506598b1a。
