"""
tokenbase.lens — Lens 多分辨率渲染(附录 A.2 复用 + A.3 #3 自研)

M1 实现:
  - signature 档(必做):函数签名 / 类型声明 / 宏定义行。
    来源:parser 在 def 时已截取的 node_text(签名头)。
    渲染:格式化为「kind  symbol  签名  // file:line」单行/多行块。
  - overview 档(可选):一句话。M1 用「kind + symbol」占位,真正摘要留 M2。

可选增强(附录 A.2 TreeContext):用 grep_ast.TreeContext 渲染代码骨架。
M1 实测 TreeContext 在某些参数下会卡死,故仅做「可用性探测」,不可用时回退
到纯签名文本——保证 M1 稳定。TreeContext 思路(参考 Aider render_tree)
留作 M2 优化。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""
from __future__ import annotations

from .tokens import count_tokens

_KIND_LABEL = {
    "function": "func",
    "prototype": "proto",
    "typedef": "type",
    "struct": "struct",
    "enum": "enum",
    "macro": "macro",
    "var": "var",
}


def make_signature_lens(symbol: str, kind: str, signature_text: str) -> tuple[str, int]:
    """生成 signature 档内容。

    返回 (content, tokens)。content 形如:
        [func] uart_send
        int uart_send(const uint8_t *data, uint32_t len);
    """
    label = _KIND_LABEL.get(kind, kind)
    sig = signature_text.strip() or symbol
    content = f"[{label}] {symbol}\n{sig}"
    return content, count_tokens(content)


def make_overview_lens(symbol: str, kind: str) -> tuple[str, int]:
    """生成 overview 档(一句话,占位)。M2 接 LLM/规则摘要替换。"""
    label = _KIND_LABEL.get(kind, kind)
    content = f"[{label}] {symbol}"
    return content, count_tokens(content)


def format_query_result(symbol: str, rows, get_lens, get_file_line_text) -> str:
    """把符号查询结果格式化为 prompt-ready 文本。

    rows:atoms 表的 def+ref 出现点列表(sqlite3.Row)。
    get_lens:callable(atom_uri)->(content, tokens)|None
    get_file_line_text:callable(file)->该文件路径(用于 provenance)

    输出形如:
        # atom://stm32_mini/uart_send  [func]

        ```c
        int uart_send(const uint8_t *data, uint32_t len);
        ```
        — definition: examples/stm32_mini/uart.c:30
        — references:
          • examples/stm32_mini/uart.c:35   (call)
          • examples/stm32_mini/main.c:25   (call)
    """
    if not rows:
        return f"(无符号 {symbol!r} 的命中)\n"

    lines: list[str] = []
    # 取一个 def 行作为代表
    defs = [r for r in rows if r["role"] == "def"]
    refs = [r for r in rows if r["role"] == "ref"]
    primary = defs[0] if defs else rows[0]
    atom_uri = primary["atom_uri"]

    # Lens 头
    lens = get_lens(atom_uri)
    if lens:
        content, tokens = lens
        lines.append(f"# {atom_uri}  [{primary['kind']}]  ({tokens} tokens)")
        lines.append("")
        lines.append("```c")
        lines.append(content)
        lines.append("```")
    else:
        lines.append(f"# {atom_uri}  [{primary['kind']}]")
        lines.append("```c")
        lines.append(symbol)
        lines.append("```")

    # Provenance:定义点
    lines.append("")
    if defs:
        lines.append("— definition:")
        for d in defs:
            lines.append(f"    {d['file']}:{d['line']}")

    # References
    if refs:
        lines.append("— references:")
        for r in refs:
            lines.append(f"    {r['file']}:{r['line']}  ({r['kind']})")

    return "\n".join(lines) + "\n"
