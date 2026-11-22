# 更新日志

## 0.1.0

- 从 AUTO-MAS MFW 快照搬出 interface 解析、运行计划、任务快照展开、Win32 窗口规则匹配和内置 MaaEnd 用的标签与 MXU 换算。
- 与宿主原代码的接口差异：建计划多了 `client_version` 参数（AUTO-MAS 客户端版本由调用方传入）；Win32 窗口匹配的第二个参数改成取窗口列表的函数，库不自己扫描窗口。
