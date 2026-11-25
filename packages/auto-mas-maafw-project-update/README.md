<!-- auto-mas:i18n
{"display_name_i18n":{"zh_CN":"MFW 项目更新","en":"MFW Project Update","ja":"MFW プロジェクト更新"},"description_i18n":{"zh_CN":"导入、更新与维护 MFW 项目副本。","en":"Import, update and maintain MFW project copies.","ja":"MFW プロジェクトのコピーをインポート・更新・保守します。"},"tags_i18n":{"zh_CN":["MaaFramework","服务插件"],"en":["MaaFramework","Service"],"ja":["MaaFramework","サービス"]}}
-->

# AUTO-MAS MaaFW Project Update

MFW 插件族的「项目更新」服务插件（插件标识 `maafw_project_update`）。负责：

- 项目副本：载荷库（`data/maafw_blobs`、`data/mfw/.payloads`）与各托管的视图（`data/mfw/<视图>`）；
- 导入、重导、克隆、立即同步，以及手动 / 运行前后的项目更新与预下载；
- 启动期维护（旧副本迁移、属主标记、副本 / agent 环境 / 运行池 / 更新缓存清理）和每日原生日志清理；
- `/api/scripts/maafw/*` 下的 13 个端点（外壳配置导入的 3 个归 `maafw_adapter`）；
- 托管属主登记：三个专项各自提供属主服务 `maafw.owner.<专项>.v1.<操作>`（8 个），把前缀
  `maafw.owner.<专项>.v1` 登记到本插件。

三个专项共用的配置胶水（默认任务快照、选项密码、账号更新准备、备份归档、属主入口）0.1.0 放在本包
`glue/` 下，之后搬进了库 `auto-mas-maafw-adapter-kit`（`maafw_adapter_kit`）。

对外服务按操作拆分为 `maafw.project.v1.<操作>`（33 个）与 `maafw.project_update.v1.<操作>`
（13 个），属主经 `maafw.project.v1.owner_register(name, prefix)` / `owner_unregister(name)` 登记与撤销。
依赖 agent 环境插件的 15 个 `maafw.agent_env.v1.<操作>`。

0.1.0 是联调版本，已知取舍见本包所在仓库的拆分契约文档。环境变量 `AUTO_MAS_MFW_NO_CLEANUP=1`
时插件不跑任何维护清理（联调保护）。

开发时把本目录联接到宿主的 `plugins/maafw_project_update`，通过插件中心加载。
