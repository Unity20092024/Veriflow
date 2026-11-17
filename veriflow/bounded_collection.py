"""One explicitly authorized free batch, driven by the existing worker.

HTTP attempts are charged durably BEFORE sending. Pending tasks survive crashes.
A session advisory lock serializes all batch I/O, including across worker copies.
There is never more than one unacknowledged review import, so the global unique
ceiling cannot overshoot. Neither activation nor restart renews the batch.
"""
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError
from urllib.request import build_opener

from psycopg.types.json import Jsonb

from .connectors import AccessDenied, CollectionError, RateLimited
from .libreviews_live import (
    BASE, SOURCE_ID, LibreReviewsClient, NoRedirect, PublicPages, public_url,
)
from .libreviews import extract_review

BATCH_ID = 'approved-free-libreviews-500'
LOCK_ID = 746395012
QUERIES = (
    'Firefox', 'uBlock Origin', 'Atom', 'KeePassXC', 'AnkiDroid', 'PeerTube',
    'SecureDrop', 'Parabola', 'Wikibase', 'Euro Truck Simulator',
    'software', 'browser', 'editor', 'operating system', 'email client',
    'chat client', 'password manager', 'development', 'LibreOffice', 'GIMP',
    'VLC', 'Thunderbird', 'Inkscape', 'Blender', 'Linux', 'Debian', 'Ubuntu',
    'Audacity', 'Nextcloud', 'Signal', 'Telegram', 'Mastodon', 'Git',
    'media player', 'computer game', 'Android application',
    'GNU', 'free software', 'open source', 'application', 'program',
    'image editor', 'text editor', 'vector graphics', 'terminal emulator',
    'office suite', 'audio editor', 'video editor', 'database', 'messaging',
    'file manager', 'BitTorrent', 'encryption', 'backup', 'feed reader',
    'Chromium', 'Tor Browser', 'Brave', 'Vivaldi', 'Emacs', 'Vim', 'Neovim',
    'Visual Studio Code', 'Notepad', 'Kate', 'Geany', 'gedit', 'Krita',
    'Darktable', 'RawTherapee', 'Scribus', 'Shotcut', 'Kdenlive', 'OBS',
    'mpv', 'Kodi', 'Rhythmbox', 'Clementine', 'Calibre', 'Okular', 'Evince',
    'Transmission', 'qBittorrent', 'Syncthing', 'Jitsi', 'Element', 'Matrix',
    'Pidgin', 'HexChat', 'Evolution', 'Geary', 'Mutt', 'Zotero', 'Joplin',
    'Obsidian', 'Logseq', 'Anki', 'Flatpak', 'Steam', 'Minetest',
    'SuperTuxKart', 'OpenTTD', '0 A.D.', 'Battle for Wesnoth',
)
_policy_cache = None


class BatchLimit(CollectionError):
    code = 'approved_batch_limit'


class OperatorInterrupted(CollectionError):
    code = 'operator_interrupted'


def permitted_candidate(product):
    """Keep native metadata classification; reject known non-software subjects."""
    return (product.get('category') in (
        'Software', 'Web browsers', 'Browser extensions', 'Developer tools')
        and product.get('name', '').casefold() not in (
            'libre game night', 'libre.fm', 'alternativeto'))



def task(conn, kind, url, data):
    conn.execute('''INSERT INTO veriflow.free_batch_tasks(batch_id,kind,url,data)
        VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
        (BATCH_ID, kind, url, Jsonb(data)))


def activate(conn, strategy='breadth_first', target_reviews=None):
    """Explicit operator command only. Existing activation is immutable."""
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_ID,))
        previous = conn.execute('SELECT id,state FROM veriflow.free_batches WHERE id=%s',
                                (BATCH_ID,)).fetchone()
        if previous:
            return dict(previous, already_activated=True)
        source = conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE',
                              (SOURCE_ID,)).fetchone()
        if not source or not source['enabled'] or source['access_status'] != 'approved':
            raise AccessDenied('The existing approved free source is required')
        from .strategy import preferences
        strategy, target_reviews = preferences(strategy,target_reviews)
        conn.execute('INSERT INTO veriflow.free_batches(id,strategy,target_reviews) VALUES (%s,%s,%s)',
                     (BATCH_ID,strategy,target_reviews))
        grant = conn.execute('''INSERT INTO veriflow.authorizations
            (source_id,method,evidence,product_keys,full_text_allowed,approved_by,
             expires_at,license_id,terms_url)
            SELECT %s,'permitted_crawl',%s,ARRAY['https://lib.reviews/mozilla-firefox']::text[],true,
             'Single administrator explicitly approved bounded multi-product batch',
             expires_at,'CC-BY-SA-4.0',%s FROM veriflow.free_batches WHERE id=%s RETURNING id''',
            (SOURCE_ID,
             'Explicit approval: 500 new unique reviews, 100 software products, '
             '1500 HTTP attempts, 10 listing pages/product, >=3s serial delay, '
             '48h from first activation, $0 paid services, lib.reviews only. '
             'CC BY-SA 4.0 credit/link/change notice retained. No recurring collection.',
             BASE+'/terms', BATCH_ID)).fetchone()
        conn.execute('UPDATE veriflow.free_batches SET authorization_id=%s WHERE id=%s',
                     (grant['id'], BATCH_ID))
        for query in QUERIES:
            task(conn, 'discover', BASE+'/actions/search?'+urlencode({'query': query}),
                 {'query': query})
    return {'id': BATCH_ID, 'state': 'running', 'paid_budget_usd': 0}


def progress(conn):
    return conn.execute('''SELECT b.id,b.state,b.started_at,b.expires_at,
        b.max_unique,b.max_products,b.max_requests,b.max_pages,b.requests,
        b.failed_requests,b.error_code,b.strategy,b.target_reviews,
        (SELECT count(*) FROM veriflow.free_batch_products p WHERE p.batch_id=b.id) AS products_discovered,
        (SELECT coalesce(sum(r.inserted),0) FROM veriflow.collection_runs r
         JOIN veriflow.import_batches i ON i.id=r.batch_id
         WHERE i.authorization_id=b.authorization_id) AS new_unique_reviews,
        (SELECT coalesce(sum(r.duplicates),0) FROM veriflow.collection_runs r
         JOIN veriflow.import_batches i ON i.id=r.batch_id
         WHERE i.authorization_id=b.authorization_id) AS duplicates_skipped,
        (SELECT count(*) FROM veriflow.free_batch_tasks t WHERE t.batch_id=b.id
         AND t.error_code IS NOT NULL) AS errors,
        (SELECT count(*) FROM veriflow.free_batch_tasks t WHERE t.batch_id=b.id
         AND t.state='pending') AS pending_tasks,
        (SELECT count(*) FROM veriflow.free_batch_products p WHERE p.batch_id=b.id
         AND NOT EXISTS(SELECT 1 FROM veriflow.free_batch_tasks t
          WHERE t.batch_id=b.id AND t.data->>'product_url'=p.url
          AND t.state IN ('pending','importing','failed'))) AS products_completed,
        'lib.reviews only (1 authorized source)' AS source_coverage,
        CASE WHEN b.state='completed' THEN 1 ELSE 0 END AS sources_completed,
        0 AS paid_spend_usd
        FROM veriflow.free_batches b WHERE b.id=%s''', (BATCH_ID,)).fetchone()


def stop(conn, state, code):
    with conn.transaction():
        conn.execute("UPDATE veriflow.free_batches SET state=%s,error_code=%s,updated_at=now() WHERE id=%s AND state='running'",
                     (state, code, BATCH_ID))


def reserve_http(conn, interval=3):
    """Persist the attempt even if the process dies before a response arrives."""
    row = conn.execute('SELECT *,now() AS db_now FROM veriflow.free_batches WHERE id=%s',
                       (BATCH_ID,)).fetchone()
    conn.commit()
    if row['state'] != 'running':
        raise OperatorInterrupted()
    wait = max(0, (row['next_http_at']-row['db_now']).total_seconds())
    if wait:
        time.sleep(wait)
    with conn.transaction():
        result = conn.execute('''UPDATE veriflow.free_batches
            SET requests=requests+1,next_http_at=now()+(%s * interval '1 second'),updated_at=now()
            WHERE id=%s AND state='running' AND requests<max_requests AND expires_at>now()
            RETURNING requests''', (max(3, interval), BATCH_ID)).fetchone()
        if not result:
            current = conn.execute('SELECT state,error_code FROM veriflow.free_batches WHERE id=%s',
                                   (BATCH_ID,)).fetchone()
            if current and current['error_code'] in ('operator_paused', 'operator_stopped'):
                raise OperatorInterrupted()
            raise BatchLimit('Original request/time limit reached')


def client_for(conn):
    transport = build_opener(NoRedirect()).open

    def send(request, **kwargs):
        reserve_http(conn, client.interval)
        try:
            return transport(request, **kwargs)
        except Exception as exc:
            # Redirect responses are not failed requests, but are counted attempts.
            if not isinstance(exc, HTTPError) or exc.code >= 400:
                with conn.transaction():
                    conn.execute('UPDATE veriflow.free_batches SET failed_requests=failed_requests+1 WHERE id=%s',
                                 (BATCH_ID,))
            raise

    client = LibreReviewsClient(transport=send, interval=3)
    global _policy_cache
    if _policy_cache and time.monotonic()-_policy_cache[0] < 3600:
        client.robots, client.terms_hash, client.interval = _policy_cache[1:]
    else:
        digest = client.verify_policy()
        with conn.transaction():
            row = conn.execute('SELECT policy_hash FROM veriflow.free_batches WHERE id=%s',
                               (BATCH_ID,)).fetchone()
            if row['policy_hash'] and row['policy_hash'] != digest:
                raise AccessDenied('Source terms changed; renewed review required')
            conn.execute('UPDATE veriflow.free_batches SET policy_hash=%s WHERE id=%s',
                         (digest, BATCH_ID))
        _policy_cache = (time.monotonic(), client.robots, client.terms_hash, client.interval)
    return client


def add_product(conn, product, grant_id):
    if not permitted_candidate(product):
        return
    url = public_url(product['url'])
    if len(urlsplit(url).path.strip('/').split('/')) != 1:
        raise AccessDenied('Discovery returned a non-product path')
    if conn.execute('SELECT 1 FROM veriflow.free_batch_products WHERE batch_id=%s AND url=%s',
                    (BATCH_ID, url)).fetchone():
        return
    count = conn.execute('SELECT count(*) AS n FROM veriflow.free_batch_products WHERE batch_id=%s',
                         (BATCH_ID,)).fetchone()['n']
    if count >= 100:
        return
    mapping = conn.execute('SELECT * FROM veriflow.source_products WHERE source_id=%s AND external_key=%s',
                           (SOURCE_ID, url)).fetchone()
    if mapping:
        if mapping['expected_name'] != product['name']:
            raise AccessDenied('Existing product identity conflicts')
        product_id = mapping['product_id']
    else:
        prospective = conn.execute('SELECT strategy FROM veriflow.free_batches WHERE id=%s',
                                   (BATCH_ID,)).fetchone()
        if prospective and prospective['strategy']:
            from .strategy import resolve_discovered_product
            canonical = resolve_discovered_product(conn,product['name'])
            matches = [{'id':canonical}] if canonical else []
        else:
            matches = conn.execute('SELECT id FROM veriflow.products WHERE lower(trim(name))=lower(%s)',
                                   (product['name'],)).fetchall()
        if len(matches) > 1:
            raise AccessDenied('Ambiguous existing product identity')
        product_id = matches[0]['id'] if matches else conn.execute(
            "INSERT INTO veriflow.products(name,vendor) VALUES (%s,'Not stated by source') RETURNING id",
            (product['name'],)).fetchone()['id']
        conn.execute('''INSERT INTO veriflow.source_products(source_id,external_key,product_id,expected_name)
            VALUES (%s,%s,%s,%s)''', (SOURCE_ID, url, product_id, product['name']))
    strategy_row = conn.execute('SELECT strategy FROM veriflow.free_batches WHERE id=%s',
                                (BATCH_ID,)).fetchone()
    if strategy_row and strategy_row['strategy']:
        # Different URLs/names for a confirmed identity are one discovery slot.
        if conn.execute('''SELECT 1 FROM veriflow.free_batch_products bp
          JOIN veriflow.products p ON p.id=bp.product_id
          WHERE bp.batch_id=%s AND coalesce(p.canonical_product_id,p.id)=
            (SELECT coalesce(canonical_product_id,id) FROM veriflow.products WHERE id=%s)''',
          (BATCH_ID,product_id)).fetchone():
            return
    category_id = conn.execute('''INSERT INTO veriflow.categories(name) VALUES (%s)
        ON CONFLICT(lower(trim(name))) DO UPDATE SET name=veriflow.categories.name RETURNING id''',
        (product['category'],)).fetchone()['id']
    conn.execute('INSERT INTO veriflow.product_categories VALUES (%s,%s) ON CONFLICT DO NOTHING',
                 (product_id, category_id))
    conn.execute('INSERT INTO veriflow.free_batch_products VALUES (%s,%s,%s,%s,%s)',
                 (BATCH_ID, product_id, url, product['name'], product['category']))
    conn.execute('''UPDATE veriflow.authorizations SET product_keys=array_append(product_keys,%s)
        WHERE id=%s AND NOT (%s=ANY(product_keys))''', (url, grant_id, url))
    task(conn, 'listing', url, {'product_url': url, 'name': product['name'], 'page': 1})


def execute_task(conn, client, item, batch):
    data = item['data']
    if item['kind'] == 'discover':
        products = client.discover(data['query'], limit=10,skip_unsupported_search_links=True)
        with conn.transaction():
            for product in products:
                add_product(conn, product, batch['authorization_id'])
    elif item['kind'] == 'listing':
        listing = PublicPages()
        listing.feed(client.get(item['url']))
        title = ' '.join(''.join(listing.title).split())
        if title.casefold() != data['name'].casefold():
            raise AccessDenied('Source product title changed')
        with conn.transaction():
            for url in listing.reviews:
                task(conn, 'review', url, data)
            if listing.next_page and data['page'] < batch['max_pages']:
                if not urlsplit(listing.next_page).path.startswith(
                        urlsplit(data['product_url']).path+'/before/'):
                    raise AccessDenied('Cross-product pagination')
                task(conn, 'listing', listing.next_page, dict(data, page=data['page']+1))
            elif listing.next_page:
                conn.execute("UPDATE veriflow.free_batch_tasks SET error_code='product_page_limit' WHERE id=%s",
                             (item['id'],))
    else:
        record = extract_review(client.get(item['url']), data['product_url'], item['url'])
        if (record['software_name'].casefold() != data['name'].casefold()
                or record['original_url'] != item['url']):
            raise AccessDenied('Review product identity changed')
        from .worker import enqueue
        with conn.transaction():
            batch_id = enqueue(conn, SOURCE_ID, batch['authorization_id'],
                               json.dumps([record], ensure_ascii=False), 'json')
            conn.execute('''UPDATE veriflow.free_batch_tasks SET state='importing',
                batch_import_id=%s WHERE id=%s''', (batch_id, item['id']))
            conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s', (SOURCE_ID,))
        return
    with conn.transaction():
        conn.execute("UPDATE veriflow.free_batch_tasks SET state='done' WHERE id=%s", (item['id'],))


def tick(conn):
    """Run one checkpointed step; normal worker handles licensed ingestion."""
    locked = conn.execute('SELECT pg_try_advisory_lock(%s) AS acquired',
                          (LOCK_ID,)).fetchone()['acquired']
    conn.commit()
    if not locked:
        return None
    item = None
    try:
        batch = progress(conn)
        conn.commit()
        if not batch or batch['state'] != 'running':
            return None
        # A single pending import is the unique-cap reservation. Never enqueue
        # another until its real inserted/duplicate result has committed.
        importing = conn.execute('''SELECT t.id,i.status FROM veriflow.free_batch_tasks t
            JOIN veriflow.import_batches i ON i.id=t.batch_import_id
            WHERE t.batch_id=%s AND t.state='importing' LIMIT 1''', (BATCH_ID,)).fetchone()
        conn.commit()
        if importing:
            if importing['status'] == 'pending':
                return None
            with conn.transaction():
                conn.execute('UPDATE veriflow.free_batch_tasks SET state=%s,error_code=%s WHERE id=%s',
                             ('done' if importing['status']=='completed' else 'failed',
                              None if importing['status']=='completed' else 'ingestion_failed',
                              importing['id']))
            return {'free_batch': BATCH_ID, 'import_status': importing['status']}
        if batch['new_unique_reviews'] >= 500:
            stop(conn, 'limited', 'unique_review_limit')
            return {'free_batch': BATCH_ID, 'state': 'limited'}
        if datetime.now(timezone.utc) >= batch['expires_at']:
            stop(conn, 'expired', 'original_48_hour_limit')
            return None
        if batch['requests'] >= 1500:
            stop(conn, 'limited', 'request_limit')
            return None
        next_http = conn.execute('SELECT next_http_at,now() AS db_now FROM veriflow.free_batches WHERE id=%s',
                                 (BATCH_ID,)).fetchone()
        conn.commit()
        if (next_http['next_http_at']-next_http['db_now']).total_seconds() > 3:
            return None
        from .worker import authorization
        with conn.transaction():
            grant = authorization(conn, SOURCE_ID, conn.execute(
                'SELECT authorization_id FROM veriflow.free_batches WHERE id=%s',
                (BATCH_ID,)).fetchone()['authorization_id'], 'permitted_crawl')
            source = conn.execute('SELECT * FROM veriflow.sources WHERE id=%s', (SOURCE_ID,)).fetchone()
            if (not source['enabled'] or source['access_status'] != 'approved'
                    or source['url'] != BASE or source['collection_method'] != 'permitted_crawl'
                    or source['required_license_id'] != 'CC-BY-SA-4.0'
                    or not source['attribution_required'] or not source['full_text_allowed']
                    or not grant['full_text_allowed'] or grant['license_id'] != 'CC-BY-SA-4.0'
                    or grant['terms_url'] != BASE+'/terms'):
                raise AccessDenied('Source authorization changed')
            if batch.get('strategy'):
                from .strategy import bounded_task
                item = bounded_task(conn,BATCH_ID,batch['strategy'],batch['target_reviews'])
            else:
                item = conn.execute('''SELECT * FROM veriflow.free_batch_tasks
                    WHERE batch_id=%s AND state='pending'
                    ORDER BY CASE kind WHEN 'discover' THEN 0 WHEN 'review' THEN 1 ELSE 2 END,id LIMIT 1''',
                    (BATCH_ID,)).fetchone()
        if not item:
            stop(conn, 'completed', None)
            return {'free_batch': BATCH_ID, 'state': 'completed'}
        execute_task(conn, client_for(conn), item, dict(batch, authorization_id=grant['id']))
        return {'free_batch': BATCH_ID, 'task': item['kind'], 'status': 'checkpoint_saved'}
    except RateLimited as exc:
        with conn.transaction():
            conn.execute('''UPDATE veriflow.free_batches SET next_http_at=
                greatest(next_http_at,now()+(%s * interval '1 second')) WHERE id=%s''',
                (max(3, exc.retry_after), BATCH_ID))
            if item:
                conn.execute("UPDATE veriflow.free_batch_tasks SET state='failed',error_code='rate_limited' WHERE id=%s",
                             (item['id'],))
        return {'free_batch': BATCH_ID, 'error_code': 'rate_limited'}
    except OperatorInterrupted:
        return {'free_batch': BATCH_ID, 'state': 'operator_interrupted'}
    except BatchLimit:
        stop(conn, 'limited', 'original_request_or_time_limit')
        return {'free_batch': BATCH_ID, 'state': 'limited'}
    except AccessDenied as exc:
        # Safe fixed error identifiers only, never raw exception strings.
        reasons = {
            'Public product/review paths only': 'non_product_search_link',
            'Unexpected source query': 'unexpected_search_link_query',
            'Discovery returned a non-product path': 'non_product_discovery',
            'Source product title changed': 'product_title_changed',
            'Review product identity changed': 'review_identity_changed',
            'Existing product identity conflicts': 'mapping_conflict',
            'Ambiguous existing product identity': 'ambiguous_product',
        }
        reason = reasons.get(str(exc))
        if reason and item:
            with conn.transaction():
                conn.execute("UPDATE veriflow.free_batch_tasks SET state='failed',error_code=%s WHERE id=%s",
                             (reason, item['id']))
            return {'free_batch': BATCH_ID, 'error_code': reason}
        stop(conn, 'blocked', 'source_policy_or_identity_denied')
        return {'free_batch': BATCH_ID, 'state': 'blocked'}
    except Exception as exc:
        conn.rollback()
        code = exc.code if isinstance(exc, CollectionError) else 'free_batch_task_failed'
        if item:
            with conn.transaction():
                conn.execute("UPDATE veriflow.free_batch_tasks SET state='failed',error_code=%s WHERE id=%s",
                             (code, item['id']))
        else:
            stop(conn, 'blocked', code)
        return {'free_batch': BATCH_ID, 'error_code': code}
    finally:
        conn.execute('SELECT pg_advisory_unlock(%s)', (LOCK_ID,))
        conn.commit()
