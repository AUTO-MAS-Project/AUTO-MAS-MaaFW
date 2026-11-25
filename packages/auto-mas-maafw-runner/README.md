<!-- auto-mas:i18n
{"display_name_i18n":{"zh_CN":"MFW 运行","en":"MFW Runner","ja":"MFW ランナー"},"description_i18n":{"zh_CN":"把一份 MFW 运行计划跑完：worker、超时与打转保护、失败截图、日志打码。","en":"Runs an MFW run plan to completion: worker process, timeout and loop guards, failure screenshots and log redaction.","ja":"MFW の実行計画を最後まで実行します：worker、タイムアウトとループ検出、失敗時のスクリーンショット、ログのマスキング。"},"tags_i18n":{"zh_CN":["MaaFramework","运行积木"],"en":["MaaFramework","Runner block"],"ja":["MaaFramework","実行ブロック"]}}
-->

# AUTO-MAS MaaFW Runner

MFW 插件族的运行积木（插件标识 `maafw_runner`，服务 `maafw.runner.v1.<操作>`）。通用 MFW、M9A、MSS 三个专项都靠它跑计划：借运行环境、起 worker 子进程、收事件、落日志，默认带整轮与单任务时限、原地打转检测、失败截图和日志打码；另有运行前设置、设备配置、桌面游戏启停、结果判定与记账、文案。

本包由宿主 `app/task/MaaFW` 的执行侧拆出（拆分依据：「MFW 插件包拆分与契约」§1、§7.2），代码只换了导入：

- `maafw_runner.core`：worker 子进程也会导入的部分（`core/runner/*`、`core/worker_protocol.py`），不导入宿主与 SDK。
- `maafw_runner.host`：只在宿主进程里跑的部分。宿主能力在函数体内经 `auto_mas_core` 取。

## 现状

- 服务：`maafw.runner.v1.<操作>` 29 个（含 `version`，契约见 `contract.py`）。0.2 的分发式服务 `maafw.runner.v1`（`call(op, …)`）已删。三个专项只经服务调本包，不再直接导入 `maafw_runner.*`。
- worker 以 `python -m maafw_runner.core.runner.worker` 启动，`PYTHONPATH` 为 binding 目录加上本包、`maafw_agent_env`、`maafw_interface`、`maafw_native` 四个包各自的父目录（`maafw_runner.host.worker_paths`）。
- 依赖 `auto-mas-maafw-agent-env`（插件依赖它的 `borrow_*`、`borrow_return` 共 5 个服务操作）和两块库 `auto-mas-maafw-interface`、`auto-mas-maafw-native`。

## 服务化（未发布）

- 登记 `maafw.runner.v1.<操作>` 29 个服务操作（契约见 `contract.py`），服务包装的原有类、函数仍在。
- 借还运行环境走 agent 环境的服务（`maafw.agent_env.v1.borrow_*`、`borrow_return`），`maafw_runner.host` 不再导入 `maafw_agent_env`；worker（`maafw_runner.core`）只经门面 `maafw_agent_env.core.worker_api` 导入，起 worker 前核对门面版本。worker 的 `PYTHONPATH` 里 agent 环境那一项由借环境结果的 `worker_paths` 带回。

## 开发

本地联调时把本目录联接到联调宿主树的 `plugins\maafw_runner`。单元测试不随仓库提交。
