"""Resume known provider runs only; never import or call submit_job/start."""
from .apify import ApifyClient
from .apify_pipeline import refresh_job


def poll_one(conn,client=None,interval=60):
    """Caller commits each attempt; durable cooldown survives process restarts.

    Serialize monitors, then let refresh_job take source-before-job locks to
    match ingestion. Manual refresh also uses the job lock and cannot double queue.
    """
    if not 30<=interval<=3600:
        raise ValueError('Poll interval must be 30-3600 seconds')
    if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtext('veriflow_apify_monitor')) AS locked").fetchone()['locked']:
        return dict(state='busy')
    job=conn.execute('''SELECT id,poll_failures FROM veriflow.apify_jobs
        WHERE state='running' AND actor_run_id IS NOT NULL AND next_poll_at<=now()
        ORDER BY next_poll_at,created_at,id LIMIT 1''').fetchone()
    if not job:
        return None
    client=client or ApifyClient()
    if not client.token:
        result=dict(job_id=str(job['id']),state='running',error_code='apify_credentials_missing')
    else:
        result=refresh_job(conn,job['id'],client)
    if result['state']=='busy':
        return result
    error=result.get('error_code')
    failures=job['poll_failures']+1 if error else 0
    delay=max(interval,min(3600,60*2**min(failures-1,6))) if error else interval
    if error=='rate_limited':
        delay=max(delay,min(86400,max(60,int(result.get('retry_after_seconds',60)))))
    elif error in ('apify_credentials_missing','apify_authentication_failed','apify_permission_denied'):
        delay=max(delay,300)
    conn.execute('''UPDATE veriflow.apify_jobs SET poll_failures=%s,
        next_poll_at=now()+(%s * interval '1 second'),updated_at=now(),error_code=%s
        WHERE id=%s''',(failures,delay,error,job['id']))
    if error:
        conn.execute('''INSERT INTO veriflow.integration_status(provider,status,error_code)
            VALUES ('apify',%s,%s) ON CONFLICT(provider) DO UPDATE
            SET status=excluded.status,error_code=excluded.error_code,updated_at=now()''',
            ('pending_credentials' if error=='apify_credentials_missing' else 'error',error))
    else:
        conn.execute("""UPDATE veriflow.integration_status SET
            status=CASE WHEN status='ready' THEN 'ready' ELSE 'discovered' END,
            error_code=NULL,last_discovered_at=now(),updated_at=now() WHERE provider='apify'""")
    result.update(poll_failures=failures,next_poll_seconds=delay)
    return result
