# 更新日志

## 未发布

- 扫描选项指向项目外的链接时只跳过该选项，修复链接后自动重新加载。

## 0.3.1

- 运行结果的 `MaaFWResourceFailure` 加 `errors`：MaaFramework 6.0 起资源包加载失败时带的结构化诊断（code、file、node、pointer、field、target），5.x 与旧 worker 为空表。
- `describe_resource_failure` 加可选参数 `load_errors`：有可用条目时优先按它说（节点重名、`next` 引用了不存在的节点、正则写错、JSON 读不了等各一句，其余给通用一句带文件 / 节点 / 字段），路径照旧相对化、脱敏；没有时照旧从原生日志里摘错误行。专项要把 `resourceFailure.errors` 传进来才会用上。

## 0.3.0

- 服务化后的第一版：插件之间只经服务调用，0.2 的分发式服务名已删（契约见积木仓 `docs/service-contract-0.3.md`）。
- 运行结果 `MaaFWRunResult` 加 `projectStoppedTasks`：完成的任务里被项目 pipeline 自己停下的；旧 worker 不带这个键时为空。
- 从运行积木搬来 `runner.run_events`、`runner.resource_failure`、`runner.game_package`、`run_redaction`（整份，日志改走标准 logging）与 `runner.models` 的三个信号常量；`controller_win32.service` 加 `find_controller` 与无窗口规则文案，`interface.loader` 加 `has_interface_file`，`MaaFWPlanRules` 加 `to_dict` / `from_dict`。
- 新模块 `service_calls`：跨插件服务调用的通用部分（调用方起止轮询、四种取消收尾、忙重试与保险丝、同步调用与线程桥、提供方句柄表），只用标准库。
- 建计划时传给项目的 `PI_CLIENT_MAAFW_VERSION` 不再多一个 `v`：maafw 发行包元数据的版本号自带 `v`（如 5.16.1 的 `v5.16.1`）时原样用，不带的照旧补上。
- `interface.loader` 的内存缓存键、磁盘缓存文件名（`sha256` 文件名）与解析用的项目根先去掉 `Path.resolve()` 偶尔交回的 `\\?\` 前缀（`\\?\UNC\` 换回 `\\`）：Windows 上别的线程正建或替换目录时 CPython 3.12 会交回带前缀的路径，同一个项目会落到两份缓存。新模块 `path_key`（与 agent 环境、项目更新积木里的同名模块同一份写法，本库不依赖它们）。没有前缀时文件名不变，已落盘的缓存不换名。

## 0.2.0

- 代码与 0.1.0 相同，版本号随其余 MFW 包一起升到 0.2。

## 0.1.0

- 从 AUTO-MAS MFW 快照搬出 interface 解析、运行计划、任务快照展开、Win32 窗口规则匹配和内置 MaaEnd 用的标签与 MXU 换算。
- 与宿主原代码的接口差异：建计划多了 `client_version` 参数（AUTO-MAS 客户端版本由调用方传入）；Win32 窗口匹配的第二个参数改成取窗口列表的函数，库不自己扫描窗口。
