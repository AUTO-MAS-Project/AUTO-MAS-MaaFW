# 更新日志

## [0.2.0] - 2026-11-22

- 托管是否完整加载改读宿主的 `Config.managed_configs_loaded()`（有托管因所属插件不可用而旁挂时为假，旧宿主退回旧名）；有视图记着这次没答上来的属主时，整轮不删任何带属主标记的视图（同宿主迁移分支 506598b1a）。
- `host.owners` 不在模块顶层导入解析库的规则表（同宿主迁移分支 5e3df58b3）。
- 有项目正在更新、或项目目录正被运行 / 导入 / 准备环境占用时，插件拒绝停用、重载、卸载（`teardown_blockers`）。
- 新增 `host.project_session.peek_project_skip(script_id)`：不占预约地判断项目此刻能不能打开，给专项托管级检查返回 `ScriptSkip` 用。
- 新增 `host.script_lifecycle`（`clone_script`、`cleanup_script_files`、`after_script_removal`），供专项的托管生命周期钩子在复制、删除托管时处理视图（搬自宿主 `seams/script_lifecycle`）。
- 启动期维护因属主还没登记而跳过副本迁移时，属主登记后补跑一轮；维护新增一步回收运行环境确认缓存。
- `zip_range`、`normalize_proxy_address` 改经 SDK 出口取（加载期用到的 `zip_range` 在旧宿主上退回宿主模块）。
- 三个专项共用的 `glue/`（`owner_entry`、`option_secrets`、`user_update`、`default_snapshot`、`backup_archive`）搬进新库 `auto-mas-maafw-adapter-kit`，本包不再带它，也不留再导出。
- 资源包核对任务登记进当前运行的进程作用域：运行被取消时宿主会等它收尾，不让它在项目预约放掉后继续写视图。

## [0.1.0] - 2026-11-22

- 首次独立发布 MFW 项目更新服务插件：项目副本、视图、导入更新、维护清理、13 个 MFW 端点与托管属主登记，供联调使用。
