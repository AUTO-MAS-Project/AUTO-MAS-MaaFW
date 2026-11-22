#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""通用 MFW、M9A、MSS 三个专项共用、但不属于任何一块积木的代码。

- ``owner_entry``：托管属主入口 ``BuiltinConfigOwner``；
- ``option_secrets``：任务选项里密码字段的加解密与任务快照取值；
- ``user_update``：账号保存前的任务快照准备（只做加密）；
- ``default_snapshot``：空任务队列写成项目默认队列；
- ``backup_archive``：配置恢复池的归档、恢复与预览。

是库，不是插件。各模块顶层只导入两块库：宿主 SDK（``auto_mas_core``）与项目更新插件
（``maafw_project_update``）都在函数体内取，离开宿主也能导入；真正调用时要在宿主里、且项目更新
已装（三个专项都依赖它）。本包不在这里再导出任何名字，按模块导入。
"""
