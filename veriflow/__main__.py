import argparse
import json
import time
from pathlib import Path
from .db import connect, seed
from .worker import enqueue, run_one
from .connectors import CollectionError


def main():
    parser = argparse.ArgumentParser(description='Veriflow private collection engine')
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('seed')
    sub.add_parser('discover-composio')
    sub.add_parser('check-database')
    trends = sub.add_parser('collect-trends')
    trends.add_argument('--binding',required=True)
    trends.add_argument('--authorization',required=True)
    trends.add_argument('--request-file',type=Path,required=True)
    worker = sub.add_parser('worker')
    worker.add_argument('--once',action='store_true')
    admin = sub.add_parser('admin')
    admin.add_argument('--port',type=int,default=8080)
    imp = sub.add_parser('import')
    imp.add_argument('--source',required=True)
    imp.add_argument('--authorization',required=True)
    imp.add_argument('--file',type=Path,required=True)
    args = parser.parse_args()
    try:
        if args.command == 'admin':
            from .admin import serve
            serve(args.port)
        elif args.command == 'discover-composio':
            from .integrations import discover
            with connect() as conn:
                inventory = discover(conn)
            print(json.dumps(dict(status=inventory['status'],error_code=inventory.get('error_code'),
                providers=sorted({a['toolkit'] for a in inventory['connected_services']}),
                tool_count=len(inventory['tools']),execution_enabled=False)))
            return 0 if inventory['status']=='discovered' else 1
        elif args.command == 'check-database':
            from .health import database_health
            with connect() as conn:
                health = database_health(conn)
            print(json.dumps(health))
            return 0 if health['healthy'] else 1
        elif args.command == 'collect-trends':
            from .integrations import collect_trends
            with args.request_file.open('rb') as f:
                data = f.read(100_001)
            if len(data)>100_000:
                raise CollectionError()
            request = json.loads(data)
            with connect() as conn:
                result = collect_trends(conn,args.binding,args.authorization,**request)
            print(json.dumps(result))
            return 0 if result['status']=='success' else 1
        elif args.command == 'worker':
            while True:
                try:
                    with connect() as conn:
                        result = run_one(conn)
                    if result:
                        print(json.dumps(result),flush=True)
                    elif not args.once:
                        time.sleep(5)
                except Exception:
                    print(json.dumps({'status':'error','error_code':'worker_database_unavailable'}),flush=True)
                    if args.once:
                        return 1
                    time.sleep(30)
                if args.once:
                    break
        elif args.command == 'seed':
            with connect() as conn:
                seed(conn)
        elif args.command == 'import':
            # Bounded read even for unexpectedly large files.
            with args.file.open('rb') as f:
                payload = f.read(5_000_001)
            if len(payload)>5_000_000:
                raise CollectionError('Import exceeds 5MB')
            with connect() as conn:
                batch = enqueue(conn,args.source,args.authorization,payload.decode('utf-8-sig'),args.file.suffix[1:].lower())
            print(json.dumps({'batch_id':str(batch),'status':'queued'}))
        return 0
    except CollectionError as exc:
        print(json.dumps({'status':'error','error_code':exc.code}))
        return 1
    except Exception:
        print(json.dumps({'status':'error','error_code':'configuration_or_database_error'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
