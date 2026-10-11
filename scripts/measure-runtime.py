"""Bounded synthetic optimizer benchmark. No production writes or payload logging.

Set OPTIMIZER_URL and OPTIMIZER_TOKEN outside Git. Output includes observed HTTP
statuses and business assertions; passing a health endpoint is not a solver proof.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import uuid
import math
import statistics
import time
import urllib.error
import urllib.request


def request(url, payload, token, timeout):
    start = time.perf_counter()
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={'Content-Type':'application/json', 'X-Optimizer-Token':token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.load(response), time.perf_counter()-start
    except urllib.error.HTTPError as error:
        return error.code, {}, time.perf_counter()-start
    except (OSError, TimeoutError):
        return 0, {}, time.perf_counter()-start


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--concurrency',type=int,default=2)
    parser.add_argument('--timeout',type=float,default=15)
    parser.add_argument('--slo-seconds',type=float,default=5)
    args=parser.parse_args()
    if not 1<=args.samples<=100 or not 1<=args.concurrency<=4 or not 0<args.timeout<=60 or not 0<args.slo_seconds<=args.timeout:
        parser.error('Разрешены 1–100 запросов, 1–4 клиента, timeout до 60 секунд')
    token=os.environ['OPTIMIZER_TOKEN']
    url=os.environ.get('OPTIMIZER_URL','http://optimizer:8004')+'/api/v2/optimize/allocations'
    producers=[{'company_id':str(uuid.UUID(int=i+1)),
        'moq_units':1,'capacity_units':100,'unit_price_rub':'10.00','lead_time_days':1} for i in range(25)]
    payload={'demand_units':100,'deadline_days':10,'producers':producers}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results=list(pool.map(lambda _:request(url,payload,token,args.timeout),range(args.samples)))
    elapsed=sorted(r[2] for r in results)
    valid=all(r[0]==200 and any(v.get('feasible') and v.get('total_units')==100 and v.get('total_cost_rub')=='1000.00' for v in r[1].get('variants', [])) for r in results)
    # Above-size rejection is independent of request success and never writes.
    excess={**payload,'producers':producers+[producers[0]]}
    overload=request(url,excess,token,args.timeout)
    p95=elapsed[max(0,math.ceil(len(elapsed)*.95)-1)]
    report={'scenario':'100 единиц, 25 синтетических поставщиков', 'samples':args.samples,
        'concurrency':args.concurrency, 'median_seconds':statistics.median(elapsed),
        'p95_seconds':p95,'max_seconds':max(elapsed),'statuses':{str(s):sum(r[0]==s for r in results) for s in {r[0] for r in results}},
        'business_result_valid':valid,'above_size_status':overload[0],
        'target_p95_seconds':args.slo_seconds,'target_met':valid and p95<=args.slo_seconds,
        'limits':'Проверена только указанная выборка. Время включает ожидание HTTP; очередь отдельно не инструментирована.'}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if valid and overload[0]==422 and p95<=args.slo_seconds else 1

if __name__=='__main__':
    raise SystemExit(main())
