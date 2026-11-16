"""Versioned first-test ceilings; environment variables may only lower them."""
import json
import os
from pathlib import Path
from .apify import usd
from .connectors import CollectionError

POLICY=Path(__file__).resolve().parents[1]/'data/collection-strategy.json'


class PaidRunsDisabled(CollectionError):
    code='apify_paid_runs_disabled'


def policy():
    value=json.loads(POLICY.read_text())['first_test']
    if not 1<=value['max_review_records']<=20 or not 0<usd(value['max_total_usd'])<=1:
        raise ValueError('Invalid approved first-test limits')
    return value


def paid_enabled():
    return os.environ.get('APIFY_PAID_RUNS_ENABLED','false').lower()=='true' and policy().get('paid_execution_authorized') is True


def require_paid_enabled():
    if not paid_enabled():raise PaidRunsDisabled()


def max_records():
    return min(policy()['max_review_records'],int(os.environ.get('APIFY_MAX_RECORDS','20')))


def summary():
    p=policy()
    return dict(pilot=p['id'],max_total_usd=str(usd(p['max_total_usd'])),
                max_review_records=max_records(),paid_runs_enabled=paid_enabled(),
                apify_token_configured=bool(os.environ.get('APIFY_TOKEN') or os.environ.get('APIFY_API_KEY')))
