"""Supabase (Postgres) read/write helpers.

Thin wrappers over psycopg3 (optional extra 'db'). Connection comes from
``SUPABASE_DB_URL`` (the project's Postgres connection string). All Phase 0
consumers can also run purely from parquet — the DB is the durable,
queryable copy, not a hard dependency.

Apply db/schema.sql once per environment: ``python -m apexodds.data.db --init``.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from apexodds.config import get_settings

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def _psycopg():
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "psycopg is not installed — install the DB extra: uv sync --extra db"
        ) from exc
    return psycopg


def get_conn(dsn: str | None = None):
    psycopg = _psycopg()
    dsn = dsn or get_settings().supabase_db_url
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    return psycopg.connect(dsn)


def apply_schema(conn, path: str | Path = SCHEMA_PATH) -> None:
    sql = Path(path).read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("applied schema from %s", path)


def _to_records(df: pd.DataFrame) -> list[tuple]:
    """NaN/NA → None so Postgres gets proper NULLs."""
    clean = df.astype(object).where(pd.notna(df), None)
    return list(map(tuple, clean.itertuples(index=False, name=None)))


def upsert_df(conn, table: str, df: pd.DataFrame, conflict_cols: list[str]) -> int:
    """INSERT ... ON CONFLICT (conflict_cols) DO UPDATE for a whole frame."""
    if df.empty:
        return 0
    _psycopg()  # raise the friendly ImportError before importing submodules
    from psycopg import sql

    cols = list(df.columns)
    update_cols = [c for c in cols if c not in conflict_cols]
    stmt = sql.SQL(
        "INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        "ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
    ).format(
        table=sql.Identifier(table),
        cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
        placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in cols),
        conflict=sql.SQL(", ").join(map(sql.Identifier, conflict_cols)),
        updates=sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in update_cols
        )
        if update_cols
        else sql.SQL("session_key = EXCLUDED.session_key"),
    )
    records = _to_records(df)
    with conn.cursor() as cur:
        cur.executemany(stmt, records)
    conn.commit()
    return len(records)


def read_df(conn, query: str, params: tuple | None = None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(query, params)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def load_normalized_session(conn, session_dir: str | Path) -> None:
    """Push one normalized session directory (parquet) into Supabase."""
    session_dir = Path(session_dir)
    table_conflicts = {
        "laps": ["session_key", "driver_number", "lap_number"],
        "results": ["session_key", "driver_number"],
        "stints": ["session_key", "driver_number", "stint_id"],
        "pitstops": ["session_key", "driver_number", "lap"],
        "race_control": None,  # append-only, no natural key
        "weather": None,
    }
    for table, conflict in table_conflicts.items():
        path = session_dir / f"{table}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if conflict:
            n = upsert_df(conn, table, df, conflict)
        else:
            records = _to_records(df)
            if records:
                from psycopg import sql

                cols = list(df.columns)
                stmt = sql.SQL("INSERT INTO {t} ({c}) VALUES ({p})").format(
                    t=sql.Identifier(table),
                    c=sql.SQL(", ").join(map(sql.Identifier, cols)),
                    p=sql.SQL(", ").join(sql.Placeholder() for _ in cols),
                )
                with conn.cursor() as cur:
                    cur.executemany(stmt, records)
                conn.commit()
            n = len(records)
        log.info("%s: %d rows -> %s", session_dir.name, n, table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Supabase helpers")
    parser.add_argument("--init", action="store_true", help="apply db/schema.sql")
    parser.add_argument("--load", default=None, help="normalized session dir to upload")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with get_conn() as conn:
        if args.init:
            apply_schema(conn)
        if args.load:
            load_normalized_session(conn, args.load)


if __name__ == "__main__":
    main()
