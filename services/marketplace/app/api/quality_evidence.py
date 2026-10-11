"""Explicit human reference approval; comparisons execute as ordinary code."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin
from ..agent_quality import METHOD, bank_tasks, compare, digest, run_rows
from ..models import AgentQualityEvaluation

router = APIRouter(tags=['quality-evidence-v3'])

class ReferenceIn(BaseModel):
    run_id: uuid.UUID
    task_scope: str = Field(min_length=3, max_length=120)
    source: str = Field(min_length=3, max_length=1000)
    bank_task_id: str | None = Field(default=None, max_length=64)
    bank_applicability_confirmed: bool = False
    critical_fields: dict = Field(default_factory=dict, max_length=30)
    expected_category: str | None = Field(default=None,max_length=120)
    conflicts_expected: bool | None = None
    questions_expected: bool | None = None
    human_approved: Literal[True]

    @field_validator('critical_fields')
    @classmethod
    def scalar_reference(cls, fields):
        import math
        for key,value in fields.items():
            if not key.strip() or len(key)>120 or not isinstance(value,(str,int,float,bool)):
                raise ValueError('Эталонные поля: содержательные ключи и скалярные значения')
            if isinstance(value,float) and not math.isfinite(value):
                raise ValueError('Эталонное число должно быть конечным')
            if isinstance(value,str) and (not value.strip() or len(value)>1000):
                raise ValueError('Эталонное значение должно быть содержательным и не длиннее 1000 символов')
        return fields

    @field_validator('expected_category')
    @classmethod
    def category_reference(cls, value):
        if value is not None and not value.strip(): raise ValueError('Укажите содержательную эталонную категорию')
        return value.strip() if value is not None else None

    @field_validator('task_scope','source')
    @classmethod
    def meaningful(cls,v):
        if len(v.strip()) < 3: raise ValueError('Укажите содержательный источник и класс задачи')
        return v.strip()

@router.get('/companies/{company_id}/quality-evidence')
async def candidates(company_id: uuid.UUID, user: CurrentUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    await require_company_admin(company_id,user,db)
    rows = await run_rows(db,since=datetime.now(timezone.utc)-timedelta(days=365),company_id=company_id)
    evaluations = (await db.scalars(select(AgentQualityEvaluation).where(AgentQualityEvaluation.company_id==company_id).order_by(AgentQualityEvaluation.created_at))).all()
    return {'company_id':company_id,'bank_tasks':bank_tasks(),'evaluations':[{'id':e.id,'run_id':e.run_id,'source':e.source,'task_scope':e.task_scope,'reference':e.reference,'assessment':e.assessment,'reviewer_user_id':e.reviewer_user_id,'created_at':e.created_at} for e in evaluations],'runs':[
        {'run_id':r['id'],'role':r['agent_type'],'state':r['state'],'initial_result':r['initial_result'],
         'model_version':r['model_version'],'prompt_version':r['prompt_version'],'used_route':r['used_route']}
        for r in rows if isinstance(r['initial_result'],dict)][-100:]}

@router.post('/companies/{company_id}/quality-evidence',status_code=201)
async def evaluate(company_id: uuid.UUID, data: ReferenceIn, user: CurrentUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    await require_company_admin(company_id,user,db)
    rows = await run_rows(db,since=datetime.min.replace(tzinfo=timezone.utc),company_id=company_id)
    run = next((r for r in rows if r['id']==data.run_id),None)
    if run is None: raise HTTPException(404,'Прогон компании не найден')
    if not isinstance(run['initial_result'],dict): raise HTTPException(409,'Исходный результат не сохранён: экспертная оценка невозможна')
    if data.bank_task_id:
        if not data.bank_applicability_confirmed: raise HTTPException(422,'Подтвердите соответствие исходного задания выбранной задаче банка')
        task = next((t for t in bank_tasks() if t['id']==data.bank_task_id),None)
        if task is None: raise HTTPException(422,'Задача банка не найдена')
        if run['agent_type']!='buyer_agent': raise HTTPException(422,'Банк предназначен для извлечения требований покупателя')
        reference = {k:v for k,v in task.items() if k not in {'input_text','extra_sources','mode'}}
    else:
        reference = data.model_dump(exclude_none=True,include={'critical_fields','expected_category','conflicts_expected','questions_expected'})
    assessment = compare(run['initial_result'],reference)
    if not assessment['total']: raise HTTPException(422,'Укажите критичные эталонные поля или ожидаемую категорию/поведение')
    reference_hash = digest({'reference':reference,'task_scope':data.task_scope,'source':data.source})
    row_id = uuid.uuid4()
    await db.execute(insert(AgentQualityEvaluation).values(id=row_id,run_id=data.run_id,company_id=company_id,
        reviewer_user_id=user.id,method_version=METHOD,task_scope=data.task_scope,source=data.source,
        bank_task_id=data.bank_task_id,reference=reference,result_hash=digest(run['initial_result']),reference_hash=reference_hash,
        assessment=assessment).on_conflict_do_nothing(index_elements=['run_id','reviewer_user_id','reference_hash']))
    await db.commit()
    entry = await db.scalar(select(AgentQualityEvaluation).where(AgentQualityEvaluation.run_id==data.run_id,
        AgentQualityEvaluation.reviewer_user_id==user.id,AgentQualityEvaluation.reference_hash==reference_hash))
    return {'id':entry.id,'run_id':entry.run_id,'assessment':entry.assessment,'result_hash':entry.result_hash,'reference_hash':entry.reference_hash}
