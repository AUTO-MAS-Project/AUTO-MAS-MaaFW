<!-- auto-mas:i18n
{"display_name_i18n":{"zh_CN":"MFW Agent 环境","en":"MFW Agent Environment","ja":"MFW Agent 環境"},"description_i18n":{"zh_CN":"准备 MFW 项目 agent 的 Python 环境与运行池。","en":"Prepares the Python environments and runtime pool for MFW project agents.","ja":"MFW プロジェクトの agent 用 Python 環境とランタイムプールを準備します。"},"tags_i18n":{"zh_CN":["MaaFramework","服务插件"],"en":["MaaFramework","Service plugin"],"ja":["MaaFramework","サービス"]}}
-->

# MFW Agent 环境

AUTO-MAS 的 MFW 服务插件之一，负责运行池（MaaFramework binding 与原生库按版本存放的公共 base venv）和各项目 agent 的 Python 环境：准备、借还、对账回收、环境缓存与预检试跑。

- 服务：`maafw.agent_env.v1.<操作>` 共 22 个（`version`、`runtime_route`、`runtime_check`、`storage_info`、`env_lookup`、`cache_prune`、`borrow_return`，以及 `borrow`、`prepare`、`trial` 的 `_start/_poll/_stop/_close` 和 `reconcile` 的 `_start/_poll/_close`），请求契约在 `maafw_agent_env.contract`。0.2 的分发式服务 `maafw.agent_env.v1`（`call(op, …)`）已删。运行（`maafw_runner`）和项目更新（`maafw_project_update`）的宿主侧只经服务调本包。
- worker 子进程只经门面 `maafw_agent_env.core.worker_api`（`WORKER_API_VERSION = 1`）导入本包。
- 不依赖别的插件，只依赖 SDK 和两块库 `auto-mas-maafw-interface`、`auto-mas-maafw-native`。
- `maafw_agent_env.core` 是 worker 子进程也会导入的部分，不导入宿主和 SDK；`maafw_agent_env.host` 只在宿主进程里跑。

## 写入的目录

本插件是这几个目录唯一的写入方（都相对宿主工作目录）：

- `config/maafw_runtime_pool`
- `config/maafw_agent_venvs`
- `config/maafw_env_cache`
- `data/maafw_agent_constraints`

## 开发

本目录将来位于 `AUTO-MAS-MaaFW` 仓库的 `packages/auto-mas-maafw-agent-env/`。本地联调时把它联接到宿主树的 `plugins/maafw_agent_env`，由宿主作为本地插件加载。

## 许可证

AGPL-3.0-or-later。
