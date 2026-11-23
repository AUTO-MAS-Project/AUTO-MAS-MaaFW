# 更新日志

## 未发布

- 项目 pipeline 自己用 StopTask 停下的任务（如 M9A v4.15.0 回不了主界面时）照旧算成功、不触发重试，但任务日志不再写「任务完成」，改写「任务已被项目停止」；运行结果带 `projectStoppedTasks`，运行记录里这个任务的类别是 `project_stopped`，统计报告的逐任务时间线标「（被项目停止）」。判据是节点动作通知里的 `action_details.action`，用户停止、超时停止不受影响。
- `core/runner/run_events.py` 与 `worker_protocol` 的三个信号常量（`SERVER_MAINTENANCE`、`CLIENT_UPDATE_REQUIRED`、`SIGNAL_SCREENSHOT_KINDS`）的权威一份搬进解析库（`maafw_interface.runner.run_events`、`maafw_interface.runner.models`），原位置原样再导出，导入写法不变；信号常量是惰性再导出，worker 导入 `worker_protocol` 时照旧不带进 pydantic。要带这两个模块的解析库。
- 登记 29 个服务操作 `maafw.runner.v1.<操作>`（账号句柄、桌面游戏、设备配置、运行前设置、跑计划），包装原有的 `MaaFWPlanRun`、`MaaFWPretaskRunner`、`MaaFWDesktopGame` 与 `device_config`，请求按 `contract.py` 校验；`account_close` 总是成功、有作业时延后；`teardown_blockers` 改数有在途作业的账号（专项旧路径上直接跑的计划照旧也算），补 `on_disable`、`on_teardown`。旧的 `maafw.runner.v1` 分发服务和原有类、函数照旧。
- 借还运行环境改调 agent 环境的服务（`borrow_*`、`borrow_return`，`requires` 写这 5 个），宿主侧不再导入 `maafw_agent_env`；起 worker 前核对借环境结果回报的门面版本，不配套就不起 worker。`core/runner/environment.py` 只留 worker 用的那一个函数，借还与拼环境挪到 `host/environment.py`，`core/runner/service.py` 只剩 `build_plan`；worker 对 agent 环境只经 `maafw_agent_env.core.worker_api` 导入。打码、原生报错摘录、游戏包名识别、`find_controller` 与无窗口规则文案改从解析库取（原名字照旧可从原模块导入）。
- `pretask_exit_watch_start` 多一个可选的 `after_scope`：为真时快照仍当场拍，作业先等调用方此刻的进程作用域收尾（`finished`）再等运行前设置的进程确认退出，与原 `release_run_reservation` 停止分支的先后一致；不传时照旧当场开始等。
- `pretask_exit_watch` 的作业任务登记成调用方进程作用域的保留任务：宿主停止收尾时会取消作用域上下文里没登记的任务（然后才置 `finished`），之前确认作业会被一起取消、结果是「已停止」，停止后项目预约一直放不掉。

## [0.2.0] - 2026-11-22

- 桌面分身里按窗口规则找窗口改用宿主通用动作 `list_windows`（匹配在本进程做）、查句柄改用 `window_in_session`，不再发 MFW 专用的 `maafw_windows`（同宿主迁移分支 da8cf41a8）。
- 由 MAS 启动（DirectExe）的游戏收尾关闭时写一行账号日志，关不掉时记 warning。
- 有计划还在跑时插件拒绝停用、重载、卸载（`teardown_blockers`）；`host.plan_run.active_plan_runs()` 给出在途个数。
- 宿主的客户端进程、进程操作、桌面分身会话与动作、运行进度类型改经 SDK 出口（`auto_mas_core.host.task_client` 等）取，不再直接导入 `app.*`；需要带这些出口的宿主。

## [0.1.0] - 2026-11-22

- 首次独立发布：MFW 运行积木由宿主 `app/task/MaaFW` 的执行侧拆出，提供服务 `maafw.runner.v1`（目前只实现 `version`）。
