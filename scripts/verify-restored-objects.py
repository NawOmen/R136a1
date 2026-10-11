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

def copy_secure():
    value = os.environ.get('MINIO_COPY_SECURE')
    if value is None:
        return settings.minio_secure
    if value.lower() not in ('true', 'false'):
        raise ValueError('MINIO_COPY_SECURE должен быть true или false')
    return value.lower() == 'true'


async def main():
    target=os.environ['MINIO_COPY_ENDPOINT']
    if target==settings.minio_endpoint:raise ValueError('Нужен отдельный MinIO')
    clients=[Minio(endpoint,access_key=settings.minio_access_key,secret_key=settings.minio_secret_key,
                   secure=secure) for endpoint, secure in ((settings.minio_endpoint, settings.minio_secure), (target, copy_secure()))]
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
            references=(await conn.execute(text('''
                SELECT file_key, NULL::text AS expected_hash FROM marketplace.documents
                UNION SELECT file_key, content_hash FROM marketplace.need_files
                UNION SELECT storage_key, sha256 FROM marketplace.deal_attachments
                UNION SELECT file_key, NULL::text FROM marketplace.product_images
                UNION SELECT photo_file_key, NULL::text FROM marketplace.production_profiles WHERE photo_file_key IS NOT NULL
            '''))).all()
    finally:await engine.dispose()
    missing=sum((settings.minio_bucket,key) not in copies[1] for key,expected in references)
    mismatches=sum(expected is not None and copies[1].get((settings.minio_bucket,key))!=expected for key,expected in references)
    equal=bool(copies[0]) and copies[0]==copies[1] and missing==0 and mismatches==0
    print(json.dumps({'equal':equal,'downloaded_objects':len(copies[0]),'linked_objects':len(references),
                      'missing_linked_objects':missing,'stored_hash_mismatches':mismatches},ensure_ascii=False,indent=2))
    return 0 if equal else 1

if __name__=='__main__':raise SystemExit(asyncio.run(main()))
