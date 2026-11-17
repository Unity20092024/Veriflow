"""Stream large authorized exports into bounded, durable import batches."""
import csv
import json
from .connectors import CollectionError,AccessDenied
from .worker import enqueue


def import_file(conn,path,source_id,grant_id,max_records=100000):
    if not 1<=max_records<=1000000:raise CollectionError('Invalid file record ceiling')
    source=conn.execute('SELECT collection_method FROM veriflow.sources WHERE id=%s',(source_id,)).fetchone()
    if not source or source['collection_method']!='approved_import':raise AccessDenied('Bulk files require approved-import authorization')
    fmt=path.suffix.lower()
    if fmt not in ('.csv','.jsonl'):raise CollectionError('Use CSV or JSONL for streaming bulk imports')
    total,batches,size=0,0,2;batch=[]
    def flush():
        nonlocal batches,batch,size
        if not batch:return
        enqueue(conn,source_id,grant_id,json.dumps(batch),'json')
        conn.commit();batches+=1;batch=[];size=2
    with path.open(encoding='utf-8-sig',newline='') as stream:
        def lines():
            while True:
                line=stream.readline(1_000_001)
                if len(line)>1_000_000:raise CollectionError('Input line too long')
                if not line:break
                yield line
        if fmt=='.csv':
            csv.field_size_limit(1_000_000)
            reader=csv.DictReader(lines())
        else:reader=(json.loads(line) for line in lines() if line.strip())
        for record in reader:
            if total>=max_records:raise CollectionError('File exceeds requested record ceiling; earlier batches remain queued')
            if not isinstance(record,dict) or len(record)>30:raise CollectionError('Invalid record')
            encoded=json.dumps(record)
            if len(encoded.encode())>1_000_000:raise CollectionError('Record too large')
            if len(batch)>=1000 or size+len(encoded.encode())>4_000_000:flush()
            batch.append(record);size+=len(encoded.encode())+1;total+=1
        flush()
    return dict(records_queued=total,batches=batches)
