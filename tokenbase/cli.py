"""
tokenbase.cli — 命令行入口(M1:index / query 两个子命令)

用法:
  python -m tokenbase index <dir>      # 建索引,写 .tokenbase/index.db
  python -m tokenbase query <symbol>   # 查询符号,返回 signature Lens + 文件:行

也可以用 console_script:`tokenbase index <dir>`(见 setup 自带的 __main__)。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import PARSER_VERSION, __version__
from .lens import make_signature_lens, format_query_result
from .parser import discover_c_files, parse_file
from .storage import Store
from .tokens import count_tokens


# .tokenbase 目录名:随工程走、零服务(RFC 第 6 节)
INDEX_DIRNAME = ".tokenbase"
DB_FILENAME = "index.db"


def _index_db_path(root: Path) -> Path:
    return root / INDEX_DIRNAME / DB_FILENAME


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.directory).resolve()
    if not root.is_dir():
        print(f"错误:目录不存在:{root}", file=sys.stderr)
        return 2

    project = args.project or root.name
    db_path = _index_db_path(root)
    store = Store(db_path)
    store.set_meta("project", project)
    store.set_meta("parser_ver", PARSER_VERSION)

    files = discover_c_files(root)
    print(f"[index] 工程名:{project}  根目录:{root}")
    print(f"[index] 发现 {len(files)} 个 C 源文件(.c/.h)")

    parsed_count = 0
    skipped_count = 0
    total_occs = 0
    for f in files:
        rel = f.relative_to(root).as_posix()
        sha = Store.sha256_of(f)
        if not args.force and not store.needs_reparse(rel, sha):
            skipped_count += 1
            continue
        # 增量:重解析前先清除该文件的旧记录
        store.forget_file(rel)
        occs = parse_file(f, root)
        store.replace_atoms_and_lenses(project, occs, make_signature_lens)
        store.mark_parsed(rel, sha)
        parsed_count += 1
        total_occs += len(occs)
        defs = sum(1 for o in occs if o.role == "def")
        print(f"   · {rel}: {len(occs)} 个出现点(def={defs})")

    def_syms = store.list_def_symbols()
    print(f"[index] 完成。重新解析 {parsed_count} 个,跳过(缓存命中) {skipped_count} 个。")
    print(f"[index] 共 {len(def_syms)} 个有定义的符号(Atom)。数据库:{db_path}")
    store.close()
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    root = Path(args.directory).resolve()
    db_path = _index_db_path(root)
    if not db_path.exists():
        print(f"错误:未找到索引数据库,请先 `index`: {db_path}", file=sys.stderr)
        return 2

    store = Store(db_path)
    rows = store.query_symbol(args.symbol)
    if not rows:
        print(f"(未找到符号 {args.symbol!r})")
        store.close()
        return 1

    # 工程名(从 meta 取,fallback 到目录名)
    project = store.get_meta("project", default=root.name)

    output = format_query_result(
        args.symbol,
        rows,
        get_lens=lambda uri: store.get_lens(uri),
        get_file_line_text=lambda f: f,
    )
    print(output)

    # —— token 对比(M1 核心验证:证明省 token)——
    lens_tokens = 0
    seen_uris = set()
    for r in rows:
        if r["atom_uri"] not in seen_uris:
            seen_uris.add(r["atom_uri"])
            lens_row = store.get_lens(r["atom_uri"])
            if lens_row:
                lens_tokens += lens_row["tokens"]

    # 对比基准:把所有「涉及到的文件」全文喂进去要多少 token
    involved_files = sorted({r["file"] for r in rows})
    full_tokens = 0
    for rel in involved_files:
        p = root / rel
        if p.exists():
            full_tokens += count_tokens(p.read_text(encoding="utf-8", errors="replace"))

    # 对比基准 2:整个工程的全部 .c/.h
    all_c_files = discover_c_files(root)
    whole_project_tokens = sum(
        count_tokens(f.read_text(encoding="utf-8", errors="replace"))
        for f in all_c_files
    )

    print("—— token 对比 ——")
    print(f"  query 返回(signature Lens + provenance): {count_tokens(output):>6} tokens")
    print(f"  Lens 内容本身:                              {lens_tokens:>6} tokens")
    print(f"  喂「涉及文件」全文({len(involved_files)} 个):            {full_tokens:>6} tokens")
    print(f"  喂「整个工程」全文({len(all_c_files)} 个 .c/.h):      {whole_project_tokens:>6} tokens")
    if whole_project_tokens > 0:
        ratio = count_tokens(output) / whole_project_tokens * 100
        print(f"  ⇒ Lens 仅占整个工程的 {ratio:.1f}%")
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tokenbase",
        description="STM32_TokenBase — AI-first 代码数据库(M1)",
    )
    p.add_argument("--version", action="version", version=f"tokenbase {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("index", help="解析目录下 C 代码,建立索引")
    pi.add_argument("directory", help="工程根目录")
    pi.add_argument("--project", default=None, help="工程名(默认取目录 basename)")
    pi.add_argument("--force", action="store_true", help="强制全量重解析,忽略缓存")
    pi.set_defaults(func=cmd_index)

    pq = sub.add_parser("query", help="查询符号,返回 signature Lens + 定位")
    pq.add_argument("symbol", help="符号名(函数/类型/宏)")
    pq.add_argument("directory", nargs="?", default=".",
                    help="工程根目录(默认当前目录)")
    pq.set_defaults(func=cmd_query)
    return p


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK,中文输出会乱码;强制 UTF-8。
    # 放这里保证 `python -m` 与 console_script `tokenbase` 两个入口都生效。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())