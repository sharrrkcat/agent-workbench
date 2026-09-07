# Agent Workbench 架构精简与重构路线图

> 状态：设计冻结，Phase 0、Phase 1、Phase 2a、Phase 2b、Phase 3 与 Phase 4 已完成（2026-09-07）
> 冻结日期：2026-09-04
> 用途：总路线图、进度检查表、后续 agent 的交接入口

## 0. 使用规则

这份文档把此前 Claude Code 对话中的产品边界、关键证据、最终决策和迁移顺序冻结下来。

- 「已冻结」内容不能在实现中被悄悄改回旧架构。
- 「待定」内容只能在对应阶段通过实现验证后调整，并在本文件的变更记录中说明原因。
- 每个实施轮次只推进一个可验收切片；完成后勾选清单并记录测试、迁移和遗留项。
- 发现代码与路线图冲突时，先做只读影响扫描并记录冲突，不要为通过局部测试重新引入已删除的概念。

本文件与 `docs/contracts/` 一起描述当前实现和后续方向；已删除扩展的历史 task card 不再作为执行依据。

## 1. 产品方向与边界

### 1.1 两个核心目标（已冻结）

1. **本地模型服务与分发**
   - 用户在应用内维护自己的本地模型 provider、模型文件和运行时。
   - 对外提供 OpenAI 兼容的 localhost 服务。
   - 内部对话与对外 API 使用同一个进程内模型抽象、错误模型和生命周期管理，不通过应用自身的 HTTP 回环复制逻辑。

2. **普通对话 + 可选的轻量 harness**
   - 默认体验是普通对话，服务于角色扮演、日常聊天、Core Memory、Worldbook 和精简后的 Knowledge/RAG。
   - 用户可以在 persona 或 session 上开启 harness，让模型在受控范围内调用工具。
   - 用户也能直接调用同一批工具；工具不是仅对模型隐藏的内部能力。

### 1.2 明确非目标（已冻结）

- 不是 Claude Code Desktop，也不是自主编程代理或长时间后台 agent。
- 不保留现有 Agent type、Action 和 YAML manifest 行为模型。
- 不保留手写 Capability/Command/插件注册体系。
- 不引入模型驱动的 Intent Routing、safe-intent 白名单或多层「裁判」。
- 本轮不下载模型文件；模型继续由用户手动放入 data/models。
- 对外 API 暂维持单 key、localhost；不扩展多用户、租户权限、局域网绑定或远程配额。
- 本轮不实现 ComfyUI 工具，也不保留内部 diffusers 图像生成。

### 1.3 体验原则

- 没有工具时，聊天路径短、可预测、可调试。
- harness 必须显式开启；工具名称、参数、结果、审批和失败状态可见。
- 工具结果进入历史时是数据，不是新的 system/developer 指令。
- 普通模型输出按纯文本处理；只有经过 schema 校验的 tool call 才具有控制意义。
- provider、runtime 或模型不可用时返回结构化、可行动的错误。

## 2. 已冻结的决策台账

| 主题 | 最终决定 | 实施约束 |
|---|---|---|
| Agent 形态 | 只保留 prompt persona，直接存数据库 | 不再有 script/prompt 类型、agent.yaml、manifest loader 或 AgentConfig 双层覆盖 |
| Persona 字段 | 名称、头像、system prompt、model profile、context policy、生成参数、harness 开关、工具白名单、Knowledge/Worldbook 默认绑定 | 不增加 translate formal/casual 一类快捷提示词 |
| 多角色 | 保留 | 同一 session 可绑定多个 persona；保留 speaker 信息和 group transcript |
| Capability/Command | 完全移除 | 用内置 Tool Registry 取代，不读取 capability manifest，不提供自定义插件目录 |
| 用户直接调用工具 | 保留 | 与模型调用共用 registry；目标入口为 /tool-name args，具体参数语法在 harness 阶段定稿 |
| Intent Routing | 完全移除 | 删除 semantic router、route test、safe-intent 和 pet_command 分支 |
| Utility LLM | 保留但降级 | 只有一个辅助模型设置，服务标题和 harness 内必要的小任务；纳入统一 Model Manager |
| 对外 API | 单 key + localhost | 只补齐当前服务能力，不做多 key、非 localhost、租户或配额体系 |
| Model Profile | 统一成一张表、一套 store、一组 CRUD | kind 至少包括 llm、embedding、reranker、image_embedding、vision |
| Reranker | 一等模型种类保留 | RAG 后置 rerank 保留；公共 /v1/rerank 延后，不删除核心抽象 |
| Knowledge/RAG | 精简而非删除 | 保留 KB、来源、分块、向量/FTS 混合检索、session 绑定、自动注入和 knowledge_search |
| 运行时安装 | 受管 worker 进程 | 不在 API 主进程 venv 内覆盖重型依赖；由应用监管安装、启动、停止和健康检查 |
| LLM 本地后端 | llama-server 二进制优先 | 替代 llama-cpp-python 和 Python 内嵌 internal_llama_cpp |
| Python 推理 | 独立 worker venv | CLIP、SigLIP2、DINOv2、Florence2、WD14 和 transformers embedding 放入 worker |
| 模型下载 | 本轮不做 | runtime 安装基础设施可为未来复用，但当前模型只能手动管理 |
| ComfyUI | 当前全部移除 | 未来若需要，从零作为工具重做，不冻结旧 capability/agent |
| 内部 diffusers | 移除 | 删除 image generation runtime、表、路由、设置、agent、capability 和 extra |
| Pet | 保留前端表现，剥离 capability | 设置放 app settings JSON；保留 overlay、sprite、宠物包和独立宠物 API |
| Pet 联动 | 与对话状态继续联动 | run step 使用稳定 kind；WAITING_FOR_USER 显示等待确认 |
| 数据库迁移 | 引入 Alembic | Phase 0 建 baseline；后续 schema 变化走迁移，测试阶段允许直接删表/删列 |
| API 与内部调用 | 共享 core/models | 外部路由和 ChatRunner 共用 adapter、ModelManager、错误和观测 |
| 测试阶段约束 | 无用户、无用户数据，允许服务长时间停用 | 不做保活、用户数据迁移、兼容、legacy、旧配置 fallback、双写或用户习惯适配；后续阶段不改变 |
| 外部连接协议 | 仅 OpenAI Compatible | 不增加品牌专属分支；不支持的操作返回明确错误 |
| 模型释放和标题 | 默认 manual；标题只用显式辅助模型 | 未配置或调用失败保持原标题，不借用主聊天模型 |

### 2.1 两轮决策的覆盖关系

对话中有两轮用户补充，后一轮覆盖了前一轮答复中的临时方案：

| 轮次 | 用户决定/讨论 | 最终采用方式 |
|---|---|---|
| 第一轮补充 | ComfyUI 可以保留，之后单独一轮纳入工具；diffusers 删除；群聊保留；API 先维持单 key + localhost；RAG 按精简范围；Pet 保留前端联动；Intent 删除、工具 LLM 保留；本轮只读 | 除 ComfyUI 外均继续有效；ComfyUI 的处置由第二轮改写 |
| 第一轮答复中的临时解释 | 曾考虑把 ComfyUI 冻结到未来工具化阶段，并建议从 RAG 移除 reranker | 不是最终基线，不得照此实施 |
| 第二轮补充 | runtime 指模型运行环境而不是模型文件下载；建议受管 worker、llama-server；模型继续手动放入；Pet 设置进 app settings；ComfyUI 不冻结而是全部移除；担心 reranker 将来重做 | 这是当前冻结基线 |
| 第二轮答复后的结论 | 统一 profile kind 保留 reranker；RAG 后置 rerank 保留；只 defer 公共 /v1/rerank；ComfyUI 将来从零做工具 | 采用此结论 |

因此，后续任务必须以「ComfyUI 当前删除、reranker 核心保留、模型不下载」为准，不能引用第一轮的冻结 ComfyUI 或删除 reranker 版本。

## 3. 当前基线与重构原因

以下是只读调研得到的基线数字，表示旧系统规模，不是目标规模。

| 维度 | 当前情况 |
|---|---|
| 后端 | ai_workbench 约 40.5k 行；capabilities 约 4.2k 行；agents 约 1.9k 行 |
| 前端 | TypeScript 约 27.2k 行；types.ts 约 2,045 行；store 约 1,661 行 |
| 测试 | 约 1,466 个测试；tests 约 33.4k 行 |
| API | 约 173 个 HTTP 路由和 1 条 WebSocket |
| SQLite | 27 张表；create_all + schema_version 守卫；没有 Alembic |
| 设置 | AppSettings 约 182 个字段，其中约 35 个属于 Web Context |
| 文档 | 约 35 个 markdown，contract 体系含大量历史约束和重复说明 |
| 旧快照 | dist/ 是约 38.9k 行的旧整包快照，已被 gitignore |

### 3.1 结构性问题

1. **模型配置有三代并存。**
   resolve_llm_config 同时叠加 manifest、环境变量、llm capability config、全局 profile、agent 旧式 model 块、AgentConfig、session 和生成参数。chat 的旧 model 块在全局默认 profile 之后覆盖设置页选择，文档和测试都没有完整表达这一陷阱。

2. **Profile CRUD 重复。**
   LLM、Embedding、Reranker、Multimodal Embedding、Vision、Image Generation 各有表、store、路由和设置面板；Embedding 由 Knowledge 路由拥有，却还承担对外 embeddings 服务。

3. **旧原则催生替代塔。**
   Intent Routing、Utility LLM、Web Context 的 Plan/Judge/Gate 和 Script Agent 的 JSON 模式，都是没有 function calling 时的补偿机制。目标架构应直接使用标准 tool_calls。

4. **Prompt Agent 主路径过长。**
   runner.py 的 _run_prompt_agent 约 420 行，串接 context、memory、worldbook、knowledge、web、文件、视觉、标题和 LLM；新增注入源需要同时修改 runner、metadata、消息渲染和文档。

5. **模型生命周期分散。**
   runtime、inference、image generation、utility LLM 和 capability ctx 各有卸载入口，没有统一的 load/unload、空闲超时、并发和崩溃恢复。

6. **对外推理契约不完整。**
   /v1/chat/completions 当前拒绝 stream，不支持 tools、视觉输入和 response_format；内部 provider 也没有统一流式能力。现有 /v1 guard、鉴权、限制和观测可以复用。

7. **前端和文档耦合过重。**
   MessageBubble、KnowledgeSettingsPanel、SettingsDetailPanel、LlmSettingsPanel 等组件过大；设置、i18n、contract 和注册表都围绕即将移除的 capability/agent 概念。

8. **已知卫生风险。**
   stateless inference skeleton 测试会向真实 data/models/embeddings 写入 a2-embed-* 桩目录；dist/ 是过期快照；SQLite 没有迁移；secret 仍明文保存。

### 3.2 应直接复用的资产

- sessions、messages、runs、run steps、EventBus 和 WebSocket 流式事件。
- Message Parts v2、附件和视觉输入的持久化/渲染骨架。
- ContextBuilder 的 context policy、selected/recent/session 和 group_transcript 投影。
- Core Memory、Worldbook 和精简后的 Knowledge/RAG。
- Provider Profile、provider status/inventory/runtime resources 和 /v1 的 guard。
- WAITING_FOR_USER、session waiting_run_id 和取消注册表，可直接成为工具审批/恢复基础。

## 4. 目标架构

总体边界：

    frontend
      ├─ Chat / Personas / Models / Knowledge / Worldbook / Tools / App Settings
      └─ REST + WebSocket
             │
    api
      ├─ /v1/*              OpenAI 兼容服务（localhost、单 key）
      ├─ /api/models/*      provider、统一 profile、状态、安装和生命周期
      ├─ /api/chat/*        session、persona、消息、run
      └─ /api/tools/*       工具列表、直接调用、审批/恢复
             │
    core
      ├─ models/            ProviderAdapter + ModelManager + ModelProfileStore
      ├─ chat/              PersonaStore + ContextBuilder + ChatRunner
      ├─ harness/           ToolRegistry + AgentLoop + ApprovalGate + builtin tools
      ├─ knowledge/         indexing + hybrid retrieval + optional rerank
      └─ runs/              lifecycle + events + streaming

### 4.1 models 层

ProviderAdapter 是唯一的 provider 调用接口，至少统一：

- chat completion 的非流式和流式调用。
- tools/tool_calls 能力声明与请求透传。
- 支持 provider 的 vision 输入。
- embeddings 和内部 rerank。
- load、unload、health、usage metadata。

统一 ModelProfile 建议包含：

- id、name、kind、provider_profile_id、model_ref/model_id。
- capabilities（streaming、tools、vision、embedding、rerank 等）。
- generation/runtime params、enabled、external_enabled。
- lifecycle policy 和可选 worker variant。

配置优先级压缩为 session 覆盖 > 全局默认；不读取扩展配置或 manifest。

ModelManager 是唯一生命周期入口。外部 base_url provider 的 load 可以是健康检查；受管 provider 的 load 是启动或唤醒进程。unload、空闲超时、并发队列、错误和事件均由它统一发出。

### 4.2 受管 runtime

运行时和 API 主进程隔离，避免 Windows DLL 占用、CUDA 上下文污染以及 uv sync 覆盖手工安装包。

- llama.cpp：下载并校验官方 llama-server release 到 data/runtimes/llama-server/<version>/，按 CPU/CUDA/Vulkan 变体启动，再由 OpenAI 兼容 adapter 接管。
- Python worker：在 data/runtimes/py/<variant>/ 建独立 venv，至少考虑 torch-cpu、torch-cu128，按需叠加 onnx-gpu。
- worker 只暴露本机 health、load、unload、embed、vision 等窄 RPC；模型文件仍由用户手动放入 data/models。
- 安装任务用 asyncio 子进程逐行读取进度；同一时间只允许一个任务，支持取消、重试、日志和幂等重跑。
- 安装前停止相关 worker，应用退出时清理子进程；崩溃进入可诊断的 failed 状态。
- uv 由应用依赖提供，从应用 venv 的 Scripts 目录调用，不依赖用户 PATH。
- PyPI、PyTorch index、GitHub release proxy 等只服务 runtime 下载设置；本轮不加入 HF/ModelScope 模型下载。

建议统一错误码：RUNTIME_NOT_INSTALLED、RUNTIME_INSTALLING、RUNTIME_BROKEN、MODEL_NOT_FOUND、MODEL_BUSY、MODEL_UNAVAILABLE。

### 4.3 chat 与 Persona

Persona 是数据库记录，不是可执行插件。最小字段：

- id、name、avatar、system_prompt。
- model_profile_id、context_policy、generation params。
- harness_enabled、tools_allowed。
- 默认 Knowledge/Worldbook 绑定。

Session 保留标题、消息、等待中的 run 和上下文模式；群聊保留 speaker 与 transcript 语义。

普通聊天路径：

1. 读取 session/persona 配置。
2. ContextBuilder 根据 policy 选择消息，并注入 memory、worldbook、knowledge 和附件。
3. ChatRunner 调用 core/models。
4. delta、run step、最终 message 和标题状态通过现有 runs/events/WS 落库并发送。

`@...`、`@...:...`、`:...` 和未知 `/...` 均按普通文本处理；Phase 4 仅识别已注册的 `/tool_name args`。新 UI 不生成旧 command/action 调用。

### 4.4 harness 与工具

Tool Registry 是内置 Python 工具的显式注册表，不读取 capability.yaml，也不加载任意目录插件。每个 ToolSpec 至少包含 name、description、JSON Schema、handler、side_effect/risk 分类和是否允许直接调用。

最小 AgentLoop：

1. ChatRunner 发送带 tools 的请求。
2. Adapter 解析标准 tool_calls。
3. AgentLoop 校验工具名、参数、persona/session 白名单。
4. 需要确认的工具进入 WAITING_FOR_USER，保存 waiting_run_id，等待批准后继续。
5. 结果以 tool_call/tool_result part 和 run step 持久化，再回填模型上下文。
6. 循环受最大迭代数、取消和超时限制。

初始工具候选：

- read_file（受允许目录限制）。
- web_search。
- fetch_url。
- knowledge_search。
- base64 encode/decode 等无副作用小工具。

Web Context 的计划/裁判管线不再存在；web_search/fetch_url 是普通工具。ComfyUI、图像生成和 MCP 不属于本轮初始工具。未来若需要扩展，优先接标准 MCP client，而不是恢复 capability/plugin SDK。

用户直接调用工具也使用同一 registry，建议保留 /tool-name args 命名空间：

- 单字符串参数可直接传原文。
- 多参数工具接受 JSON，必要时再提供受限的 key=value 解析。
- 结果标记为工具数据，不能被当作 system/developer 指令。
- 工具错误、审批拒绝和取消都要有可渲染 part 与结构化 run 状态。

### 4.5 Knowledge/RAG

保留：

- Knowledge Base、source、chunk 和索引生命周期。
- 向量检索 + FTS/keyword 混合召回。
- session 绑定、自动上下文注入和 knowledge_search。
- embedding 与 reranker 使用统一 ModelProfile/ModelManager。
- RRF 合并后可选 rerank；没有 reranker 或失败时回退 RRF 顺序。

删除或后置：

- query expansion。
- 多套 markdown chunk profile。
- managed origins 扫描/导入的复杂两段式流程。
- 独立 reranker profile 表、store、设置面板和专属生命周期入口。
- 公共 /v1/rerank 本轮 defer；未来沿用统一鉴权、日志和模型白名单。

### 4.6 Pet

保留前端 overlay、sprite、宠物包格式、设置面板和 /api/pets/* 独立路由。设置落在 app settings JSON，不再从 capability_configs 读取。

删除 /pet 命令、pet capability、intent 的 pet_command、command_texts 以及解析聊天命令触发动作的旧路径；唤醒、收起和切换由设置面板直接操作。

RunStep 增加稳定 kind，例如 context、model、tool、approval、save。Pet 按 kind 查 i18n，不再硬匹配 Resolving agent 或 Starting script。PENDING/RUNNING、WAITING_FOR_USER、DONE、FAILED/CANCELLED/INTERRUPTED 都要有稳定表现；WAITING_FOR_USER 显示等待用户确认。设置和宠物列表由定时轮询改为初始化加载、变更时刷新。

## 5. 分阶段迁移计划

阶段以可验收切片推进，中间状态允许服务长时间停用，不需要保活。项目始终按测试阶段、无用户、无用户数据处理；不考虑用户习惯，不做用户数据迁移或兼容。明确遗弃的方法和结构必须直接删除，禁止 legacy、旧配置 fallback、兼容转发和双写。这些约束在后续阶段不会改变。破坏性阶段不承诺数据库回滚，测试库可重建。

### Phase 0：冻结、卫生和数据库基线

目标：建立安全边界和迁移工具，不改变用户可见行为。

- [x] 将本路线图作为重构任务的 read-first 文档。
- [x] 确认 dist/ 不是用户数据后删除或移出。
- [x] 修复 stateless inference skeleton 的真实 data 目录泄漏，桩模型全部使用临时根目录。
- [x] 引入 Alembic，为当前 27 张表生成可复现 baseline。
- [x] 明确 data/models、data/runtimes、附件和日志目录的所有权与备份策略。
- [x] 冻结新增 capability、script agent、intent、image generation 功能。

验收：

- 空数据库可以从 baseline 建成当前 schema。
- 备份副本可升级且不丢 session、message、knowledge、worldbook。
- 测试不再写入仓库真实模型目录。
- 本阶段没有 API 或用户工作流变化。

### Phase 1：减法，拆除旧扩展塔

目标：让普通聊天主路径变短，删除不再符合方向的代码。

- [x] 删除 Intent Routing 全链路、设置、路由、前端测试页和 metadata。
- [x] 删除 Capability/Command registry、CapabilityConfig、CommandRunner、manifest commands 和自定义插件入口。
- [x] 删除 core/script.py、Script Agent SDK、特定 script agents 及测试。
- [x] 删除 Web Context 管线、Plan/Judge/Gate、对应设置和前端控制；保留未来工具所需的最小网络安全边界。
- [x] 删除 ComfyUI capability、agent、preset/workflow 旧入口；未来工具从零实现。
- [x] 删除内部 diffusers/image generation runtime、表、路由、设置、agent、capability 和 extra。
- [x] 删除 forms/action-form、旧 command-buttons part 和相关 UI。
- [x] 让 Pet 脱离 capability runtime，保留前端和独立宠物 API。
- [x] 把 Utility LLM 收敛为辅助模型设置和内部接口，不保留 intent 专用路由。
- [x] 保留 reranker 核心，但删除独立 reranker profile 栈和旧专属设置。

验收：

- 应用可进行普通聊天、群聊、memory/worldbook 和精简 Knowledge。
- /pet、旧 command、旧 action 和 script agent 不再由新 UI 暴露。
- 删除模块没有通过隐式 import 或兼容分支继续参与主路径。
- tests、contracts、i18n 和生成文档同步收敛。

### Phase 2a：统一模型层与对外服务

目标：先统一调用面，再接 runtime。

- [x] 定义 ProviderAdapter 接口、能力声明和错误模型。
- [x] 建立统一 model_profiles 表、store、schema 和按 kind 过滤的 API。
- [x] 重建整个 SQLite 测试库，删除旧 profile 表，以统一表承载五种 kind；不迁入旧记录，不删除模型、附件等文件目录。
- [x] 实现 ModelManager 的 load/unload/health、并发和空闲策略。
- [x] 将内部 ChatRunner 和 /v1 路由切到同一 core/models。
- [x] 为 /v1/chat/completions 增加 streaming、tools、vision input、response_format 的兼容请求/响应。
- [x] 保持单 key + localhost guard、请求大小限制和观测日志。
- [x] 将 embedding、内部 rerank 和标题辅助模型纳入统一生命周期。
- [x] 清理旧环境变量和扩展配置的最终解析依赖。

验收：

- 同一 ModelProfile 在内部聊天和 /v1 中得到一致的 provider、模型和生命周期行为。
- stream=false、stream=true 和支持 provider 的 tool_calls 均有测试。
- 不支持的能力返回明确错误，不静默切换到错误模型。
- 旧六套 profile 路由不再被新前端调用。

### Phase 2b：受管 runtime 与安装任务

目标：用户能在网页中安装和管理运行环境，而不污染 API 主进程。

- [x] 建立 runtime catalog、版本/变体校验和安装状态模型。
- [x] 实现 llama-server 下载、校验、启动、健康检查、停止和日志收集。
- [x] 实现 Python worker venv 的 uv 创建、固定 requirements 安装和 worker RPC。
- [x] 将 CLIP、SigLIP2、DINOv2、Florence2、WD14、transformers embedding 迁入 worker。
- [x] 安装任务支持进度事件、取消、重试、单任务互斥和失败日志。
- [x] Provider/Model 设置显示未安装、安装中、就绪、损坏和版本。
- [x] 缺失 runtime 统一返回 RUNTIME_NOT_INSTALLED，并提供可执行安装动作。
- [x] 安装/卸载与 ModelManager 串联；应用退出清理受管子进程。

验收：

- 用户不需要手动执行 uv 操作即可安装受支持 runtime。
- 安装变体不会替换应用主 venv 的 CUDA/CPU 依赖。
- worker 崩溃、取消、重启和卸载都有可观测状态。
- 本阶段仍不下载模型文件。

### Phase 3：Persona 与群聊数据库化

目标：让对话对象从 YAML agent 变成可编辑数据。

- [x] 新增 personas 表及 Alembic 迁移。
- [x] 将 chat/translate 的必要初始内容转为默认 persona seed，不再读取 agent.yaml。
- [x] 将 session 关联扩展为 persona 语义（不保留旧字段）。
- [x] 为多角色 session 增加 session-persona 关联、当前 speaker 和 group transcript 配置。
- [x] 将 model/context/params/harness/tools/knowledge/worldbook 绑定落到 persona/session。
- [x] 删除 AgentRegistry、AgentConfig 双层覆盖、manifest viewer 和 agent YAML 依赖。
- [x] 前端 Agents 页改为 Persona 编辑器，不显示 Agent type、Action 或 capability 列表。
- [x] 明确普通前缀文本的稳定行为；新 UI 只生成普通文本和未来 `/tool`。

验收：

- 删除或改名 agent.yaml 后，已有 persona、session 和历史消息仍可工作。
- 普通对话不需要 action/default action 概念。
- 群聊 speaker metadata、上下文投影和 UI 回归测试通过。

### Phase 4：轻量 harness 与直接工具调用

目标：在普通聊天稳定后加入可控、可见、可取消的工具循环。

- [x] 建立 ToolSpec、ToolRegistry、schema 校验和 allowlist。
- [x] 实现 AgentLoop 的最大迭代、超时、取消、错误回填和 tool_calls 流式处理。
- [x] 增加 tool_call、tool_result message parts 和前端 renderer。
- [x] 复用 WAITING_FOR_USER/waiting_run_id 实现 ApprovalGate 和恢复。
- [x] 实现 read_file、web_search、fetch_url、knowledge_search 和无副作用 codec 工具。
- [x] 实现 /tool-name args 直接调用，结果持久化为 tool_result 数据。
- [x] 为副作用工具定义风险等级、确认文案、允许目录和网络限制。
- [x] 将 RunStep.kind 接入 Pet 和运行面板。
- [x] 为 provider 能力差异、拒绝、超时、审批和多轮循环补齐测试。

验收：

- harness 关闭时模型不会收到 tools，也不会进入循环。
- harness 开启时工具名称、参数、结果、审批和最终回答可追踪。
- 用户直接调用和模型调用共享 handler、权限、错误和持久化路径。
- 工具结果不会提升为 system/developer 指令。

### Phase 5：收尾与文档收敛

目标：消除新旧架构并存，形成可维护产品。

- [ ] 删除过期分支、旧表和孤立 imports。
- [ ] 将设置收敛为 Models、Chat/Persona、Knowledge、Worldbook、Harness、Pet 和 App 基础项。
- [ ] 拆分前端巨型组件及 types/store，保持行为不变。
- [ ] 将 contract 文档压缩为 models、chat/context、harness/tools、knowledge、runs/streaming、settings 等 5–6 个主题。
- [ ] 重写 README 的产品边界、runtime 安装和 API 示例。
- [ ] 运行 docs size、全量后端测试、前端测试和构建。
- [ ] 为未来 ComfyUI tool、/v1/rerank、图像服务、MCP 和模型下载各留短设计记录，但不提前实现。

## 6. 文件与模块去向

### 6.1 保留并复用

- ai_workbench/core/context.py
- ai_workbench/core/events.py
- ai_workbench/core/run_lifecycle.py
- ai_workbench/core/message_parts.py（移除旧 command/form 类型后扩展 tool 类型）
- ai_workbench/core/attachments.py
- ai_workbench/core/memory_context.py
- ai_workbench/core/worldbook.py、worldbook_context.py
- 精简后的 knowledge_*、retrieval.py、keyword_search.py、vector_store.py
- runtime_resources.py；模型状态与只读 inventory 已收敛至 core/models
- /v1 的鉴权、限制、模型列表、观测和请求 guard
- 前端 PetOverlay.tsx、PetSprite.tsx、PetSettingsPanel.tsx 和宠物包资源

### 6.2 重写或合并

- core/runner.py → ChatRunner + AgentLoop + run event 组合
- core/runtime.py → 简化输入、等待恢复和生命周期协调
- core/llm_config.py → 删除；session 覆盖 > 全局默认，两层选择直接调用 ModelManager
- db/models.py → Alembic 管理的统一 model_profiles、personas、session-persona、runtime jobs
- api/deps.py → 少量明确依赖，不再注入旧的 19 个服务
- settings.py、agent_settings.py、前端 Settings 面板/store/types → 新的模型、persona、harness 设置
- capabilities/llm 的 provider 逻辑 → core/models/adapters
- core/rerank.py 的 provider 分发 → adapter.rerank；保留 retrieval 的候选重排边界
- Pet API → 独立于 capability runtime 的小路由

### 6.3 计划删除

- core/script.py
- core/agent_registry.py 及 manifest loader 的 agent 执行依赖
- core/capability_registry.py、capability_runtime.py、command_registry.py
- core/intent_*.py
- core/web_context.py、web_prompts.py
- core/forms.py
- core/image_generation*
- capabilities/ 下的旧 capability/command 实现，包括 llm、pet、comfyui、image_generation、web_search 等目录
- agents/ 下的 YAML agent、script agent、ComfyUI agent 和 image generator agent
- 独立 reranker profile 表、store、设置和专属路由
- action-form、旧 command-buttons、pet_command 相关分支

Phase 1 已在测试数据库直接完成删除；后续删除仍须有对应 Alembic revision 和契约测试。

### 6.4 明确后置

- ComfyUI tool（从零设计）
- 公共 /v1/rerank
- /v1/images/generations 和真实图像模型服务
- MCP client（若工具扩展确有需要）
- HF/ModelScope 模型下载
- 多 key、非 localhost、用户/租户权限和配额

## 7. 数据库策略

1. Phase 0 为当前 schema 建 Alembic baseline；Phase 1 使用 `0002_phase1_prune` 直接删除不再需要的表和列。
2. 本项目处于测试阶段，没有用户和用户数据；所有阶段不复制、转换、双写或校验旧用户数据。Phase 2a 重建整个 SQLite 测试库（包括会话、设置、Knowledge、Worldbook、模型记录），空库 `upgrade head` 是主要启动验收。
3. 破坏性 revision 的 `downgrade()` 明确报错，不伪装成可恢复迁移；开发者可重建测试数据库。
4. 新写入只使用通用 message parts、run step kinds 和严格 schema；应用不读取已删除扩展配置。
5. 未来新增表或字段仍须通过 Alembic；模型文件、附件和日志目录不由迁移脚本递归删除。

## 8. API 与事件目标

### 8.1 外部 /v1

边界保持：

- 只监听 localhost。
- 使用单一 API key。
- 继续执行启用开关、请求大小、模型可见性和观测 guard。

逐步补齐：

- /v1/models
- /v1/chat/completions 的非流式和 SSE streaming
- tools/tool_calls
- vision message parts
- response_format 的受支持子集
- /v1/embeddings

公共 `/v1/rerank` 后置，未在 Phase 2a 开放；图像生成不属于当前实现。

### 8.2 内部 REST/WS

- /api/models/*：provider、model profile、inventory/status、runtime jobs、load/unload。
- /api/chat/*：personas、sessions、messages、runs、取消和 waiting resume。
- /api/tools/*：工具 catalog、直接调用、审批和结果查询。
- WS：run lifecycle、step、message delta/completed、tool call/result、approval 等事件。

内部调用不通过 /v1 HTTP 回环；两条入口只在 API 层分流，之后共用 core/models 和 runs。

## 9. 测试与质量门槛

每个阶段至少覆盖：

- 数据/迁移：空库 baseline、破坏性 prune、重复执行幂等和 schema 签名。
- 模型层：adapter 能力、配置优先级、load/unload、缺失 runtime 和错误映射。
- 聊天：普通文本、附件/视觉、memory/worldbook、Knowledge、群聊 transcript 和标题。
- harness：schema、allowlist、循环上限、取消、审批恢复、工具结果投影和直接调用。
- 流式：SSE/WS delta 合并、tool_calls 分片、失败和重连。
- 前端：persona、model/runtime 状态、tool parts、waiting 状态、Pet 联动和双语 i18n。

Phase 0 修复已知测试卫生问题后，才把全量 pytest 作为门槛。每轮总结必须写明改动文件、迁移、命令结果、API/设置/part/工作流是否变化，以及下一轮清理项。

## 10. 交接规则

接手任务的 agent：

1. 先读本文件，再按任务类型读 docs/ai/TASK_*.md 和对应 contract。
2. 找到当前 phase 和验收标准，不从旧 generated registry 推断新目标。
3. 先做只读影响扫描，列出 import、路由、表、前端入口和测试引用。
4. 用 Alembic 记录 schema 变化；Phase 1 测试阶段允许破坏性删表/删列，不复制或迁移用户数据。
5. 一次完成一个可验证切片，结束时更新清单、测试结果和决策记录。
6. 不重新引入 agent type、action、capability manifest、intent router、script SDK 或 ComfyUI 旧入口。
7. 新工具必须同时支持模型调用和用户直接调用，并共享 schema、权限、审批、错误和持久化路径。
8. 如需改变已冻结决策，先说明原因、替代方案和迁移影响，再更新本文件。

## 11. 尚未冻结的实现细节

这些问题不改变产品方向，需在对应阶段定稿：

- ModelProfile 参数与 capability 命名已在 Phase 2a 契约中冻结；Phase 2b 的 worker 参数、CPU 版本矩阵、动态回环端口、哈希来源和下载设置见 managed-runtime 契约。
- `/tool_name args` 已在 Phase 4 冻结为小写 snake_case；单一必填字符串保留原文，其余必须为 JSON 对象，不支持 key=value。见 harness-tools 契约。
- Phase 4 冻结每次文件/网络调用前审批、公网 HTTP(S)、三次重定向与 1 MiB 响应上限；文件只读 data/knowledge 和 data/attachments，见 harness-tools 契约。
- 群聊已在 Phase 3 冻结为手动选择当前 speaker、每条输入只生成一位 Persona 的回复，见 persona-chat 契约。
- 标题只使用显式选定的辅助模型；未配置或失败时保持标题不变（2026-09-05 已冻结）。
- 公共 rerank 请求格式在开放该端点时确定；Phase 2a 不增加品牌专属连接协议。

这些细节应通过小型 schema、契约测试和用户可见示例确定，不应扩大为插件生态或自动意图识别。

## 12. 当前进度快照

截至 2026-09-07：

- [x] 完成只读架构调研和问题证据整理。
- [x] 确认产品目标、减法范围、runtime worker 方向和 reranker 保留策略。
- [x] 确认 Pet 前端保留、app settings 存储和对话状态联动。
- [x] 确认 ComfyUI 与内部 diffusers 当前全部移除。
- [x] 确认模型文件继续由用户手动放入，不做模型下载。
- [x] 确认 Alembic baseline 纳入 Phase 0。
- [x] 新建本路线图文档。
- [x] Phase 0 实施：静态 Alembic baseline、旧库安全接管、测试隔离、数据目录文档和只读审计脚本已完成。
- [x] Phase 1 实施：单一路径 Chat、显式核心服务、破坏性 prune migration、前端与文档契约收敛。
- [x] Phase 2a 实施：统一 Models、ModelManager、外部协议、前端和测试库重建。
- [x] Phase 2b 受管 runtime 与安装任务。
- [x] Phase 3 Persona 数据化。
- [x] Phase 4 harness。
- [ ] Phase 5 文档和前端收尾。

Phase 0 建立迁移与卫生边界；Phase 1 完成旧扩展塔删除；Phase 2a 完成统一模型调用面；Phase 2b 完成受管 runtime 与安装任务。当前 API、设置和消息契约以 `docs/contracts/` 与代码为准，以下旧阶段记录只用于说明历史，不恢复旧兼容实现。

### Phase 4 收尾与验收记录（2026-09-07）

- 完成六个内置工具、严格 JSON/schema/allowlist、共享直接调用与模型循环。模型工具参数按 index 合并；重复调用 ID、能力缺失、模型拒绝、超时和取消产生明确错误。单次运行最多八个工具轮次，允许最后一次文本回答；30 秒工具超时与五分钟累计主动执行预算包含上下文构建，审批等待不占预算或模型 lease。
- 私有 HarnessState 保存有序剩余调用、原始 transcript、Persona/搜索服务配置、轮次及主动耗时。批准/拒绝后先完成原轮剩余调用；有效待审批状态可在重启后恢复。删除普通消息隐式恢复路径与 resume run kind；新消息/直接调用在审批期间被阻断，三种执行入口共享取消和结果持久化。
- 文件读取限制在允许目录，拒绝绝对路径、穿越、符号链接/junction 逃逸；DNS 校验结果绑定实际连接，逐跳校验重定向并限制流式读取。网络请求使用 identity encoding，拒绝压缩响应。参数/结果公开投影隐藏绝对路径与 URL 凭据，工具结果不会进入 system/developer 指令。
- 前端 ToolsPanel 接通 catalog、直接 JSON 调用、结果和 SearXNG 设置；RunPanel 展示具体审批参数、风险及批准/拒绝/取消操作。MessageBubble 以数据渲染工具 parts，Pet 使用稳定 kind 双语标签。重复/乱序事件、微秒时间戳、旧刷新及跨会话响应均有状态测试；删除“执行未启用”的旧 Persona 文案。
- 数据库：完成静态 `0006_phase4_tools`，重建 run kind 约束与私有 harness 状态，清理 disposable messages/run events/steps 和等待引用。实际库从 0005 升至 0006，integrity=ok、外键检查为空；迁移前后受保护目录内 **45,427** 个文件的路径、大小、mtime 一致，没有模型下载或目录删除。
- 主要后端文件：`core/harness/{agent_loop,registry,schema,builtins,network,settings}.py`、`core/{chat_runner,runtime,context,network_policy,json_data,message_parts,stores}.py`、`core/schema/{message,run}.py`、`api/routes/{tools,runs,messages}.py`、`db/{models,stores}.py`、`alembic/versions/0006_phase4_tools.py`。
- 主要前端文件：`types.ts`、`api/client.ts`、`store/{useWorkbenchStore,messageStream}.ts`、`components/{ChatInput,ChatView,MessageBubble,RunPanel,PetOverlay}.tsx`、`components/settings/{ToolsPanel,PersonasPanel}.tsx`、`components/personas/SessionSettingsDialog.tsx`、`styles.css`、中英文 `runs/settings/personas` locales。同步 README、AI_CONTEXT、runtime/data/task cards、harness/message/persona/settings/pet 契约与本路线图。
- 测试文件：新增 `tests/{tool_fixtures,test_phase4_tools,test_phase4_harness}.py`，更新 Phase 1/3 契约测试；新增 `frontend/scripts/test-harness.mjs` 并接入 package.json，更新 Phase 1 frontend contracts。
- 验证：`uv run --no-sync pytest -q --tb=short` 为 **233 passed**（含 98 个 Phase 4 专项用例）；`uv run --no-sync python -m compileall -q ai_workbench` 通过。前端 `npm run build`、`check:i18n`、`test:harness`、`test:model-stream`、`test:phase1-contracts`、`test:knowledge-citations`、`test:url` 通过；docs size、workspace audit 和 `git diff --check` 通过。
- API/工作流：新增 `/api/tools` catalog/settings/call/approval/run 接口；调用/审批响应包含 run、steps、messages 和 session。直接调用不要求 Harness 开关，但要求白名单；失败/拒绝直接调用为 FAILED，取消为 CANCELLED。审批只能通过专用接口，不能发送普通聊天消息代替批准。公共 `/v1` 继续只透传工具，不执行工具。
- 剩余限制：模型/SearXNG 交互通过 MockTransport 和本机 HTTP 测试服务验证，未使用真实模型权重或真实搜索服务；前端完成状态与 SSR 渲染测试，未宣称浏览器手工验收。Phase 5、MCP、图像生成、ComfyUI、公共 rerank 和模型下载均未提前实施。

### Round 3 / Phase 3 实施记录（2026-09-06）

- 新增 `0005_phase3_personas`，为 disposable SQLite 重建 Persona、session-persona、Persona Knowledge/Worldbook bindings、session overrides 和 run configuration snapshots；固定 seed 为可编辑 Chat 与 Translate，迁移不触碰模型、附件或 runtime 文件。
- 新增严格 `Persona`/`SessionPersona`/resolved-config schemas、SQL/memory `PersonaStore` 与 `ChatService`。解析顺序为 session model > Persona model > global default；上下文、生成、harness/tools 采用 session override > Persona；资料采用当前 speaker Persona 默认或 session override/显式空列表。
- ChatRunner 删除 `ChatTargetCatalog`/`PromptTarget` 依赖，群聊每次只回复手动选择的 speaker；assistant 消息保留 Persona id/name/avatar 快照，run 私有保存完整配置以抵抗中途编辑和切换。Harness/tools 本轮仅存储展示，不发送或执行。
- 新增 `/api/personas/*`、session Persona/member/configuration API、头像引用保护与 Persona 默认资料绑定 API；前端新增 PersonasPanel、SessionSettingsDialog、当前 speaker、选定上下文、头像和双语文案。
- 验证：`uv run --no-sync pytest -q`、`uv run --no-sync pytest tests/test_phase3_personas.py -q`、compileall、frontend build、i18n、model-stream、phase1 contracts、knowledge citations、URL helpers、docs size、workspace audit、git diff --check 均通过。Round 3 专项覆盖迁移、SQL/memory、优先级、群聊 speaker、资料继承/清空、头像引用、等待恢复、取消和 in-flight snapshot。
- API/设置/工作流变化：Settings 增加 Personas；session 返回成员、current speaker 和 effective config；run 以 persona_id 取代 target；知识库/世界书返回 inherit/override 与 effective ids。公共 `/v1`、工具执行/审批、自动轮询、多 key、模型下载和其他后置边界未改变。

### Phase 2b 实施记录（2026-09-06）

- 新增代码内锁定 runtime catalog，首批启用 x86_64 Windows/Linux 的 llama-server CPU 与 Python worker torch-cpu；CUDA、Vulkan、torch-cu128 和 onnx-gpu 保留为明确 unsupported 条目。llama.cpp b10809 的 Windows/Linux CPU 资产使用官方 HTTPS URL 与固定 SHA-256；Python worker requirements 使用带哈希锁文件。
- 新增 `RuntimeStore`、`RuntimeSupervisor`、Alembic `0004_phase2b_runtimes`、安装/卸载任务 API、动态回环端口、Windows Job Object/跨平台进程组、10 MiB 脱敏日志和 20 条历史保留。安装 staging 和 runtime 目录与模型/附件目录分离，迁移不删除文件。
- `ModelProfile` 增加 runtime_id/runtime_variant/runtime_options；`ModelManager` 统一托管 LlamaServerAdapter 与 PythonWorkerAdapter。Python worker 通过 token-authenticated HTTP RPC 暴露 health/load/unload/embed/rerank/image-embed/vision，并强制离线、本地模型加载。
- Models UI 增加 RuntimesPanel、runtime profile 绑定、任务进度/取消/重试/卸载/日志和双语文案；全局 runtime/model events 可在没有聊天 session 时订阅。
- 验证：`uv run --no-sync pytest -q` 为 **115 passed**；Phase 2b 专项测试 35 passed；compileall、前端 build、i18n、model-stream、Phase 1 contracts、Knowledge citations、URL helpers、docs size、workspace audit、git diff --check 均通过。实际 `llama-server/cpu` 与 `python-worker/torch-cpu` 安装完成；Python 3.12.11、PyTorch CPU、Transformers、ONNX Runtime 导入检查通过；未下载任何模型文件。
- API/设置变化：新增 `/api/models/runtime/settings`、`/api/models/runtimes/*`、受管 profile 字段和 `/api/models/profiles/{id}/log`；新增 `runtime_job_updated`/`runtime_status` 全局事件。聊天 Run、消息、附件和 `/v1` 外部边界未扩展。
- 实际 CPU 前向检查：在临时目录生成随机权重，用安装好的 worker Python 验证 embedding、reranker、CLIP、SigLIP2、DINOv2 的有限值输出；临时权重已清理。此检查不代表预训练模型质量验收。
- 剩余限制：当前只启用 CPU runtime；预训练 GGUF/Florence2/WD14 权重和 Linux 主机运行未实测。浏览器已验证桌面安装完成状态与窄屏设置页；窄屏运行环境列表因浏览器标签丢失未完成交互验收。CUDA/Vulkan、公共 `/v1/rerank`、模型下载和后续阶段边界不变。

### Phase 0 实施记录（2026-09-04）

- 数据库 `data/agent_workbench.db` 已由无版本旧库安全接管并标记为 `0001_current_schema`；当前 27 张业务表、FTS5 `kb_chunk_fts` 和 46 个显式索引均通过校验。
- 迁移前备份保存在 `data/backups/database/agent_workbench.pre-baseline-20260904T041013Z.db`，对应 manifest 记录 SHA-256、完整性检查和关键表行数；此前的预检查备份也保留。备份目录不提交版本库。
- baseline 是静态、可复现的 SQL，保留 `messagerecord.content_json` 与 `output_type` 历史列；旧消息写入同时填充兼容列，不改变 MessageSchema/API 表现。
- `dist/` 已确认是可重建的旧 portable 快照并删除；`data/models/embeddings` 下 176 个仅含 `{}` 的精确 `a2-embed-*` 测试桩已删除，`bge-m3` 及其他用户数据保留。
- `tests/test_stateless_inference_skeleton.py` 已传入临时 root；`tests/conftest.py` 会比较仓库 `data/models` 普通文件的路径、大小和 SHA-256，防止回归泄漏。
- 验证命令：`uv run pytest tests/test_phase0_migrations.py tests/test_stateless_inference_skeleton.py -q`（54 passed）；`uv run pytest tests/test_persistence.py -q`（通过）；`uv run python scripts/phase0_audit.py --check`（通过）。全量套件为 1451 passed、23 failed，失败属于既有旧 MessageSchema/Intent 测试契约、可选依赖提示和 Knowledge 分块数量契约，不是 Phase 0 迁移路径。
- API、设置、消息 parts、事件和用户工作流未作有意变更；旧架构减法留待 Phase 1。

### Phase 1 实施记录（2026-09-04）

- `ChatTargetCatalog` 只包含代码内 `chat`（公开默认）和 `translate`（内部测试）目标；所有前缀输入按普通文本发送。
- Runtime/ChatRunner 统一处理等待恢复、上下文、Memory、Worldbook、Knowledge、附件、群聊 transcript、标题与 run/event 持久化。
- RuntimeState 改为显式注入 sessions/messages/runs、LLM、Utility LLM、Knowledge、Pet、NetworkPolicy 等服务；启动不扫描扩展目录。
- 删除 Agent/Command/Capability/Intent/Web Context/ComfyUI/image-generation/script/forms/action UI 代码、路由、测试和相关前端入口。
- `0002_phase1_prune` 对测试数据库执行破坏性删表删列；不做数据复制、双写、旧字段转换或回滚伪装。
- `AppSettings.pet`、`RunStep.kind`、Utility LLM 错误码、Knowledge RRF fallback 与 `NetworkPolicy` 契约测试已补齐；前端设置导航和 Pet 状态契约有静态测试。
- 验证：后端 `uv run pytest -q`（41 passed）；前端 build、i18n、Knowledge citations、URL helper 与 Phase 1 contracts 均通过。

### Phase 2a 实施记录（2026-09-05）

- 新增 `core/models/`：统一 ProviderAdapter、严格 schema、ModelProfileStore、ModelSettingsStore、ModelManager、OpenAI adapter、inventory、错误和观测。五种 kind 共用模型表，内部只用 UUID，外部只用全局唯一 alias。
- Provider 连接只实现 OpenAI Compatible；请求、模型列表及 health/load 共用有界队列，取消、断流、配置更新和退出均释放占用。相同 provider/model_ref 的别名共享占用、状态事件与最保守释放策略，默认 manual。
- `api/routes/models.py` 提供统一 provider/profile CRUD、kind 过滤、status、inventory、health/load/unload 和 settings；密钥不回显，引用删除及繁忙更新返回明确错误。
- `api/routes/openai_compatible.py` 共用 manager，支持非流式/SSE、tools/tool_calls、tool 消息、图像输入、response_format 子集及 float/base64 embeddings。保留 localhost、单 key、body 限制和完整流结束后的日志；工具仅透传、不执行。
- ChatRunner、UtilityLLMService、Knowledge indexing/query embedding/rerank 改为 manager 调用；标题只用显式辅助模型。修改向量配置会使 memory/SQLite 两种 store 的 KB/source 索引失效，检索阈值和数量限制透传到 retrieval。
- 删除旧 profile 表/store/route、core/inference 进程内推理、LLM 配置解析、品牌 runtime、旧环境变量和主进程重型推理 extras；删除旧 vision/multimodal 公共接口与过期契约，没有兼容转发或旧配置读取。
- `0002_phase1_prune` 改为固定历史 DDL，避免引用最新 ORM；新增静态 `0003_phase2a_models` 重建整个测试 SQLite，Alembic 成为唯一 schema authority。实际库由 0001 经 0002 升至 0003，审计为 18 张业务表、31 个显式索引、integrity=ok；重建前后数据库外 1,174 个文件的内容摘要一致。
- 前端新增 `ModelsPanel.tsx`、`useModelsStore.ts`、`messageStream.ts`，统一五类模型、连接、参数、能力、生命周期和外部服务设置；聊天和 Knowledge 共用模型源。修正 WS delta、完成消息覆盖、旧刷新响应、会话切换隔离、RunPanel 选择器及弹窗焦点；双语同步。
- 更新 AGENTS、AI_CONTEXT、README、task cards、运行/数据/模型契约。审计脚本改为 `scripts/audit_workspace.py`，不再调用旧 baseline 兼容检查；便携构建补齐 Alembic 文件，官方 launcher 仅允许 loopback。
- 验证：`uv run --no-sync pytest -q` 为 **80 passed**；`compileall`、前端 build、i18n（11 namespaces）、model-stream、Phase 1 contracts、Knowledge citations、URL helpers、docs size、workspace audit、`git diff --check` 均通过。便携临时目录可独立创建 0003 schema；实际服务根页面与 health 返回 200。
- 协议测试含 MockTransport 及真实本机 HTTP/SSE/WS：工具参数分片、中文字节分片、usage、错误、断流取消、队列上限/超时/更新互斥及 HTTP 完成前收到 WS delta。前端状态测试覆盖重复/乱序/完成事件和并发刷新。按用户要求停止浏览器 smoke，未宣称浏览器验收通过；未使用真实模型权重或实际外部推理服务。
- Phase 2a 边界：外部连接可执行 LLM 和文本 embeddings；远端 residency=unknown，unload 明确 unsupported。reranker/image_embedding/vision 配置和内部接口已建立，生产执行等待 Phase 2b 受管后端；RAG 在 rerank 不可用时保持 RRF。Persona、harness、公共 rerank、图像服务和模型下载未提前实施。

## 13. 决策变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-04 | 初版：将 Claude Code 对话中的目标、证据、最终决策、目标架构、迁移阶段和交接规则冻结为文档。 |
| 2026-09-04 | 记录最终覆盖关系：受管 worker、llama-server、手动放模型、Pet 在 app settings、ComfyUI 当前移除、reranker 保留但公共 API defer、Alembic 纳入 Phase 0。 |
| 2026-09-04 | 完成 Phase 0：静态 baseline、旧库备份/校验/stamp、测试模型目录隔离、`DATA_LAYOUT.md` 与只读审计脚本；未改变 API 或用户工作流。 |
| 2026-09-04 | 完成 Phase 1：普通聊天单一路径、显式核心服务、破坏性 schema prune、前端/契约测试与文档依赖收敛。 |
| 2026-09-05 | 完成 Phase 2a：统一模型层/表/接口/前端，补齐 OpenAI 兼容流式与工具/视觉/格式子集，删除旧进程内推理与配置栈，整体重建测试库；冻结 OpenAI Compatible 单协议、manual 默认释放、标题仅显式辅助模型。 |
| 2026-09-05 | 永久确认测试阶段无用户/用户数据、允许长期停服、不做保活或旧结构兼容、不迁移数据和不考虑旧习惯；模型/附件/runtime 等文件不随 schema 删除。 |
| 2026-09-06 | Phase 2b 完成：首批 CPU runtime、代码内锁定 catalog、动态回环 HTTP worker、SQLite 安装任务与全局事件；GPU 变体显式 unsupported，模型仍手动管理。 |
| 2026-09-07 | Phase 4 完成：显式内置工具、八轮循环与主动预算、可恢复审批、共享取消、直接调用与双语前端；0006 schema、233 后端测试及前端质量门槛通过，Phase 5 待实施。 |
