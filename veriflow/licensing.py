"""Minimal public credit required by a source's approved content license."""
import re
from urllib.parse import urlsplit
from .connectors import AccessDenied,CollectionError,canonical_url

LICENSES={'CC-BY-SA-4.0':'https://creativecommons.org/licenses/by-sa/4.0/',
          'CC-BY-4.0':'https://creativecommons.org/licenses/by/4.0/'}
FIELDS={'license_id','license_url','source_terms_url','public_credit','attribution_url','text_modified','change_note'}


def validate_license(metadata,source,grant):
    required=source.get('required_license_id')
    if not required and metadata is None:return None
    if not required or required not in LICENSES or not isinstance(metadata,dict):
        raise AccessDenied('Approved license metadata required')
    if set(metadata)-FIELDS or metadata.get('license_id')!=required or grant.get('license_id')!=required:
        raise AccessDenied('License does not match approved source/grant')
    if metadata.get('license_url')!=LICENSES[required]:raise AccessDenied()
    source_host=urlsplit(source['url']).hostname
    for key in ('source_terms_url','attribution_url'):
        value=metadata.get(key)
        if not isinstance(value,str) or len(value)>2048:raise CollectionError()
        url=canonical_url(value)
        parts=urlsplit(url)
        mangrove_review_link = (
            key == 'attribution_url'
            and source.get('id') == 'mangrove-reviews'
            and parts.netloc == 'api.mangrove.reviews'
            and re.fullmatch(r'/review/[A-Za-z0-9_-]{40,200}',parts.path)
            and not parts.query
        )
        if parts.hostname!=source_host and not mangrove_review_link:raise AccessDenied()
    if metadata['source_terms_url']!=grant.get('terms_url'):raise AccessDenied()
    credit=metadata.get('public_credit')
    if not isinstance(credit,str) or not credit.strip() or len(credit)>200 or '\n' in credit or re.search(r'\S+@\S+\.\S+',credit):
        raise CollectionError('Only minimal public attribution is accepted')
    if not source.get('attribution_required'):raise AccessDenied()
    if not isinstance(metadata.get('text_modified'),bool):raise CollectionError()
    note=metadata.get('change_note')
    if note is not None and (not isinstance(note,str) or len(note)>1000):raise CollectionError()
    if metadata['text_modified'] and (not note or not note.strip()):raise AccessDenied('Describe text changes')
    return {key:metadata.get(key) for key in sorted(FIELDS)}


def validate_mapping(mapping,source,grant):
    fields=mapping.get('license_fields',{})
    constants=mapping.get('license_constants',{})
    required=source.get('required_license_id')
    if not required:
        if fields or constants:raise AccessDenied('License mapping requires approved source license policy')
        return
    if not isinstance(fields,dict) or not isinstance(constants,dict):raise AccessDenied()
    if set(fields)|set(constants) != FIELDS or set(fields)&set(constants):
        raise AccessDenied('Complete non-overlapping license mapping required')
    if not {'public_credit','attribution_url'}.issubset(fields):raise AccessDenied('Credit must come from source output')
    if set(fields)-{'public_credit','attribution_url'}:raise AccessDenied('Review the fixed licensing constants separately')
    if required not in LICENSES or constants.get('license_id')!=required or grant.get('license_id')!=required:
        raise AccessDenied()
    if not source.get('attribution_required') or constants.get('license_url')!=LICENSES[required]:raise AccessDenied()
    terms=constants.get('source_terms_url')
    if terms!=grant.get('terms_url') or urlsplit(canonical_url(terms)).hostname!=urlsplit(source['url']).hostname:
        raise AccessDenied()
    if not isinstance(constants.get('text_modified'),bool):raise AccessDenied()
    if constants['text_modified'] and not str(constants.get('change_note') or '').strip():raise AccessDenied()
    for path in fields.values():
        if not isinstance(path,list) or not 1<=len(path)<=10 or not all(isinstance(k,str) and k and ',' not in k for k in path):
            raise AccessDenied()
