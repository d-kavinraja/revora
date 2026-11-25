"""Asyncpg dialect hardening for PostgreSQL connection recovery.

asyncpg can raise a client-side ``InternalClientError`` (for example
``cannot switch to state 15; another operation (2) is in progress``) when a
server terminates an idle backend while the client is starting the next
protocol operation. SQLAlchemy decides whether to invalidate a pooled
connection from the outcome of the pre-ping, but its stock asyncpg ``do_ping``
lets that client-state error escape: the pool then keeps the dead connection
and the caller sees an opaque internal error instead of a transparent
reconnect.

A pre-ping is only a liveness probe. If it fails for any reason the physical
connection cannot be trusted, so the override reports the ping as failed and
lets the pool invalidate this connection and retry on a fresh one.
"""

from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg


class RevoraAsyncpgDialect(PGDialect_asyncpg):
    # Keep SQL compilation caching enabled; SQLAlchemy only honours the flag when
    # the dialect used for the engine declares it explicitly.
    supports_statement_cache = True

    def do_ping(self, dbapi_connection) -> bool:
        try:
            dbapi_connection.ping()
        except Exception:
            return False
        return True
