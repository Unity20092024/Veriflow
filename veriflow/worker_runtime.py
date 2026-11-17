"""Serialize the existing worker cycle across process copies on one DB session."""
WORKER_LOCK = 746395011


def run_cycle(conn):
    acquired = conn.execute('SELECT pg_try_advisory_lock(%s) AS acquired',
                            (WORKER_LOCK,)).fetchone()['acquired']
    conn.commit()
    if not acquired:
        return []
    try:
        from .worker import run_one
        from .jobs import run_one_collection_page
        from .bounded_collection import tick
        results = []
        # Use the SAME connection for lock and work, including across commits.
        # Losing the connection releases ownership and prevents stale DB writes.
        for operation in (run_one, run_one_collection_page, tick):
            result = operation(conn)
            conn.commit()
            if result:
                results.append(result)
        return results
    finally:
        if not conn.closed:
            conn.rollback()
            conn.execute('SELECT pg_advisory_unlock(%s)', (WORKER_LOCK,))
            conn.commit()
