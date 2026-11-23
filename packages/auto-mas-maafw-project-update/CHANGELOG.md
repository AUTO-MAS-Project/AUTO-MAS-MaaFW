# 更新日志

## 未发布

- 查看副本状态、导入、推断游戏包名、预览 interface 四个端点重新标成 MCP 工具（内置时有，搬进插件后漏了标记）。
- 托管还登记着、项目视图却一个都不在时（只恢复了配置、数据目录被挪走），启动维护不再回收运行环境缓存。
- 新增 46 个服务操作 `maafw.project.v1.<操作>`（33 个）与 `maafw.project_update.v1.<操作>`（13 个），带请求契约 `contract.py`；属主可按新形 `owner_register(name, prefix)` 登记（每个方法一个服务名），旧的 `owner.register(service=…)` 与旧分发服务、旧函数入口原样保留，两种登记都认。停用 / 重载时有在途项目操作会被拒绝，退出时最多等 2 秒。
- 不再直接导入 agent 环境插件：准备环境、更新预检、运行池回收、环境缓存、运行池路由都改成调 agent 环境服务（工作线程里经线程桥），版本换算与包索引读法改用原生库识别库；`requires` 换成用到的 15 个 agent 环境操作。

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
