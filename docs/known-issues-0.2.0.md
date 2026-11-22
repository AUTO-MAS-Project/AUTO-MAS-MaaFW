# 0.2.0 已知问题

这份是 `known-issues-0.1.0.md` 的续篇：积木仓库 main 上 0.2 的内容（版本号还是 0.1.0，发布前统一升）做完后，0.1.0 的清单逐条复核，消掉的移到文末「已消」一节并注明提交，没消的留在「清单」里（描述按现状改过），新发现的接在后面（第 38 条起）。编号沿用 0.1.0。三个专项这一轮由别人在改，专项那边的条目按积木仓库这一侧能看到的写，没有核实专项的结果。

0.1.0 的口径是「主路径能装能跑就交，已知问题列清单，以后再消」。这份清单合并了六个包（本仓库五个包，加上 `AUTO-MAS-MaaFW-Adapter`、`AUTO-MAS-M9A-Adapter`、`AUTO-MAS-MSS-Adapter` 三个专项）实现时交回的已知问题和偏差，以及拆分契约文档（「MFW 插件包拆分与契约」，下称「契约」）§8 的取舍，去了重。

先说最要紧的：六个包**已经在联调宿主里装上、启用，三种类型都走到了「导入项目 → 准备 agent 环境」**（2026-11-22，见下面「宿主联调」一节），但**还没有真跑过一轮**（没派发运行、没拉游戏和模拟器）。下面「验证状况」一节写清了做过什么。之后在宿主迁移分支上用本地源码接入，三种托管各用空白窗口程序真跑了一轮，并拿正式版配置的副本演练了升级，见「迁移分支联调（2026-11-22）」。

## 0.2 的验证状况

| 做过的 | 结果 |
| --- | --- |
| 从 HEAD 的 `git archive` 用 `scripts/build_all.py` 打六个包，另用 `uv build` 打五个改过的包 | 都打得出来；`twine check --strict` 12 个产物全部通过；wheel 里没有测试（运行积木的 sdist 原先会带上本地测试，`df2d5d6` 补了 `prune tests`） |
| 宿主源码取迁移分支 `b8351bf0f` 的 `git archive` 放进导入路径，SDK 从同一份源码的 `plugins/auto_mas_core` 拷出来装；全新 venv 装六个包的 wheel，每个模块单起子进程导入 | 141 个模块全部成功 |
| 同一 venv，宿主不在路径上，`scripts/smoke_import.py` 导入两块库和 worker 侧 `core` | 65 个模块全部成功，没带出 `app` 和 `auto_mas_core` |
| 同一 venv（对 wheel）跑全部本地测试：native 5、interface 20、专项共用库 9、等价对拍 6，加 0.2 新补的 agent_env 4、runner 6、project_update 16（真 SDK、真宿主模块，拆卸预检走宿主 `Plugin._precheck_teardown`） | 全过 |
| 改坏验证：0.2 的每处改动故意改坏，跑对应测试 | 17 处全部变红 |

没做的：在宿主里装起来跑一轮（派发运行、真机）；三个专项接钩子后的联调。

## 迁移分支联调（2026-11-22）

宿主迁移分支 `feat/mfw-plugin-migration-20261121`（`6bd32b3a5`，内置 MFW 族已删）上，六个插件用本地源码接入（本仓库 `eef753e`、三个专项各自 master 的 HEAD），三块库用本地 `uv build` 的 wheel，干净数据起后端。做法和结果见宿主仓库 `docs/mfw-plugins-local-integration.md`。

| 做过的 | 结果 |
| --- | --- |
| 核对装的是哪一份 | 六个插件 `source=local`；`plugins\pypi\site-packages` 里三块库逐文件与源码一致（`maafw_native` 的 `project_runtime.py` 与 PyPI 0.1.0 不同，比对能区分），uv 这次拿的是本地 wheel |
| 启用 | 只启用三个专项，三块积木连带启用，日志无 WARNING；`/api/scripts/types` 有 MaaFW、M9A、MSS |
| 三种托管：新建、导入、预览、新建账号、复制、删除、准备环境 | 全部 200。新账号默认队列：MaaFW 14 个、M9A 9 个、MSS 空（项目没有 `default_check`，见第 36 条）；复制托管当场带副本；删托管当场删副本；准备环境 MaaFW 走 isolated_venv，M9A、MSS 走 project_python |
| 密码字段 | 自造带 `password: true` 输入项的项目副本，写账号快照后盘上是 `mas-dpapi:` 密文，搜不到明文，接口读回也是密文 |
| 真跑（自编注册 `UnityWndClass` 的空白窗口程序当游戏，`win_process` 游戏目标，Win32 控制器、PostMessage、由 MAS 启动游戏、单任务时限 1 分钟、次数 1、自动更新关） | 三种各一轮，都在 1–2 分钟内结束：拉起假程序 → worker（本地源码布局，`-m maafw_runner.core.runner.worker`）→ 连控制器 → 起 agent → 任务超时（MaaFW）或认不出画面失败（M9A、MSS）→「已关闭本次由 MAS 启动的游戏」→ 假程序、worker、agent 都退出，游戏目标占用清空 |
| 存量升级演练（正式版配置只读副本，没拷 data，不派发） | `legacy-maafw-plugin/scripts.yaml` 与原件逐字节相同；托管、账号、队列引用、定时项、计划表全部原样；与删内置实现之前的宿主（`b8351bf0f`）对同一副本升级的结果相比，只多出插件配置类自带的小写 `info`、`custom_webhooks`、`notify` 键；再起一次文件不变 |

没做的：桌面分身（第 16 条）、M9A 登录、MSS 活动期判定的真实分支、`/maafw/update` 的 apply、外壳配置导入（第 17 条）。模拟器和 ADB 控制器见下一节。

## 模拟器真机（2026-11-22）

同一棵宿主树（`c7dc72efc`），六个插件仍是本地源码（本仓库 `b87b32e`、三个专项各自 master 的 HEAD）。新建一个 M9A 托管（ADB 控制器、官服资源），游戏目标绑魔改 AVD 测试实例，由 MAS 无头开关模拟器，只派发一次。

| 做过的 | 结果 |
| --- | --- |
| M9A 专项经 ADB 真跑：启动游戏、收取荒原、领取奖励、关闭游戏 | 301 秒，四个任务全部完成，终态 `success`；同一天上午内置实现跑同样四个任务是 356 秒，差在项目更新的下载和游戏内状态 |
| 运行前项目更新 | v4.9.0 → v4.15.0，区间差量，实际下载 58.7 MB（整包 188.1 MB） |
| 原生库与 binding 版本 | 这一版探测到原生库 v6.0.0-beta.3，下载了同版本 binding；上午内置时用的是 5.12.3、日志有版本不一致的警告，这次没有（`a6d6144`） |
| 游戏目标占用 | 跑前为空，跑中一直被这个托管占着，结束后清空 |
| 历史记录 | 写了，带账号日志、worker、原生、项目日志四个附件 |
| 后端日志 | 没有 ERROR 和 Traceback；WARNING 只有项目 interface 里不支持的顶层字段 `telemetry` |
| 运行在途时停用专项（另起一轮空白窗口程序上试） | 被拒：`PluginPrecheckError`，原因两条，「脚本配置已锁定」和 `teardown_blockers` 给的「有 1 个 M9A 托管的运行还没结束」；运行没被打断 |

没做的：到游戏里核对奖励是否真的领到；通用 MFW、MSS 的模拟器路径；手动停止和超时停止。

## 0.1.0 时的验证状况

| 做过的 | 结果 |
| --- | --- |
| 五个包从干净的 `git archive` 用 `scripts/build_all.py` 构建 | 五个包的 wheel 和 sdist 都打出来，`twine check --strict` 全部通过 |
| 三个专项 `uv build` + `twine check --strict` | 全部通过；wheel 不带测试，M9A 的 wheel 带 `login_assets/*.png` |
| 全新 venv，只装五个 wheel 和运行池依赖，逐个导入两块库和 worker 侧 `core/`（`scripts/smoke_import.py`） | 65 个模块全部成功，没带出 `app` 和 `auto_mas_core` |
| 全新 venv，五个 wheel 加 SDK，宿主不在路径上，每个模块单起子进程导入 | 154 个模块成功 106 个；失败的 48 个全是 `No module named 'app'`（runner 1 个即 `plugin.py`，project_update 47 个）。原因见第 1 条 |
| 同上，把宿主源码（迁移分支 `46785ce81` 的 `git archive`）放进路径 | 154 个全部成功 |
| 三个专项装进同一环境，宿主源码在路径上，并在进程内摘掉宿主内置的三种类型（模拟让位分支） | 33 个模块全部成功；不摘时全部被「仍内置」守卫拦下（守卫有效） |
| 六个包之间所有跨包 `import` 的名字逐条解析（宿主形态，用真包不用桩） | 317 条全部能解析 |
| 跨包调用的实参能否绑定到提供方签名（AST 找调用点，`inspect.signature().bind`） | 631 处全部能绑定 |
| 三块服务插件各自的本地单元测试改用真包（不再用 agent_env 桩）重跑 | agent_env 11、runner 17（含真实 worker 子进程冒烟）、project_update 17，全过 |
| 两块库的单元测试，只装 wheel | 25 个全过 |

没做的：跑一轮（派发运行、worker 起来、L3 外壳与管理器的实际执行）；真机；GitHub 上的 CI 和发布工作流一次都没跑过。

### 宿主联调（2026-11-22）

宿主是联调分支 `int/mfw-plugins-20261122`（树 `D:\MAS\code\trees\mfwint`，内置 MFW / M9A / MSS 已让位），按那棵树的 `docs/mfw-plugins-local-integration.md` 接入：六个插件包用目录联接指向本仓库 `packages/` 下三块服务插件和三个专项仓库根，两块库用本仓库 HEAD（`e776a15`）`git archive` 后 `uv build` 出的 wheel，后端端口 36196。期间没有改任何插件代码。

| 做过的 | 结果 |
| --- | --- |
| 首次启动时宿主联合解析插件依赖 | 成功；`auto_mas_maafw_interface-0.1.0`、`auto_mas_maafw_native-0.1.0` 从本地 wheel 装进 `plugins\pypi\site-packages`（两块库不在 PyPI 上，靠 `UV_CONFIG_FILE` 的 find-links 解析到，契约 §6 第 6 步原先的「推测」由此坐实） |
| `/api/plugin/list` | 六个插件都被发现（`source=local`），`requires` 与契约一致 |
| 依次写 `info.enable` 触发器：agent_env → runner → project_update → maafw_adapter → m9a_adapter → mss_adapter | 六个都 `succeeded`，`state=enabled`、`last_error` 为空；日志里没有 ERROR |
| 重启后端 | 六个插件自动启用；三个托管、账号、控制器与资源都在，副本健康 |
| `GET /api/scripts/types` | 含 `M9A`、`MaaFW`、`MSS` |
| MaaFW：新建托管 → 导入 `D:\MAS\test\walkref\maabbb`（MAA_bbb v1.13.3）→ 预览（36 个任务，控制器 桌面端 / 安卓端）→ 补控制器「桌面端」资源「键鼠操作」→ 新建账号 → 读账号 → 准备 agent 环境 | 全部 200；导入 12.8 s；准备环境 21 s（新建运行池 runtime、下载 maafw 5.13.0 binding、建隔离 venv） |
| M9A：同上，项目 `D:\MAS\test\walkref\m9a`（v4.9.0），托管类型落成 `M9AConfig` | 全部 200；预览 29 个任务；控制器「ADB」资源「官服」；准备环境复用运行池，项目自带 Python 3.13，agent 导入检查通过 |
| MSS：同上，项目 `D:\MAS\test\mfw-src\StellaSora-v1.4.4`（MaaStellaSora v1.4.4），托管类型 `MSSConfig`；另建 `MSSPlanConfig` 计划表 | 全部 200；预览 15 个任务；控制器「桌面端」资源「官服」；准备环境通过；`/api/plan/add {"type":"MSSPlanConfig"}` 成功 |
| 建计划（库级，不经专项的 `account_run`）：用 `plugins\pypi\site-packages` 里实际装上的 `maafw_interface`，对三个副本 `resolve_default_snapshot` + `build_maafw_run_plan` | MaaFW 14 个任务、M9A 11 个任务建出计划；MSS 默认队列为空（见第 36 条），手选两个任务后建出计划，`PI_CLIENT_VERSION` 按传入值落进 `piEnv` |

没做到的：专项 `account_run` / L3 外壳的建计划和执行（要派发运行）；第 12、13、17、24 条仍未核实。

## 清单

| # | 位置 | 现象或简化 | 影响 | 打算怎么消 |
| --- | --- | --- | --- | --- |
| 1 | SDK `auto_mas_core/__init__.py` 顶层 `from app.config import …` | 凡是碰到 SDK 的模块（插件类、配置类、`host/`、`api/`、项目更新的 `core/project_update`、三个专项的大部分）离开宿主都导入不了。六个包的「无宿主逐模块导入」都按字面达不到 | 只能在宿主进程里导入和测；单元测试要拿宿主源码（`AUTO_MAS_HOST_SOURCE`） | SDK 改成顶层不导入 `app`（门面惰性转发），或者给出不依赖宿主的类型与基类 |
| 2 | 三块服务插件的包 `__init__`（PEP 562 惰性给出 `PLUGIN`）对比三个专项（照 SRC 急切导出） | 两种写法并存。惰性写法下，加载器 `getattr(module, "PLUGIN")` 时抛的 `ImportError` 不会被包成 `PluginPrecheckError`；本地源码布局下 `plugin.py` 不经免 pyc 的 finder，会写 `.pyc` | 积木插件建类出错时报错形状和别的插件不一样；开发版插件目录里会出现 `__pycache__` | 加载器在 `getattr` 时也做预检包装；或 SDK 不依赖宿主后积木改回急切导出 |
| 3 | `auto-mas-core` | 不在 PyPI 上，由宿主提供 | 在宿主外 `pip install` 任何插件包都解不出依赖（专项、积木都一样，SRC / MAA 同理） | 不用消；CI 只装 wheel 不解依赖 |
| 4 | 服务 `maafw.agent_env.v1`、`maafw.runner.v1` | 只实现 `version`；`maafw.project.v1` 另有 `owner.register` / `owner.unregister`。契约 §2.1–§2.3 的目标 op 都没做 | 插件之间实际靠直接 import | 0.2 起按契约 §2 的表逐条换成服务，先换 `plan.*`、`project.*` |
| 5 | 跨插件直接 import（契约 §3.2 的 R1、P1、S1、S2、S3） | runner → agent_env（`core/runner/environment.py`、`runner.py`、`host/plan_run.py`、`pretask_run.py`、`worker_paths.py`）；project_update → agent_env（`host/live_projects.py`、`precheck.py`、`precheck_gate.py` 顶层，其余在函数体）；三个专项的 `manager`、`account_run`、`config_view`、`startup` 顶层导入 runner / project_update / agent_env 的 `host.*` 和 glue；专项直接用积木里的数据类和异常类；属主入口是项目更新的 `BuiltinConfigOwner` 对象，方法在调用门外被调。都受规则 L 约束（`plugin.py` 的顶层导入链里没有），各包有测试守着 | 积木重载后，下游手里还是旧模块；积木出破坏性次版本会直接打断专项 | 同第 4 条；数据类挪进解析库或改成纯字典；属主协议拆成 `owner.list/read/write` op |
| 6 | 专项与积木的 `pyproject.toml` | 专项对积木、积木之间都写了次版本上限（0.2.0 时是 `>=0.2.0,<0.3`），偏离方案 §5 的「只写下限」 | 积木再升次版本时，九个包要一起改依赖范围、一起发 | 第 4、5 条做完后专项对积木只写下限 |
| 7 | runner 函数体内直接导入宿主（SDK 没有门面） | 0.2 已改经 SDK 出口：`task_client`、`utils_common_process_operations`、`utils_common_process_session`、`task_desktop_session_worker`、`utils_windows_desktop_session_process_runner`（`cca2526`）。还剩 `app.utils.common.game_resolution.UnityGameResolutionOverride`、`app.utils.process_platform`、`app.services.telemetry` 没有出口 | 宿主改这三处内部模块就会打断 runner；换过出口的这些要求宿主带 SDK 第三组出口（见第 38 条） | SDK 补剩下三个门面 |
| 8 | project_update 直接导入宿主 | 0.2 已改经 SDK 出口：`zip_range`（加载期导入，旧宿主退回宿主模块）、`normalize_proxy_address`（`7d1bfbb`）；`backup_archive` 那半句随 glue 搬进专项共用库已消（`bbb895a`）。还剩 `plugin.py` 的 `app.core.config.manager._PROCESS_STARTED_AT`（私有常量）、`api/update.py` 的 `app.services.common.update.transport` | 同上 | SDK 补这两个出口 |
| 9 | 三个专项直接导入宿主 | `manager.py` 顶层 `app.core.notify.lifecycle.NotificationTaskBase`（基类，挪不进函数体）；通用 MFW 的 `manager`、`account_run`、`shell_instances`、`shell_api` 顶层仍有一串 `app.*`；M9A、MSS 函数体里的 `app.task.client`、`app.task.game`、`process.session`、`game_calendar`、`ocr` 宿主已有出口（SDK 第三组），换不换在专项那边 | 同上 | 专项改经出口；`NotificationTaskBase`、`notify.formats.maafw` 等 SDK 补门面；0.2 改成 `UserExpander` + `ModeWorker` 后基类问题消失 |
| 10 | 留在宿主的模型和常量（契约 §8 第 13 条） | `schema.py` 的 MaaFW 模型、`ws/protocol.py` 两个常量、`notify/formats/maafw`、`MSSPlanKey` 经 `auto_mas_core.host.*` 或直接从 `app.*` 取 | 宿主 P4 删掉它们之前必须先搬 | P4 前搬进对应的包 |
| 11 | 三个专项的执行入口（契约 §8 第 5 条） | L3 外壳 `main_task` 整轮交给沿用的脚本级管理器，没有改成 `UserExpander` + `ModeWorker`；L3 的账号循环、`can_run_user` 都不用。服务侧已备好托管级良性跳过：`maafw_project_update.host.project_session.peek_project_skip(script_id)` 不占预约地给出「切换中 / 更新中 / 被占用」的结局，专项的 `check()` 可据此返回 `ScriptSkip(outcome.reason)`（`224b7a1`）；专项接没接要看专项那边。它只是一瞥，之后管理器真去预约时仍可能拿不到，那时照旧记「异常」 | L3 收尾可能把管理器记的「跳过」覆盖成「完成」（契约 B5，没解决）；MSS 外壳没把管理器回调的错误回报给 L2 | 方案 §8 最后一行；专项 `check()` 接 `peek_project_skip` |
| 12 | 三个专项的管理器 `host_locked_config` | 宿主 L2 已持托管 X 锁时管理器不再取锁；管理器在锁外的写回（导入报告、默认队列）能否照常写入只按 ContextVar 推测，没实跑（契约 §10） | 写回可能被锁挡住 | 联调第一件事核实 |
| 13 | 外壳没设 `after_config_lock`、没传预下载路径（契约 §8 第 9 条） | L2 给插件准备的 `prefetch_paths` 没交给管理器 | 预下载过的发行包可能再下一次 | 外壳里补设，或等 SDK |
| 14 | 宿主 L2 的「仅更新」模式（契约 §8 第 8 条） | 对插件类型不走插件路径，落到旧工厂报「该托管没有内建执行能力」 | 隐藏的更新任务对 MFW 家族失效 | 宿主 L2 给插件路径补更新模式 |
| 15 | 插件类型没有配置回调（契约 §8 第 6 条） | 宿主已有 SDK 托管生命周期钩子（`on_script_cloned`、`on_script_removed`、`prepare_user_read`、`on_user_added`、`prepare_user_update`）。服务侧已备好：复制 / 删除托管时处理视图的 `maafw_project_update.host.script_lifecycle`（`clone_script`、`cleanup_script_files`、`after_script_removal`，`224b7a1`），新账号默认队列、读前补齐、保存前加密在专项共用库（`default_snapshot.initialize_user` / `prepare_user_read`、`user_update.prepare_user_update`）。专项覆盖钩子、调这些函数要在专项那边做；配置备份恢复池仍没有出口 | 专项接上之前：界面上新账号的队列为空；复制后第一次运行要重新导入；删托管后视图晚一轮才回收 | 专项覆盖五个钩子；恢复池等 SDK |
| 16 | 桌面分身（契约 §8 第 7、19 条） | 运行积木在分身里查窗口已改走宿主通用的 `list_windows` / `window_in_session`（`cca2526`，同宿主 da8cf41a8），分身进程不再要导入插件包。专项要在 `ScriptTypeDecl` 声明 `desktop_session`（按配置判定游戏类型用 `game_kind`）才会被宿主放进分身，这在专项那边；`_settle_m9a_migration` 认不出插件类型仍是 P4 的事 | 专项声明之前 Win32 托管只能在主桌面跑 | 专项声明 `desktop_session`；P4 |
| 17 | 通用 MFW `shell_api` | 宿主 `Config.add_user` / `update_user` 原地改写传入字典，插件类型的加密走 `MaaFWUserConfig.update()` 覆盖，不改写调用方字典 | `/maafw/shell-instances/apply` 返回的 snapshot 可能是加密前的样子（推测，未实跑） | 联调核实；必要时在端点里自己加密后返回 |
| 18 | 项目更新 `on_enable` 的维护 | 与宿主原来的不完全一样：`Config.maafw_maintenance` 不为 `None`（宿主没让位）时整个不起维护也不注入加载信号；`AUTO_MAS_MFW_NO_CLEANUP=1` 时连加载信号也不注入（导入、更新后的「不在了」清理一并跳过）；原生日志清理改成启动维护后一次、之后每 24 小时一次（原来挂在每日日历上）；启动计时那几行没搬；维护循环常驻占一个后台任务席位。0.2 起加载信号读 `Config.managed_configs_loaded()`（旧宿主退回 `script_config_loaded_intact`，认不出旁挂） | 联调宿主必须把 `Config.maafw_maintenance` 置成 `None`，否则插件不维护 | 日历对齐等 SDK 有定时出口 |
| 19 | 项目更新：风味分支删除后的行为变化 | 没有 `scriptId` 的预览（新建托管对话框）一律用空规则表（原来按项目认领的风味取，例如 M9A）；专项项目种类不符时拒收原文改由属主给，识别出错的 warning 文案改了；多了 `owners.owner_project_mismatch_hook` | 新建 M9A 托管时的预览少了 M9A 规则表 | 预览按项目内容问各属主认领（0.2） |
| 22 | 代码放置（契约 §8 第 10、11、12、17 条） | glue 五个模块已搬进专项共用库 `auto-mas-maafw-adapter-kit`（`bbb895a`）。还剩：`game_package.py` 在 runner 和项目更新各一份；`agent-env/prepare` 端点在项目更新；外壳配置导入的 3 个端点在通用 MFW 专项 | 两份 `game_package` 要手动同步；只装 M9A / MSS 的用户没有外壳导入 | `game_package` 并进解析库；端点拆分（契约 §8） |
| 23 | 长调用（契约 §8 第 4 条） | `agent-env/prepare`、`update/job` 等端点仍是长等，没改成「开始 + 查询」。0.2 起运行积木、项目更新实现了 `teardown_blockers`：有运行在途、项目在更新、项目目录被运行 / 导入 / 准备环境占着时，宿主整体拒绝停用、重载、卸载（`89bab4e`、`224b7a1`），不会再拆到一半 | 宿主先关调用准入、等在途调用结束才问 `teardown_blockers`，长调用期间点停用仍要等它结束；项目更新的拒绝也会被维护期间一闪而过的视图预约触发，重试即可 | 0.2 之后改成「开始 + 查询」 |
| 24 | worker 的 `PYTHONPATH`（契约 §8 第 1 条） | 发行包布局下是整个 `plugins/pypi/site-packages`；本地源码布局（四个包各在自己的 `src`）2026-11-22 在迁移分支宿主上真跑过三轮，worker 和 agent 都起来了，但 `PYTHONPATH` 的具体内容没看 | 别的插件的依赖可能被 worker 导入到 | 改成方案 §6 的 `engine/<标识>/` |
| 25 | runner `core/runner/runner.py`、`worker.py` | 删掉了脚本方式运行时的裸名导入回退（`except ImportError: from x import …`、`__package__` 为空的分支） | 只能 `-m maafw_runner.core.runner.worker` 起 worker（plan_run 一直这么起） | 不用消 |
| 26 | 惰性 logger（agent_env `host/_logging.py`、runner `host/_sdk.py`） | 首次写日志才经 SDK 取宿主 logger，代理只转发属性 | 对它做 `isinstance(…, loguru.Logger)` 或调 dunder 方法会不一样（包内没有这种用法） | SDK 不依赖宿主后改回直接取 |
| 27 | 建计划时的客户端版本 | 解析库不再自己读 `res/version.json`，`PI_CLIENT_VERSION` 由调用方传：通用 MFW、M9A 取 `Config.VERSION`，MSS 读宿主源码根的 `res/version.json`（两者现在是同一个值）。通用 MFW 原来没传，装配时补上 | 两种取法将来可能不一致 | 统一成 SDK 给的版本号 |
| 28 | `[tool.auto-mas]`（契约 §8 第 16 条） | `bundled` / `default-enabled` 没写 | 不随安装包预装，装好后默认不启用 | P4 定 |
| 30 | 前端（契约 §8 第 20 条） | 插件类型的托管和账号载荷从 `UserData` 变成 `users`，多了 `info` | 界面可能有读不到字段的地方（没核实前端） | P0-前端 / 生成接口客户端 |
| 31 | 三个专项的配置类 | pydantic 报 `Field name "Info" / "Notify" shadows an attribute in parent`（SDK 基类自带小写 `info`、`notify`），SRC 同样如此。积木仓库里没有配置类；三个专项这一轮各自在改（本清单没有核实他们的结果） | 每次加载都刷 stderr | 专项那边消，序列化键不变 |
| 32 | 测试 | 插件包的单元测试按口径不提交，只留在各自本地；CI 只跑两块库的测试和导入检查；三个专项的本地测试用桩代替积木，没有改成对真包；MSS 的 `account_run` 主流程没有单测，宿主那两个对拍守卫没移植。**0.1.0 时三块服务插件的本地测试（agent_env 11、runner 17、project_update 17）在 0.2 开工时已不在盘上**，0.2 只补了这一版改动的本地测试（project_update 16、runner 6、agent_env 4） | 回归只能靠本地；0.1.0 的那批回归没了 | 联调稳定后挑代表性的随仓提交 |
| 33 | 发布 | 积木仓库的 CI 和发布工作流、专项的 `publish.yml` 都没在 GitHub 上跑过；CI 里 worker 侧导入检查要装 `maafw==5.16.1`，Linux wheel 是否齐全没核实；PyPI 可信发布者和发布环境还没建；发布开关 `PUBLISH_ENABLED` 默认不存在（只构建不上传） | 第一次推上去可能要修工作流 | 推上去先看 CI，再建环境和可信发布者、开开关 |
| 34 | 专项仓库分支 | 三个专项本地分支是 `master`（与 SRC、MAA 一致，`pyproject.toml` 里的链接也指向 `blob/master`），GitHub 上新建的空仓库默认分支是 `main` | 推成 `main` 的话 PyPI 页上的更新日志、文档链接会 404 | 推 `master` 后把默认分支改成 `master`，或者本地改名并改链接 |
| 35 | 第 15 条的联调实证（`int/mfw-plugins-20261122` 宿主的 `_get_script_config_handler` 对 `ScriptEntry` 一律返回 `None`，`add_user` / `get_user` / 删托管都不回调插件） | 新建账号后 `Task.TaskSnapshot` 是 `"{ }"`，读账号也不补；删掉一个已导入的托管后，它的副本 `data\mfw\<前 12 位>` 留在盘上，到下次启动「MFW 维护」才清。迁移分支宿主已有托管生命周期钩子，服务侧函数已备好，等专项接（见第 15 条） | 界面上新账号队列为空，要等开跑前专项自己补；删托管后磁盘晚一轮才回收 | 同第 15 条 |
| 36 | MSS 测试项目与默认队列 | `D:\MAS\test\walkref\starres` 是 MaaStarResonance（星痕共鸣），导入 MSS 托管被拒（「导入失败：这不是 MSS 项目。要用别的项目，请新建通用 MFW 托管。」，行为正确）；联调改用 `D:\MAS\test\mfw-src\StellaSora-v1.4.4`。这个版本的 interface 没有 `preset`、15 个任务的 `default_check` 全是 false，默认队列为空，`build_maafw_run_plan` 抛 `MaaFWRunPlanError: 当前 controller/resource 下没有可执行任务` | MSS 新账号不手选任务就开跑会直接失败（解析库行为与内置时相同，不是迁移带来的） | 不用消；走查 testbed 表里 MSS 那行要改成 StellaSora 的目录 |
| 38 | 对 SDK 的依赖下限 | 0.2 用到的宿主能力（SDK 第三组的 12 个 `auto_mas_core.host` 出口、托管生命周期钩子、`teardown_blockers`、`Config.managed_configs_loaded()`、分身通用动作 `list_windows` / `window_in_session`）只在迁移分支 `feat/mfw-plugin-migration-20261121` 合入 SDK 三组之后（`b8351bf0f` 核过）才有，而那里的 SDK 版本仍是 `5.9.0b1`，与联调分支 `int/mfw-plugins-20261122`、PyPI 期的宿主同号，`auto-mas-core>=5.9.0b1,<6` 表达不出这个要求，所以没改 | 装在旧宿主上：项目更新能加载（加载期的 `zip_range` 有退路），但运行积木起桌面游戏、在分身里查窗口、进程收尾等用到新出口的地方会 `ModuleNotFoundError`；`teardown_blockers` 不会被调用 | 宿主发下一个带这些出口的版本后，把下限提到那个版本 |
| 42 | 属主登记后补跑维护（第 37 条的做法） | 只在第一个属主登记 10 秒后补跑一次；专项之间启用间隔超过 10 秒时，后到的属主不在这一轮里，它名下的老副本这轮不迁移（有视图记着它时第 20 条的保护会让清理整轮不删） | 那个属主名下的老副本到下次启动才迁移 | 等 SDK 有「全部插件启用完」的出口 |
| 43 | 运行积木由 MAS 启动游戏（`DirectExe`）时的启动参数 | `host/desktop_game.py` 只用托管的 `Game.Arguments`；游戏目标（`win_process`）上的「启动参数」「工作目录」不读，那两项只在游戏管理里点「打开」时用。与内置时相同，不是迁移带来的 | 用户在游戏目标上填了启动参数，MFW 运行时不生效、也没有提示（联调时窗口标题因此没对上，报「游戏窗口在 60s 内未就绪」） | 定口径：要么运行积木合并游戏目标的参数，要么界面上说明以托管为准 |
| 44 | 只有配置、没有副本时的启动维护 | 第 21 条的 `clean_env_cache` 按「托管完整加载 + 视图在不在」判断谁还在用；只恢复 `config` 不恢复 `data`（或 `data` 被挪走）时，所有视图都不在，`config\maafw_env_cache` 被整批回收（升级演练里回收了 12 份） | 缓存能重建，只是下次准备环境要重下；托管配置不受影响 | 不急；要的话视图缺失时不回收、记一条提示 |
| 45 | 项目自己停掉流水线时的终态（M9A v4.15.0，空白窗口上跑「领取奖励」） | 账号日志先有「⚠ 回主界面失败：当前画面无法识别，本轮后续任务已停止」，紧接着是「任务完成: 领取奖励」，派发终态 `success`。同一托管在 v4.9.0 时是「停在 ReturnMain」、终态 `error`。还没查是项目新版本主动把这种情况报成成功，还是专项该把它判成失败 | 画面认不出时可能记成成功 | 查 M9A v4.15.0 的 agent 怎么结束任务，再定专项要不要按这条提示判失败 |
| 46 | 运行前更新会连带同一项目的其它托管 | 一个托管运行前把项目更新到新版本后，同一版本谱系的其它托管的副本也跟着切过去（日志「已同步 1 个脚本」），它们本地改过的文件按新版本覆盖，旧内容留在 `data\maafw_project_state\<谱系>\local-modified\` | 与内置时相同，是设计行为；用户未必想到别的托管也换了版本 | 不用消；要的话在界面或日志里说得更明白 |

## 已消

| # | 原来的问题 | 怎么消的 | 提交 |
| --- | --- | --- | --- |
| 20 | 「属主没答上来就整轮不删带标记视图」和「托管类型解析不出来时信号为假」两条没做 | 托管完整加载改读 `Config.managed_configs_loaded()`（有托管因所属插件不可用而旁挂时为假），属主入口（专项共用库 `owner_entry`）同改；「有视图记着没答上来的属主」的判断提到删除循环之前，命中就整轮不删带属主标记的视图、不回收载荷；`owners` 的规则表改成用到时才导入。旧宿主没有新出口时退回 `script_config_loaded_intact`，那时认不出旁挂 | `9cb0c97`（同宿主迁移分支 506598b1a、5e3df58b3） |
| 21 | 只增不减，没有清理 | `maafw_agent_env.host.env_cache.prune_prepared_environments` 按应保留的项目目录回收，项目更新的启动期维护新加一步 `clean_env_cache` 调它（托管没完整加载、有属主没答上来时整轮不删） | `2e63019`、`224b7a1` |
| 29 | 每次启动的受管任务整理、一次性迁移仍由宿主做 | 宿主已把 M9A 的一次性迁移、beta.1 补救与每次启动的受管任务整理搬进宿主自有的 `app/core/config/m9a_legacy/`，删 `app/task/M9A` 不再牵连迁移 | 宿主迁移分支 `b8351bf0f`（不在本仓库） |
| 41 | Q1：脚本后任务抛异常时崩溃回调被调两次 | 三个专项的 `account_run.final_task` 不再自己调 `on_crash`，交给宿主的收尾桥调一次 | 专项仓库 `d38fdf2`（maafw）、`0d22425`（m9a）、`8bfd1c4`（mss） |
| — | Q2：手动停止后账号日志没有说明、任务状态没有结束时间 | 三个专项收尾时在账号日志写「已手动停止」；宿主任务状态查询回传 `finishedAt`（不只是手动停止，所有终态原先都是空） | 三个专项与宿主迁移分支各一个提交 |
| — | Q4：等待、获取游戏实例只写账号日志，后端日志里看不到 | 宿主游戏会话同时写后端日志 | 宿主迁移分支 |
| — | Q5：资源包核对任务没登记进运行的进程作用域，取消时工作线程可能在预约放掉后继续写视图 | `resource_repair` 起任务后登记进当前进程作用域 | 本仓库 |
| 39、40 | 包版本号没升，与 PyPI 上的 0.1.0 同号、内容不同；项目更新对 agent 环境新函数的要求表达不出 | 九个包统一升 0.2.0，包之间的依赖范围改成 `>=0.2.0,<0.3` | 发 0.2.0 的提交 |
| 37 | 依次启用时，项目更新先于三个专项启用，启动维护跑在属主登记之前，日志「MFW 维护」记一条 WARNING：「MFW 托管属主的回答这次不算数，跳过 MFW 副本迁移」；重启后（六个插件一起启用）正常：`MFW 副本迁移完成：采纳 0 个、失败 0 个` | 启动期维护因属主还没登记跳过副本迁移时（`migration_deferred`），第一个属主经 `owner.register` 登记后等 10 秒补跑一轮启动期维护，同一次启用只补一次 | `224b7a1` |
