# STM32_TokenBase — AI-First Database

> 一种专为 AI 消费的数据库范式:以「语义原子(Atom)」为基本单元、以「token 预算(Token Budget)」为一等约束、以「意图查询(Intent Query)」为接口、以「prompt-ready 包」为输出。

## 这是什么

传统数据库为「**人读**」设计——优化存储成本与查询延迟,以行/文档为单位。STM32_TokenBase 为「**AI 读**」设计:当消费者是大模型(以 token 为食、有上下文窗口上限、会幻觉、需要可追溯证据),优化目标随之变为 **token 经济学**——在固定 token 预算内,向 AI 传递最高密度的相关信息。

STM32_TokenBase 不是某一种存储引擎,而是一组**抽象 + 协议**。任何实现这套抽象的系统都是 STM32_TokenBase 实例。

## 四核心抽象

| 抽象 | 一句话 |
| --- | --- |
| **Atom** | 最小可独立消费单元(函数/类型/事实),带稳定 URI `atom://...` |
| **Lens** | 同一 Atom 的多分辨率投影(概览/签名/全文/调用图),按需切换 |
| **Intent Query** | 声明式意图查询,DB 内部自动规划多跳检索 |
| **Token Budget** | 查询携带 token 预算,预算内最大化信息增益(贪心背包调度) |

外加两个增强:**Provenance**(证据指针,防幻觉)、**Diff Stream**(变更流,AI 最常问「改了什么」)。

## 状态

Draft v0.2。**M0(RFC 定稿)✓** · **M1(最小可用原型)✓** —— 已实现:tree-sitter 解析 C(含自研 reference 提取)→ 单文件 SQLite → `atom://` 寻址 → signature Lens → `index`/`query` CLI → 增量缓存。实测 query 返回 token 仅占整个工程的 ~3–7%。下一步 **M2**:Intent 规划器 + Token Budget 调度。

## 快速开始(M1)

```bash
py -3.13 -m venv .venv
.venv/Scripts/activate          # Windows(Linux/macOS 用 source .venv/bin/activate)
pip install -e .

# 建索引:解析工程下所有 .c/.h,写 .tokenbase/index.db
tokenbase index examples/stm32_mini/

# 查询符号:返回 signature Lens + 文件:行 + token 对比
tokenbase query uart_send examples/stm32_mini/
```

查询输出(prompt-ready,可直接喂模型):
```
# atom://stm32_mini/uart_send  [function]  (21 tokens)
int uart_send(const uint8_t *data, uint32_t len);
— definition: examples/stm32_mini/uart.c:35, uart.h:31
— references:  main.c:37 (call)
```

## 文档

- 📄 [设计白皮书 RFC](docs/RFC.md) —— 范式定义、四抽象(含 schema)、查询协议、与传统 DB 对比、token 经济学、分层架构、落地路径 M0–M4、附录 A(M1 选型与复用决策)

## 起源与许可

起源于 [EmbeddedAiCoder](https://github.com/KiteFlyerX/STM32EmbeddedAiCoder)(STM32 编码自动化工具)的上下文引擎需求,因其价值大于宿主项目而独立孵化。许可 **GPLv3**。
