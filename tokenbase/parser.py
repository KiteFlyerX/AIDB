"""
tokenbase.parser — C 符号解析(附录 A.2 复用 + A.3 自研)

复用(Aider c-tags.scm 思路):
  - def 提取:function / typedef / macro / struct / enum / 全局变量

自研(A.3 #1,C 的 reference query):
  - reference 提取:函数调用位、被调标识符、字段访问。
    Aider 的 C query 仅抓 def,ref 靠 Pygments 兜底(无行号、有噪声);
    此处用 tree-sitter 自写 c-refs,精确到行号。

atom 粒度对齐 RFC 第 11.2 条:函数级为默认,类型/宏/全局变量同为 Atom。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tree_sitter_c
from tree_sitter import Language, Parser, Query, QueryCursor, Node

# 复用 tree-sitter-language-pack 也行;这里直接用 tree-sitter-c 更轻量。
_LANGUAGE: Language | None = None
_PARSER: Parser | None = None

# —— def query(对齐 Aider c-tags.scm 的 def 抓取思路)——
# 把 def 分为几类 capture:name = 函数名;tname = typedef 名;sname = struct/enum 名;
# macro = 宏名;gvar = 全局/文件作用域变量名。
# 注意函数指针与带 static/指针返回值的 declarator 嵌套,需多分支覆盖。
DEF_QUERY_SRC = r"""
(function_definition
  declarator: [
    (function_declarator declarator: (identifier) @function.def.name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @function.def.name))
  ])

; 函数原型(头文件里的声明)也算该函数的 def occurrence
(declaration
  declarator: [
    (function_declarator declarator: (identifier) @prototype.def.name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @prototype.def.name))
  ])

(type_definition declarator: (type_identifier) @typedef.def.name)

(struct_specifier name: (type_identifier) @struct.def.name)
(enum_specifier name: (type_identifier) @enum.def.name)

(preproc_def name: (identifier) @macro.def.name)
(preproc_function_def name: (identifier) @macrofn.def.name)

; 文件作用域变量(全局变量)。declarator 可能是裸 identifier、
; array_declarator(数组)或 init_declarator(带初值)。函数原型用的是
; function_declarator,已被上面 prototype.def.name 抓走,互不重叠。
(declaration
  declarator: (identifier) @var.def.name)
(declaration
  declarator: (array_declarator declarator: (identifier) @var.def.name))
(declaration
  declarator: (init_declarator declarator: (identifier) @var.def.name))
"""

# —— ref query(自研,A.3 #1)——
# 抓三类精准 reference:
#   1. 函数调用位的被调标识符: call_expression -> function identifier
#   2. 类型引用: type_identifier(如函数参数/变量声明里的 uart_cfg_t)
#   3. 裸 identifier 引用:宏/常量引用(如 LED_PIN),以及对外部函数名的引用。
#      这条会抓到所有 identifier(含变量定义名/参数名),需在后处理里过滤——
#      排除「父节点是 declarator」(那是定义/声明,不是引用),并只保留
#      「此前已抓为 def 的名字」或「全大写宏式」。
# 不抓:field_identifier(字段名不是独立 Atom)、字符串/数字。
REF_QUERY_SRC = r"""
( call_expression function: (identifier) @call.ref.name )
( call_expression
  function: (field_expression field: (field_identifier) @call.field.ref) )
( type_identifier ) @type.ref.name
( identifier ) @ident.ref.name
"""


@dataclass(frozen=True)
class SymbolOccurrence:
    """一个符号在某文件某行的出现点。"""
    name: str           # 符号名(标识符文本)
    kind: str           # function / prototype / typedef / struct / enum / macro / var /
                        #   call / type_ref / ident_ref / field_ref
    role: str           # "def" 或 "ref"
    file: str           # 相对索引根的路径(POSIX 风格)
    line: int           # 1-based 行号
    node_text: str = "" # 用于 def 时取签名(截取到函数定义行的文本段)


def _get_parser() -> Parser:
    global _LANGUAGE, _PARSER
    if _PARSER is None:
        _LANGUAGE = Language(tree_sitter_c.language())
        _PARSER = Parser(_LANGUAGE)
    return _PARSER


def _captures(root: Node, src: str) -> QueryCursor:
    """语法糖:构造 QueryCursor(每次解析新建,避免状态污染)。"""
    return QueryCursor


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line_of(node: Node) -> int:
    return node.start_point[0] + 1  # 转 1-based


# 函数体/控制块内的节点类型——出现这些祖先则说明是局部作用域,非文件作用域
_LOCAL_SCOPE_ANCESTORS = frozenset({
    "compound_statement", "for_statement", "while_statement", "do_statement",
    "if_statement", "else_clause", "switch_statement", "case_statement",
    "labeled_statement", "block",
})


def _is_file_scope(node: Node) -> bool:
    """判断 identifier 是否处于「文件作用域」(顶层全局变量)。

    向上遍历祖先,若先遇到 translation_unit 则为文件作用域;
    若先遇到函数体/控制块则不是(局部变量)。
    """
    cur = node.parent
    while cur is not None:
        if cur.type in _LOCAL_SCOPE_ANCESTORS:
            return False
        if cur.type == "translation_unit":
            return True
        cur = cur.parent
    return True  # 兜底:无祖先视为文件作用域


# capture 名 -> (kind, role)
_DEF_MAP = {
    "function.def.name": ("function", "def"),
    "prototype.def.name": ("prototype", "def"),
    "typedef.def.name": ("typedef", "def"),
    "struct.def.name": ("struct", "def"),
    "enum.def.name": ("enum", "def"),
    "macro.def.name": ("macro", "def"),
    "macrofn.def.name": ("macro", "def"),
    "var.def.name": ("var", "def"),
}

# ref capture 名 -> (kind, role)
_REF_MAP = {
    "call.ref.name": ("call", "ref"),
    "call.field.ref": ("call", "ref"),      # p->method() 的方法调用(归为 call)
    "type.ref.name": ("type_ref", "ref"),
    "ident.ref.name": ("ident_ref", "ref"),
}


def parse_c_source(source: bytes) -> list[SymbolOccurrence]:
    """解析一段 C 源码,返回所有符号出现点(def + ref)。

    file 字段留空,由上层 parse_file 填入相对路径。
    """
    parser = _get_parser()
    tree = parser.parse(source)
    root = tree.root_node

    occs: list[SymbolOccurrence] = []

    # —— def ——
    lang = _LANGUAGE  # type: ignore[assignment]
    assert lang is not None
    def_q = Query(lang, DEF_QUERY_SRC)
    def_caps = QueryCursor(def_q).captures(root)
    for cap_name, nodes in def_caps.items():
        if cap_name not in _DEF_MAP:
            continue
        kind, role = _DEF_MAP[cap_name]
        for n in nodes:
            name = _node_text(n, source)
            # var.def.name 只保留「全局变量」:父链直达 translation_unit 的才是文件作用域;
            # 函数体内的局部变量(父链含 compound_statement/for_statement 等)不是 Atom,
            # 按 RFC 11.2「函数级为默认 + 全局变量」原则丢弃,避免噪声。
            if cap_name == "var.def.name" and not _is_file_scope(n):
                continue
            # 对 function/prototype/var,签名 = 整个声明/定义的首行(到 '{' 或 ';')
            sig = _signature_text(n, source) if role == "def" else ""
            occs.append(SymbolOccurrence(
                name=name, kind=kind, role=role, file="", line=_line_of(n),
                node_text=sig,
            ))

    # —— ref(自研,A.3 #1)——
    ref_q = Query(lang, REF_QUERY_SRC)
    ref_caps = QueryCursor(ref_q).captures(root)

    # 已知 def 名字集合(用于 ident_ref 过滤「真正的符号引用」)
    known_def_names = {o.name for o in occs if o.role == "def"}
    # def 名字 + (行,列) 集合:同符号同行的 def 不算 ref
    def_name_points = {(o.name, o.line) for o in occs if o.role == "def"}
    # call 位点集合:ident_ref 若重合某个 call,则已由 call 抓走,跳过避免重复
    call_points: set[tuple[str, int]] = set()
    for n in ref_caps.get("call.ref.name", []):
        call_points.add((_node_text(n, source), _line_of(n)))

    for cap_name, nodes in ref_caps.items():
        if cap_name not in _REF_MAP:
            continue
        kind, role = _REF_MAP[cap_name]
        for n in nodes:
            name = _node_text(n, source)
            line = _line_of(n)
            # 去重:同符号同行的 def 不算 ref(避免把函数定义名当调用)
            if (name, line) in def_name_points:
                continue
            # ident_ref 噪声最大:它抓了所有 identifier(含变量名/参数名/定义名)。
            # 过滤规则:
            #   a) 该 identifier 已被当作 call 抓走 -> 跳过;
            #   b) 父节点是 declarator*/parameter_declaration -> 声明里的被定义名,丢弃;
            #   c) 否则只保留「全大写宏式」或「此前已抓为 def 的名字」(真正的符号引用)。
            if kind == "ident_ref":
                if (name, line) in call_points:
                    continue
                parent_type = n.parent.type if n.parent else ""
                declarator_parents = {
                    "declarator", "array_declarator", "init_declarator",
                    "parameter_declaration", "function_declarator",
                    "pointer_declarator", "parenthesized_declarator",
                    "abstract_pointer_declarator",
                }
                if parent_type in declarator_parents:
                    continue
                looks_macro = name.isupper() or (
                    "_" in name and name.replace("_", "").isupper()
                )
                if name not in known_def_names and not looks_macro:
                    continue
            occs.append(SymbolOccurrence(
                name=name, kind=kind, role=role, file="", line=line, node_text="",
            ))

    return occs


def _signature_text(def_node: Node, source: bytes) -> str:
    """从 def 名字节点向上找到包含返回类型与参数的声明头,截取其首行作为签名。

    对 function_definition:取到 '{' 之前;
    对 prototype/declaration:取到 ';' 之前;
    对 typedef:取到 typedef 名字(含),补 ';'(结构体本体略,签名只需身份);
    对 struct/enum:取「struct/enum Name;」;
    对 macro:整行。
    """
    node = def_node
    targets = {"function_definition", "type_definition", "declaration",
               "preproc_def", "preproc_function_def", "struct_specifier",
               "enum_specifier"}
    while node is not None and node.type not in targets:
        node = node.parent
    if node is None:
        node = def_node

    raw = _node_text(node, source)

    # typedef:截到 type_identifier(名字)结束,补 ';'(省略结构体字段,签名聚焦身份)
    if node.type == "type_definition":
        # 找 declarator:type_identifier 子节点位置
        tid = None
        for ch in _iter_all(node):
            if ch.type == "type_identifier":
                tid = ch
                break
        if tid is not None:
            up_to = source[node.start_byte: tid.end_byte].decode("utf-8", "replace")
            return " ".join(up_to.strip().split()) + ";"

    # struct/enum specifier(作为顶层 type 定义时):返回「struct Name;」式身份
    if node.type in ("struct_specifier", "enum_specifier"):
        head = node.child_by_field_name("name")
        kw = "struct" if node.type == "struct_specifier" else "enum"
        if head is not None:
            return f"{kw} {head.text.decode('utf-8','replace')};"

    # function / prototype / declaration:取到第一个 '{' 或 ';' 之前(含)
    cut = raw
    for sep in ("{", ";"):
        idx = cut.find(sep)
        if idx != -1:
            cut = cut[: idx + 1]
    first = cut.strip().splitlines()
    return " ".join(first[0].split()) if first else raw.strip()


def _iter_all(node: Node):
    """深度优先遍历所有后代节点。"""
    stack = list(node.children)
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(cur.children)


def parse_file(path: Path, root: Path) -> list[SymbolOccurrence]:
    """解析单个 C 文件,返回带相对路径的出现点列表。"""
    source = path.read_bytes()
    rel = path.relative_to(root).as_posix()
    occs = parse_c_source(source)
    # 填入相对路径
    return [SymbolOccurrence(o.name, o.kind, o.role, rel, o.line, o.node_text)
            for o in occs]


def discover_c_files(root: Path) -> list[Path]:
    """递归发现根目录下的所有 C 源文件(.c/.h)。"""
    files = []
    for ext in ("*.c", "*.h"):
        files.extend(root.rglob(ext))
    # 排除 .tokenbase 目录自身
    return sorted(p for p in files if ".tokenbase" not in p.parts)
