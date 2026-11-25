# 更新日志

## [0.3.1] - 2026-11-25

- 认不出托管、且有属主没答上来时（一个属主都没登记，或登记了但专项插件此刻不在运行），报「没有在运行的专项插件认领这个托管，请检查专项插件的状态」，不再报「托管配置类型错误, 不是 MFW 类型」；已登记的属主都答上来、没有一个认领时照旧是后一句。失败码不变。

## [0.3.0] - 2026-11-25

- 服务化后的第一版：插件之间只经服务调用，0.2 的分发式服务名已删（契约见积木仓 `docs/service-contract-0.3.md`）。
- 查看副本状态、导入、推断游戏包名、预览 interface 四个端点重新标成 MCP 工具（内置时有，搬进插件后漏了标记）。
- 托管还登记着、项目视图却一个都不在时（只恢复了配置、数据目录被挪走），启动维护不再回收运行环境缓存。
- 新增 46 个服务操作 `maafw.project.v1.<操作>`（33 个）与 `maafw.project_update.v1.<操作>`（13 个），带请求契约 `contract.py`；属主按 `owner_register(name, prefix)` 登记（每个方法一个服务名）。停用 / 重载时有在途项目操作会被拒绝，退出时最多等 2 秒。
- `maafw.project.v1.open_start` 的请求多一个可选字段 `round_started_at`（ISO 8601），提供方在一处还原成秒数交给项目会话，与旧路径会话拿到的值相同；不带时缺省 0（同旧请求的缺省）。
- `repair_start` 的作业任务登记成调用方进程作用域的保留任务：用户停止后作业交给 `run_release` 等核对跑完，之前宿主停止收尾时它会被一起取消，连带把它等着的核对任务也取消了。
- 不再直接导入 agent 环境插件：准备环境、更新预检、运行池回收、环境缓存、运行池路由都改成调 agent 环境服务（工作线程里经线程桥），版本换算与包索引读法改用原生库识别库；`requires` 换成用到的 15 个 agent 环境操作。
- 删除 `host.project_path.release_run_reservation`：三个专项交回预约已改用专项共用库的同名函数（经项目服务 `run_release`），这里不再有人调用。
- 删除旧的分发式服务 `maafw.project.v1` / `maafw.project_update.v1`（`call(op, …)`）与旧的属主登记 `owner.register(name, service)`，一律用按操作拆分的服务；属主晚于本插件登记时照旧补跑一轮启动期维护。
- 属主登记：插件停用、退出、启用时撤掉经 `owner_register` 登记的属主；同名再登记以新的为准，不再回 `owner_conflict`。之前重载或停用 agent 环境会连带重载本插件和三个专项，专项的注销被调用门拒掉，旧登记留在表里，三个专项重新登记时报「重复的托管属主登记」、进入运行故障，要重启后端才恢复。
- `maafw.project_update.v1.update_start` 的请求多一个可选字段 `round_started_at`（ISO 8601），还原方式与缺省值同 `open_start`。
- 项目预约键（`normalize_project_path`）、项目状态目录与项目锁文件名、更新包下载的进程内锁、`DurableFileLock` 的进程内锁表键先去掉 `Path.resolve()` 偶尔交回的 `\\?\` 前缀（`\\?\UNC\` 换回 `\\`）再归一：Windows 上别的线程正建或替换目录时 CPython 3.12 会交回带前缀的路径，同一个项目会算出两个预约键，第二次预约本该被挡却放行了。没有前缀时键不变。

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
