"""
tokenbase.tokens — Token 估算(M1:用于证明 query 显著省 token)

策略:
  1. 优先用 tiktoken 的 cl100k_base(Claude/GPT 同量级 BPE),最贴近真实;
  2. tiktoken 初始化失败(如离线缺 vocab)时,回退到「字符数 / 4」粗估。

M1 只需估算对比数字,不做 Token Budget 调度(那是 M2)。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""
from __future__ import annotations

try:
    import tiktoken  # type: ignore
    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        """估算 text 的 token 数(cl100k_base BPE)。"""
        return len(_ENC.encode(text))
except Exception:  # 离线 / 缺 vocab
    _ENC = None

    def count_tokens(text: str) -> int:
        """估算 token 数(粗估:字符数 / 4)。"""
        return max(1, len(text) // 4)
