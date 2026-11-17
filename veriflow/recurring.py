"""Durable recurring free collection; no paid provider submissions."""
from datetime import datetime,timezone,timedelta
from uuid import uuid5,NAMESPACE_URL
from .admin_ops import identifier,request_job
from .free_collection import SOURCE_ID
from .free_providers import adapter,mode_for
from .connectors import CollectionError,AccessDenied,RateLimited


def save_schedule(conn,product_id='',category_id='',hours=24,max_reviews=20,enabled=False,source_id=SOURCE_ID):
    hours=int(hours);max_reviews=int(max_reviews)
    if not 6<=hours<=168:raise CollectionError('Recurring interval must be 6-168 hours')
    provider=adapter(source_id)
    payload=dict(mode=mode_for(source_id,'collection'),product_id=product_id,category_id=category_id,max_reviews=max_reviews)
    provider.validate_payload('collection',payload)
    if enabled:provider.validate_source(conn)
    mapping=conn.execute('''SELECT 1 FROM veriflow.source_products sp WHERE source_id=%s
        AND (%s='' OR product_id=CAST(NULLIF(%s,'') AS uuid))
        AND (%s='' OR EXISTS(SELECT 1 FROM veriflow.product_categories pc WHERE pc.product_id=sp.product_id AND pc.category_id=CAST(NULLIF(%s,'') AS uuid))) LIMIT 1''',
        (source_id,product_id,product_id,category_id,category_id)).fetchone()
    if not mapping:raise AccessDenied('Discover an eligible product/category first')
    row=conn.execute('''INSERT INTO veriflow.recurring_schedules(source_id,product_id,category_id,interval_seconds,max_reviews,enabled)
        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(source_id,product_id,category_id) DO UPDATE
        SET interval_seconds=excluded.interval_seconds,max_reviews=excluded.max_reviews,enabled=excluded.enabled,
            next_run_at=CASE WHEN NOT veriflow.recurring_schedules.enabled AND excluded.enabled THEN now() ELSE veriflow.recurring_schedules.next_run_at END,
            updated_at=now() RETURNING id''',
        (source_id,identifier(product_id) if product_id else None,identifier(category_id) if category_id else None,hours*3600,max_reviews,bool(enabled))).fetchone()
    return str(row['id'])


def queue_due(conn,limit=10):
    """Caller commits schedule changes and idempotent job creation together."""
    if not 1<=limit<=100:raise ValueError('Invalid scheduling batch')
    rows=conn.execute('''SELECT * FROM veriflow.recurring_schedules WHERE enabled AND next_run_at<=now()
        ORDER BY next_run_at,id FOR UPDATE SKIP LOCKED LIMIT %s''',(limit,)).fetchall()
    queued=0
    now=datetime.now(timezone.utc)
    for s in rows:
        interval=timedelta(seconds=s['interval_seconds']);next_run=now+interval
        status='queued';error=None;job_id=s['last_job_id']
        try:
            provider=adapter(s['source_id'])
            provider.validate_source(conn)
            active=conn.execute("SELECT state FROM veriflow.admin_jobs WHERE id=%s",(s['last_job_id'],)).fetchone() if s['last_job_id'] else None
            if active and active['state'] in ('queued','running'):
                status='awaiting_previous_job';next_run=now+timedelta(seconds=300)
            else:
                payload=dict(mode=mode_for(s['source_id'],'collection'),product_id=str(s['product_id']) if s['product_id'] else '',category_id=str(s['category_id']) if s['category_id'] else '',max_reviews=s['max_reviews'])
                key=str(uuid5(NAMESPACE_URL,'veriflow-schedule:'+str(s['id'])+':'+s['next_run_at'].astimezone(timezone.utc).isoformat()))
                job_id=request_job(conn,'collection',payload,key,s['source_id'])
                queued+=1
        except (AccessDenied,RateLimited) as exc:
            status='paused_source' if isinstance(exc,AccessDenied) else 'source_cooldown'
            error=exc.code;next_run=now+timedelta(seconds=exc.retry_after if isinstance(exc,RateLimited) else 300)
        conn.execute('''UPDATE veriflow.recurring_schedules SET next_run_at=%s,last_job_id=%s,
            last_status=%s,last_error=%s,last_queued_at=CASE WHEN %s='queued' THEN now() ELSE last_queued_at END,updated_at=now()
            WHERE id=%s''',(next_run,job_id,status,error,status,s['id']))
    return dict(schedules_checked=len(rows),jobs_queued=queued)
