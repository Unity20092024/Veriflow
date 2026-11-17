"""Bounded Apify v2 client. Token only in headers; provider responses never logged."""
import json
import os
import re
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .config import load_environment
from .connectors import CollectionError, RateLimited

BASE_URL='https://api.apify.com/v2'


class ApifyError(CollectionError):
    code='apify_request_failed'


class StartUnknown(ApifyError):
    code='apify_start_unknown'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):
        raise CollectionError('Invalid provider identifier')
    return value


def usd(value):
    try:
        amount=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):
        raise CollectionError('Invalid cost') from None
    if not amount.is_finite() or amount<0:
        raise CollectionError('Invalid cost')
    return amount


class ApifyClient:
    def __init__(self,token=None,transport=None):
        load_environment()
        self.token=token or os.environ.get('APIFY_TOKEN')
        self.transport=transport or build_opener(NoRedirect()).open

    def request(self,method,path,params=None,body=None,raw=False):
        if not self.token:
            error=ApifyError();error.code='apify_credentials_missing';raise error
        if not path.startswith('/') or '?' in path or '..' in path:
            raise ApifyError()
        url=BASE_URL+path+('?' + urlencode(params) if params else '')
        req=Request(url,data=json.dumps(body).encode() if body is not None else None,
                    method=method,headers={'Authorization':'Bearer '+self.token,
                    'Content-Type':'application/json','Accept':'application/json'})
        try:
            with self.transport(req,timeout=30) as response:
                payload=response.read(5_000_001)
                if len(payload)>5_000_000:
                    raise ApifyError('Provider response exceeds 5MB')
                return payload if raw else json.loads(payload)
        except HTTPError as exc:
            if exc.code==429:
                try:delay=int(exc.headers.get('Retry-After','60'))
                except (TypeError,ValueError):delay=60
                raise RateLimited(delay) from None
            error=ApifyError()
            error.code='apify_authentication_failed' if exc.code==401 else 'apify_permission_denied' if exc.code==403 else 'apify_request_failed'
            if method=='POST' and path.endswith('/runs') and exc.code>=500:
                raise StartUnknown() from None
            raise error from None
        except (URLError,TimeoutError,OSError,ValueError):
            if method=='POST' and path.endswith('/runs'):
                raise StartUnknown() from None
            raise ApifyError() from None

    def actor(self,actor_id):
        return self.request('GET','/acts/'+identifier(actor_id))['data']

    def build(self,build_id):
        return self.request('GET','/actor-builds/'+identifier(build_id))['data']

    def start(self,actor_id,build_number,actor_input,max_usd,max_records,timeout):
        if not re.fullmatch(r'\d+\.\d+\.\d+',build_number):
            raise CollectionError('Pin a numeric Actor build')
        max_usd=usd(max_usd)
        if max_usd<=0 or not 1<=max_records<=1000 or not 30<=timeout<=3600:
            raise CollectionError('Invalid run bounds')
        serialized=json.dumps(actor_input)
        if len(serialized.encode())>100_000 or (self.token and self.token in serialized):
            raise CollectionError('Actor input must not contain the Apify credential')
        params=dict(build=build_number,memory=512,maxTotalChargeUsd=str(max_usd),maxItems=max_records,
                    timeout=timeout,restartOnError='false',forcePermissionLevel='LIMITED_PERMISSIONS')
        response=self.request('POST','/acts/'+identifier(actor_id)+'/runs',params,actor_input)
        data=response.get('data',{})
        if not data.get('id'):
            raise StartUnknown()
        return data

    def run(self,run_id):
        return self.request('GET','/actor-runs/'+identifier(run_id))['data']

    def abort(self,run_id):
        return self.request('POST','/actor-runs/'+identifier(run_id)+'/abort')['data']

    def export(self,dataset_id,fields,limit=100,offset=0,format='json'):
        if format not in ('json','csv') or not 1<=limit<=1000 or offset<0:
            raise CollectionError('Invalid export bounds')
        # No skipEmpty/clean filtering: offsets must refer to stable raw rows.
        params=dict(format=format,limit=limit,offset=offset,fields=','.join(fields),
                    clean='false',skipEmpty='false',skipHidden='true')
        result=self.request('GET','/datasets/'+identifier(dataset_id)+'/items',params,raw=format=='csv')
        if format=='json' and (not isinstance(result,list) or len(result)>limit):
            raise ApifyError('Invalid dataset response')
        return result

    def items(self,dataset_id,fields,max_records):
        if not 1<=max_records<=1000:
            raise CollectionError('Invalid collection bound')
        rows=[]
        while len(rows)<max_records:
            limit=min(100,max_records-len(rows))
            page=self.export(dataset_id,fields,limit,len(rows))
            rows.extend(page)
            if len(page)<limit:break
        return rows
