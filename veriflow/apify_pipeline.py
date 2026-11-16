"""Review collection through reviewed Actors, bounded spending, and private imports.

submit_job commits a durable reservation before a paid POST. Uncertain starts
are never retried automatically. refresh_job resumes a known run without spending
on another run. Composio is not imported or consulted by this pipeline.
"""
import json
import hashlib
import os
from datetime import date, datetime, timezone
from jsonschema import Draft202012Validator
from .apify import ApifyClient, ApifyError, StartUnknown, usd
from .connectors import AccessDenied, CollectionError, RateLimited, canonical_url
from .worker import authorization, enqueue


class BudgetDenied(CollectionError):
    code='apify_budget_denied'


class JobPending(CollectionError):
    code='apify_job_already_pending'


def value_at(item,path):
    if not isinstance(path,list) or not 1<=len(path)<=10 or not all(isinstance(p,str) for p in path):
        raise CollectionError('Invalid field path')
    for key in path:
        if isinstance(item,list) and key.isdigit() and int(key)<len(item):
            item=item[int(key)]
        elif isinstance(item,dict) and key in item:
            item=item[key]
        else:
            raise CollectionError('Required provider field missing')
    return item


def binding_fingerprint(binding):
    return hashlib.sha256(json.dumps(dict(binding),sort_keys=True,default=str).encode()).hexdigest()


def pricing_snapshot(actor):
    now=datetime.now(timezone.utc).isoformat()
    prices=[p for p in actor.get('pricingInfos',[]) if p.get('startedAt','')<=now
            and (not p.get('endedAt') or p['endedAt']>now)]
    if not prices:
        raise BudgetDenied('Unknown Actor pricing')
    price=max(prices,key=lambda p:p.get('startedAt',''))
    # Preserve all event prices while ignoring notification timestamps/prose.
    return {k:price.get(k) for k in ('pricingModel','isPPEPlatformUsagePaidByUser','pricingPerEvent')}


def validate_binding(conn,binding,grant_id):
    source=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE',(binding['source_id'],)).fetchone()
    if not binding['enabled'] or not source or not source['enabled'] or source['access_status']!='approved' or source['collection_method']!='apify' or source['category']=='market_research':
        raise AccessDenied()
    grant=authorization(conn,source['id'],grant_id,'apify')
    if binding['product_key'] not in grant['product_keys']:
        raise AccessDenied()
    target=canonical_url(binding['target_url'])
    from urllib.parse import urlsplit
    host=urlsplit(target).hostname;expected=urlsplit(source['url']).hostname
    if host!=expected and not host.endswith('.'+expected):
        raise AccessDenied()
    if value_at(binding['approved_input'],list(binding['target_input_path']))!=target:
        raise AccessDenied('Approved Actor input must target the reviewed product URL')
    if binding['approved_input'].get(binding['limit_input_key'])!=binding['max_records']:
        raise BudgetDenied('Actor input must enforce the approved row limit')
    from .pilot import max_records
    if not 1<=binding['max_records']<=max_records():
        raise BudgetDenied()
    # No network-resolved JSON Schema refs or executable validation extensions.
    def refs_local(item):
        if isinstance(item,dict):
            for key,value in item.items():
                if key in ('$ref','$dynamicRef') and (not isinstance(value,str) or not value.startswith('#')):
                    raise AccessDenied()
                refs_local(value)
        elif isinstance(item,list):
            for value in item:refs_local(value)
    refs_local(binding['input_schema'])
    try:
        Draft202012Validator.check_schema(binding['input_schema'])
        Draft202012Validator(binding['input_schema']).validate(binding['approved_input'])
    except Exception:
        raise AccessDenied('Actor input does not satisfy reviewed schema') from None
    mapping=binding['field_mapping']
    fields=mapping.get('fields',{})
    required={'external_id','software_name','published_at','original_url'}
    if not required.issubset(fields) or not set(fields).issubset(required|{'review_text','rating','rating_scale'}):
        raise CollectionError('Review mapping lacks required provenance fields')
    if ('review_text' in fields or mapping.get('text_parts')) and not (source['full_text_allowed'] and grant['full_text_allowed']):
        raise AccessDenied('Reviewed Actor text output requires explicit text authorization')
    paths=list(fields.values())+[p['path'] for p in mapping.get('text_parts',[])]
    if mapping.get('source_path'):paths.append(mapping['source_path'])
    for path in paths:
        # Validate paths before any paid request.
        if not isinstance(path,list) or not path or not all(isinstance(p,str) and p and ',' not in p for p in path):
            raise CollectionError('Invalid mapping')
        if any(part.lower().replace('_','').replace('-','') in {'reviewer','author','reviewername','authorname','username','userid','email','avatar','profileurl','revieweremail','authoremail'} for part in path):
            raise AccessDenied('Do not request unnecessary reviewer identity fields')
    from .licensing import validate_mapping
    validate_mapping(mapping,source,grant)
    product=conn.execute('''SELECT * FROM veriflow.source_products WHERE source_id=%s AND external_key=%s FOR SHARE''',
                         (source['id'],binding['product_key'])).fetchone()
    if not product:
        raise AccessDenied()
    return source,grant


def submit_job(conn,binding_id,grant_id,client=None):
    from .pilot import require_paid_enabled,policy
    require_paid_enabled()
    pilot=policy()
    client=client or ApifyClient()
    if not client.token:
        error=ApifyError();error.code='apify_credentials_missing';raise error
    # Serialize budget reservations for all sources in this deployment.
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('veriflow_apify_budget'))")
    binding=conn.execute('SELECT * FROM veriflow.apify_bindings WHERE id=%s FOR SHARE',(binding_id,)).fetchone()
    if not binding:
        raise AccessDenied()
    source,grant=validate_binding(conn,binding,grant_id)
    if (grant['expires_at']-datetime.now(timezone.utc)).total_seconds()<binding['timeout_seconds']+30:
        raise AccessDenied('Approval expires before the bounded run can finish')
    pending=conn.execute("SELECT id FROM veriflow.apify_jobs WHERE binding_id=%s AND state IN ('starting','start_unknown','running','queued') LIMIT 1",(binding_id,)).fetchone()
    if pending:raise JobPending()
    limit=usd(os.environ.get('APIFY_MAX_RUN_USD','0'))
    daily=usd(os.environ.get('APIFY_ROLLING_24H_BUDGET_USD','0'))
    charge=usd(binding['max_charge_usd'])
    review=binding['pricing_review']
    if review.get('full_pricing_confirmed') is not True or review.get('total_cost_control_confirmed') is not True or not str(review.get('evidence','')).strip():
        raise BudgetDenied('Full pricing and total-cost control are unconfirmed')
    reservation=usd(review.get('max_incremental_cost_usd'))
    if reservation<charge or reservation>usd(pilot['max_total_usd']):raise BudgetDenied()
    lifetime=conn.execute('''SELECT coalesce(sum(coalesce(confirmed_billed_usd,reserved_usd)),0) AS amount,
        coalesce(sum(reserved_records) FILTER (WHERE confirmed_billed_usd IS DISTINCT FROM 0 OR state NOT IN ('failed','aborted')),0) AS records
        FROM veriflow.apify_jobs WHERE pilot_id=%s''',(pilot['id'],)).fetchone()
    if lifetime['amount']+reservation>usd(pilot['max_total_usd']) or lifetime['records']+binding['max_records']>pilot['max_review_records']:
        raise BudgetDenied('First-test total allowance exhausted')
    used=conn.execute('''SELECT coalesce(sum(coalesce(confirmed_billed_usd,reserved_usd)),0) AS amount
        FROM veriflow.apify_jobs WHERE created_at>now()-interval '24 hours' OR confirmed_billed_usd IS NULL''').fetchone()['amount']
    if charge<=0 or reservation>limit or reservation+used>daily:
        raise BudgetDenied()
    actor=client.actor(binding['actor_id'])
    price=pricing_snapshot(actor)
    if price!=binding['pricing_snapshot'] or price['pricingModel']!='PAY_PER_EVENT' or price['isPPEPlatformUsagePaidByUser'] is True:
        raise BudgetDenied('Only unchanged PPE pricing without separately billed platform usage is supported')
    build=client.build(binding['build_id'])
    schema=build.get('inputSchema')
    if isinstance(schema,str):
        try:schema=json.loads(schema)
        except ValueError:raise AccessDenied('Unreadable Actor schema') from None
    if (build.get('actId')!=binding['actor_id'] or build.get('buildNumber')!=binding['build_number']
        or build.get('status')!='SUCCEEDED' or schema!=binding['input_schema']):
        raise AccessDenied('Pinned build or reviewed schema changed')
    job=conn.execute('''INSERT INTO veriflow.apify_jobs
        (binding_id,source_id,authorization_id,state,actor_id,build_id,reserved_usd,binding_fingerprint,pilot_id,reserved_records)
        VALUES (%s,%s,%s,'starting',%s,%s,%s,%s,%s,%s) RETURNING id''',
        (binding_id,binding['source_id'],grant_id,binding['actor_id'],binding['build_id'],reservation,binding_fingerprint(binding),pilot['id'],binding['max_records'])).fetchone()['id']
    conn.commit()  # Must survive a crash or timeout during the following paid POST.
    try:
        run=client.start(binding['actor_id'],binding['build_number'],binding['approved_input'],
                         charge,binding['max_records'],binding['timeout_seconds'])
        if run.get('actId')!=binding['actor_id'] or run.get('buildId')!=binding['build_id']:
            raise StartUnknown()
        from .apify import identifier
        run_id=identifier(run['id'])
        conn.execute("UPDATE veriflow.apify_jobs SET state='running',actor_run_id=%s,updated_at=now() WHERE id=%s",(run_id,job))
        conn.execute("UPDATE veriflow.integration_status SET status='discovered',error_code=NULL,last_discovered_at=now(),updated_at=now() WHERE provider='apify'")
        conn.commit()
        return dict(job_id=str(job),state='running')
    except Exception as exc:
        code=exc.code if isinstance(exc,CollectionError) else 'apify_start_unknown'
        rejected=code in ('apify_credentials_missing','apify_authentication_failed','apify_permission_denied','rate_limited')
        conn.execute('''UPDATE veriflow.apify_jobs SET state=%s,error_code=%s,
            confirmed_billed_usd=CASE WHEN %s THEN 0 ELSE NULL END,updated_at=now() WHERE id=%s''',
            ('failed' if rejected else 'start_unknown',code,rejected,job))
        conn.commit()
        return dict(job_id=str(job),state='failed' if rejected else 'start_unknown',error_code=code)


def normalize_items(rows,binding):
    result=[]
    mapping=binding['field_mapping']
    for item in rows:
        if mapping.get('source_path') and value_at(item,mapping['source_path'])!=mapping.get('source_value'):
            raise AccessDenied('Unexpected source label in Actor dataset')
        row={field:value_at(item,path) for field,path in mapping['fields'].items()}
        for field in ('external_id',):
            if isinstance(row[field],(str,int)) and not isinstance(row[field],bool):row[field]=str(row[field])
        if 'rating_scale' not in row and 'rating_scale_constant' in mapping:
            row['rating_scale']=mapping['rating_scale_constant']
        if mapping.get('text_parts'):
            text=[row['review_text']] if row.get('review_text') else []
            for part in mapping['text_parts']:
                value=value_at(item,part['path'])
                if not isinstance(value,str):raise CollectionError('Expected text field')
                if value:text.append(part.get('label','')+(': ' if part.get('label') else '')+value)
            row['review_text']='\n\n'.join(text) or None
        published=row['published_at']
        if isinstance(published,str):
            row['published_at']=(datetime.fromisoformat(published.replace('Z','+00:00')).date().isoformat()
                                 if 'T' in published else date.fromisoformat(published).isoformat())
        if mapping.get('license_fields') or mapping.get('license_constants'):
            row['license_metadata']=dict(mapping.get('license_constants',{}))
            row['license_metadata'].update({key:value_at(item,path) for key,path in mapping.get('license_fields',{}).items()})
        row['product_key']=binding['product_key']
        result.append(row)
    return result


def refresh_job(conn,job_id,client=None):
    client=client or ApifyClient()
    initial=conn.execute('SELECT source_id FROM veriflow.apify_jobs WHERE id=%s',(job_id,)).fetchone()
    if not initial:raise CollectionError('Unknown job')
    # Match ingestion worker's source-before-job lock order.
    conn.execute('SELECT id FROM veriflow.sources WHERE id=%s FOR SHARE',(initial['source_id'],))
    job=conn.execute('SELECT * FROM veriflow.apify_jobs WHERE id=%s FOR UPDATE SKIP LOCKED',(job_id,)).fetchone()
    if not job:return dict(state='busy')
    if job['state'] in ('queued','ingested','failed','aborted','start_unknown','starting'):
        return dict(job_id=str(job_id),state=job['state'])
    try:
        with conn.transaction():
            binding=conn.execute('SELECT * FROM veriflow.apify_bindings WHERE id=%s FOR SHARE',(job['binding_id'],)).fetchone()
            run=client.run(job['actor_run_id'])
            if run.get('id')!=job['actor_run_id'] or run.get('actId')!=job['actor_id'] or run.get('buildId')!=job['build_id']:
                raise AccessDenied('Run provenance does not match')
            usage=usd(run['usageTotalUsd']) if run.get('usageTotalUsd') is not None else None
            # Usage is a provider-reported measurement, not a verified invoice total.
            conn.execute('UPDATE veriflow.apify_jobs SET reported_usage_usd=%s,updated_at=now() WHERE id=%s',(usage,job_id))
            status=run.get('status')
            if status in ('FAILED','TIMED-OUT','ABORTED'):
                state='aborted' if status=='ABORTED' else 'failed'
                conn.execute('UPDATE veriflow.apify_jobs SET state=%s,error_code=%s WHERE id=%s',(state,'apify_run_'+status.lower(),job_id))
                return dict(job_id=str(job_id),state=state)
            if status!='SUCCEEDED':
                try:
                    if not binding or binding_fingerprint(binding)!=job['binding_fingerprint']:
                        raise AccessDenied()
                    validate_binding(conn,binding,job['authorization_id'])
                except AccessDenied:
                    state='running'
                    if status in ('READY','RUNNING'):
                        stopped=client.abort(job['actor_run_id'])
                        state='aborted' if stopped.get('status')=='ABORTED' else 'running'
                    conn.execute('UPDATE veriflow.apify_jobs SET state=%s,error_code=%s,updated_at=now() WHERE id=%s',(state,'access_denied',job_id))
                    return dict(job_id=str(job_id),state=state,error_code='access_denied')
                return dict(job_id=str(job_id),state='running')
            if not binding or binding_fingerprint(binding)!=job['binding_fingerprint']:
                raise AccessDenied('Actor binding changed after reservation')
            validate_binding(conn,binding,job['authorization_id'])
            fields={'.'.join(path) for path in binding['field_mapping']['fields'].values()}
            fields.update('.'.join(path) for path in binding['field_mapping'].get('license_fields',{}).values())
            for part in binding['field_mapping'].get('text_parts',[]):fields.add('.'.join(part['path']))
            if binding['field_mapping'].get('source_path'):fields.add('.'.join(binding['field_mapping']['source_path']))
            rows=client.items(run['defaultDatasetId'],sorted(fields),binding['max_records'])
            if not isinstance(rows,list) or len(rows)>binding['max_records']:
                raise CollectionError('Dataset exceeds approved bound')
            if not rows:
                conn.execute("UPDATE veriflow.apify_jobs SET state='ingested',dataset_id=%s,retrieved=0,error_code=NULL WHERE id=%s",(run['defaultDatasetId'],job_id))
                return dict(job_id=str(job_id),state='ingested',retrieved=0)
            normalized=normalize_items(rows,binding)
            batch=enqueue(conn,job['source_id'],job['authorization_id'],json.dumps(normalized),'json',provider_job_id=job_id)
            conn.execute("UPDATE veriflow.apify_jobs SET state='queued',dataset_id=%s,retrieved=%s,error_code=NULL,updated_at=now() WHERE id=%s",(run['defaultDatasetId'],len(rows),job_id))
            return dict(job_id=str(job_id),state='queued',retrieved=len(rows),batch_id=str(batch))
    except Exception as exc:
        code=exc.code if isinstance(exc,CollectionError) else 'apify_normalization_failed'
        # Permission/validation failures require operator correction; transient reads
        # remain resumable. There is no second paid Actor start in this function.
        permanent=isinstance(exc,(AccessDenied,CollectionError,ValueError,TypeError,KeyError)) and not isinstance(exc,(ApifyError,RateLimited))
        conn.execute('UPDATE veriflow.apify_jobs SET state=%s,error_code=%s,updated_at=now() WHERE id=%s',('failed' if permanent else 'running',code,job_id))
        result=dict(job_id=str(job_id),state='failed' if permanent else 'running',error_code=code)
        if isinstance(exc,RateLimited):result['retry_after_seconds']=exc.retry_after
        return result
