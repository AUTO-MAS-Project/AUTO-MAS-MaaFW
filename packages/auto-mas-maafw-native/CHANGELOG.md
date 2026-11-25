# 更新日志

## 0.3.0

- 服务化后的第一版：插件之间只经服务调用，0.2 的分发式服务名已删（契约见积木仓 `docs/service-contract-0.3.md`）。
- 从 agent 环境搬来子进程环境口径 `subprocess_env`（`host_environment` 整份，加包索引的两个读法）、`versions.pep440_to_maafw_tag` 与 `infer_exact_maafw_version`；`requirement` 加 `project_exact_maafw_version`，`layout` 加 `view_dir`。

## 0.2.0

- 原生库版本探测先丢掉解析不了的候选再要求恰好一个：编译器拆出的 `6.0.0-bA` 残片不再让 MaaEnd 带的 `v6.0.0-beta.3` 读不出来。

## 0.1.0

- 从 AUTO-MAS MFW 快照搬出原生库识别代码。
