"""
tokenbase — STM32_TokenBase 的 Python 实现(M1 里程碑)

STM32_TokenBase 是一个 AI-first 的代码数据库:解析 C 代码 → 存 SQLite →
按符号查询返回带定位的多分辨率 Lens,在固定 token 预算内最大化信息密度。

M1 范围(严格):
  - C 符号解析:tree-sitter(C grammar)提取 def,自研 reference 提取
  - 单文件 SQLite 存储(.tokenbase/index.db),Atom schema 对齐附录 A.4
  - atom:// URI 寻址
  - Lens signature 档(函数签名/类型声明)
  - CLI:tokenbase index <dir> / tokenbase query <symbol>
  - 增量缓存:(path, sha256, parser_ver) 只重解析变更文件

不做:向量/embedding、Intent 规划器、Token Budget 调度、MCP server。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""

__version__ = "0.1.0-m1"
PARSER_VERSION = "tree-sitter-c/m1.0"  # 解析器版本,变更则触发全量重解析
