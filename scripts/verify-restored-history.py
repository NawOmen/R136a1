"""Compare every row in auth/marketplace/agents on quiescent PostgreSQL copies.

Read-only. Does not print row contents, company IDs, file names, or credentials.
Run before restarting writers/seed. Object downloads need a separate MinIO check.
"""
import argparse
import json
import re
import subprocess


def history(container, user, database):
    def sql(query):
        return subprocess.check_output(['docker','exec',container,'psql','-U',user,'-d',database,'-Atc',query],text=True).strip()
    tables=sql("SELECT schemaname||'.'||tablename FROM pg_tables WHERE schemaname IN ('auth','marketplace','agents') ORDER BY 1").splitlines()
    if not tables:
        raise ValueError('Нет продуктовых схем: пустая база не является доказательством')
    result={}
    for table in tables:
        if not re.fullmatch(r'(auth|marketplace|agents)\.[a-z_][a-z_0-9]*',table):
            raise ValueError('Неожиданное имя таблицы')
        result[table]=sql(f"SELECT count(*)||'|'||COALESCE(md5(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text)),'empty') FROM {table} t")
    if all(v.startswith("0|") for v in result.values()):
        raise ValueError("В схемах нет строк: пустая копия не является доказательством")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True)
    p.add_argument('--target',required=True)
    p.add_argument('--user',default='sborka')
    p.add_argument('--database',default='sborka')
    a=p.parse_args()
    if a.source==a.target:p.error('Нужна отдельная копия')
    first=history(a.source,a.user,a.database)
    second=history(a.target,a.user,a.database)
    different=[table for table in set(first)|set(second) if first.get(table)!=second.get(table)]
    print(json.dumps({'equal':not different,'tables':len(first), 'different_tables':sorted(different),
        'nonempty_tables':sum(not v.startswith('0|') for v in first.values())},ensure_ascii=False,indent=2))
    return 1 if different else 0

if __name__=='__main__':raise SystemExit(main())
