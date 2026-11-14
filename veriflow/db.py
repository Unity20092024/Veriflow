import os
import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row,
                          connect_timeout=10, options='-c statement_timeout=30000')


def seed(conn):
    from .registry import load_registry
    for s in load_registry():
        conn.execute('''INSERT INTO veriflow.sources
            (id,name,url,category,aliases,provenance,collection_method,access_status,
             enabled,schedule_seconds,minimum_interval_seconds,full_text_allowed,policy_notes)
            VALUES (%(id)s,%(name)s,%(url)s,%(category)s,%(aliases)s,%(provenance)s,
            %(collection_method)s,%(access_status)s,%(enabled)s,%(schedule_seconds)s,
            %(minimum_interval_seconds)s,%(full_text_allowed)s,%(policy_notes)s)
            ON CONFLICT (id) DO NOTHING''', s)
