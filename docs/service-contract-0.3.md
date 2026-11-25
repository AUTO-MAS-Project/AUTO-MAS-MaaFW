# MFW 服务契约（0.3.0 起）

三块服务插件（agent 环境 `maafw_agent_env`、运行 `maafw_runner`、项目更新 `maafw_project_update`）对外只经「服务」提供功能；三个专项（通用 MFW、M9A、MSS）与两块服务插件之间互调都走这里列的服务名，不再直接导入别的插件包。本文是这些服务的契约，从 0.3.0（服务化之后的第一版）起生效。

- 依据是代码，不是设计稿：请求字段取自三份 `contract.py`（`packages/*/src/*/contract.py`，每个操作一个 pydantic 模型），句柄、事件、取消、忙重试取自解析库 `maafw_interface.service_calls`，出参与失败 code 取自各块的 `host/services.py`（项目更新是 `host/project_services.py`），调用方一侧取自专项共用库 `maafw_adapter_kit.services` 与 `owner_entry`。设计稿是 AUTO-MAS 工作区的《MFW 服务化实施方案》§2–§3，和代码不一致的地方以代码为准，差异列在文末。
- 操作清单是从三块插件类的 `provides_services` 实际求出来的（agent 环境 22 个、运行 29 个、项目 33 个加项目更新 13 个），与三份 `contract.py` 的 `REQUEST_MODELS` 逐个相同。改契约时两边一起改，再跑 `scripts/contract_compat.py`（见 §8）。
- **0.2 的分发式整名 0.3.0 不带**：`maafw.runner.v1`、`maafw.agent_env.v1`、`maafw.project.v1` 这三个「一个服务名、`call(op, …)` 分发」的旧入口已删，0.3.0 的插件不登记它们，调用方不许再用。版本号走各块的 `version` 操作。

## 1. 服务名

- 形状：`maafw.<族>.v1.<操作>`。族：`agent_env`、`runner`、`project`、`project_update`，以及专项提供的属主服务 `owner.<专项插件 id>`（如 `maafw.owner.maafw_adapter.v1.read`）。
- 族名本身（`maafw.runner.v1` 之类）不登记为服务。
- 长操作是四件套 `<x>_start` / `<x>_poll` / `<x>_stop` / `<x>_close`；没有取消点的族不登记 `_stop`，只有三件（§6 列出是哪几个）。
- 每个插件一个 `version`：`maafw.agent_env.v1.version`、`maafw.runner.v1.version`、`maafw.project.v1.version`。项目更新族没有自己的 `version`（与项目族是同一个插件）。
- 字段语义要变时不改原操作，另起 `v2` 的操作名（§8）。

## 2. 请求

- 请求是只含 JSON 值的 `dict`：路径一律字符串；发方负责把模型、路径、元组、时刻转成 JSON 值（共用库的请求构造函数都这样做），收方负责还原成内部类型。请求为 `None` 时按 `{}` 处理。
- 时刻：带时区的时刻出 ISO 8601 字符串（`datetime.isoformat()`，空值 `null`）——托管记录的 `imported_at`，项目 `open_start` / `update_start` 的 `round_started_at`。下面几处是**数字**（秒），照原接口保留，不是 ISO 字符串：运行 `account_open.run_started_at`（`time.time()`）、`plan_start.game_started_at`、`plan_start.task_deadlines`（宿主进程里的 `time.monotonic()` 截止时刻，两边同一进程）、项目 `finish_start.round_started_at`，以及 `device_adb_config.emulator_process.process_started_at`。
- 校验：每个提供方在自己的 `contract.py` 里用 pydantic 校验，`extra="ignore"`（顶层与嵌套的请求模型都是）、`hide_input_in_errors=True`。多出来的键忽略，服务层只按键名记一条 debug，**不记值**。
- **不许把请求写进日志**：请求里有解密后的任务密码（`plan_start.run_secrets`、`plan` 里的选项）、代理凭据（`proxy_url`、`record.proxy_address`）、Mirror 酱 CDK（`record.mirror_cdk`）。调用方客户端每次调用只记服务名、耗时与 `ok` / `code`。
- `contract.py` 只依赖 pydantic，不导入宿主、SDK 与本包别的模块：同仓测试和兼容核对脚本要单独导入它。

## 3. 结果与错误

成功、失败、跳过三种形状，都带 `ok`：

| 形状 | 字段 |
| --- | --- |
| 成功 | `{"ok": true, ...}` |
| 预期内失败 | `{"ok": false, "code", "message", "detail"}` |
| 良性跳过 | `{"ok": true, "outcome": "skipped", "reason", "message"}` |

调用方读结果只按键取，忽略不认识的键。提供方自己的 bug 照常抛异常（不包成结果）；长操作作业里的异常都进 `result`，不从 `_poll` 抛。

所有操作都可能回的 code：

- `invalid_request`：缺必填字段、类型不对，或取值不合字段约束（如 `plan_start` 运行池两项为空串）。`message` 是「<块中文名>收到的请求格式不对：<字段路径>」，不带输入值；`detail` 只有 `{"errors": [{"loc": [...], "type": "..."}]}`（取自 `exc.errors(include_input=False, include_url=False)`，`loc` 转成 list）。三块的前缀原文：
  - agent 环境：「agent 环境积木收到的请求格式不对：」
  - 运行：「运行积木收到的请求格式不对：」
  - 项目 / 项目更新：「项目积木收到的请求格式不对：」
- `unknown_handle`：句柄不在本插件实例的句柄表里（提供方重载、停用过，或句柄已关）。`detail` 为 `{}`，`message` 是三句固定话：
  - 运行：「MFW 运行插件已重新加载或停用，本次运行的结果拿不到了」
  - agent 环境：「MFW agent 环境插件已重新加载或停用，本次环境准备的结果拿不到了」
  - 项目 / 项目更新：「MFW 项目插件已重新加载或停用，本次项目操作的结果拿不到了」

由「提供方内部抛异常」变来的失败（`exception_result`）：`message` 是 `str(exc)` 原文，`detail.exception_type` 是异常类名。长操作作业里没接住的异常也走它，code 是该族登记的失败 code（运行各族 `run_failed`；agent 环境 `borrow` 为 `borrow_failed`、`prepare` 与 `trial` 为 `prepare_failed`；项目 `open` 为 `import_failed`、项目更新 `prefetch` / `discover` 为 `prefetch_failed` / `discover_failed`），没登记的族是 `internal_error`。调用方在原来让异常往上抛的地方 `raise RuntimeError(message)`，文案逐字不变。长操作作业被取消且自己没给结果时，结果是 `{"ok": false, "code": "cancelled", "message": "", "detail": {}}`（各块多数给了自己的取消结果，见 §9）。

调用方一侧另有 `service_unavailable`（不是提供方回的，是解析库 / 共用库在拿不到服务时合成的）：`{"ok": false, "code": "service_unavailable", "message": <同 unknown_handle 那句>, "detail": {"service": <服务名>, "reason": <原因>}}`，`reason` 是 `sealed`（注册表已封，宿主在退出）、`not_registered`（没登记或已注销）、`fuse`（忙重试 10 分钟保险丝到了）、`unbound`（专项的服务槽没绑：插件没启用或已停用）。

## 4. 句柄四件套

| 操作 | 请求 | 出参 |
| --- | --- | --- |
| `<x>_start` | 各族自己的请求（§9） | `{"ok": true, "handle": "<32 位十六进制>", "stop_grace": float \| null}`；或开始前就判定的失败 / 跳过 |
| `<x>_poll` | `handle`（必填）、`cursor: int`（缺省 0）、`wait: float`（缺省 0）、`limit: int \| null` | `{"ok": true, "events": [...], "cursor": int, "done": bool, "result": dict \| null, "dropped": int}` |
| `<x>_stop` | `handle`（必填）、`reason: str \| null` | `{"ok": true}`，只置停止、不等 |
| `<x>_close` | `handle`（必填） | `{"ok": true, "detached": bool}` |

- `_poll`：先把 `seq ≤ cursor` 的事件当作已读丢掉；有新事件或作业已结束就立即返回，否则最多等 `wait` 秒。`wait` 上限 1.0（超出按 1.0，负数、NaN、非数字按 0）；`limit` 缺省 500、上限 2000（非正数、非数字按 500）。回的 `cursor` 是本批最后一条事件的 `seq`（没事件时原样回）。`done` 只在作业结束**且**事件全部交出之后为真，这时 `result` 才有值（自带 `ok`）。调用方的缺省是 `wait=1.0`、不带 `limit`。
- 积压：一个句柄最多积压 10000 条未读事件，超了只丢最老的 `log` / `progress`，丢掉的条数在下一次 `_poll` 的 `dropped` 里回一次；`download` 事件未读的只留最新一条。
- `_stop`：只置停止标记（`reason` 原样记在作业上，第一次的为准），作业登记了停止回调就调它，否则取消作业任务。`reason` 只有项目的 `open`、`confirm` 与项目更新的 `update` 认（`cancelled` / `stop_requested`，缺省按 `cancelled`）；项目这一侧的 `_stop` 只收这两个值或 `null`，运行与 agent 环境收任意字符串、不区分。
- `_close`：作业已结束时丢掉结果（`detached: false`）；没结束时**脱手**（`detached: true`）：不取消，提供方让作业跑完自己收尾（借到的租约还掉、预约照原规则放、不写缓存）。要取消先 `_stop`。
- 终态的句柄 600 秒没被访问（`_poll` / `_stop` 都算访问），在下一次本块任何 `_start` / `_poll` 时顺手删掉（借成却没被取走的租约先还）。不起后台循环。
- 句柄表放在插件实例上，重载后旧句柄一律 `unknown_handle`。
- 运行的账号句柄（`account_open` 给的 `account`）不设超时：专项在收尾最外层的 `finally` 里调 `account_close`，它**总是成功**；账号下还有作业时回 `deferred: true`，最后一个作业结束时提供方丢掉账号状态。

## 5. 事件

`{"seq": int, "at": float, "type": ..., ...}`。`seq` 每个句柄从 1 递增、保持发出顺序；`at` 是发出时刻（`time.time()`）。

| type | 字段 | 谁发 |
| --- | --- | --- |
| `log` | `message: str`、`warning: bool` | 运行（`warning` 照原事件）、agent 环境（恒为 false）、项目（修复作业照原事件，其余恒为 false） |
| `point` | `stage`、`state`、`key` | 运行、项目 |
| `record` | `data`（worker 的结构化运行记录，形状见解析库 `runner.run_events`） | 运行 |
| `stage` | `stage`、`ok: bool \| null` | 运行 |
| `download` | `received`、`total` | 项目更新（`prefetch`） |
| `progress` | `data: dict`（原样的进度字典） | agent 环境 |

调用方先按 `seq` 把本批事件交给回调，再看 `done`；不认识的 `type` 记 debug 后忽略。

## 6. 取消规则与 `stop_grace`

`_start` 回的 `stop_grace` 与调用方（共用库 `FAMILY_CANCEL_RULES`）被取消时走的规则：

| 族 | `_stop` | `stop_grace` | 调用方被取消时 |
| --- | --- | --- | --- |
| 运行 `desktop_launch`、`pretask`、`plan` | 有 | null | 规则 1：`_stop` → 一直轮询到 `done`（事件照常交）→ `_close` → 重抛；等的期间再来的取消一律吞掉，只有 `unknown_handle`、服务已注销或注册表已封时才脱手 |
| 运行 `desktop_quit`、`pretask_kill`、`pretask_exit_watch` | 无 | null | 规则 3：即 `_close` 脱手 → 重抛，提供方把清理做完 |
| agent 环境 `borrow`、`prepare` | 有 | 2.0 | 规则 2：`_stop` → 最多等 `stop_grace + 5` 秒；到时、或期间再被取消 → `_close` 脱手 → 重抛 |
| agent 环境 `trial` | 有 | null | 规则 1 |
| agent 环境 `reconcile` | 无 | null | 规则 3 |
| 项目 `open`、`confirm` | 有 | 2.0 | 规则 2 |
| 项目 `repair` | 有（只置令牌） | 0.0 | 规则 4：发 `_stop`，不 `_close`，句柄交给 `run_release(after_job=…)` |
| 项目 `finish`、`view_ensure`、`script_cloned`、`script_removed` | 无 | null | 规则 3 |
| 项目更新 `update` | 有 | 60.0 | 规则 2 |
| 项目更新 `prefetch`、`discover` | 有 | 5.0 | 规则 2 |

没有 `_stop` 的族 `_start` 也回 `stop_grace: null`，调用方按族名而不是按这个值决定走规则 3。

同步停止（宿主在同步回调里通知专项停止时）：共用库 `Operation.stop()` 不 `await`——先置本地标记；已有句柄就在事件循环上补发 `_stop`；`_start` 还在途就等它回来再补发；还没 `_start` 的，`confirm`、`update` 两族在 `_start` 请求里带 `stop_requested: true`。`open`、`confirm`、`update` 的补发带 `reason`（缺省 `stop_requested`），别的族不带。

## 7. 调用方

- **现取**：每次调用前 `require(服务名)`，不缓存服务对象；忙重试的每一次尝试也重新 `require`。专项经模块级 `ServiceSlot`（插件 `on_enable` 绑、`on_disable` 解）拿宿主给的解析器。
- **忙与不可用**：

  | 情形 | 怎么认 | 做法 |
  | --- | --- | --- |
  | 注册表已封（宿主退出） | 解析器 `accepting` 为假，或 `require` 抛 `PluginBusyError` | 立即放弃，`service_unavailable`（`sealed`） |
  | 服务没登记 / 已注销 | `require` 抛 `PluginError` 但不是 `PluginBusyError` | 立即放弃，`service_unavailable`（`not_registered`） |
  | 提供方暂停准入 | `require` 拿到了，调用时抛 `PluginBusyError` | 0.2 秒退避后重新 `require` 再试，不设固定上限；调用方被取消就停止重试；从第一次撞忙算起 600 秒还忙按 `service_unavailable`（`fuse`） |
  | 生命周期钩子里的调用（`owner_register`、`owner_unregister` 等） | 调用方自知 | 用只试一次的入口（`call_once`），异常原样上抛 |

  `PluginBusyError` / `PluginError` 按类名认（SDK 没导出这两个类）。提供方作业里再调别的服务时同样经解析库，失败转成结果字典，不许让 `PluginBusyError` 从自己的服务方法里冒出去。
- **线程**：工作线程里调同步服务（属主操作、`desktop_check`）用同步助手（退避用 `time.sleep(0.2)`，判定同上）；调异步服务经线程桥（事件循环在起线程前取好）。线程里每次调用、每次重试都经起线程前取好的解析器现取。
- **上下文**：会起进程、找窗口、取模拟器的操作在这次调用里读 `current_process_scope`、`desktop_process_target`、`current_game_session`；长操作的作业在 `_start` 里 `asyncio.create_task(…)`（不传 `context=`）建，读得到调用方设的 contextvars。

## 8. 兼容规则与版本

- 请求新增字段必须可选、缺省等于旧行为；字段语义变了走新的 `v2` 操作；已有的操作不删（要删也走 `v2` 并保留旧的一个大版本）。提供方忽略多出来的键，调用方忽略不认识的结果键。这样「新共用库 + 旧提供方」「旧共用库 + 新提供方」两种错配都退回旧行为。
- 共用库不依赖三块服务插件（它拼的请求靠上一条与旧提供方相容），所以发版前用 `scripts/contract_compat.py` 拿上一发行版的 `contract.py` 校验共用库当前拼出的每种请求（用法见脚本开头；0.3.0 是第一个带 `contract.py` 的版本，这一版只能 `--self` 自检，从 0.3.1 起每次发版对上一版跑）。
- 版本范围：两块库与共用库被直接导入，0.3.x 内只许增加，破坏性改动升 0.4 并与专项一起发；三块服务插件之间、专项对服务插件只写下限（`>=0.3.0`，无上限）。具体到每个文件的改法见 [`release-0.3.0.md`](release-0.3.0.md)。

## 9. 操作清单

请求字段按 `contract.py`：标「必填」的必须给，其余写的是缺省值；`str?` 表示可为 `null`。`record` 是 §9.5 的托管记录。

### 9.1 agent 环境 `maafw.agent_env.v1.*`（22 个，提供方 `maafw_agent_env`，`requires` 为空）

| 操作 | 种类 | 请求 | 出参 / 终态 | 失败 code | 调用方 |
| --- | --- | --- | --- | --- | --- |
| `version` | async | `{}` | `package`、`version`、`worker_api: [1]` | — | 诊断 |
| `runtime_route` | async（内部线程，可能等池锁） | `{}` | `root`、`pool_id` | `runtime_route_unavailable` | 三个专项；项目更新 |
| `runtime_check` | async（内部线程） | `project_path` 必填 | `problem: str?` | — | 三个专项运行前检查 |
| `storage_info` | async | `{}` | `runtime_pool_root`、`has_runtimes`、`agent_venvs_root`、`has_agent_venvs` | — | 项目更新维护 |
| `borrow_start/_poll/_stop/_close` | 句柄 | `project_path` 必填；`runtime_pool_root: str?`；`runtime_pool_id: str?`；`lease_owner`（缺省 `automas-maafw-runner`）；`lease_ttl_seconds: float?`（缺省 86400，显式 null 表示不设有效期）；`agents: list[dict]`（缺省 `[]`，每项 `MaaFWAgent` 按别名 dump）；`agent_env_root: str?`；`proxy_url: str?` | 终态 `python_executable`、`venv_path`、`packages`、`maafw_version`、`maafw_requirement`、`runtime_id`、`runtime_pool_root`、`runtime_pool_id`、`lease_id`、`binding_dir`、`binding_version`、`native_dir`、`worker_env`、`agent_plans`、`worker_paths`、`worker_api`；事件 `log`、`progress` | `borrow_failed`、`stopped` | 运行 |
| `borrow_return` | async | `runtime_pool_root`、`runtime_id`、`lease_id`、`binding_version`（都是 `str?`，借到的原样交回） | `released` | `return_failed` | 运行 |
| `env_lookup` | async（内部线程） | `project_path` 必填；`want_previously_prepared`（缺省 false） | `fingerprint`、`cached`、`previously_prepared` | — | 项目更新 |
| `prepare_start/_poll/_stop/_close` | 句柄 | `project_path` 必填；`runtime_pool_root: str?`；`runtime_pool_id: str?`；`proxy_url: str?`（最终生效值）；`lenient_health_check`（false）；`store_cache`（false）；`fallback_fingerprint: str?`；`import_check: off \| warn`（缺省 `off`） | 终态 `environment`（camelCase 原样）、`health_warnings`、`stored`；事件 `log`、`progress` | `interface_load_failed`、`runtime_route_unavailable`、`prepare_failed`、`stopped` | 项目更新 |
| `trial_start/_poll/_stop/_close` | 句柄 | `project_path` 必填；`runtime_pool_root: str?`；`proxy_url: str?`；`previous_version: str?` | 终态 `{}`；事件 `log` | `agent_module_missing`（`detail.modules`）、`prepare_failed`、`stopped` | 项目更新预检（工作线程，线程桥） |
| `reconcile_start/_poll/_close` | 句柄，无 stop | `target: runtime_pool \| agent_venvs` 必填；`keep_paths: list[str]` 必填；`reason: str?`；`updated_project_path: str?`；`previous_version: str?`；`detach`（false） | 终态 `report`，或跳过 `abstained` | — | 项目更新（后台对账、维护） |
| `cache_prune` | async | `keep_project_paths: list[str]` 必填 | `removed` | — | 项目更新维护 |

停用拦截（`teardown_blockers`）：「MFW agent 环境还有 N 个运行环境准备没有结束，请等它们结束后再操作」「MFW 运行池回收正在进行，请稍后再操作」「MFW 有 N 个运行正在使用运行环境」。

### 9.2 运行 `maafw.runner.v1.*`（29 个，提供方 `maafw_runner`）

`requires`：`maafw.agent_env.v1.borrow_start`、`borrow_poll`、`borrow_stop`、`borrow_close`、`borrow_return`（5 个）。

| 操作 | 种类 | 请求 | 出参 / 终态 | 失败 code | 调用方 |
| --- | --- | --- | --- | --- | --- |
| `version` | async | `{}` | `package`、`version` | — | 诊断 |
| `account_open` | async | `owner`、`label`、`run_started_at: float`（都必填） | `account` | — | 三个专项运行前检查通过后 |
| `account_close` | async | `account` 必填 | `deferred: bool`，总是成功（不存在当已关） | — | 三个专项收尾最外层 `finally` |
| `desktop_check` | **同步** | `spec` 必填（下表 Spec） | `managed`、`error` | — | 三个专项运行前检查（工作线程，同步助手） |
| `desktop_launch_start/_poll/_stop/_close` | 句柄 | `account`、`spec` 必填；`controller: dict?`（选中控制器按别名 dump，interface 没加载时 null）；`controller_name: str?`；`interface_loaded: bool?`（缺省按 `controller` 是否为 null 判） | 终态 `desktop: {opened, started_at}`；事件 `log`、`point` | `desktop_launch_failed`、`cancelled`（都带 `detail.desktop`）、`unknown_account`、`account_busy`；`controller` 不合模型时 `invalid_request`（`loc` 以 `controller` 开头） | 三个专项「客户端」阶段 |
| `desktop_quit_start/_poll/_close` | 句柄，无 stop | `account`、`spec`（收尾用，可带 `*_error`）、`mode: retry \| final` 必填；`controller: dict?`；`controller_name: str?`；`interface_loaded: bool?`；`controller_type: str?`；`failed`（false） | 终态 `closed`、`desktop` | `client_path_unreadable`、`desktop_quit_failed`（都带 `detail.desktop`）、`unknown_account`、`account_busy`；`controller` 不合模型时 `invalid_request`（`loc` 以 `controller` 开头） | 重试之间、最终收尾 |
| `device_adb_path` | async | `emulator_id`、`device_uid` 必填；`configured_path`（任意，缺省 null）；`device_title: str?`；`address`（缺省 `""`）；`host_adb_path: str?`（调用方缓存，null 时才解析）；`ask_toolkit: never \| if_unresolved`（缺省 `never`） | `host_adb_path`、`adb_path`、`events` | — | ADB 分支开头 |
| `device_adb_config` | async | `emulator_id`、`target_id`、`device_uid`、`address` 必填；`adb_path: str?`；`profile: {emulator_type?, screencap_extra=false, input_extra=false, config={}} \| null`（调用方缓存，null 时才建）；`emulator_process: {process_id: int?, process_started_at: float?}`；`configured_screencap_methods`、`configured_input_methods`（脚本配置 `Device.AdbScreencapMethods` / `Device.AdbInputMethods` 的原值，只在非 MuMu / 雷电 / ModAVD 时用；缺省或 null 按这两个配置项的缺省值 -57 / -1 算，与内置时代没配置时相同；原值转不成整数时回 `device_config_failed`） | `device_config`、`profile`、`events` | `avd_profile_unavailable`、`device_config_failed` | ADB 分支 |
| `device_win32_config` | async | `controller: dict` 必填；`configured_hwnd`、`configured_screencap_method`、`configured_mouse_method`、`configured_keyboard_method`（任意） | `device_config`、`hwnd`、`events` | `hwnd_not_in_session`、`no_window_rules`、`window_not_found`、`device_config_failed`（其余异常）；`controller` 不合模型时 `invalid_request`（`loc` 以 `controller` 开头） | Win32 分支 |
| `pretask_rerun_check` | async | `has_pretasks`、`client_reset` 必填；`controller_type: str?`；`interface_loaded`（false）；`controller_name: str?`；`controller: dict?`；`configured_hwnd`（任意） | `rerun`、`events` | `controller_not_found`、`rerun_check_failed`（其余异常）；`controller` 不合模型时 `invalid_request`（`loc` 以 `controller` 开头） | 每次重试前 |
| `pretask_start/_poll/_stop/_close` | 句柄 | `account`、`project_path` 必填；`pretasks: list[dict]`（`[]`）；`run_time_limit_minutes`（任意，0 / 空按 120）；`plan_env: dict[str,str]`；`extra_env: dict[str,str]`；`secrets: list[str]` | 终态 `{}`；事件 `log` | `pretask_failed`、`run_failed`、`cancelled`、`unknown_account`、`account_busy` | 每次尝试 |
| `pretask_kill_start/_poll/_close` | 句柄，无 stop | `account` 必填 | 终态 `{}`；事件 `log` | `unknown_account`、`account_busy`；作业异常按 `run_failed` | 收尾 |
| `pretask_exit_watch_start/_poll/_close` | 句柄，无 stop | `account: str?`（没开过账号时 null，当场确认）；`after_scope`（false；为真时作业先等调用方此刻的进程作用域收尾再等确认退出，快照仍在 `_start` 当场拍） | 终态 `confirmed` | `unknown_account`（start 时） | 共用库 `release_run_reservation` |
| `plan_start/_poll/_stop/_close` | 句柄 | 必填：`account`、`project_path`、`plan: dict`（`MaaFWRunPlan.model_dump(mode="json")`）、`device_config: dict`、`runtime_pool_root: str`、`runtime_pool_id: str`（运行环境池的根目录与池 id，调用方先经 agent 环境的 `runtime_route` 取得；两项都不许为 null 或空串，`runtime_pool_id` 先去首尾空白再判，不合时回点名字段的 `invalid_request`）、`lease_owner`、`run_time_limit_minutes: int`、`attachment_root`；可选：`declared_agents: list[dict]`（`[]`，`plan.declaredAgents` 按别名 dump——它带 `exclude=True`，整份 dump 时被丢，另由这里带）、`task_time_limit_seconds`（0）、`task_time_limit_overrides: dict[str,int]`、`task_deadlines: dict[str,float]`、`loop_guard`（false）、`run_secrets`、`project_log_secrets`（`[]`）、`redaction_notice: str?`、`game_start_source: desktop \| given`（`given`）、`game_started_at: float?`、`game_start_disk_quiet`（false）、`game_wait_seconds`（任意，0）、`proxy_url: str?`、`agent_plans: list[dict]?`（沿用的 agent 命令计划，null 时用这次借环境算出的）、`extra_env: dict[str,str]`、`avd: {emulator_id} \| null`（ModAVD） | 终态 `result`（`MaaFWRunResult` dump）、`attachments`、`native_errors`、`agent_plans`；事件 `log`、`point`、`record`、`stage` | `run_timeout`、`task_deadline_expired`（`detail.task_name`）、`run_failed`、`cancelled`，都带 `detail.{attachments, native_errors, agent_plans}`；`unknown_account`、`account_busy` | 每次尝试 |

Spec（`desktop_*` 的 `spec`，替掉 `MaaFWDesktopGameSpec`，字段名不变）：`launch_mode` 必填；`game_path: str?`；`launcher_path: str?`；`url`（`""`）；`arguments`、`wait_seconds`（任意）；`unity_resolution: list[int]?`；`close_mode`（`OnFailure`）；`configured_hwnd`（任意）；`game_path_error: str?`、`launcher_path_error: str?`（只给收尾用：读路径时的异常原文）。

- `account_busy` 只表示「同一账号同一族作业已有一个没结束」；`account_close` 从不回它。
- 停用拦截：「MFW 运行积木还有 N 个运行没有结束，请先停止任务再操作」，N 数有在途作业（含已脱手、还在跑的 `desktop_quit`、`pretask_kill`）的账号。

### 9.3 项目 `maafw.project.v1.*`（33 个）

提供方 `maafw_project_update`。`requires`：`maafw.agent_env.v1.runtime_route`、`storage_info`、`env_lookup`、`prepare_start/_poll/_stop/_close`、`trial_start/_poll/_stop/_close`、`reconcile_start/_poll/_close`、`cache_prune`（15 个）。属主服务不写进 `requires`，按登记的前缀每次现取。

| 操作 | 种类 | 请求 | 出参 / 终态 | 失败 code / 跳过 | 调用方 |
| --- | --- | --- | --- | --- | --- |
| `version` | async | `{}` | `package`、`version` | — | 诊断 |
| `owner_register` | async | `name`、`prefix` 必填 | `{}` | —（同名再登记以新的为准，见表下） | 三个专项 `on_enable`（只试一次） |
| `owner_unregister` | async | `name` 必填 | `{}` | — | 三个专项 `on_disable`（只试一次） |
| `managed_find` | async | `script_id` 必填 | `owner`、`record` | `invalid_id`、`not_found`、`not_managed` | 通用 MFW 外壳导入 |
| `project_context` | async | `record` 必填；`with_view_import_check`（false） | `auto_update_mode`、`proxy_url`（机密）、`follow_source`、`source_form`、`channel`、`shell_hint`、`view_dir`、`view_imported_from_source` | — | 三个专项 |
| `project_peek` | async | `script_id` 必填 | `reserved`、`updating`、`switching`、`skip: {reason, message} \| null` | — | M9A 外壳 |
| `run_reserve` | async | `script_id` 必填 | `key` | 跳过 `updating`、`occupied` | 三个专项账号流程 |
| `run_release` | async | `key` 必填；`after_job: str?`（修复作业的句柄，还在跑时把释放挂到它完成上）；`on_job_error: keep \| release`（`release`） | `released`、`deferred` | — | 共用库 `release_run_reservation` |
| `open_start/_poll/_stop/_close` | 句柄 | `script_id`、`owner`、`record` 必填；`script_name`（`""`）；`round_started_at: ISO 字符串?`（这一轮开始的时刻，提供方还原成秒数，缺省 0） | 终态 `outcome: opened`（带 `lease`、`record_update`、`env_confirm_needed`）/ `stopped` / 失败（`detail.record_update`）；事件 `log` | 跳过 `switching`、`updating`、`occupied`；`import_failed`、`view_missing` | 三个专项运行前检查（共用库 `open_project`） |
| `open_release` | async | `handle` 必填 | `released`、`deferred` | — | 同上 |
| `confirm_start/_poll/_stop/_close` | 句柄 | `script_id`、`record`、`phase: BeforeRun \| AfterRun` 必填；`owner`（`""`）；`stop_requested`（false） | 终态 `outcome`、`notice: {level, message} \| null` | — | 三个专项 |
| `finish_start/_poll/_close` | 句柄，无 stop | `script_id`、`record`、`sync_group: bool` 必填；`owner`、`script_name`（`""`）；`round_started_at: float`（0） | 终态 `env_confirm_needed` | — | 三个专项收尾 |
| `repair_start/_poll/_stop/_close` | 句柄 | `script_id`、`record`、`kind` 必填；`script_name`（`""`）；`already_checked`（false） | 终态 `checked_now`、`rerun: {line, title} \| null`；事件 `log`（带 `warning`） | — | 三个专项账号流程 |
| `view_ensure_start/_poll/_close` | 句柄，无 stop | `script_id: str?`；`fallback_path`（`""`） | 终态 `root` | `invalid_managed`、`busy`、`import_failed`、`no_path` | 通用 MFW 外壳 |
| `script_cloned_start/_poll/_close` | 句柄，无 stop | `source_id`、`target_id`、`owner`、`source_record` 必填 | 终态 `outcome: cloned` / 跳过 `occupied`、`follow_source_clone_unavailable` | `clone_failed` | 三个专项 `on_script_cloned` |
| `script_removed_start/_poll/_close` | 句柄，无 stop | `script_id`、`owner` 必填 | 终态 `outcome: removed \| absent \| kept_other_owner`、`recorded_owner`、`view_path` | — | 三个专项 `on_script_removed` |

属主登记：

- 属主名就是专项插件 id，同一个 id 不会同时有两个活着的专项实例。同名再登记一律以新的为准，替换旧登记并记一行 info；同名换了 `prefix` 时旧前缀一并作废。同名同前缀再登记什么也不变。早先文档里的失败码 `owner_conflict` 从此不会再出现。
- 提供方停用、退出时撤掉经 `owner_register` 登记的全部属主，启用时也先撤一遍。原因：连带重载（比如重载 agent 环境）时，宿主先关项目更新的调用门，专项 `on_disable` 里的 `owner_unregister` 会被拒（「插件正在释放，不再受理调用」），而项目更新的模块不重新导入，属主表会留下来。
- 直接调 `owners.register_owner` 登记的属主（对拍仓的世界、旧内置形态）不归提供方撤，由登记方自己撤。

停用拦截：「MFW 有 N 个项目正在更新，请等更新结束后再操作」「MFW 有 N 个项目目录正被运行、导入或准备运行环境占用，请等它们结束后再操作」「MFW 有 N 项项目操作正在进行（打开、更新、确认环境、修复、复制或删除托管），请等它们结束后再操作」。

### 9.4 项目更新 `maafw.project_update.v1.*`（13 个，提供方同 §9.3）

| 操作 | 种类 | 请求 | 出参 / 终态 | 失败 code / 跳过 | 调用方 |
| --- | --- | --- | --- | --- | --- |
| `update_start/_poll/_stop/_close` | 句柄 | `script_id`、`record`、`phase: BeforeRun \| AfterRun` 必填；`owner`、`script_name`（`""`）；`prefetch_paths: dict`（`{}`，值是路径字符串）；`prefetch_token: str?`；`round_started_at: ISO 字符串?`；`stop_requested`（false） | 终态 `outcome`、`notice`（更新失败也是 `ok: true`，照原口径只发通知）；事件 `log`、`point` | — | 三个专项 |
| `prefetch_start/_poll/_stop/_close` | 句柄 | `script_id`、`record` 必填；`owner`（`""`） | 终态 `outcome: downloaded` 带 `token` / 跳过；事件 `download` | `prefetch_failed` | 三个专项 |
| `prefetch_discard` | async | `token` 必填 | `{}` | — | 三个专项 |
| `discover_start/_poll/_stop/_close` | 句柄 | `script_id`、`record` 必填；`owner`（`""`） | 终态 `downloads: [{url, rid, content_hash, downloader}]` | `discover_failed` | 三个专项 `prefetch_check` |

### 9.5 托管记录 `record`

由共用库 `owner_entry.record_payload(uid, config, order=0)` 生成，项目更新在一处（`ManagedRecord` 的构造辅助）还原，`imported_at` 用 `datetime.fromisoformat` 转回：

`uid` 必填；`kind`（`""`，配置类名去掉 `Config`）；`order`（0）；`name: str?`；`source_path: str?`；`report: str | dict | null`；`source_version: str?`；`imported_at: ISO 字符串?`；`follow_source`（false）；`channel: str?`；`update_source: str?`；`auto_update_mode: str?`；`package_mode: str?`；`proxy_address: str?`（机密）；`mirror_cdk: str?`（机密）；`running`（false）。

### 9.6 属主服务 `maafw.owner.<专项插件 id>.v1.*`（每个专项 8 个，专项提供、项目更新消费）

共用库 `owner_provides(plugin_id)` 生成 `provides_services` 那 8 项，`OwnerServiceMixin` 把它们接到 `ConfigOwner` 上；专项在 `on_enable` 里经 `owner_register(name, prefix)` 登记，前缀是 `maafw.owner.<专项插件 id>.v1`。没有 `contract.py`，请求按键取。

| 操作 | 种类 | 请求 | 出参 |
| --- | --- | --- | --- |
| `list` | 同步 | `{}` | `ready`、`items: [record]` |
| `read` | 同步 | `script_id` | `status: mine \| not_mine \| missing \| invalid_id`、`record`、`detail` |
| `check_source_path` | 同步 | `script_id`、`path` | `status: ok \| cleared \| error`、`detail` |
| `plan_rules` | 同步 | `{}` | `rules`（`MaaFWPlanRules.to_dict()`，解析库 `from_dict` 还原） |
| `project_mismatch` | 同步 | `project_root` | `message: str?` |
| `lock` | async | `script_id` | `ticket: str?`（拿不到锁或不归本属主时 null） |
| `unlock` | async | `script_id`、`ticket` | `{}` |
| `write` | async | `script_id`、`patch`（键见下，键不在 = 不写）、`ticket?` | 成功 `{ok: true, reason: "", detail: ""}`；没写成 `{ok: false, reason: not_found \| rejected, detail, code, message}` |

`patch` 认的键：`source_path`、`report`、`source_version`、`imported_at`、`channel`。专项写自己的托管时不经服务，直接用 `write_or_raise(owner, …, holds_lock=…)`；`holds_lock` 只是 Python 参数，经属主服务进来的写回用不了它。

## 10. 与实施方案 §2–§3 的差异（以代码为准）

1. agent 环境 `borrow_start` 多一个可选字段 `agent_env_root`（方案的入参摘要里没有）。
2. 运行 `pretask_exit_watch_start`：`account` 可为 null（没开过账号时当场确认）；多一个可选字段 `after_scope`（共用库交回预约时带 true）。
3. 运行 `desktop_launch_start` / `desktop_quit_start` 多两个可选字段 `controller_name`、`interface_loaded`。interface 加载了却没找到控制器时：`desktop_launch` 在原来那一步报「未找到 controller」，回 `desktop_launch_failed`；`desktop_quit` 不失败——`mode: final` 收尾时找控制器的异常被接住（`desktop_game.py` 的 `close_after_run` 与 `_attached_game_window_pids`），只在后端日志记一条 warning（桌面分身那一路另在运行日志写一行「关闭游戏失败」，这次收尾也不再关游戏 / 启动器 exe），结果是 `{"ok": true, "closed": null, …}`；`mode: retry` 不看控制器。`desktop_quit_start.controller` 可省；两族都可能回 `unknown_account`、`account_busy`（方案只给 launch 列了）。
4. 项目 `open_start`、项目更新 `update_start` 多一个可选字段 `round_started_at`（ISO 字符串，提供方还原成秒数）。
5. 方案 §2.2 写「时刻一律 ISO 8601 字符串」；代码里 `account_open.run_started_at`、`plan_start.game_started_at`、`plan_start.task_deadlines`、`finish_start.round_started_at`、`device_adb_config.emulator_process.process_started_at` 是数字（§2）。
6. 属主 `plan_rules` 的出参是 `{"ok": true, "rules": {...}}`，规则字典放在 `rules` 里，不是铺在顶层。
7. `_stop` 的 `reason`：项目这一侧的契约只收 `cancelled` / `stop_requested` / null（`prefetch`、`discover`、`repair` 的 `_stop` 也按这个校验），运行与 agent 环境收任意字符串。
8. `_poll` 的 `wait` 在提供方缺省为 0（不等），调用方缺省传 1.0；方案只写了取值范围。
9. 项目 `confirm_start`、`finish_start`、项目更新 `update_start`、`prefetch_start`、`discover_start` 的 `owner` 是可选（缺省 `""`）；`open_start`、`script_cloned_start`、`script_removed_start` 的 `owner` 必填。
10. 运行多两个兜底失败 code，方案没列：`device_adb_config`、`device_win32_config` 的其余异常回 `device_config_failed`，`pretask_rerun_check` 的其余异常回 `rerun_check_failed`。
