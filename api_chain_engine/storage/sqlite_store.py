"""SQLite 持久化存储"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from typing import Any

import yaml

from models.chain import ChainDefinition, ChainResult
from models.step import StepDefinition, ExtractRule, AssertRule


class ChainStore:
    """
    链路模板持久化（SQLite）
    只保存链路结构和参数模板，不保存本次执行的具体参数值
    """

    def __init__(self, db_path: str = "chain_store.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # WAL（Write-Ahead Logging）模式：提升并发读取性能，避免读写互相阻塞，
        # 适合多线程/多进程同时读取链路模板的使用场景。
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    tags TEXT,
                    global_variables TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    step_order INTEGER NOT NULL,
                    api_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    param_overrides TEXT,
                    extracts TEXT,
                    assertions TEXT,
                    depends_on TEXT,
                    on_failure TEXT DEFAULT 'stop',
                    pre_scripts TEXT,
                    post_scripts TEXT,
                    FOREIGN KEY (chain_id) REFERENCES chains(chain_id)
                );

                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms REAL,
                    result_summary TEXT
                );
            """)

    # ──────────────────────────────────────────────
    # 链路 CRUD
    # ──────────────────────────────────────────────

    def save_chain(self, chain: ChainDefinition) -> None:
        """保存链路（存在则更新）"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM chains WHERE chain_id = ?", (chain.chain_id,)
            ).fetchone()
            if existing:
                self.update_chain(chain)
                return

            conn.execute(
                """INSERT INTO chains (chain_id, name, description, tags, global_variables, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chain.chain_id,
                    chain.name,
                    chain.description,
                    json.dumps(chain.tags, ensure_ascii=False),
                    json.dumps(chain.global_variables, ensure_ascii=False),
                    chain.created_at or now,
                    chain.updated_at or now,
                ),
            )
            self._save_steps(conn, chain)

    def load_chain(self, chain_id: str) -> ChainDefinition:
        """加载链路定义"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM chains WHERE chain_id = ?", (chain_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"链路 '{chain_id}' 不存在")

            steps = self._load_steps(conn, chain_id)
            return ChainDefinition(
                chain_id=row["chain_id"],
                name=row["name"],
                description=row["description"] or "",
                steps=steps,
                global_variables=json.loads(row["global_variables"] or "{}"),
                tags=json.loads(row["tags"] or "[]"),
                created_at=row["created_at"] or "",
                updated_at=row["updated_at"] or "",
            )

    def list_chains(self) -> list[dict[str, Any]]:
        """列出所有链路摘要"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT chain_id, name, description, tags, created_at, updated_at FROM chains"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_chain(self, chain_id: str) -> None:
        """删除链路"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM steps WHERE chain_id = ?", (chain_id,))
            conn.execute("DELETE FROM chains WHERE chain_id = ?", (chain_id,))

    def update_chain(self, chain: ChainDefinition) -> None:
        """更新链路"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE chains SET name=?, description=?, tags=?, global_variables=?, updated_at=?
                   WHERE chain_id=?""",
                (
                    chain.name,
                    chain.description,
                    json.dumps(chain.tags, ensure_ascii=False),
                    json.dumps(chain.global_variables, ensure_ascii=False),
                    now,
                    chain.chain_id,
                ),
            )
            conn.execute("DELETE FROM steps WHERE chain_id = ?", (chain.chain_id,))
            self._save_steps(conn, chain)

    def save_execution_summary(self, result: ChainResult) -> None:
        """保存执行摘要"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO executions (chain_id, status, started_at, finished_at, duration_ms, result_summary)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    result.chain_id,
                    result.status,
                    result.started_at,
                    result.finished_at,
                    result.total_duration_ms,
                    json.dumps(result.summary, ensure_ascii=False),
                ),
            )

    def get_execution_history(self, chain_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取执行历史"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM executions WHERE chain_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (chain_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def export_chain_yaml(self, chain_id: str, file_path: str) -> None:
        """导出链路为 YAML"""
        chain = self.load_chain(chain_id)
        data = self._chain_to_dict(chain)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def import_chain_yaml(self, file_path: str) -> ChainDefinition:
        """从 YAML 导入链路"""
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        chain = self._dict_to_chain(data)
        self.save_chain(chain)
        return chain

    # ──────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────

    def _save_steps(self, conn: sqlite3.Connection, chain: ChainDefinition) -> None:
        for order, step in enumerate(chain.steps):
            conn.execute(
                """INSERT INTO steps
                   (chain_id, step_id, step_order, api_id, name, param_overrides,
                    extracts, assertions, depends_on, on_failure, pre_scripts, post_scripts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chain.chain_id,
                    step.step_id,
                    order,
                    step.api_id,
                    step.name,
                    json.dumps(step.param_overrides or {}, ensure_ascii=False),
                    json.dumps([self._extract_rule_to_dict(r) for r in (step.extracts or [])], ensure_ascii=False),
                    json.dumps([self._assert_rule_to_dict(r) for r in (step.assertions or [])], ensure_ascii=False),
                    json.dumps(step.depends_on or [], ensure_ascii=False),
                    step.on_failure or "stop",
                    json.dumps(step.pre_scripts or [], ensure_ascii=False),
                    json.dumps(step.post_scripts or [], ensure_ascii=False),
                ),
            )

    def _load_steps(self, conn: sqlite3.Connection, chain_id: str) -> list[StepDefinition]:
        rows = conn.execute(
            "SELECT * FROM steps WHERE chain_id = ? ORDER BY step_order", (chain_id,)
        ).fetchall()
        steps = []
        for row in rows:
            extracts_data = json.loads(row["extracts"] or "[]")
            assertions_data = json.loads(row["assertions"] or "[]")
            steps.append(
                StepDefinition(
                    step_id=row["step_id"],
                    api_id=row["api_id"],
                    name=row["name"],
                    param_overrides=json.loads(row["param_overrides"] or "{}"),
                    extracts=[self._dict_to_extract_rule(d) for d in extracts_data],
                    assertions=[self._dict_to_assert_rule(d) for d in assertions_data],
                    depends_on=json.loads(row["depends_on"] or "[]"),
                    on_failure=row["on_failure"] or "stop",
                    pre_scripts=json.loads(row["pre_scripts"] or "[]"),
                    post_scripts=json.loads(row["post_scripts"] or "[]"),
                )
            )
        return steps

    @staticmethod
    def _extract_rule_to_dict(rule: ExtractRule) -> dict:
        return {
            "var_name": rule.var_name,
            "source": rule.source,
            "extractor": rule.extractor,
            "expression": rule.expression,
            "default": rule.default,
        }

    @staticmethod
    def _dict_to_extract_rule(d: dict) -> ExtractRule:
        return ExtractRule(
            var_name=d["var_name"],
            source=d["source"],
            extractor=d["extractor"],
            expression=d["expression"],
            default=d.get("default"),
        )

    @staticmethod
    def _assert_rule_to_dict(rule: AssertRule) -> dict:
        return {
            "name": rule.name,
            "source": rule.source,
            "expression": rule.expression,
            "operator": rule.operator,
            "expected": rule.expected,
            "message": rule.message,
        }

    @staticmethod
    def _dict_to_assert_rule(d: dict) -> AssertRule:
        return AssertRule(
            name=d["name"],
            source=d["source"],
            expression=d["expression"],
            operator=d["operator"],
            expected=d.get("expected"),
            message=d.get("message", ""),
        )

    def _chain_to_dict(self, chain: ChainDefinition) -> dict:
        return {
            "chain_id": chain.chain_id,
            "name": chain.name,
            "description": chain.description,
            "global_variables": chain.global_variables,
            "tags": chain.tags,
            "created_at": chain.created_at,
            "updated_at": chain.updated_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "api_id": s.api_id,
                    "name": s.name,
                    "param_overrides": s.param_overrides,
                    "extracts": [self._extract_rule_to_dict(r) for r in s.extracts],
                    "assertions": [self._assert_rule_to_dict(r) for r in s.assertions],
                    "depends_on": s.depends_on,
                    "on_failure": s.on_failure,
                    "pre_scripts": s.pre_scripts,
                    "post_scripts": s.post_scripts,
                }
                for s in chain.steps
            ],
        }

    def _dict_to_chain(self, data: dict) -> ChainDefinition:
        steps = []
        for s in data.get("steps", []):
            steps.append(
                StepDefinition(
                    step_id=s["step_id"],
                    api_id=s["api_id"],
                    name=s["name"],
                    param_overrides=s.get("param_overrides", {}),
                    extracts=[self._dict_to_extract_rule(r) for r in s.get("extracts", [])],
                    assertions=[self._dict_to_assert_rule(r) for r in s.get("assertions", [])],
                    depends_on=s.get("depends_on", []),
                    on_failure=s.get("on_failure", "stop"),
                    pre_scripts=s.get("pre_scripts", []),
                    post_scripts=s.get("post_scripts", []),
                )
            )
        return ChainDefinition(
            chain_id=data["chain_id"],
            name=data["name"],
            description=data.get("description", ""),
            steps=steps,
            global_variables=data.get("global_variables", {}),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
