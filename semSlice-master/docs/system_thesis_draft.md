# 北京邮电大学本科毕业设计（论文）草稿

说明：本稿按“附件5：北京邮电大学2026届本科毕业设计（论文）模板”章节体例撰写，可直接将“论文题目—附录”部分内容粘贴到模板正文中。封面信息、诚信声明签字页请在模板中手动填写。

论文题目：面向语义通信的网络切片资源编排系统设计与实现  
学院：计算机学院（国家示范性软件学院）  
专业：软件工程（示例，占位）  
姓名/学号/班级/指导教师：请按实际填写

## 摘要
面向6G智能网络的发展趋势，传统“以比特误码率为中心”的通信优化方法已难以直接反映任务完成质量。语义通信强调“任务语义有效传输”，网络切片强调“多业务隔离与资源保障”，二者协同后可在同等资源约束下提升业务质量与系统效率。围绕该问题，本文完成了一个前后端分离的语义通信网络切片资源编排系统。系统采用 FastAPI + Vanilla JavaScript 技术栈，形成“管理员配置—租户提交任务—语义处理—切片适配—资源分配—性能评估—可视化反馈”的闭环流程，支持多租户并发场景下的策略切换与结果对比。

在方法上，本文将语义估计、切片构建、切片-业务适配、资源编排、性能评估拆分为独立服务模块。语义处理模块依据链路噪声、带宽、功率与距离估计 SNR、时延与保真度；切片模块固定构建 3 类词表切片（`en`/`en90`/`en80`）；适配模块提供基于词表相似性的匹配机制；资源编排模块采用在线 PSO 优化并结合能耗阈值约束与低SNR趋势补偿；评估模块统一输出平均保真度、平均时延、通过率、平均能耗等指标。系统同时保留 legacy 适配层，可切换到历史实验脚本或 `paper_sim` 对比模式，实现 SemSlice / NetSlice / NoSlice 三策略横向比较。

实验部分基于项目内置 `fitSNR`、`fit5TASK`、`fit15TASK` 三类场景数据进行验证。结果表明：相较 NetSlice，SemSlice 在三场景平均时延下降 16.89%，平均语义得分（SS）提升 10.64%；相较 NoSlice，平均时延下降 30.32%，平均 SS 提升 28.61%。结果说明语义感知切片与资源协同优化可显著提升多任务场景下的语义服务质量。

关键词：语义通信；网络切片；资源编排；多租户系统；粒子群优化

## Title
Design and Implementation of a Semantic Communication-Oriented Network Slicing Resource Orchestration System

## ABSTRACT
With the evolution toward 6G intelligent networking, traditional bit-level optimization can no longer directly represent task-level service quality. Semantic communication focuses on effective semantic delivery, while network slicing provides isolation and guarantees for heterogeneous services. Their coordination is expected to improve service quality under limited resources.

This thesis implements a front-back separated semantic communication network slicing platform. The system is built with FastAPI and Vanilla JavaScript, and provides an end-to-end workflow: administrator configuration, tenant task submission, semantic processing, slice adaptation, resource allocation, performance evaluation, and visual feedback. The architecture is modularized into semantic processing, slicing, adaptation, orchestration, and evaluation services.

The orchestration module adopts an online PSO-based optimizer with energy threshold constraints and low-SNR trend compensation. The system supports multi-strategy comparison (SemSlice, NetSlice, NoSlice) through a legacy-compatible adapter. Experiments are conducted on three scenarios (`fitSNR`, `fit5TASK`, `fit15TASK`) using built-in project datasets. Results show that SemSlice reduces average delay by 16.89% and improves average semantic score (SS) by 10.64% over NetSlice; compared with NoSlice, SemSlice reduces delay by 30.32% and improves SS by 28.61%.

These results demonstrate that semantic-aware slicing with coordinated resource orchestration can effectively improve task-level quality and efficiency in multi-tenant communication services.

KEY WORDS: Semantic Communication; Network Slicing; Resource Orchestration; Multi-tenant System; PSO

## 第一章 绪论

### 1.1 研究背景
随着业务类型从“数据传输”向“任务执行”演进，通信系统评价目标逐渐由比特级可靠性扩展到语义级有效性。传统网络优化主要围绕吞吐、时延、误码率展开，但在智能问答、语义检索、任务协同等业务中，用户关心的是“语义是否正确传达”，而不是“每个比特是否完全正确”[1]。这使语义通信成为新一代通信系统的重要研究方向。

同时，5G/6G 网络切片技术为异构业务提供了逻辑隔离和资源保障能力[4][5]。但现有切片机制大多聚焦带宽和时延等底层指标，较少直接引入语义质量作为优化目标，导致在复杂任务下“链路指标可接受但业务效果不理想”的问题。

因此，本文聚焦“语义通信 + 网络切片 + 资源编排”融合场景，通过系统工程化方法将算法能力封装为可配置、可观测、可比较的平台，降低实验复现门槛并提高工程可用性。

### 1.2 国内外研究现状
语义通信方面，DeepSC 证明了端到端神经语义编解码在低信噪比场景下相较传统通信有更好的任务语义鲁棒性[1]。后续研究逐渐关注跨任务、跨领域、跨模态条件下的语义传输性能与自适应能力。

网络切片方面，已有研究系统性定义了切片架构、编排与管理框架[4][7]，在工业互联网、车联网等场景得到广泛应用。但多数切片调度仍采用 QoS/QoE 指标，语义层面指标尚未成为主流。

综上，当前痛点主要在“算法与系统脱节”：不少方案停留在离线脚本验证，缺乏可运行、可观测、可维护的工程平台。本文工作定位于该缺口，即构建可直接承载语义切片策略的前后端系统，并提供策略对比能力。

### 1.3 研究目标与主要内容
本文目标是实现一个语义通信切片资源编排系统，支持管理员与租户双角色操作，并完成多策略实验比较。主要内容如下：

1. 设计前后端分离架构，完成统一 API、状态管理与可视化控制台。
2. 构建业务配置、网络配置、切片配置、切片适配、资源分配、性能评估六类核心能力。
3. 采用在线 PSO + 约束裁剪 + 低SNR补偿机制实现资源编排。
4. 建立 SemSlice / NetSlice / NoSlice 三策略可复现实验流程并给出定量结果分析。

### 1.4 论文结构
第一章介绍研究背景、问题与目标。  
第二章给出系统需求分析与总体设计。  
第三章阐述关键模块设计与实现。  
第四章给出实验设计、结果与分析。  
第五章总结全文并展望后续工作。

## 第二章 系统关键技术与实现方案

### 2.1 语义通信网络切片关键技术
本文系统并非简单地将语义通信算法和网络切片界面化展示，而是围绕“语义质量可估计、切片对象可构建、业务与切片可匹配、资源可按策略编排、结果可量化评估”五个环节进行工程化实现。结合仓库中的 `semantic_service.py`、`slicing_service.py`、`adaptation_service.py`、`orchestration_service.py` 与 `evaluation_service.py`，本系统涉及的关键技术如下。

#### 2.1.1 语义信道建模与语义质量估计技术
系统首先需要将用户任务从“业务请求”转换为“可参与后续切片和资源分配的语义业务对象”。在实现中，业务数据由 `BusinessConfig` 和 `UserBusinessItem` 建模，任务的核心属性包括业务类型、负载符号数、传输距离、基础语义相似度以及词表信息。`semantic_service.py` 中的 `build_business_config()` 负责生成标准化任务列表，`process_services()` 与 `semantic_metrics_for_user()` 负责完成语义质量估计。

该过程本质上是在轻量工程系统中构建一个可计算的语义信道模型。系统并未直接复现 DeepSC 的端到端训练过程，而是依据功率、带宽、距离和噪声估计信噪比，再进一步推导传输时延与语义保真度。SNR 计算方式为：

\[
\mathrm{SNR}_{dB}=10\log_{10}\left(\frac{P}{B\times10^6\times d^2\times N_0}\right),
\quad N_0=10^{\frac{\mathrm{noise\_dbm}}{10}}\times10^{-3}
\]

在得到信噪比后，系统根据香农容量近似计算单位任务的传输时延：

\[
C=B\times10^6\log_2(1+10^{\mathrm{SNR}_{dB}/10}),\quad
\mathrm{delay}_{ms}=\frac{\mathrm{payload\_symbols}\times30}{C}\times10^3
\]

随后，系统结合基础语义相似度、编码等级增益和时延惩罚项估计语义保真度：

\[
f=\mathrm{clip}(f_0+0.018(\mathrm{SNR}_{dB}-3)+g_{enc}-p_{delay},0,1)
\]

其中，编码等级增益 \(g_{enc}\) 由 `select_encoder_level()` 决定，分别对应不同知识等级切片的语义恢复能力；时延惩罚项 \(p_{delay}\) 则体现时延过高对语义任务完成质量的负面影响。通过上述方法，系统将复杂语义通信问题压缩为可在线计算、可解释、可用于调度决策的指标体系。

#### 2.1.2 面向知识分层的语义切片构建技术
传统网络切片主要依据带宽、时延和隔离需求划分资源，而本文系统进一步将“知识库层级”和“语义恢复能力”纳入切片定义。在 `slicing_service.py` 中，系统默认构建 3 个切片实例，并分别绑定 `vocab_en`、`vocab_en90`、`vocab_en80` 三类词表知识库。每个切片同时关联一个编解码器对象，形成“切片实例 - 编解码器 - 知识库”的固定映射关系。

这种设计有两个作用。其一，它将语义通信中的词表覆盖率差异转化为可管理的切片属性，使不同知识等级的语义服务具备工程上的可配置性。其二，它为后续“业务与切片适配”提供了明确的匹配对象，而不是仅在资源层面进行抽象分配。代码中的 `build_slice_config()` 并不追求切片数量的任意扩张，而是有意固定为 3 类代表性语义切片，以便与历史实验脚本中的 SemSlice、NetSlice、NoSlice 策略进行稳定比较。

#### 2.1.3 业务-切片语义适配技术
仅有切片实例并不足以体现语义切片的优势，系统还需要回答“某一任务应进入哪个切片”的问题。对此，`adaptation_service.py` 提供了基于词表标签和知识等级的适配机制。系统首先从用户任务的 `task_vocab`、`task_pkl` 或 `domain_type` 中推断任务对应的语义词表标签，再从切片的 `kb_type`、`kb_id` 和 `slice_name` 中提取切片标签，最后计算业务与切片之间的相似度得分。

在评分策略上，若用户任务与切片知识等级完全一致，则赋予更高分值；若存在一个等级差，则给予中等分值；差异进一步扩大时则降权处理。同时，系统还会对高保真业务追加额外权重，以体现其对知识匹配质量更为敏感的特点。最终，`_choose_slice_by_vocab()` 按“相似度优先、知识等级兜底”的规则选择最优切片，从而把语义知识匹配过程显式地纳入资源编排前置环节。

#### 2.1.4 面向多任务场景的资源编排技术
资源编排是连接语义通信和网络切片的核心环节。系统在 `orchestration_service.py` 中实现了三类策略统一入口：`semslice`、`netslice` 和 `noslice`。其中，`semslice` 代表语义切片策略，强调知识匹配结果、业务类型和链路状态的协同；`netslice` 更强调负载规模、距离和实时性等传统网络因素；`noslice` 则作为不使用切片的基线方案。

在具体实现上，系统首先依据用户业务特征计算基础权重。例如，对于 `netslice` 策略，任务符号负载、传输距离和低时延要求会共同影响权重值；对于 `semslice` 策略，相似度得分和任务类型对分配结果有更强影响。随后，系统依据不同策略形成带宽、功率和计算资源的比例分配，并执行总带宽、总功率、总算力与总能耗等约束裁剪，其中能耗模型表示为：

\[
\mathrm{energy}=1.8\times compute+45\times power
\]

此外，系统还构造了低 SNR 趋势补偿机制。`_snr_trend_factor()` 和 `_trend_strength_by_strategy()` 根据当前信噪比区间对不同策略进行差异化修正，使 `semslice` 在低信噪比条件下获得更强的补偿力度，以体现语义感知切片在弱信道环境下的鲁棒性优势。该设计并非停留在概念层，而是直接进入实际资源分配与实验结果生成流程。

#### 2.1.5 任务级性能评估技术
为了验证资源编排是否真正改善了业务完成质量，系统在 `evaluation_service.py` 中建立了面向任务的评估机制。与传统仅统计链路吞吐不同，本文同时考察语义保真度、时延和能耗，并根据业务类型采用差异化通过判据：低时延任务要求 `delay_ms <= 130`，高保真任务要求 `fidelity >= 0.60`。

在此基础上，系统输出 `avg_fidelity`、`avg_delay_ms`、`avg_energy` 等核心指标，并生成面向前端展示的用户级和策略级图表数据。更重要的是，评估模块还将“知识匹配得分”和“低 SNR 策略增益”重新注入到最终语义质量计算中，从而保证评估结果不仅反映底层链路状态，也反映切片与业务适配是否有效。这使得 SemSlice、NetSlice 和 NoSlice 三类策略能够在统一指标口径下进行横向比较。

### 2.2 系统实现技术介绍
在完成关键算法抽象后，本文进一步将其封装为可运行系统。第二章在此不再泛泛介绍“B/S 架构”或“前后端分离”等通用概念，而是结合本项目代码说明系统实现时真正使用到的技术与作用。

#### 2.2.1 基于 FastAPI 的接口组织与流程编排实现
后端入口位于 `backend/app/main.py`。系统使用 FastAPI 创建服务实例，统一注册 `/api/v1` 路由前缀，并在启动阶段执行 `init_db()` 和 `seed_default_users()` 完成数据库初始化与默认账号写入。之所以选用 FastAPI，不是因为其概念新，而是因为本系统需要频繁接收结构化配置对象、执行多阶段流水线、并向前端返回嵌套结果，FastAPI 在这类 JSON API 场景下能够直接与 Pydantic 模型配合，减少手工解析和字段错误。

在 `routes.py` 中，系统将接口分为认证、业务配置、网络配置、切片配置、适配、资源分配、性能评估和端到端运行几类。更关键的是，`_build_strategy_response()`、`_run_submission()` 与 `_create_submission_and_run()` 将“配置读取 - 业务生成 - 适配 - 分配 - 评估 - 结果持久化”串联为完整流程，使管理员和租户都可以通过单次请求触发后端自动执行整条处理链路。因此，FastAPI 在本文中的作用不是简单提供 HTTP 服务，而是承载系统流程编排和模块集成的统一入口。

#### 2.2.2 基于 Pydantic 的统一数据模型与参数校验实现
系统中的业务对象、网络对象、切片对象、适配关系、资源分配结果和评估结果均定义在 `backend/app/models/schemas.py` 中。典型模型包括 `UserBusinessItem`、`NetworkConfig`、`SliceInstance`、`AdaptationRow`、`UserResourceAllocation` 和 `PerformanceEvaluateResponse`。这些模型通过字段类型、默认值和取值范围约束，保证前端输入、模块内部调用和数据库持久化使用同一套数据口径。

例如，`payload_symbols` 被限制为正整数，`base_similarity` 和 `knowledge_level` 被限制在 `[0,1]` 区间，`total_bandwidth`、`total_power`、`cpu_capacity` 等资源参数必须为正值。这样做的意义在于：一旦管理员或租户输入了非法参数，系统会在接口层即时拦截，而不是等到资源分配或评估阶段才暴露异常。对于一个需要频繁比较多组实验结果的系统而言，统一数据模型是保证实验口径一致和减少调试成本的关键工程手段。

#### 2.2.3 基于状态仓储的运行数据管理实现
为了支撑管理员配置下发、租户任务提交、运行状态跟踪和策略对比结果回看，系统在 `backend/app/store/` 目录下实现了轻量状态管理与持久化机制。其中，`database.py` 负责数据库初始化，`repository.py` 提供配置保存、任务创建、运行结果落库、策略摘要写入和状态快照构建等仓储函数，`state.py` 则维护运行期内存状态。

这一实现方式与论文后续实验分析直接相关。管理员提交网络配置和切片配置后，系统可以通过 `active_network_response()` 与 `active_slice_response()` 读取当前生效配置；租户发起任务后，系统通过 `create_task_submission()` 和 `create_workflow_run()` 为每次运行生成独立记录；三种策略运行结束后，再通过 `persist_run_results()`、`complete_workflow_run()` 和 `save_strategy_compare_summary()` 保存用户级结果与策略级摘要。这样，系统不仅能展示当前运行结果，还能为后文实验图表和历史对比提供可追溯的数据基础。

#### 2.2.4 基于原生 JavaScript 的交互与可视化实现
前端代码集中在 `frontend/app.js`。系统没有引入重量级前端框架，而是使用原生 JavaScript 完成登录态管理、表单采集、接口调用、轮询刷新、表格渲染和图表渲染。这样处理的原因在于，本系统的重点在于验证语义切片资源编排流程，而非构建复杂单页应用；使用轻量前端可以降低部署复杂度，并使系统结构更容易与后端实验逻辑对应。

从实现细节看，前端通过 `callApi()` 统一封装接口访问，通过 `networkPayloadFromForm()` 和 `slicePayloadFromForm()` 将页面输入组装为后端所需结构化配置，通过 `renderTable()`、`renderBars()` 和 `renderUnifiedCompareChart()` 将评估结果展示为任务表格和柱状图。管理员界面支持策略切换与实时刷新，租户界面支持任务提交和个人结果查看。由此可见，前端技术的作用并不是停留在“页面展示”，而是承担实验配置输入、运行结果承载和策略对比可视化三个核心职责。

#### 2.2.5 面向历史实验脚本的兼容与对比实现
考虑到本文工作既要体现系统实现，又要保留与既有算法脚本的可比性，项目专门设计了 `legacy_adapter.py` 作为兼容层。该模块通过 `MODULE_MAP` 和 `NO_SLICE_MODULE_MAP` 将 `DeepSC-master` 目录下的历史脚本统一映射到 `semslice`、`netslice`、`noslice` 三类策略入口，并在运行时动态加载旧实验代码。

这一兼容层的作用主要体现在两个方面。第一，它避免了将历史实验脚本完全重写进新系统，降低了迁移工作量；第二，它使当前系统能够直接复用 `fitSNR`、`fit5TASK` 和 `fit15TASK` 等场景数据，在统一前端界面和统一指标体系下完成多策略对比。因此，legacy 适配并不是附属功能，而是连接“算法原型验证”和“工程系统实现”的桥梁，也是本文实验部分能够保持可复现性的重要技术支撑。

综合来看，本章从语义信道建模、知识分层切片、业务适配、资源编排和性能评估五个关键技术出发，进一步说明了后端接口组织、统一数据模型、运行状态管理、前端交互以及历史脚本兼容等系统实现技术，为第三章的模块设计与实现奠定了基础。

## 第三章 核心模块设计与实现

### 3.1 开发环境与技术栈
后端采用 FastAPI + Uvicorn + Pydantic + NumPy；前端采用 HTML/CSS/Vanilla JavaScript。依赖中额外引入 Torch、TensorFlow、bert4keras 等包用于 legacy 实验兼容。

### 3.2 数据模型设计
系统通过 `schemas.py` 定义统一模型，核心对象包括：

1. 业务对象：`BusinessConfig`、`UserBusinessItem`。
2. 网络对象：`NetworkConfig`。
3. 切片对象：`SliceConfigRequest`、`SliceInstance`。
4. 适配对象：`AdaptationRow`。
5. 分配对象：`UserResourceAllocation`。
6. 评估对象：`PerformanceEvaluateResponse`。

统一模型避免了模块间“字段命名不一致”和“单位口径不一致”的工程问题。

### 3.3 认证与权限模块
认证模块内置管理员与租户账号，登录后签发随机 Token 并写入会话字典。接口层通过依赖注入读取当前用户，并在管理员接口上执行角色校验。租户调用资源分配与评估接口时会自动进行租户级数据过滤，避免跨租户访问。

### 3.4 语义通信处理模块
语义模块在 `semantic_service.py` 中实现。给定用户任务与网络参数，先计算信噪比，再估计传输时延和语义保真度。

SNR 计算公式：

\[
\mathrm{SNR}_{dB}=10\log_{10}\left(\frac{P}{B\times10^6\times d^2\times N_0}\right),
\quad N_0=10^{\frac{\mathrm{noise\_dbm}}{10}}\times10^{-3}
\]

时延估计公式：

\[
C=B\times10^6\log_2(1+10^{\mathrm{SNR}_{dB}/10}),\quad
\mathrm{delay}_{ms}=\frac{\mathrm{payload\_symbols}\times30}{C}\times10^3
\]

保真度估计公式：

\[
f=\mathrm{clip}(f_0+0.018(\mathrm{SNR}_{dB}-3)+g_{enc}-p_{delay},0,1)
\]

其中 \(g_{enc}\in\{0.08,0.04,0.01\}\) 对应不同编码等级，\(p_{delay}=\max(0,\frac{delay-130}{1300})\)。

### 3.5 切片构建与分发模块
切片模块固定构建 3 个切片实例，与 `vocab_en`、`vocab_en90`、`vocab_en80` 三类知识库绑定，同时为每个切片配置对应编解码器。该设计便于对比不同词表覆盖率下的语义恢复质量。

### 3.6 切片-业务适配模块
适配模块根据用户任务词表标签与切片标签计算匹配分值。当词表等级一致时给予高分，不一致时按差值降权；高保真任务附加额外权重。最终按“相似度优先 + 知识等级兜底”策略选择匹配切片。

### 3.7 资源编排模块
资源编排是系统核心。策略映射关系如下：

1. `semslice`、`netslice`：进入 PSO 分配器执行联合优化。
2. `noslice`：进入规则分配（等权基线）路径。

分配后统一执行以下约束：

1. 带宽、功率、计算资源不超过总量上限。
2. 总能耗约束：\(\mathrm{energy}=1.8\times compute+45\times power\)。
3. 超阈值时按比例回缩。

此外，系统引入低SNR趋势补偿函数，对不同策略在低信噪比区间进行差异化资源修正，使 SemSlice 在低SNR下获得更高补偿强度，体现语义感知优势。

### 3.8 性能评估与可视化模块
评估模块计算用户级指标与系统级指标。通过条件如下：

1. 低时延任务：`delay_ms <= 130`。
2. 高保真任务：`fidelity >= 0.60`。

系统级指标定义为：

1. `avg_fidelity`：用户保真度均值。
2. `avg_delay_ms`：用户时延均值。
3. `pass_rate`：达标任务比例。
4. `avg_energy`：平均能耗。

前端将结果渲染为任务表、柱状图和资源占用图，并支持管理员端三策略对比图联动切换。

## 第四章 系统测试与实验结果分析

### 4.1 实验目标
实验目标包括两类：

1. 功能验证：验证多租户流程与六模块链路正确性。
2. 性能验证：比较 SemSlice、NetSlice、NoSlice 三策略在不同任务规模下的时延与语义质量差异。

### 4.2 实验设置
实验使用项目内置对比数据 `docs/figures/algorithm_comparison_full.csv`，场景包括：

1. `fitSNR`（信噪比拟合场景）
2. `fit5TASK`（5任务场景）
3. `fit15TASK`（15任务场景）

策略对比在统一资源向量 \([0.2,0.3,0.5,0.6,0.8,0.6]\) 下进行，来源于 `legacy_adapter.py` 中 `paper_sim` 模式。

### 4.3 指标定义
对比指标包括：

1. 平均时延 `avg_delay_ms`，值越小越好。
2. 平均语义得分 `avg_ss`，值越大越好。
3. 平均语义频谱效率 `avg_s_se`，值越大越好。

### 4.4 实验结果
表4-1 给出三场景对比结果（来自 `algorithm_comparison_full.csv`）。

| 场景 | 策略 | 平均时延/ms | 平均SS | 平均S-SE |
| --- | --- | ---: | ---: | ---: |
| fitSNR | SemSlice | 65.9022 | 0.8443 | 0.0846 |
| fitSNR | NetSlice | 77.4896 | 0.7720 | 0.0774 |
| fitSNR | NoSlice | 92.9428 | 0.6660 | 0.0666 |
| fit5TASK | SemSlice | 59.7316 | 0.8914 | 0.0891 |
| fit5TASK | NetSlice | 74.0494 | 0.8000 | 0.0802 |
| fit5TASK | NoSlice | 87.6339 | 0.6887 | 0.0687 |
| fit15TASK | SemSlice | 69.2510 | 0.8112 | 0.0814 |
| fit15TASK | NetSlice | 82.8175 | 0.7298 | 0.0730 |
| fit15TASK | NoSlice | 98.9540 | 0.6258 | 0.0627 |

可视化图可引用 `docs/figures/algorithm_comparison_full.png`（建议作为“图4-1 三策略综合对比图”）。

### 4.5 结果分析
由表4-1可得：

1. SemSlice 相较 NetSlice 的时延降幅分别为 14.95%、19.34%、16.38%，三场景平均降幅 16.89%。
2. SemSlice 相较 NoSlice 的时延降幅分别为 29.09%、31.84%、30.02%，三场景平均降幅 30.32%。
3. SemSlice 相较 NetSlice 的 SS 提升分别为 9.36%、11.42%、11.14%，三场景平均提升 10.64%。
4. SemSlice 相较 NoSlice 的 SS 提升分别为 26.77%、29.44%、29.62%，三场景平均提升 28.61%。

说明在统一资源约束下，语义感知切片与资源协同分配能同时改进时延与语义质量，且在任务规模扩增时保持更稳定性能。

### 4.6 系统功能验证
在功能链路上，系统已实现以下验证：

1. 管理员发布配置后，租户可即时提交并触发自动运行。
2. 租户仅能访问自身任务结果，管理员可查看全局任务板。
3. 策略切换可触发重算或直接切换展示，前端图表实时更新。
4. 评估输出与图表数据一致，具备可追溯性。

## 第五章 总结与展望

### 5.1 工作总结
本文围绕语义通信网络切片场景，完成了一个具备工程可用性的前后端系统，实现了从任务提交到性能评估的完整闭环。系统在架构上实现模块化解耦，在算法上完成语义估计、适配、PSO资源优化与评估统一接口，在实验上完成三策略多场景对比，验证了 SemSlice 方案的有效性。

### 5.2 主要创新点
本文工作的主要创新体现在：

1. 将语义通信与网络切片从“脚本验证”推进到“可运行平台”。
2. 建立统一数据模型与统一 API，支撑多模块协同。
3. 在资源分配中引入低SNR趋势补偿与能耗约束联合机制。
4. 提供可复现实验适配层，兼顾在线编排与历史策略对比。

### 5.3 不足分析
当前系统仍有以下限制：

1. 实验主要基于 `paper_sim` 与规则建模，真实链路数据接入不足。
2. 当前仅覆盖文本语义任务，尚未扩展到图像/视频多模态。
3. 鉴权仍为轻量会话模式，生产级安全机制有待完善。

### 5.4 后续展望
后续可从以下方向开展：

1. 引入在线真实网络指标采集，增强结果可信度。
2. 扩展多模态语义任务与跨模态切片策略。
3. 将强化学习或多目标进化算法引入资源编排。
4. 完善数据库与审计日志，提升可运维与可监管能力。

## 参考文献
[1] Xie H, Qin Z, Li G Y, et al. Deep Learning Enabled Semantic Communication Systems[J]. IEEE Transactions on Signal Processing, 2021, 69: 2663-2675.  
[2] Zhou Y, Feng L, Zhou F, et al. SemSlice: Semantic Communication-Oriented Network Slicing Framework[EB/OL]. GitHub Repository.  
[3] Kennedy J, Eberhart R. Particle Swarm Optimization[C]. Proceedings of ICNN, 1995: 1942-1948.  
[4] Rost P, Banchs A, Berberana I, et al. Mobile Network Architecture Evolution toward 5G[J]. IEEE Communications Magazine, 2016, 54(5): 84-91.  
[5] Foukas X, Patounas G, Elmokashfi A, et al. Network Slicing in 5G: Survey and Challenges[J]. IEEE Communications Magazine, 2017, 55(5): 94-100.  
[6] 3GPP. TS 28.530: Management and Orchestration; Concepts, Use Cases and Requirements[S].  
[7] FastAPI Documentation[EB/OL]. https://fastapi.tiangolo.com/  
[8] Paszke A, Gross S, Massa F, et al. PyTorch: An Imperative Style, High-Performance Deep Learning Library[C]. NeurIPS, 2019.  
[9] Abadi M, Barham P, Chen J, et al. TensorFlow: A System for Large-Scale Machine Learning[C]. OSDI, 2016.  
[10] 北京邮电大学本科毕业设计（论文）模板（2026届更新版）[Z].  

## 致谢
在毕业设计与论文撰写过程中，感谢指导教师在选题、系统设计、实验分析与论文修改阶段给予的持续指导；感谢课题组同学在系统联调、问题排查与测试验证中的支持与帮助；感谢家人对学习和科研工作的理解与鼓励。本文尚有不足，恳请各位老师批评指正。

## 附录

### 附录A 主要接口清单
1. `POST /api/v1/auth/login`  
2. `POST /api/v1/auth/logout`  
3. `GET /api/v1/auth/me`  
4. `POST /api/v1/module/business/config`  
5. `POST /api/v1/module/network/config`（管理员）  
6. `POST /api/v1/module/slice/config`（管理员）  
7. `POST /api/v1/module/adaptation`  
8. `POST /api/v1/module/resources/allocate`  
9. `POST /api/v1/module/performance/evaluate`  
10. `POST /api/v1/system/admin/run`  
11. `POST /api/v1/system/tenant/submit`  
12. `POST /api/v1/analysis/legacy/strategy-compare`  

### 附录B 系统运行步骤
1. 后端运行：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. 前端运行：

```bash
cd frontend
python -m http.server 5173
```

3. 浏览器访问：`http://127.0.0.1:5173`。  
4. 默认账号：管理员 `admin/admin123`；租户 `tenant1/tenant123`。
