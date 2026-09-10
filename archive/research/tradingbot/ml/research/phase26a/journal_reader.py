"""Read-only paper execution records from production TradeJournal SQLite."""



from __future__ import annotations



import sqlite3

from pathlib import Path

from typing import Any





def read_paper_executions(base_dir: str | Path | None = None) -> list[dict[str, Any]]:

    """Legacy executions table (backward compatible)."""

    root = Path(base_dir or ".")

    db_path = root / "data" / "trade_journal.db"

    if not db_path.is_file():

        return []



    with sqlite3.connect(db_path) as conn:

        conn.row_factory = sqlite3.Row

        rows = conn.execute(

            """

            SELECT ts, mode, symbol, timeframe, direction, lot,

                   requested_price, fill_price, slippage_pips, sl, tp,

                   ticket, success, message

            FROM executions

            WHERE mode = 'paper' AND success = 1

              AND direction IN ('BUY', 'SELL')

            ORDER BY ts

            """

        ).fetchall()



    return [dict(row) for row in rows]





def read_completed_paper_trades(base_dir: str | Path | None = None) -> list[dict[str, Any]]:

    """Full lifecycle rows from paper_trades table (Phase 26C)."""

    root = Path(base_dir or ".")

    db_path = root / "data" / "trade_journal.db"

    if not db_path.is_file():

        return []



    with sqlite3.connect(db_path) as conn:

        conn.row_factory = sqlite3.Row

        try:

            rows = conn.execute(

                """

                SELECT *

                FROM paper_trades

                WHERE status = 'closed'

                  AND direction IN ('BUY', 'SELL')

                  AND fill_price > 0

                ORDER BY time_open

                """

            ).fetchall()

        except sqlite3.OperationalError:

            return []



    return [dict(row) for row in rows]


