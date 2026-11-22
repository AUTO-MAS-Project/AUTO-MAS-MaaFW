# 0.1.0 已知问题

0.1.0 的口径是「主路径能装能跑就交，已知问题列清单，以后再消」。这份清单合并了六个包（本仓库五个包，加上 `AUTO-MAS-MaaFW-Adapter`、`AUTO-MAS-M9A-Adapter`、`AUTO-MAS-MSS-Adapter` 三个专项）实现时交回的已知问题和偏差，以及拆分契约文档（「MFW 插件包拆分与契约」，下称「契约」）§8 的取舍，去了重。

先说最要紧的：六个包**已经在联调宿主里装上、启用，三种类型都走到了「导入项目 → 准备 agent 环境」**（2026-11-22，见下面「宿主联调」一节），但**还没有真跑过一轮**（没派发运行、没拉游戏和模拟器）。下面「验证状况」一节写清了做过什么。

## 验证状况

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
| 6 | 专项与积木的 `pyproject.toml` | 专项对积木写了 `>=0.1.0,<0.2`，偏离方案 §5 的「只写下限」 | 积木发 0.2 时三个专项要一起改依赖、一起发 | 第 4、5 条做完后专项对积木只写下限 |
| 7 | runner 函数体内直接导入宿主（SDK 没有门面） | `app.task.client.ClientProcess`、`app.utils.common.game_resolution.UnityGameResolutionOverride`、`app.utils.common.process.operations`（`managed_process` / `terminate_process`）、`app.utils.common.process.session.desktop_process_target`、`app.task.desktop_session_worker.request_desktop_action`、`app.utils.windows.desktop_session.process_runner`、`app.utils.process_platform`、`app.services.telemetry` | 宿主改这些内部模块就会打断 runner | SDK 补门面 |
| 8 | project_update 直接导入宿主 | 顶层：`core/project_update/projection_heal.py`、`range_delta.py` 的 `app.utils.common.zip_range`；函数体：`host/update_credentials.py` 的 `normalize_proxy_address`、`plugin.py` 的 `app.core.config.manager._PROCESS_STARTED_AT`（私有常量）、`api/update.py` 的 `app.services.common.update.transport`；`glue/backup_archive.py` 顶层 `from auto_mas_core.host.utils_common_config import archive` 依赖宿主先导入过这个子模块 | 同上；`backup_archive` 依赖导入顺序 | SDK 补门面；`backup_archive` 改成函数体内取 |
| 9 | 三个专项直接导入宿主 | `manager.py` 顶层 `app.core.notify.lifecycle.NotificationTaskBase`（基类，挪不进函数体）；通用 MFW 的 `manager`、`account_run`、`shell_instances`、`shell_api` 顶层仍有一串 `app.*`；M9A、MSS 的其余宿主导入挪进了函数体（`app.task.client`、`app.task.game`、`app.utils.common.game_resolution`、`process.session`、`notify.formats.maafw`、`game_calendar`、`ocr`） | 同上 | SDK 补门面；0.2 改成 `UserExpander` + `ModeWorker` 后基类问题消失 |
| 10 | 留在宿主的模型和常量（契约 §8 第 13 条） | `schema.py` 的 MaaFW 模型、`ws/protocol.py` 两个常量、`notify/formats/maafw`、`MSSPlanKey` 经 `auto_mas_core.host.*` 或直接从 `app.*` 取 | 宿主 P4 删掉它们之前必须先搬 | P4 前搬进对应的包 |
| 11 | 三个专项的执行入口（契约 §8 第 5 条） | L3 外壳 `main_task` 整轮交给沿用的脚本级管理器，没有改成 `UserExpander` + `ModeWorker`；L3 的账号循环、`can_run_user` 都不用 | L3 收尾可能把管理器记的「跳过」覆盖成「完成」（契约 B5）；MSS 外壳没把管理器回调的错误回报给 L2 | 方案 §8 最后一行 |
| 12 | 三个专项的管理器 `host_locked_config` | 宿主 L2 已持托管 X 锁时管理器不再取锁；管理器在锁外的写回（导入报告、默认队列）能否照常写入只按 ContextVar 推测，没实跑（契约 §10） | 写回可能被锁挡住 | 联调第一件事核实 |
| 13 | 外壳没设 `after_config_lock`、没传预下载路径（契约 §8 第 9 条） | L2 给插件准备的 `prefetch_paths` 没交给管理器 | 预下载过的发行包可能再下一次 | 外壳里补设，或等 SDK |
| 14 | 宿主 L2 的「仅更新」模式（契约 §8 第 8 条） | 对插件类型不走插件路径，落到旧工厂报「该托管没有内建执行能力」 | 隐藏的更新任务对 MFW 家族失效 | 宿主 L2 给插件路径补更新模式 |
| 15 | 插件类型没有配置回调（契约 §8 第 6 条） | 新账号不自动补默认队列（开跑前才补）、复制托管不复制视图、删托管不立刻清视图、配置备份恢复不可用；MSS 的 docstring 还写着「经配置回调」 | 界面上新账号的队列为空；复制后第一次运行要重新导入 | SDK 托管生命周期出口（方案 §9 第 4 条） |
| 16 | 桌面分身（契约 §8 第 7、19 条） | 插件类型没有桌面分身；`_settle_m9a_migration` 和分身判定认不出插件类型 | Win32 托管只能在主桌面跑 | SDK §9 第 6 条；P4 |
| 17 | 通用 MFW `shell_api` | 宿主 `Config.add_user` / `update_user` 原地改写传入字典，插件类型的加密走 `MaaFWUserConfig.update()` 覆盖，不改写调用方字典 | `/maafw/shell-instances/apply` 返回的 snapshot 可能是加密前的样子（推测，未实跑） | 联调核实；必要时在端点里自己加密后返回 |
| 18 | 项目更新 `on_enable` 的维护 | 与宿主原来的不完全一样：`Config.maafw_maintenance` 不为 `None`（宿主没让位）时整个不起维护也不注入加载信号；`AUTO_MAS_MFW_NO_CLEANUP=1` 时连加载信号也不注入（导入、更新后的「不在了」清理一并跳过）；原生日志清理改成启动维护后一次、之后每 24 小时一次（原来挂在每日日历上）；启动计时那几行没搬；维护循环常驻占一个后台任务席位 | 联调宿主必须把 `Config.maafw_maintenance` 置成 `None`，否则插件不维护 | 联调分支照契约 §5 A1 改宿主；日历对齐等 SDK 有定时出口 |
| 19 | 项目更新：风味分支删除后的行为变化 | 没有 `scriptId` 的预览（新建托管对话框）一律用空规则表（原来按项目认领的风味取，例如 M9A）；专项项目种类不符时拒收原文改由属主给，识别出错的 warning 文案改了；多了 `owners.owner_project_mismatch_hook` | 新建 M9A 托管时的预览少了 M9A 规则表 | 预览按项目内容问各属主认领（0.2） |
| 20 | 属主「没答上来」与加载信号（契约 §8 第 14 条） | 「属主没答上来就整轮不删带标记视图」和「托管类型解析不出来时信号为假」两条没做 | 视图目录名撞上托管 uuid 前 12 位时有误删风险（极少）；有 `AUTO_MAS_MFW_NO_CLEANUP` 可关 | SDK §9 第 2 条 |
| 21 | `config/maafw_env_cache`（契约 §8 第 15 条） | 只增不减，没有清理 | 磁盘慢慢涨 | agent_env 补清理 |
| 22 | 代码放置（契约 §8 第 10、11、12、17 条） | glue 五个模块由三个专项共用一份，放在项目更新；`game_package.py` 在 runner 和项目更新各一份；`agent-env/prepare` 端点在项目更新；外壳配置导入的 3 个端点在通用 MFW 专项 | 两份 `game_package` 要手动同步；只装 M9A / MSS 的用户没有外壳导入 | glue 搬进各专项；`game_package` 并进解析库；端点拆分（契约 §8） |
| 23 | 长调用（契约 §8 第 4 条） | `agent-env/prepare`、`update/job` 等端点仍是长等，没改成「开始 + 查询」 | 停用积木时可能卡住 | 0.2 |
| 24 | worker 的 `PYTHONPATH`（契约 §8 第 1 条） | 发行包布局下是整个 `plugins/pypi/site-packages`；本地源码布局（四个包各在自己的 `src`）没实测，只测了 `--target` 目录布局 | 别的插件的依赖可能被 worker 导入到 | 改成方案 §6 的 `engine/<标识>/` |
| 25 | runner `core/runner/runner.py`、`worker.py` | 删掉了脚本方式运行时的裸名导入回退（`except ImportError: from x import …`、`__package__` 为空的分支） | 只能 `-m maafw_runner.core.runner.worker` 起 worker（plan_run 一直这么起） | 不用消 |
| 26 | 惰性 logger（agent_env `host/_logging.py`、runner `host/_sdk.py`） | 首次写日志才经 SDK 取宿主 logger，代理只转发属性 | 对它做 `isinstance(…, loguru.Logger)` 或调 dunder 方法会不一样（包内没有这种用法） | SDK 不依赖宿主后改回直接取 |
| 27 | 建计划时的客户端版本 | 解析库不再自己读 `res/version.json`，`PI_CLIENT_VERSION` 由调用方传：通用 MFW、M9A 取 `Config.VERSION`，MSS 读宿主源码根的 `res/version.json`（两者现在是同一个值）。通用 MFW 原来没传，装配时补上 | 两种取法将来可能不一致 | 统一成 SDK 给的版本号 |
| 28 | `[tool.auto-mas]`（契约 §8 第 16 条） | `bundled` / `default-enabled` 没写 | 不随安装包预装，装好后默认不启用 | P4 定 |
| 29 | M9A 迁移（契约 §8 第 18 条） | 每次启动的受管任务整理、一次性迁移仍由宿主做 | 宿主删 `app/task/M9A` 之前要先改写迁移 | 方案 §4.3 |
| 30 | 前端（契约 §8 第 20 条） | 插件类型的托管和账号载荷从 `UserData` 变成 `users`，多了 `info` | 界面可能有读不到字段的地方（没核实前端） | P0-前端 / 生成接口客户端 |
| 31 | 三个专项的配置类 | pydantic 报 `Field name "Info" / "Notify" shadows an attribute in parent`（SDK 基类自带小写 `info`、`notify`），SRC 同样如此 | 只是警告 | 不用消 |
| 32 | 测试 | 插件包的单元测试按口径不提交，只留在各自本地；CI 只跑两块库的测试和导入检查；三个专项的本地测试用桩代替积木，没有改成对真包；MSS 的 `account_run` 主流程没有单测，宿主那两个对拍守卫没移植 | 回归只能靠本地 | 联调稳定后挑代表性的随仓提交 |
| 33 | 发布 | 积木仓库的 CI 和发布工作流、专项的 `publish.yml` 都没在 GitHub 上跑过；CI 里 worker 侧导入检查要装 `maafw==5.16.1`，Linux wheel 是否齐全没核实；PyPI 可信发布者和发布环境还没建；发布开关 `PUBLISH_ENABLED` 默认不存在（只构建不上传） | 第一次推上去可能要修工作流 | 推上去先看 CI，再建环境和可信发布者、开开关 |
| 34 | 专项仓库分支 | 三个专项本地分支是 `master`（与 SRC、MAA 一致，`pyproject.toml` 里的链接也指向 `blob/master`），GitHub 上新建的空仓库默认分支是 `main` | 推成 `main` 的话 PyPI 页上的更新日志、文档链接会 404 | 推 `master` 后把默认分支改成 `master`，或者本地改名并改链接 |
| 35 | 第 15 条的联调实证（宿主 `app/core/config/manager.py` 的 `_get_script_config_handler` 对 `ScriptEntry` 一律返回 `None`，`add_user` / `get_user` / 删托管都不回调插件） | 新建账号后 `Task.TaskSnapshot` 是 `"{ }"`，读账号也不补（内置时 `initialize_user` / `prepare_user_read` 会按项目默认写入）；删掉一个已导入的托管后，它的副本 `data\mfw\<前 12 位>` 留在盘上，到下次启动「MFW 维护」才清（日志「已清理无脚本引用的 MFW 内嵌副本」） | 界面上新账号队列为空，要等开跑前专项自己补；删托管后磁盘晚一轮才回收 | 同第 15 条：SDK 给插件托管类型开配置回调出口 |
| 36 | MSS 测试项目与默认队列 | `D:\MAS\test\walkref\starres` 是 MaaStarResonance（星痕共鸣），导入 MSS 托管被拒（「导入失败：这不是 MSS 项目。要用别的项目，请新建通用 MFW 托管。」，行为正确）；联调改用 `D:\MAS\test\mfw-src\StellaSora-v1.4.4`。这个版本的 interface 没有 `preset`、15 个任务的 `default_check` 全是 false，默认队列为空，`build_maafw_run_plan` 抛 `MaaFWRunPlanError: 当前 controller/resource 下没有可执行任务` | MSS 新账号不手选任务就开跑会直接失败（解析库行为与内置时相同，不是迁移带来的） | 不用消；走查 testbed 表里 MSS 那行要改成 StellaSora 的目录 |
| 37 | 首次启用顺序（`maafw_project_update` 的维护） | 依次启用时，项目更新先于三个专项启用，启动维护跑在属主登记之前，日志「MFW 维护」记一条 WARNING：「MFW 托管属主的回答这次不算数，跳过 MFW 副本迁移」；重启后（六个插件一起启用）正常：`MFW 副本迁移完成：采纳 0 个、失败 0 个` | 第一次启用那一轮不做副本迁移，重启后补上；没有托管时无实际影响 | 维护在属主登记后再触发一次，或 SDK 给「全部插件启用完」的出口 |
