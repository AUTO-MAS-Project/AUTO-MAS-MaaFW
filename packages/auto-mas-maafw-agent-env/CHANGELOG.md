# 更新日志

## [0.3.0] - 2026-11-25

- 服务化后的第一版：插件之间只经服务调用，0.2 的分发式服务名已删（契约见积木仓 `docs/service-contract-0.3.md`）。
- 登记 22 个服务操作 `maafw.agent_env.v1.<操作>`（借还运行环境、准备环境、更新预检、对账回收用句柄四件套，其余是普通调用），请求按 `contract.py` 校验；补 `teardown_blockers`、`on_disable`、`on_teardown`，没被取走的租约由插件自己还。原函数入口照旧。
- 新门面 `core.worker_api` 给 worker 用；`host_environment`、安装器的包索引两个读法、`binding_fallback.pep440_to_maafw_tag`、`pool_reconcile.previous_maafw_version` 改成转调原生库识别库里的同一份。
- 路径当键的地方（环境缓存键、隔离 venv 的锁键与路径键、约束文件名、预检 staging 子目录、运行池锁、binding 引用计数与下载锁、项目 binding 选择键、隔离 venv 清单里的 `projectPath`）先去掉 `Path.resolve()` 偶尔交回的 `\\?\` 前缀（`\\?\UNC\` 换回 `\\`）再归一：Windows 上别的线程正建或替换目录时 CPython 3.12 会交回带前缀的路径，同一个目录会算出两个键。没有前缀时键不变，已落盘的缓存不失效；旧清单里带前缀的 `projectPath` 按去前缀后的值比，不因此重建隔离 venv。
- 删掉 0.2 的分发式服务 `maafw.agent_env.v1`（`call(op, …)`，只认 `version`）：`provides_services` 不再登记整名，插件上的 `call` 一并删掉；版本照旧走 `maafw.agent_env.v1.version`，其余操作级服务名不变。0.2.0 的专项与运行、项目更新积木配不上这一版，不保留这个名字。

## [0.2.0] - 2026-11-22

- 运行环境确认缓存（`config/maafw_env_cache`）不再只增不减：新增 `host.env_cache.prune_prepared_environments`，由项目更新的启动期维护按仍在的托管回收。

## [0.1.0] - 2026-11-22

- 首次从宿主内置的 MFW 引擎拆出：运行池与 agent 环境（原 `app/task/MaaFW/tools/core/agent_env`、`runtime_pool` 及 `embedded` 下的对账、环境缓存、试跑、路由、检查）。
- 登记服务 `maafw.agent_env.v1`，本版只提供 `version` 操作。
