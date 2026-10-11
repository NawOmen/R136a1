"""Typed denial evidence survives rollback of the rejected business action."""
import hashlib
import uuid
import logging
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from .models import BusinessDenialEvent
from .security import decode_access_token
from .database import get_db

log = logging.getLogger(__name__)

class BusinessDenied(HTTPException):
    def __init__(self, status_code, detail, *, company_id, reason_code='admission', role='supplier_admission', entity_type='company', entity_id=None):
        super().__init__(status_code,detail)
        self.company_id=company_id; self.reason_code=reason_code; self.role=role
        self.entity_type=entity_type; self.entity_id=entity_id

async def handle_denial(request, exc):
    # Open an independent unit of work: the rejected action is never committed.
    provider = request.app.dependency_overrides.get(get_db,get_db)
    generator = provider()
    db = await anext(generator)
    try:
        token = request.headers.get('authorization','').removeprefix('Bearer ')
        uid = uuid.UUID(str(decode_access_token(token)['sub']))
        authorized = await db.scalar(text("SELECT EXISTS (SELECT 1 FROM auth.company_members m JOIN auth.users u ON u.id=m.user_id WHERE m.company_id=:cid AND m.user_id=:uid AND u.account_status='active')"),{'cid':exc.company_id,'uid':uid})
        if authorized:
            body = await request.body()
            fingerprint = hashlib.sha256(request.url.path.encode()+b'\0'+body+b'\0'+exc.reason_code.encode()).hexdigest()
            await db.execute(insert(BusinessDenialEvent).values(id=uuid.uuid4(),company_id=exc.company_id,user_id=uid,
                role=exc.role,reason_code=exc.reason_code,entity_type=exc.entity_type,entity_id=exc.entity_id,
                fingerprint=fingerprint).on_conflict_do_nothing(index_elements=['company_id','fingerprint']))
            await db.commit()
    except Exception:
        await db.rollback()
        log.exception('Не удалось сохранить типизированную блокировку бизнес-действия')
    finally:
        await generator.aclose()
    return JSONResponse(status_code=exc.status_code,content={'detail':exc.detail,'reason_code':exc.reason_code})
