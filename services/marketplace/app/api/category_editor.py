"""A human editor publishes validated, immutable rule revisions under a lock."""
import uuid
import json
from copy import deepcopy
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_category_editor
from ..models import CategoryRegistryRevision
from ..category_registry import registry_snapshot, validate_registry, base_registry_snapshot
from ..category_units import UNIT_FAMILIES
from ..trust import record_human_approval, payload_hash

router=APIRouter(prefix='/editor/categories',tags=['category-editor'])


class RulePublicationIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    category_id: str
    expected_registry_hash: str = Field(min_length=64,max_length=64)
    technical_profile: dict
    reason: str = Field(min_length=5,max_length=1000)
    approved: bool = False


def proposed_registry(current,data):
    candidate=deepcopy(current)
    leaf=next((leaf for group in candidate['groups'] for leaf in group['leaves'] if leaf['id']==data.category_id),None)
    if leaf is None:raise HTTPException(422,'Категория не найдена')
    if leaf['admission_state']=='unsupported':raise HTTPException(409,'Медицинское назначение пока не поддерживается; редактор не может снять это ограничение')
    profile=deepcopy(data.technical_profile)
    if len(json.dumps(profile,ensure_ascii=False)) > 60000:
        raise HTTPException(422,"Профиль превышает допустимый размер")
    # Editors change declared domain rules, never classifier IDs or runtime code.
    if set(profile) != {'version','state','fields','required_for_product','passport'}:
        raise HTTPException(422,'Профиль должен содержать поля, обязательные свойства и полный паспорт')
    profile['version']=leaf['technical_profile']['version']+1
    profile['state']='prepared'
    passport=profile['passport']
    required_sections={'identification','units','producer','commercial','resource','documents','compatibility','logistics','acceptance','repeat','sources','update_policy'}
    if not isinstance(passport,dict) or set(passport)!=required_sections:
        raise HTTPException(422,'Укажите все разделы паспорта категории')
    if any(not isinstance(passport[key],dict) for key in required_sections-{'sources','update_policy'}):
        raise HTTPException(422,'Разделы паспорта должны содержать структурированные правила')
    if not isinstance(passport['sources'],list) or not passport['sources'] or not isinstance(passport['update_policy'],str):
        raise HTTPException(422,'Укажите источники и порядок обновления')
    units=passport.get('units',{}).get('allowed',[])
    if not isinstance(units,list) or not units or any(not isinstance(unit,str) or unit not in UNIT_FAMILIES for unit in units) or len(set(units))!=len(units):
        raise HTTPException(422,'Укажите известные неповторяющиеся единицы')
    if passport['identification'].get('required') != profile['required_for_product']:
        raise HTTPException(422,'Обязательные свойства паспорта и формы должны совпадать')
    if passport['compatibility'].get('hard_fields') != profile['required_for_product']:
        raise HTTPException(422,'Жёсткие свойства должны соответствовать обязательной идентификации')
    if passport['repeat'] != {'new_draft':True,'revalidate':True,'copy_approvals':False,'copy_documents':False}:
        raise HTTPException(422,'Повтор должен перепроверять данные и не переносить прежний допуск')
    if passport['documents'].get('review_required') is not True or passport['documents'].get('admission_profile') != leaf['admission_profile_key']:
        raise HTTPException(422,'Редактирование профиля не отменяет проверку документов и существующий допуск')
    if passport['commercial'].get('price_basis') != leaf['technical_profile']['passport']['commercial']['price_basis']:
        raise HTTPException(422,'Цена остаётся в рублях за единицу заказа')
    if not isinstance(profile['fields'],list) or len(profile['fields'])>25:raise HTTPException(422,'В профиле допускается не более 25 характеристик')
    leaf['technical_profile']=profile
    leaf['revision']+=1
    candidate['registry_version']='catalog-4-rules-'+payload_hash({'parent':payload_hash(current),'category':leaf['id'],'profile':profile})[:16]
    try:validate_registry(candidate)
    except (ValueError,TypeError,KeyError) as exc:raise HTTPException(422,'Некорректный профиль: '+str(exc)) from None
    return candidate


@router.get('')
async def editor_registry(user: CurrentUser=Depends(get_current_user),db: AsyncSession=Depends(get_db)):
    await require_category_editor(user,db)
    data=registry_snapshot()
    return {'registry':data,'registry_hash':payload_hash(data)}


@router.post('/preview')
async def preview_publication(data: RulePublicationIn,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    await require_category_editor(user,db)
    current=registry_snapshot()
    if data.expected_registry_hash!=payload_hash(current):raise HTTPException(409,'Правила изменились; обновите реестр')
    candidate=proposed_registry(current,data)
    return {'registry_hash':payload_hash(candidate),'registry':candidate,'reason':data.reason}


@router.post('/publish')
async def publish_rules(data:RulePublicationIn,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    await require_category_editor(user,db)
    if data.approved is not True:raise HTTPException(428,'Просмотрите изменения и явно подтвердите публикацию')
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('category-registry', 0))"))
    latest=await db.scalar(select(CategoryRegistryRevision).order_by(CategoryRegistryRevision.sequence.desc()).limit(1))
    current=latest.registry if latest else base_registry_snapshot()
    if data.expected_registry_hash!=payload_hash(current):raise HTTPException(409,'Другой редактор изменил правила; обновите сравнение')
    candidate=proposed_registry(current,data)
    revision=CategoryRegistryRevision(sequence=latest.sequence+1 if latest else 1,parent_hash=payload_hash(current),
        registry_hash=payload_hash(candidate),registry=candidate,published_by_user_id=user.id)
    db.add(revision)
    await db.flush()
    published_leaf = next(leaf for group in candidate['groups'] for leaf in group['leaves'] if leaf['id'] == data.category_id)
    await record_human_approval(db,action='category_rules_published',entity_type='category',entity_id=revision.id,
        actor_user_id=user.id,permission='category_editor_or_marketplace_admin',decision='approved',
        reason=data.reason,source_refs=[{'type':'category','id':data.category_id}],
        explanation=data.reason,payload={'previous_hash':payload_hash(current),'current_hash':revision.registry_hash,
          'category_id':data.category_id,'technical_profile':deepcopy(published_leaf['technical_profile']),'registry_version':candidate['registry_version']})
    await db.commit()
    return {'registry':candidate,'registry_hash':revision.registry_hash}
