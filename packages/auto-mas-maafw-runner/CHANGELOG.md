# 更新日志

## 未发布

- 项目 pipeline 自己用 StopTask 停下的任务（如 M9A v4.15.0 回不了主界面时）照旧算成功、不触发重试，但任务日志不再写「任务完成」，改写「任务已被项目停止」；运行结果带 `projectStoppedTasks`，运行记录里这个任务的类别是 `project_stopped`，统计报告的逐任务时间线标「（被项目停止）」。判据是节点动作通知里的 `action_details.action`，用户停止、超时停止不受影响。

## [0.2.0] - 2026-11-22

- 桌面分身里按窗口规则找窗口改用宿主通用动作 `list_windows`（匹配在本进程做）、查句柄改用 `window_in_session`，不再发 MFW 专用的 `maafw_windows`（同宿主迁移分支 da8cf41a8）。
- 由 MAS 启动（DirectExe）的游戏收尾关闭时写一行账号日志，关不掉时记 warning。
- 有计划还在跑时插件拒绝停用、重载、卸载（`teardown_blockers`）；`host.plan_run.active_plan_runs()` 给出在途个数。
- 宿主的客户端进程、进程操作、桌面分身会话与动作、运行进度类型改经 SDK 出口（`auto_mas_core.host.task_client` 等）取，不再直接导入 `app.*`；需要带这些出口的宿主。

## [0.1.0] - 2026-11-22

- 首次独立发布：MFW 运行积木由宿主 `app/task/MaaFW` 的执行侧拆出，提供服务 `maafw.runner.v1`（目前只实现 `version`）。
