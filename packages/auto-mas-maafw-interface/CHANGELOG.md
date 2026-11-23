# 更新日志

## 未发布

- 运行结果 `MaaFWRunResult` 加 `projectStoppedTasks`：完成的任务里被项目 pipeline 自己停下的；旧 worker 不带这个键时为空。
- 从运行积木搬来 `runner.run_events`、`runner.resource_failure`、`runner.game_package`、`run_redaction`（整份，日志改走标准 logging）与 `runner.models` 的三个信号常量；`controller_win32.service` 加 `find_controller` 与无窗口规则文案，`interface.loader` 加 `has_interface_file`，`MaaFWPlanRules` 加 `to_dict` / `from_dict`。
- 新模块 `service_calls`：跨插件服务调用的通用部分（调用方起止轮询、四种取消收尾、忙重试与保险丝、同步调用与线程桥、提供方句柄表），只用标准库。
- 建计划时传给项目的 `PI_CLIENT_MAAFW_VERSION` 不再多一个 `v`：maafw 发行包元数据的版本号自带 `v`（如 5.16.1 的 `v5.16.1`）时原样用，不带的照旧补上。

## 0.2.0

- 代码与 0.1.0 相同，版本号随其余 MFW 包一起升到 0.2。

## 0.1.0

- 从 AUTO-MAS MFW 快照搬出 interface 解析、运行计划、任务快照展开、Win32 窗口规则匹配和内置 MaaEnd 用的标签与 MXU 换算。
- 与宿主原代码的接口差异：建计划多了 `client_version` 参数（AUTO-MAS 客户端版本由调用方传入）；Win32 窗口匹配的第二个参数改成取窗口列表的函数，库不自己扫描窗口。
