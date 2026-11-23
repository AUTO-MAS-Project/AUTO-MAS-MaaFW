# 更新日志

## 未发布

- 登记 22 个服务操作 `maafw.agent_env.v1.<操作>`（借还运行环境、准备环境、更新预检、对账回收用句柄四件套，其余是普通调用），请求按 `contract.py` 校验；补 `teardown_blockers`、`on_disable`、`on_teardown`，没被取走的租约由插件自己还。旧的 `maafw.agent_env.v1` 分发服务和原函数入口照旧。
- 新门面 `core.worker_api` 给 worker 用；`host_environment`、安装器的包索引两个读法、`binding_fallback.pep440_to_maafw_tag`、`pool_reconcile.previous_maafw_version` 改成转调原生库识别库里的同一份。

## [0.2.0] - 2026-11-22

- 运行环境确认缓存（`config/maafw_env_cache`）不再只增不减：新增 `host.env_cache.prune_prepared_environments`，由项目更新的启动期维护按仍在的托管回收。

## [0.1.0] - 2026-11-22

- 首次从宿主内置的 MFW 引擎拆出：运行池与 agent 环境（原 `app/task/MaaFW/tools/core/agent_env`、`runtime_pool` 及 `embedded` 下的对账、环境缓存、试跑、路由、检查）。
- 登记服务 `maafw.agent_env.v1`，本版只提供 `version` 操作。
