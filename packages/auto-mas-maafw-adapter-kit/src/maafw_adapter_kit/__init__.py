#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""通用 MFW、M9A、MSS 三个专项共用、但不属于任何一块积木的代码。

- ``owner_entry``：托管属主入口（属主服务 ``ConfigOwner``、
  ``OwnerServiceMixin``、``record_payload`` 等）；
- ``option_secrets``：任务选项里密码字段的加解密与任务快照取值；
- ``user_update``：账号保存前的任务快照准备（只做加密）；
- ``default_snapshot``：空任务队列写成项目默认队列；
- ``backup_archive``：配置恢复池的归档、恢复与预览；
- ``services`` / ``project_texts``：调三块服务插件的那一层，项目这一块的几句固定话；
- ``attempt_ledger``、``run_record``、``run_report``、``run_messages``、``run_notices``、``run_verdict``、
  ``signal_notice``、``proxy_quota``、``run_settings``、``telemetry_project``、``host_client``、
  ``device_state``：账号流程的记账、判定、文案与宿主胶水（从运行积木搬来）。

是库，不是插件。各模块顶层只导入两块库（解析库、原生库识别库）：宿主 SDK（``auto_mas_core``）在
函数体内取，离开宿主也能导入；真正调用时要在宿主里。三块服务插件一律经 ``services`` 调，只有旧的
属主服务在函数体内取项目更新的属主协议数据类。本包不在这里再导出任何名字，按模块导入。
"""

