"""Safe DDL helpers for domain index migrations.

Each domain's ``adapters/migrations.py`` retro-fits performance indexes at
startup with ``CREATE INDEX IF NOT EXISTS``. Index / table / column names are
module-level constants today, but building that DDL by raw f-string
interpolation is a SQL-injection footgun the moment any dynamic value reaches
it — and identifiers cannot be passed as bound parameters the way values can.

:func:`create_index_if_not_exists` is the single choke point: it validates every
identifier against a strict pattern (raising before any SQL runs) and quotes
each via the dialect's identifier preparer, so the interpolation can never
inject and reserved-word table names (e.g. ``groups``) are quoted correctly.
"""

import re
from typing import Iterable, Union

from sqlalchemy import text
from sqlalchemy.engine import Connection

# A conservative SQL identifier: a leading letter/underscore followed by
# letters, digits, or underscores. Deliberately stricter than any dialect
# allows — domain index/table/column names all satisfy it.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str) -> str:
    """Return ``name`` (stripped) if it is a safe SQL identifier.

    Raises:
        ValueError: if ``name`` does not match :data:`_IDENTIFIER_RE`.
    """
    candidate = name.strip()
    if not _IDENTIFIER_RE.match(candidate):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return candidate


def create_index_if_not_exists(
    conn: Connection,
    *,
    index_name: str,
    table: str,
    columns: Union[str, Iterable[str]],
) -> None:
    """Emit ``CREATE INDEX IF NOT EXISTS`` with validated, quoted identifiers.

    Args:
        conn: An open SQLAlchemy :class:`~sqlalchemy.engine.Connection`.
        index_name: Name of the index to create.
        table: Table to index.
        columns: The index columns. A ``str`` is split on commas (so a single
            column and a comma-separated composite are both accepted); any other
            iterable is taken as an already-split list of column names.

    Every identifier (index, table, and each column) must be a plain SQL
    identifier per :data:`_IDENTIFIER_RE`, or a :class:`ValueError` is raised
    before any SQL is executed.
    """
    if isinstance(columns, str):
        column_list = columns.split(",")
    else:
        column_list = list(columns)

    if not column_list:
        raise ValueError("create_index_if_not_exists requires at least one column")

    preparer = conn.dialect.identifier_preparer
    quoted_index = preparer.quote(_safe_identifier(index_name))
    quoted_table = preparer.quote(_safe_identifier(table))
    quoted_columns = ", ".join(
        preparer.quote(_safe_identifier(column)) for column in column_list
    )

    conn.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {quoted_index} "
            f"ON {quoted_table} ({quoted_columns})"
        )
    )
