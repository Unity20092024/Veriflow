"""Checkpoint controls using existing states/metadata, with no schema changes."""
import uuid
from .connectors import AccessDenied, CollectionError

PAUSED = 'operator_paused'
STOPPED = 'operator_stopped'


def control(conn, action, *, job_id=None, batch_id=None):
    if action not in ('pause', 'stop', 'resume') or bool(job_id) == bool(batch_id):
        raise CollectionError('Select exactly one existing job or batch')
    if batch_id:
        from .bounded_collection import BATCH_ID
        if batch_id != BATCH_ID:
            raise AccessDenied()
        table, key = 'free_batches', batch_id
        active, parked, resumed = ('running',), 'blocked', 'running'
        expiry = 'expires_at<=now() OR requests>=max_requests'
    else:
        try:
            key = str(uuid.UUID(str(job_id)))
        except (ValueError, TypeError, AttributeError):
            raise CollectionError('Invalid job identifier') from None
        table = 'collection_jobs'
        active, parked, resumed = ('queued', 'running'), 'cancelled', 'queued'
        expiry = "strategy IS NOT NULL AND created_at<=now()-interval '48 hours'"
    with conn.transaction():
        row = conn.execute(f'SELECT id,state,error_code,({expiry}) AS expired '
                           f'FROM veriflow.{table} WHERE id=%s FOR UPDATE', (key,)).fetchone()
        if not row:
            raise AccessDenied('Existing collection not found')
        paused = row['state'] == parked and row['error_code'] in (PAUSED, STOPPED)
        if action == 'resume':
            if not paused or row['expired']:
                raise AccessDenied('Only an unexpired operator-paused/stopped collection can resume')
            state, code = resumed, None
        else:
            if row['state'] not in active and not paused:
                raise AccessDenied('Terminal collections cannot be changed or restarted')
            state, code = parked, PAUSED if action == 'pause' else STOPPED
        # Never reset a cursor, counter, budget, target, approval or deadline.
        conn.execute(f'UPDATE veriflow.{table} SET state=%s,error_code=%s,updated_at=now() '
                     'WHERE id=%s', (state, code, key))
    return dict(id=str(key), state='paused' if code == PAUSED else
                'stopped' if code == STOPPED else state)


def import_allowed(conn, batch):
    """Called inside ingest transaction; controls wait for an active ingest to finish."""
    if batch.get('collection_job_item_id'):
        row = conn.execute('''SELECT j.state FROM veriflow.collection_jobs j
            JOIN veriflow.collection_job_items i ON i.job_id=j.id
            WHERE i.id=%s FOR SHARE OF j''', (batch['collection_job_item_id'],)).fetchone()
        if not row or row['state'] not in ('queued', 'running'):
            return False
    rows = conn.execute('SELECT state,error_code FROM veriflow.free_batches '
                        'WHERE authorization_id=%s FOR SHARE', (batch['authorization_id'],)).fetchall()
    return not any(r['error_code'] in (PAUSED, STOPPED) for r in rows)
