"""Run inside marketplace image against quiescent source and restored MinIO.

Uses existing service credentials; target must use matching keys. No object names,
contents or credentials are logged. MINIO_COPY_ENDPOINT explicitly selects copy.
"""
import asyncio
import hashlib
import json
import os
from minio import Minio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings

async def main():
    target=os.environ['MINIO_COPY_ENDPOINT']
    if target==settings.minio_endpoint:raise ValueError('Нужен отдельный MinIO')
    clients=[Minio(endpoint,access_key=settings.minio_access_key,secret_key=settings.minio_secret_key,
                   secure=False) for endpoint in (settings.minio_endpoint,target)]
    copies=[]
    for client in clients:
        hashes={}
        for bucket in client.list_buckets():
            for item in client.list_objects(bucket.name,recursive=True):
                response=client.get_object(bucket.name,item.object_name)
                try:
                    digest=hashlib.sha256()
                    for block in response.stream(1024*1024):digest.update(block)
                    hashes[(bucket.name,item.object_name)]=digest.hexdigest()
                finally:response.close();response.release_conn()
        copies.append(hashes)
    engine=create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            keys=(await conn.execute(text('SELECT file_key FROM marketplace.documents UNION SELECT file_key FROM marketplace.need_files UNION SELECT storage_key FROM marketplace.deal_attachments'))).scalars().all()
    finally:await engine.dispose()
    missing=sum((settings.minio_bucket,key) not in copies[1] for key in keys)
    equal=bool(copies[0]) and copies[0]==copies[1] and missing==0
    print(json.dumps({'equal':equal,'downloaded_objects':len(copies[0]),'linked_objects':len(keys),
                      'missing_linked_objects':missing},ensure_ascii=False,indent=2))
    return 0 if equal else 1

if __name__=='__main__':raise SystemExit(asyncio.run(main()))
