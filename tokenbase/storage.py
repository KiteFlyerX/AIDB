"""
tokenbase.storage — SQLite 存储层(单文件 .tokenbase/index.db)

schema 对齐附录 A.4:Atom 表 = (atom_uri, kind, file, line, role)。
  - atoms:每个「符号 × 出现点」一行(atom_uri 是符号身份,file/line/role 是出现点)。
  - lenses:每个 atom_uri × lens 档 一行;M1 实现 signature 档。
  - cache:增量缓存 (path, sha256, parser_ver),只重解析变更文件。
  - meta:工程元信息(project 名、parser_ver、索引时间)。

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (c) KiteFlyerX
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from . import PARSER_VERSION
from .parser import SymbolOccurrence

# role 取值(对齐 SCIP role 思想:M1 简化为 def/ref 两类)
ROLE_DEF = "def"
ROLE_REF = "ref"

LENS_SIGNATURE = "signature"  # M1 必做档
LENS_OVERVIEW = "overview"    # M1 可选档(预留)


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Atom 出现点表:一个符号可能在多处出现(.h 声明 + .c 定义 + 多处调用)
CREATE TABLE IF NOT EXISTS atoms (
    atom_uri  TEXT NOT NULL,   -- 符号稳定身份 atom://<project>/<symbol>
    symbol    TEXT NOT NULL,   -- 符号名(冗余,便于查询)
    kind      TEXT NOT NULL,   -- function / typedef / struct / enum / macro / var / prototype
    file      TEXT NOT NULL,   -- 相对索引根的路径
    line      INTEGER NOT NULL,-- 1-based 行号
    role      TEXT NOT NULL    -- 'def' 或 'ref'
);
CREATE INDEX IF NOT EXISTS idx_atoms_symbol ON atoms(symbol);
CREATE INDEX IF NOT EXISTS idx_atoms_uri    ON atoms(atom_uri);
CREATE INDEX IF NOT EXISTS idx_atoms_uri_def ON atoms(atom_uri) WHERE role='def';

-- Lens 多分辨率表:每 (atom_uri, lens) 一行
CREATE TABLE IF NOT EXISTS lenses (
    atom_uri TEXT NOT NULL,
    lens     TEXT NOT NULL,    -- 'signature' / 'overview' / 'body' / ...
    content  TEXT NOT NULL,    -- 该分辨率的文本内容
    tokens   INTEGER NOT NULL  -- 该内容的 token 估算
);
CREATE INDEX IF NOT EXISTS idx_lenses_uri ON lenses(atom_uri);

-- 增量缓存:文件内容哈希 + 解析器版本;二者未变则跳过解析
CREATE TABLE IF NOT EXISTS file_cache (
    path        TEXT PRIMARY KEY,  -- 相对索引根的路径
    sha256      TEXT NOT NULL,
    parser_ver  TEXT NOT NULL,
    parsed_at   REAL NOT NULL
);
"""


class Store:
    """SQLite 存储句柄,封装建库、写入、查询。"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False:CLI 单线程,留余地给未来 MCP
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # —— meta ——
    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # —— 增量缓存 ——
    @staticmethod
    def sha256_of(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()

    def needs_reparse(self, rel_path: str, sha: str) -> bool:
        """根据 (sha256, parser_ver) 判断是否需要重新解析。"""
        row = self.conn.execute(
            "SELECT sha256, parser_ver FROM file_cache WHERE path=?", (rel_path,)
        ).fetchone()
        if row is None:
            return True
        return row["sha256"] != sha or row["parser_ver"] != PARSER_VERSION

    def mark_parsed(self, rel_path: str, sha: str) -> None:
        self.conn.execute(
            "INSERT INTO file_cache(path,sha256,parser_ver,parsed_at) VALUES(?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "  sha256=excluded.sha256, parser_ver=excluded.parser_ver, "
            "  parsed_at=excluded.parsed_at",
            (rel_path, sha, PARSER_VERSION, time.time()),
        )
        self.conn.commit()

    def forget_file(self, rel_path: str) -> None:
        """删除某文件关联的所有 atom 出现点(重解析前调用)。

        同时清除「该文件贡献了 def」的 URI 的 lens,避免旧 lens 残留。
        对「该文件只有 ref、def 在别处」的 URI,保留 lens(def 未变)。
        """
        # 先找出该文件贡献了 def 的 URI
        uris_to_clear = [
            r["atom_uri"] for r in self.conn.execute(
                "SELECT DISTINCT atom_uri FROM atoms WHERE file=? AND role='def'",
                (rel_path,),
            )
        ]
        self.conn.execute("DELETE FROM atoms WHERE file=?", (rel_path,))
        if uris_to_clear:
            placeholders = ",".join("?" * len(uris_to_clear))
            self.conn.execute(
                f"DELETE FROM lenses WHERE atom_uri IN ({placeholders})",
                uris_to_clear,
            )
        self.conn.commit()

    # —— Atom / Lens 写入 ——
    def replace_atoms_and_lenses(self, project: str,
                                 occs: list[SymbolOccurrence],
                                 lens_factory) -> None:
        """把一批出现点写入 atoms 表,并为每个 def 出现点生成 signature Lens。

        lens_factory: callable(symbol, kind, signature_text) -> (content, tokens)
        """
        # 按 (symbol, kind, def签名) 聚合:同 URI 只生成一份 signature Lens
        seen_lens: set[str] = set()
        rows = []
        for o in occs:
            from .uri import make_uri
            uri = make_uri(project, o.name)
            rows.append((uri, o.name, o.kind, o.file, o.line, o.role))
            # 只对 def 生成 Lens(签名);ref 不产生 Lens
            if o.role == ROLE_DEF and uri not in seen_lens:
                seen_lens.add(uri)
                content, tokens = lens_factory(o.name, o.kind, o.node_text)
                self.conn.execute(
                    "INSERT OR REPLACE INTO lenses(atom_uri,lens,content,tokens) "
                    "VALUES(?,?,?,?)",
                    (uri, LENS_SIGNATURE, content, tokens),
                )
        self.conn.executemany(
            "INSERT INTO atoms(atom_uri,symbol,kind,file,line,role) VALUES(?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    # —— 查询 ——
    def query_symbol(self, symbol: str) -> list[sqlite3.Row]:
        """精确符号查询:返回该符号的所有出现点(def + ref)。"""
        return self.conn.execute(
            "SELECT atom_uri, symbol, kind, file, line, role "
            "FROM atoms WHERE symbol=? ORDER BY role, file, line",
            (symbol,),
        ).fetchall()

    def get_lens(self, atom_uri: str, lens: str = LENS_SIGNATURE) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT content, tokens FROM lenses WHERE atom_uri=? AND lens=?",
            (atom_uri, lens),
        ).fetchone()

    def list_def_symbols(self) -> list[sqlite3.Row]:
        """列出所有有 def 的符号(用于 stats / 调试)。"""
        return self.conn.execute(
            "SELECT DISTINCT atom_uri, symbol, kind, file, line FROM atoms "
            "WHERE role='def' ORDER BY file, line"
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
