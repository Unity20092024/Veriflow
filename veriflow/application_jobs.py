"""Durable operator requests, processed separately from the web server."""
import json
from psycopg.types.json import Jsonb
from .connectors import AccessDenied,CollectionError
from .worker import run_one,authorization
from .admin_ops import discover_catalog


def run_job(conn):
    """Dedicated session connection; claim is durable and work/result commit together.

    Session advisory locking requires direct PostgreSQL or session pooling, as
    used by this application. A lost worker session releases the lock. Its
    running request is then recovered, never a paid provider submission.
    """
    locked=conn.execute("SELECT pg_try_advisory_lock(hashtext('veriflow_admin_jobs')) AS locked").fetchone()['locked']
    if not locked:return None
    try:
        conn.execute("UPDATE veriflow.admin_jobs SET state='queued',error_code='worker_interrupted' WHERE state='running'")
        job=conn.execute("SELECT * FROM veriflow.admin_jobs WHERE state='queued' ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not job:return None
        conn.execute("UPDATE veriflow.admin_jobs SET state='running',started_at=now(),attempts=attempts+1 WHERE id=%s",(job['id'],))
        conn.commit()
        conn.execute('SELECT 1')  # Keep business changes and final result atomic.
        result=execute_job(conn,job)
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        if not conn.closed:
            conn.execute("SELECT pg_advisory_unlock(hashtext('veriflow_admin_jobs'))")
            conn.commit()


def execute_job(conn,job):
    result={};state='succeeded';code=None
    try:
        with conn.transaction():
            conn.execute("UPDATE veriflow.admin_jobs SET state='running',started_at=now() WHERE id=%s",(job['id'],))
            if job['kind']=='export':
                from .exports import build_export
                result=build_export(conn,str(job['id']),job['payload'])
                conn.execute("UPDATE veriflow.admin_jobs SET artifact_name=%s,artifact_expires_at=now()+interval '7 days' WHERE id=%s",(result['artifact_name'],job['id']))
            elif job['kind']=='catalog':
                result=discover_catalog(conn,job['source_id'],job['authorization_id'],job['payload']['records'])
            else:
                source=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR UPDATE',(job['source_id'],)).fetchone()
                if not source or not source['enabled'] or source['access_status']!='approved':raise AccessDenied()
                authorization(conn,source['id'],job['authorization_id'],source['collection_method'])
                if source['collection_method']=='apify':
                    from .pilot import require_paid_enabled
                    require_paid_enabled()
                    # Paid POST/commit is intentionally excluded from this transactional queue.
                    # An operator must use the reviewed start command after explicit activation.
                    raise AccessDenied('Paid queue submission is not enabled')
                if source['collection_method']!='approved_import':raise AccessDenied()
                pending=conn.execute("SELECT 1 FROM veriflow.import_batches WHERE source_id=%s AND authorization_id=%s AND status='pending' LIMIT 1",(source['id'],job['authorization_id'])).fetchone()
                if not pending:
                    result=dict(status='no_pending_imports',inserted=0,duplicates=0)
                else:
                    conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(source['id'],))
                    result=run_one(conn,source_id=source['id'],grant_id=job['authorization_id']) or {}
                    if result.get('status')!='success':raise CollectionError()
    except Exception as exc:
        code=exc.code if isinstance(exc,CollectionError) else 'application_job_failed'
        state='blocked' if isinstance(exc,AccessDenied) or code=='apify_paid_runs_disabled' else 'failed'
        result={}
    conn.execute('''UPDATE veriflow.admin_jobs SET state=%s,result=%s,error_code=%s,
        payload='{}',started_at=coalesce(started_at,now()),finished_at=now() WHERE id=%s''',
        (state,Jsonb(result),code,job['id']))
    return dict(result,job_id=str(job['id']),state=state,error_code=code)
