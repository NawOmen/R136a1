"""Only an administrator appoints an editor, and revocation is immediate."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import select,text
from app.models import User,SecurityEvent
from app.security import create_access_token


async def test_signup_cannot_appoint_editor_and_admin_can_revoke(client,db_session):
    signup=await client.post('/api/v1/auth/register',json={'last_name':'Тестовый','first_name':'Редактор','email':'editor@demo.ru','password':'synthetic-password','is_category_editor':True,'is_superuser':True})
    assert signup.status_code in (201,422)
    if signup.status_code==422:
        signup=await client.post('/api/v1/auth/register',json={'last_name':'Тестовый','first_name':'Редактор','email':'editor@demo.ru','password':'synthetic-password'})
    assert signup.status_code==201,signup.text
    identifier=signup.json()['user']['id'];ordinary={'Authorization':f"Bearer {signup.json()['access_token']}"}
    assert signup.json()['user']['is_category_editor'] is False
    admin=User(email='category-admin@demo.ru',first_name='Синтетический',last_name='Администратор',password_hash='synthetic-hash',is_marketplace_admin=True)
    db_session.add(admin);await db_session.commit()
    headers={'Authorization':f'Bearer {create_access_token(str(admin.id))}'}
    route=f'/api/v1/admin/users/{identifier}/category-editor'
    assert (await client.put(route,headers=ordinary,json={'enabled':True,'reason':'Самостоятельное назначение'})).status_code==403
    appointed=await client.put(route,headers=headers,json={'enabled':True,'reason':'Проверка синтетического редактора'})
    assert appointed.status_code==200 and appointed.json()['is_category_editor'] is True,appointed.text
    assert (await client.get('/api/v1/auth/me',headers=ordinary)).json()['user']['is_category_editor'] is True
    revoked=await client.put(route,headers=headers,json={'enabled':False,'reason':'Полномочия отозваны'})
    assert revoked.status_code==200 and revoked.json()['is_category_editor'] is False
    assert (await client.get('/api/v1/auth/me',headers=ordinary)).json()['user']['is_category_editor'] is False
    events=(await db_session.scalars(select(SecurityEvent).where(SecurityEvent.event=='admin.category_editor_role'))).all()
    assert len(events)==2


async def test_0005_defaults_false_and_repeat_upgrade_keeps_appointment(db_session,monkeypatch):
    path=Path(__file__).resolve().parents[1]/'alembic/versions/0005_category_editor.py'
    spec=importlib.util.spec_from_file_location('editor_role_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    user=User(email='old-editor@demo.ru',first_name='Синтетический',last_name='Пользователь',password_hash='unchanged')
    db_session.add(user);await db_session.flush()
    assert user.is_category_editor is False
    connection=await db_session.connection()
    def upgrade(sync_connection):
        monkeypatch.setattr(module,'op',SimpleNamespace(execute=sync_connection.exec_driver_sql))
        module.upgrade();module.upgrade()
    await connection.run_sync(upgrade)
    await db_session.execute(text('UPDATE auth.users SET is_category_editor=true WHERE id=:id'),{'id':user.id})
    await connection.run_sync(upgrade);await db_session.refresh(user)
    assert user.is_category_editor is True and user.password_hash=='unchanged'
