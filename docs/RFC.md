# STM32_TokenBase — AI-First Database

### 一份设计白皮书 / RFC

| 项 | 值 |
| --- | --- |
| 状态 | Draft v0.2(加入 M1 选型与复用决策) |
| 日期 | 2026-06-26 |
| 作者 | KiteFlyerX / EmbeddedAiCoder Project |
| 许可 | 随仓库 GPLv3 |
| 关联 | EmbeddedAiCoder 的上下文引擎;可独立孵化 |

---

## 0. 摘要(TL;DR)

传统数据库的根本假设是「**由人来读**」:它优化存储成本与查询延迟,以「行/文档」为单位,用 SQL 做精确匹配,输出给人看的结果集。

大模型改变了这个假设。当数据库的消费者变成 **AI(以 token 为食、有上下文窗口上限、会幻觉、需要可追溯证据)**,优化目标随之彻底改变:**从「查询效率」转向「token 经济学」——在固定 token 预算内,向 AI 传递最高密度的相关信息。**

**STM32_TokenBase** 是为这一新假设设计的数据库范式。本文定义其四个第一性抽象(**Atom / Lens / Intent Query / Token Budget**)、两个增强(**Provenance / Diff Stream**)、查询协议、数据模型、分层架构与落地路径。

> 核心主张:**范式是新的,引擎可复用**。STM32_TokenBase 的创新在「抽象层与查询协议」,不必重写存储引擎;但为极致 token 效率,可为 Atom 设计专用序列化格式。

---

## 1. 动机

在 AI 辅助编程(尤其嵌入式/STM32)中,核心瓶颈不是「模型不够强」,而是**上下文供给**:

- 整个工程(HAL 库动辄数万行)远超上下文窗口;
- 每次把无关代码喂给模型 = 烧钱(token)+ 稀释注意力;
- 模型需要的是「**与当前问题相关的、带定位的、密度最高的片段**」,而非整库。

现有方案(向量库 / 全文检索 / SCIP 索引)各自解决一部分,但都是**为人或为单一检索模式**设计的组件,**没有一个把「AI 作为读者」作为第一性原则**。STM32_TokenBase 填补这一空白。

---

## 2. 核心论点:AI 改变了「读者」假设

| 维度 | 传统 DB(为人) | STM32_TokenBase(为 AI) |
| --- | --- | --- |
| 优化目标 | 存储成本、查询延迟 | **token 经济学**(信息密度/token) |
| 基本单元 | 行 / 文档 / KV | **语义原子**(Atom) |
| 查询方式 | 精确匹配、SQL join | **意图 + 多跳规划** |
| 输出形态 | 结果集(表格) | **prompt-ready token 包** |
| 交互模型 | 无状态、一次性 | **有状态、迭代探索** |
| 可信度假设 | 人能自行判断 | **自带证据指针**(防幻觉) |
| 一等公民 | 数据完整性(ACID) | **变更流 + 可寻址性** |

每一行都是范式级差异,不是工程包装。

---

## 3. 范式定义

> **STM32_TokenBase 是一种以「语义原子」为基本单元、以「token 预算」为一等约束、以「意图查询」为接口、以「prompt-ready 包」为输出的数据库范式。**

它不是某一种存储引擎,而是一组**抽象 + 协议**。任何实现这套抽象的系统都是 STM32_TokenBase 实例。

---

## 4. 四大核心抽象

### 4.1 Atom(语义原子)—— 最小可独立消费单元

Atom 不是行,而是一个**自洽的语义实体**:一个函数、一个类型、一个配置项、一个事实。每个 Atom 携带其完整身份与多种分辨率。

**Schema:**
```json
{
  "uri": "atom://stm32/uart_send",
  "kind": "function",
  "lens": { "...": "见 4.2" },
  "provenance": "Core/Src/uart.c:42",
  "embed": [0.012, -0.033, "..."],
  "version": "a1b2c3"
}
```

- **URI 寻址**:`atom://<scope>/<path>`,稳定、可引用。AI 可在回答中写「见 `atom://stm32/uart_send`」。
- **kind**:function / type / macro / config / fact / register …,决定可用 Lens。

### 4.2 Lens(多分辨率镜头)—— 同一 Atom 的多视图

一个 Atom 同时存储多个分辨率投影,AI 按需切换,**先廉价概览定位、再付费展开**:

| Lens | 分辨率 | 大致 token | 用途 |
| --- | --- | --- | --- |
| `overview` | 一句话摘要 | ~20 | 概览/定位 |
| `signature` | 函数签名/类型声明 | ~50 | 接口判断 |
| `body` | 完整实现 | ~200+ | 改码/深入 |
| `callgraph` | 调用/被调/引用 | ~50 | 关系定位 |
| `config` | 关联配置(.ioc/寄存器) | ~30 | 外设诊断 |

> 这是「渐进式披露(progressive disclosure)」的原生化:传统库要 AI 自己决定读多少,STM32_TokenBase 把分辨率做成一等维度。

### 4.3 Intent Query(意图查询)—— 声明式,内置规划

AI 不写 `SELECT`,而是声明**意图**,STM32_TokenBase 内部自动规划多跳检索并综合:

```
POST /query
{
  "intent": "定位串口初始化失败的可能原因",
  "budget_tokens": 2000,
  "scope": "atom://stm32/**",
  "hints": { "symbols": ["MX_USART2_UART_Init"], "error": "HAL_ERROR" }
}
```

DB 内部规划(示例):`uart_init 原子 → 取 signature+config → 找调用方 → 关联 .ioc 波特率配置 → 检查 Error_Handler 路径`。

- **规划器**:M1 用规则图遍历;M2 可选 LLM 辅助规划。
- 输出是综合后的上下文包,而非原始命中行。

### 4.4 Token Budget(预算契约)—— 一等约束

每次查询携带 token 预算,STM32_TokenBase **在预算内最大化信息增益**。这是传统 DB 完全没有的维度。

**调度算法(贪心背包变体):**
1. 多路召回候选 Atom × Lens 组合,每个标注 `(gain, cost_tokens)`;
2. 按优先级分桶:**精确命中 > 关系链 > 语义召回**;
3. 桶内按 `gain / cost` 降序贪心选取,直到预算用尽;
4. **分辨率降级**:若超预算,将已选 Atom 的 Lens 从 `body`→`signature`→`overview` 逐级降级,腾出预算纳入更多相关 Atom。

结果:给定 2000 token,模型拿到的是「**8 个高度相关函数的签名 + 2 个关键函数体**」,而非「1 个无关大文件的全文」。

### 4.5 增强:Provenance(证据指针)

每条返回事实附带 `provenance`(文件:行 / 寄存器地址 / 配置路径)。模型生成答案时引用它,**显著降低幻觉**,并支持回查验证。

### 4.6 增强:Diff Stream(变更流)

AI 最常问「这次改了什么 / 上一轮为何失败」。STM32_TokenBase 原生维护版本与变更:查询可带 `since=<version>`,只返回变更的 Atom。闭环调试天然受益。

---

## 5. 查询协议(Query Protocol)

一套面向 AI 客户端的、与传输无关的协议(可走 stdio / HTTP / **MCP**)。

### 5.1 请求
```json
{
  "intent": "<自然语言意图>",
  "budget_tokens": 2000,
  "scope": "atom://stm32/**",
  "hints": { "symbols": [], "errors": [], "files": [] },
  "since": "<可选版本,启用 Diff Stream>",
  "lens_pref": "auto"
}
```

### 5.2 响应(prompt-ready token 包)
```json
{
  "context_pack": "<已按 token 预算打包、可直接插入 prompt 的文本>",
  "tokens_used": 1840,
  "atoms": ["atom://stm32/MX_USART2_UART_Init", "..."],
  "provenance": { "atom://...": "Core/Src/main.c:88" },
  "next_suggestions": ["展开 uart_send 函数体", "查看 USART2 中断处理"]
}
```

- `context_pack` 是**可直接喂模型**的文本,带寻址标签与关系摘要;
- `next_suggestions` 支撑**迭代探索**(AI 下一步可下钻)。

### 5.3 寻址方案
```
atom://<scope>/<path>[#<lens>][@<version>]
atom://stm32/uart_send#body@v3
```
稳定、可缓存、可对比版本。

### 5.4 典型交互(迭代探索)
```
① query("串口为何不通", budget=500)   → 返回 overview 级 8 个 Atom
② query("展开 MX_USART2_UART_Init", budget=1500) → 返回其 body + 配置
③ query("谁调用了它", budget=500)     → 返回 callgraph
```

---

## 6. 数据模型与索引

- **存储**:**SQLite**(单文件 `.tokenbase/index.db`,随工程走、零服务)。
  - 表:`atoms(uri, kind, provenance, version, embed_blob)`、`lenses(uri, lens, content, tokens)`、`edges(src, rel, dst)`(调用/引用图)、`meta(key, val)`。
- **符号解析**:`ctags`(MVP,快)→ `libclang`(精确,理解宏/类型)。
- **语义索引**:`SCIP/LSIF` 作为可选高质量前端。
- **检索**:多路召回(精确符号 + 图遍历 N 跳 + 向量相似 + 关键字),由 Intent 规划器编排。

---

## 7. Token 经济学(核心指标)

STM32_TokenBase 引入专属度量,替代传统 DB 的 QPS/延迟:

| 指标 | 定义 |
| --- | --- |
| **信息密度** | 相关信息量 / token |
| **预算达成率** | 实际返回相关信息 / 预算内最优 |
| **命中率** | 返回 Atom 中被 AI 实际采纳的比例 |
| **幻觉关联率** | 返回但无关的比例(越低越好) |

这些指标可直接作为检索质量回归基准。

---

## 8. 分层架构(「新」的边界)

| 层 | 是否新 | 内容 |
| --- | --- | --- |
| **L3 范式层** | ✅ 全新(核心 IP) | Atom / Lens / Intent / Budget 抽象 |
| **L2 协议层** | ✅ 新 | 查询协议、prompt-ready 序列化、MCP 暴露 |
| **L1 实现层** | 🔁 可复用 | SQLite / 图索引 / 向量;日后可换专用 `.tokenbase` 格式 |
| **L0 引擎层** | 🔁 复用 | 除非追求学术级创新,后置 |

**结论**:把创新投入 L3/L2;L1/L0 站在巨人肩膀。日后为极致 token 效率,可为 Atom 设计专用二进制序列化(这是可选的真创新点)。

---

## 9. 落地路径

| 里程碑 | 交付 | 验证 |
| --- | --- | --- |
| **M0** | 本 RFC(范式定稿) | 评审通过 ✓ |
| **M1** | Atom + Lens + 寻址;ctags 解析 C → SQLite;**符号精确查询**(无向量) | 给定符号返回带定位的 Lens,token 显著低于喂全文 |
| **M2** | **Intent 规划器(规则版)+ Token Budget 调度器** | 预算约束下召回质量达标 |
| **M3** | 向量召回 + Provenance + Diff Stream | 多路召回融合,幻觉关联率下降 |
| **M4** | **MCP server** 暴露;独立孵化评估;`.tokenbase` 格式调研 | Claude/Codex/Cursor 共用一份索引 |

---

## 10. 非目标(边界)

- **不**做通用 OLTP/OLAP,不取代关系数据库;
- **不**追求高并发事务(面向单机 AI 工具);
- 第一版**不**做分布式 / 多租户;
- **不**重新实现编程语言解析器(复用 ctags/libclang/SCIP)。

---

## 11. 决策记录(原开放问题,已定)

1. **命名** ✅:**STM32_TokenBase**(先以 STM32 为案例验证可靠性;验证通过后再考虑去前缀通用化)。
2. **Atom 粒度** ✅:**函数级为默认**,类型/宏/全局变量同为 Atom;后续可配置更细粒度。
3. **Intent 规划** ✅:**M2 规则版图遍历优先**(可解释、零额外 token 成本);LLM 辅助规划留 M3+,仅用于模糊意图。
4. **增量触发** ✅:**文件保存自动触发**(watchman / inotify / Qt QFileSystemWatcher)。
5. **跨语言** ✅:**STM32(C)先行验证**;Python/Rust 待验证可靠后再扩。
6. **是否独立 repo** ✅:**独立孵化**(已拆为独立仓库,与 EmbeddedAiCoder 平级)。

---

## 12. 相关工作

经对 GitHub 同类项目的深读调研,现有方案分四类,均与 STM32_TokenBase **互补而非替代**:

### 12.1 语义/向量索引(code-as-document RAG)
- **CocoIndex / cocoindex-code**([github.com/cocoindex-io](https://github.com/cocoindex-io/cocoindex-code)):Rust 增量引擎 + tree-sitter 切块 + embedding,嵌入式 SQLite。**通用 RAG pipeline,缺 Atom/Lens/Intent/Budget 全部范式**,且依赖 Rust + ~1GB torch,与桌面工具「单文件 SQLite + 零服务」约束冲突。STM32_TokenBase 仅借鉴其增量与存储**形态**,不依赖其代码。

### 12.2 代码图 / 代码智能
- **SCIP / LSIF**([sourcegraph/scip](https://github.com/sourcegraph/scip)):编译器级精确符号图(定义/引用/类型/宏),protobuf 产物。**STM32_TokenBase 直接以其数据模型(Symbol URI / Occurrence / role 位)作为 Atom 存储蓝本**。C/C++ indexer `scip-clang` 为 Beta 且**无 Windows 原生二进制**,故 M1 不采用其为前端,但 schema 对齐以便 M2 可插拔。
- **Meta Glean**:大规模代码图索引(2021 开源),clang-based,自有 schema。

### 12.3 Token-aware 代码地图(最接近 STM32_TokenBase 理念)
- **Aider repo map**([github.com/Aider-AI/aider](https://github.com/Aider-AI/aider)):tree-sitter 提符号 + **Personalized PageRank** 排序 + token 预算内压缩成静态地图。**STM32_TokenBase 直接复用其符号提取 query、PageRank 边权公式、TreeContext 渲染**作为 M1 地基;差异在于 Aider 是「预处理生成静态地图喂 LLM」,STM32_TokenBase 是「查询时按 Intent 动态调度多分辨率 Lens」。

### 12.4 其他
- **GraphRAG**:图 + 向量混合检索,STM32_TokenBase 多路召回受其启发。
- **向量库**(Chroma / Qdrant / FAISS / sqlite-vec):L1 实现选项,M1 不启用。
- **MCP(Model Context Protocol)**:STM32_TokenBase 的 L2 协议经 MCP 暴露,服务 Claude / Codex / Cursor 等。
- **LSP**:面向 IDE / 人;STM32_TokenBase 面向 AI,读者不同。

> **调研结论**:基础能力(embedding / tree-sitter / SCIP / repo-map)均已被解决,STM32_TokenBase 不重造,作为 L1 复用;STM32_TokenBase 的贡献集中在 L3/L2 范式与协议层(token budget + intent + 多分辨率)。详细复用/自研清单见附录 A。

---

## 13. 与 EmbeddedAiCoder 的关系 / 独立孵化

- **短期**:作为 EmbeddedAiCoder 的上下文引擎,支撑 F-07(源码上下文检索)与 F-23(知识库),直接降低 AI 改码的 token 成本。
- **中期**:封装为 **MCP server**,让 Claude Opus / Codex / Claude Code **共用一份索引**。
- **长期**:STM32_TokenBase 的价值**可能大于** EmbeddedAiCoder 本身,具备独立开源与标准化(`.tokenbase` 格式)的潜力,届时拆分为独立仓库与项目。

---

---

## 附录 A:M1 选型与复用决策

> 基于对 Aider repo map、SCIP/scip-clang、CocoIndex 的深读调研得出。

### A.1 选型(核心一句话)
**自建轻量 Python;ctags + tree-sitter 双前端;Atom schema 对齐 SCIP;首版无向量。**

### A.2 直接复用

| 复用项 | 来源 | 用法 |
| --- | --- | --- |
| C 的 tree-sitter def query | Aider `c-tags.scm` | 提取 Atom 定义 |
| Personalized PageRank + 边权公式 | Aider `get_ranked_tags`(`√引用 × 命名风格 × 上下文`) | Atom 重要性排序起点 |
| TreeContext 层级渲染 | Aider / grep_ast | 实现 Lens「签名」档 |
| 二分 token 收敛 + 行采样估算 | Aider | 单 Lens 内裁剪 |
| SCIP 数据模型(Symbol URI / Occurrence / role 位) | `scip.proto` | Atom 存储设计蓝本 |
| 增量哈希缓存 + 嵌入式 SQLite + MCP 单 tool | CocoIndex | 形态借鉴,代码自写(~50 行) |

### A.3 必须自研(三者皆无)

1. **C 的 reference query** —— Aider 的 C query 仅抓 def,靠 Pygments 兜底(无行号、有噪声);STM32_TokenBase 须自写 `c-refs.scm`。
2. **`atom://` URI 体系**(对齐 SCIP 文法)+ 稳定身份。
3. **Lens 多分辨率**(概览/签名/全文/调用图 四档)。
4. **Intent Query 多跳规划器**。
5. **Token Budget 调度**(per-Query,在 Lens 间分配以最大化信息增益)。
6. **Prompt-ready 序列化** + SQLite importer / 查询层。

### A.4 关键架构决策

- **双前端、schema 对齐 SCIP、存储前端无关**:Atom 表设计为 `(atom_uri, kind, file, line, role)`,ctags 与未来 SCIP 灌入皆同 → M1 用 ctags/tree-sitter 不阻塞,M2 加 scip-clang(高精度,Linux/WSL)为纯增量。
- **M1 不用 scip-clang**:无 Windows 原生二进制 + 需 compile_commands + Beta;而 STM32 主战场在 Windows,此为决定性因素。
- **不依赖 CocoIndex**:拖 Rust 引擎 + ~1GB torch,与「单文件 SQLite + 零服务 + 嵌入桌面应用」硬冲突。

---

*本 RFC 欢迎评审与迭代。后续修订以版本号递增记录于本表。*
