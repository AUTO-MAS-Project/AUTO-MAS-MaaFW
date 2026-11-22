# 更新日志

## [0.2.0] - 2026-11-22

- 运行环境确认缓存（`config/maafw_env_cache`）不再只增不减：新增 `host.env_cache.prune_prepared_environments`，由项目更新的启动期维护按仍在的托管回收。

## [0.1.0] - 2026-11-22

- 首次从宿主内置的 MFW 引擎拆出：运行池与 agent 环境（原 `app/task/MaaFW/tools/core/agent_env`、`runtime_pool` 及 `embedded` 下的对账、环境缓存、试跑、路由、检查）。
- 登记服务 `maafw.agent_env.v1`，本版只提供 `version` 操作。
