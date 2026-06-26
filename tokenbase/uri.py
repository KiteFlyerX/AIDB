"""
tokenbase.uri — atom:// URI 体系(附录 A.3 必须自研项 #2)

URI 文法(对齐 RFC 5.3 / 附录 A.4 的稳定身份诉求):

    atom://<project>/<symbol>

  - project:工程名(取索引根目录的 basename),作为 scope。
  - symbol :符号标识符(函数名 / 类型名 / 宏名 / 全局变量名)。

设计取舍:
  * M1 用「裸符号名」而非「带文件路径的路径」,因为 STM32 工程里符号通常
    全局唯一,且符合人类引用习惯(「uart_send 这个函数」)。
  * 当同名符号在多个文件出现(如 .h 声明 + .c 定义,或同名 static)时,
    用 role(def/ref)与 file/line 区分,URI 仍保持「符号级」稳定身份;
    查询时把同 URI 的多处 occurrence 一并返回。
  * 对附录 A.4 的 (atom_uri, kind, file, line, role) 表,atom_uri 作主键的
    「符号身份」,file/line/role 作「出现点」——这正是 SCIP Symbol/occurrence
    的分离思想。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""

from __future__ import annotations
import re
from urllib.parse import quote, unquote

_SCHEME = "atom://"


def make_uri(project: str, symbol: str) -> str:
    """根据工程名与符号名构造 atom:// URI。

    >>> make_uri("stm32_mini", "uart_send")
    'atom://stm32_mini/uart_send'
    """
    if not project or not symbol:
        raise ValueError("project 与 symbol 均不可为空")
    # 仅做基本净化:工程名/符号名一般是合法 C 标识符,做防御性 quote
    p = re.sub(r"[^A-Za-z0-9_.\-]", "_", project)
    s = quote(symbol, safe="")
    return f"{_SCHEME}{p}/{s}"


def parse_uri(uri: str) -> tuple[str, str]:
    """拆解 atom:// URI 为 (project, symbol)。

    >>> parse_uri("atom://stm32_mini/uart_send")
    ('stm32_mini', 'uart_send')
    """
    if not uri.startswith(_SCHEME):
        raise ValueError(f"非法 atom URI(缺少 scheme): {uri!r}")
    body = uri[len(_SCHEME):]
    if "/" not in body:
        raise ValueError(f"非法 atom URI(缺少符号段): {uri!r}")
    project, _, symbol = body.partition("/")
    return project, unquote(symbol)
