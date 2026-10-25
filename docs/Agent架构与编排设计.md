# Embedded Engineer Agent：架构、构建与编排

更新：2026-10-18。依据当前源码整理；图中绿色为已实现模块，蓝色为外部模型服务，黄色与虚线为待接入或当前项目未执行部分。

当前不是多模型 Agent 集群。“训练”指诊断反馈、测试用例与修复流程完善，没有训练模型权重。

## 1. 总体架构图

模型负责提出动作；控制器负责约束；工具提供真实执行结果。当前是单模型驱动的本地工程系统。

```mermaid
flowchart TD
  user["用户<br/>需求、确认、模型配置"]
  web["本地工作台<br/>web/app.js"]
  api["HTTP API · 8765<br/>server.py"]
  auto["自动运行器<br/>AutonomousRunner"]
  model["决策与上下文整理<br/>ModelDecider / model_context"]
  budget["共享预算与密钥保护<br/>BudgetModel / DPAPI"]
  deepseek["外部 DeepSeek API<br/>结构化动作与代码补丁"]
  ctrl["决策控制器<br/>契约、版本、依赖、权限"]
  runs["运行与回执存储<br/>runtime/control-runs"]
  service["工程业务服务<br/>EngineeringService"]
  evidence["资料与参数证据<br/>文档、原文、页码、未知项"]
  artifacts["方案与工程产物<br/>接口、连接图、C/H 草案"]
  tools["受控工具适配器<br/>编译、测试、诊断、回归"]
  store["项目、源码与验证结果<br/>本地 JSON / 隔离工作目录"]
  user --> web
  web --> api
  api --> auto
  auto --> model
  model --> budget
  budget --> deepseek
  auto --> ctrl
  ctrl --> runs
  ctrl --> service
  service --> evidence
  service --> artifacts
  service --> tools
  artifacts --> store
```

箭头表示主要调用方向；模型响应和工具回执沿调用链返回。密钥不进入项目文件或浏览器返回值。

## 2. 决策与任务编排图

每一步依据当前项目与真实回执推进；没有新输入时不会通过反复调用模型解除暂停。

```mermaid
flowchart TD
  start["用户启动自动推进"]
  read["读取项目与运行上下文<br/>需求、计划、近期结果"]
  gate["检查运行前置条件<br/>确认、状态、重复动作、额度"]
  pause["暂停并说明原因<br/>等待回答或明确恢复"]
  decide["模型选择下一步<br/>动作 / 多步计划 / 暂停"]
  validate["契约与执行资格校验<br/>JSON、版本、ready 任务"]
  feedback["结构化错误反馈<br/>字段、失败参数、规则"]
  exec["保存待执行动作并执行<br/>pending → executing"]
  receipt["持久化真实回执<br/>更新任务、项目与修复次数"]
  next["仍有待办或可修复失败<br/>重新读取上下文"]
  finish["交付已完成<br/>结束本轮"]
  start --> read
  read --> gate
  gate --> pause
  gate --> decide
  decide --> validate
  validate --> feedback
  validate --> exec
  exec --> receipt
  receipt --> next
  receipt --> finish
```

左侧错误反馈和底部待办均可回到“读取上下文”，前提是预算与重试次数允许。用户确认和未知费用暂停不会由模型自行解除。

## 3. 工程产物构建与验证图

把工程草案、对象编译、主机行为测试、完整链接和实物验收分开记录。

```mermaid
flowchart TD
  req["需求与验收条件"]
  design["证据、候选方案与功耗<br/>用户确认条件式方案"]
  interface["接口表<br/>interfaces"]
  circuit["连接数据与 SVG 图<br/>circuit"]
  firmware["生产源码与原测试<br/>firmware"]
  verify["draft_verify<br/>绑定当前源码哈希"]
  arm["ARMCC Cortex-M0+<br/>目标文件编译"]
  host["MSVC 主机行为测试<br/>原测试 + 冻结扩展用例"]
  result["汇总真实验证结果<br/>失败修复，通过才可交付"]
  zip["交付 ZIP<br/>源码、图纸、清单、报告"]
  link["当前项目后续：完整链接<br/>启动文件、驱动、内存布局"]
  board["当前项目后续：实物验证<br/>烧录、接线、电气与功能"]
  req --> design
  design --> interface
  interface --> circuit
  circuit --> firmware
  firmware --> verify
  verify --> arm
  verify --> host
  arm --> result
  host --> result
  result --> zip
  zip -.-> link
  link -.-> board
```

连接图是工程草案，不是可生产 PCB。当前机器人完成的是对象编译与 mock 测试；完整固件链接、烧录和硬件验收未执行。

## 4. 诊断与定向修复图

工作台已接入定向修复与冻结扩展测试；独立脚本保留用于诊断演练。

```mermaid
flowchart TD
  failure["真实失败与当前源码<br/>编译日志、断言、文件哈希"]
  trace["隔离诊断重放（可用时）<br/>实际标量、调用与分支记录"]
  focus["工作台定向修复<br/>focused_repair.py"]
  web["工作台自动推进<br/>失败后切换定向修复"]
  tests["冻结的原测试与额外用例<br/>补充测试只在隔离目录组合"]
  model["共享预算 → DeepSeek<br/>模型生成最小补丁"]
  patch["控制器 + draft_patch<br/>哈希及唯一原文校验"]
  original["原测试与 MCU 编译<br/>原测试不可删改"]
  rollback["回归保护<br/>证据可比较时恢复检查点"]
  extra["额外冻结边界测试<br/>独立报告与用例哈希"]
  deliver["原测试及扩展测试均通过<br/>服务端才允许交付打包"]
  failure --> trace
  failure --> focus
  web --> focus
  trace --> tests
  tests --> model
  focus --> model
  model --> patch
  patch --> original
  original --> rollback
  original --> extra
  extra --> deliver
```

失败回馈下一轮模型修复。诊断重放不是原测试结果；回归恢复不是对任意改动的无条件保证。已关联测试集的源码哈希及测试集哈希均通过后，服务端 execute 才允许交付。

## 5. 费用与上下文控制图

按人民币预算控制，缓存输入、非缓存输入和输出分别计费，不换算成固定 token 数。

```mermaid
flowchart TD
  state["当前必要状态<br/>保留需求、源码和近期结果"]
  compact["确定性整理上下文<br/>稳定前缀 + 动态数据"]
  size["检查测试期 200KB 上限<br/>超限不发出请求"]
  reserve["SQLite 原子预留费用<br/>每日上限 ¥10"]
  request["DeepSeek API 请求"]
  usage["收到可信 token 用量<br/>按实际分类结算"]
  unknown["连接失败或费用不确定<br/>保留预留金额并暂停"]
  next["下一次请求重新检查预算"]
  confirm["用户确认保留预留费用<br/>恢复后续新请求"]
  state --> compact
  compact --> size
  size --> reserve
  reserve --> request
  request --> usage
  request --> unknown
  usage --> next
  unknown --> confirm
```

恢复不重放失败请求、不退还未知费用预留。缓存前缀只提高命中机会；实际命中以 API 用量为准。本地限额不涵盖同一密钥在其他客户端的花费。

## 6. 本地部署与数据分布图

当前运行路径是 Windows 本地服务；Docker 和 AgentArts 托管不在本轮工作路径中。

```mermaid
flowchart TD
  browser["浏览器工作台<br/>127.0.0.1:8765"]
  scripts["离线检查与定向修复<br/>tools/"]
  server["Python 本地 HTTP 服务<br/>工程服务与控制器"]
  compile["本机 ARMCC / MSVC<br/>隔离构建目录"]
  data["项目 / 运行 / 报告<br/>runtime/ 与本地资料库"]
  ledger["共享模型配置与费用账本<br/>DPAPI + SQLite"]
  cloud["外部 DeepSeek HTTPS API<br/>启用、授权及预算内调用"]
  hardware["开发板与实物器件<br/>当前项目未验证"]
  browser --> server
  scripts --> server
  server --> compile
  server --> data
  server --> ledger
  ledger --> cloud
  compile -.-> hardware
```

文件存储适合当前本地单进程场景，不代表多用户事务或云平台部署。联网搜索和实时报价不能因存在接口模块就视为已接入。

## 模块与实际入口

| 职责 | 实现 |
|---|---|
| 工作台、HTTP、进度 | `src/embedded_agent/server.py`、`src/embedded_agent/web/app.js` |
| 普通自动决策 | `autonomy.py`、`decision_protocol.py`、`model_context.py` |
| 控制、计划、契约和限制 | `control.py`、`planning.py`、`contracts.py`、`runtime_policy.py` |
| 工程业务和工具注册 | `service.py`、`application.py`、`adapters.py` |
| 资料、方案、参数、功耗 | `library.py`、`design.py`、`selection.py`、`power.py` |
| 草案、验证、诊断、回归 | `draft.py`、`draft_verification.py`、`assertion_diagnostics.py`、`repair_coach.py`、`draft_regression.py` |
| 额外测试隔离组合 | `supplemental_tests.py` |
| 本地模型与共享预算 | `local_model.py` |
| 项目存储与交付判定 | `storage.py`、`readiness.py` |
| 独立定向修复 | `tools/run_focused_repair.py` |
| 边界审计与离线回归 | `tools/check_robot_boundaries.py`、`tools/run_offline_curriculum.py` |

表内未写目录的 Python 文件均在 `src/embedded_agent/`。旧 `Workflow / StageAgent` 线性骨架保留，主要用于需求入口；其中阶段占位对象不等于当前工作台所有阶段的执行器。

## 当前验证范围

2026-10-17 的机器人版本已通过原始 mock 测试与新增八类边界用例，并通过 Cortex-M0+ 对象编译；源码、验证结果与交付包按哈希核对。该结果只针对该版本及已有用例，不证明任意工程都能独立完成。完整固件链接、实物验证、电气审查保持未执行。

已验证交付记录：`runtime/focused-repair/20261017-220108/verified-summary.json`。边界审计：`runtime/boundary-audit/20261017-220353/report.json`。不把这些历史记录称为对后续版本的持续有效认证。

## 已有步骤的下一步完善

1. 已接入工作台：失败时定向生成单文件补丁，复测、打包与结束由程序确定性调度。
2. 已接入服务端门禁：已关联冻结测试集的项目必须同时通过原测试与扩展测试，旧报告不能解锁交付。
3. 统一主机编译日志编码，减少中文乱码。
4. 持续补充跨项目边界用例，验证恢复、费用限制与已通过行为。

2026-10-18 更新：上述两项接入已完成，已用离线替身流程和当前项目真实编译复测验证；不据此宣称模型通用独立能力。日志编码与跨项目覆盖继续完善。
