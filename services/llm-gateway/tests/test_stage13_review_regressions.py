import asyncio
import json
import os
import uuid

import pymupdf as fitz
import pytest
from sqlalchemy import text

from test_stage13_safety import real_wav


async def test_native_timeout_kills_worker_before_return(tmp_path, monkeypatch):
    from app import extractors
    marker = tmp_path / 'pid'
    script = tmp_path / 'file_worker.py'
    script.write_text(f"import os,time\nopen({str(marker)!r},'w').write(str(os.getpid()))\ntime.sleep(120)\n")
    monkeypatch.setattr(extractors, '__file__', str(tmp_path / 'extractors.py'))
    with pytest.raises(TimeoutError):
        await extractors.bounded_decode('pdf', b'synthetic', {}, timeout=0.2)
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    # A timed-out worker has released the slot and no child remains.
    assert not extractors._slots.locked()


async def test_native_cancellation_also_reaps_worker(tmp_path, monkeypatch):
    from app import extractors
    marker = tmp_path / 'pid'
    (tmp_path / 'file_worker.py').write_text(f"import os,time\nopen({str(marker)!r},'w').write(str(os.getpid()))\ntime.sleep(120)\n")
    monkeypatch.setattr(extractors, '__file__', str(tmp_path / 'extractors.py'))
    task = asyncio.create_task(extractors.bounded_decode('pdf', b'synthetic', {}, timeout=30))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


async def test_main_upload_does_not_transcribe_forged_audio(client, token, monkeypatch):
    from app import api
    async def forbidden(*args):
        raise AssertionError('invalid audio reached transcriber')
    monkeypatch.setattr(api.transcriber, 'transcribe', forbidden)
    response = await client.post('/api/v3/buyer-agent/runs', headers={'Authorization': f'Bearer {token}'},
        data={'request_text': 'Нужно 5000 стаканов в Москву', 'request_key': str(uuid.uuid4())},
        files={'files': ('note.wav', b'MZsynthetic', 'audio/wav')})
    assert response.status_code == 201, response.text
    assert response.json()['state'] not in ('processing_sources', 'failed')
    assert any(call['status'] == 'failed' for call in response.json()['tool_calls'])


async def test_audio_decoder_error_has_final_recoverable_run(client, token, monkeypatch):
    from app import api
    async def malformed(*args):
        raise ValueError('synthetic decoder exception')
    monkeypatch.setattr(api.transcriber, 'transcribe', malformed)
    response = await client.post('/api/v1/buyer-agent/runs', headers={'Authorization': f'Bearer {token}'},
        data={'request_text': 'Нужно 5000 стаканов в Москву'},
        files={'files': ('note.wav', real_wav(), 'audio/wav')})
    assert response.status_code == 201, response.text
    assert response.json()['state'] == 'needs_clarification'
    assert 'synthetic decoder exception' not in response.text


async def test_password_pdf_does_not_crash_or_stick(client, token):
    document = fitz.open()
    document.new_page().insert_text((20, 20), 'Synthetic protected material')
    data = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='synthetic', user_pw='synthetic')
    document.close()
    response = await client.post('/api/v1/buyer-agent/runs', headers={'Authorization': f'Bearer {token}'},
        data={'request_text': 'Нужно 5000 стаканов в Москву'}, files={'files': ('protected.pdf', data, 'application/pdf')})
    assert response.status_code == 201, response.text
    assert response.json()['state'] == 'needs_clarification'


async def test_main_audio_path_enforces_transcription_deadline(client, token, monkeypatch):
    from app import api
    from app.config import settings
    async def slow(*args):
        await asyncio.sleep(10)
    monkeypatch.setattr(api.transcriber, 'transcribe', slow)
    monkeypatch.setattr(settings, 'transcribe_timeout_seconds', 0.02)
    response = await client.post('/api/v1/buyer-agent/runs', headers={'Authorization': f'Bearer {token}'},
        data={'request_text': 'Нужно 5000 стаканов в Москву'}, files={'files': ('note.wav', real_wav(), 'audio/wav')})
    assert response.status_code == 201 and response.json()['state'] == 'needs_clarification'


@pytest.mark.parametrize('allowed', [False, True])
async def test_external_boundary_has_only_counters_and_separate_permission(client, token, fake_provider, allowed):
    from app.schemas import RawExtraction, RawFact
    marker = 'Синтетическое ФИО паспорт 9911 000000 адрес вымышленный'
    fake_provider.extraction = RawExtraction(category='Бумажные стаканы', facts=[
        RawFact(key='delivery_city', value=marker, source_id='request_text', confidence=0.7),
        RawFact(key=marker, value=marker, source_id=marker, confidence=0.9)])
    response = await client.post('/api/v1/buyer-agent/runs', headers={'Authorization': f'Bearer {token}'},
        data={'request_text': 'Нужно 5000 стаканов', 'route': 'complex_auto', 'external_context_allowed': str(allowed).lower()},
        files=[('files', ('synthetic1.txt', marker.encode(), 'text/plain')), ('files', ('synthetic2.txt', b'5000', 'text/plain'))])
    assert response.status_code == 201, response.text
    prompts = [prompt for model, prompt, external in fake_provider.prompts if external]
    if not allowed:
        assert prompts == []
    else:
        assert len(prompts) == 1 and marker not in prompts[0]
        payload = json.loads(prompts[0])
        assert set(payload) == {'source_count', 'fact_count', 'low_confidence_count', 'repeated_key_count'}
        assert all(type(value) is int and 0 <= value <= 1000 for value in payload.values())


async def test_pdf_expanded_stream_budget_is_enforced():
    from app.extractors import pdf_to_text, UnreadableMaterial
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    doc = fitz.open()
    doc.new_page()
    xref = doc.get_new_xref()
    doc.update_object(xref, '<< >>')
    doc.update_stream(xref, b'q\n' * (9 * 1024**2), compress=True)
    data = doc.tobytes()
    doc.close()
    assert len(data) < 25 * 1024**2
    provider = SimpleNamespace(vision_text=AsyncMock())
    with pytest.raises(UnreadableMaterial):
        await pdf_to_text(data, provider)
    provider.vision_text.assert_not_awaited()


async def test_overall_ocr_material_deadline_is_enforced(monkeypatch):
    from app import extractors
    from app.config import settings
    async def slow(*args):
        await asyncio.sleep(10)
    monkeypatch.setattr(extractors, '_material_to_text', slow)
    monkeypatch.setattr(settings, 'material_processing_timeout_seconds', 0.02)
    with pytest.raises(extractors.UnreadableMaterial, match='время'):
        await extractors.material_to_text('synthetic.png', 'image/png', b'synthetic', None, None)


@pytest.mark.parametrize('actor', ['anonymous', 'foreign', 'blocked', 'no_role', 'revoked', 'admin', 'switched'])
async def test_agent_private_read_write_original_and_approval_denial_matrix(client, token, user_id, db_session, actor):
    import jwt
    from app.config import settings
    from test_agent_tasks import make_company, make_buyer_run, create_task, TASKS
    company = await make_company(db_session, user_id)
    run = await make_buyer_run(client, token, company)
    task = await create_task(client, token, company)
    current_token = token
    if actor in ('foreign', 'admin'):
        foreign = uuid.uuid4()
        await db_session.execute(text("INSERT INTO auth.users (id,last_name,first_name,email,password_hash,account_status,is_marketplace_admin) "
            "SELECT :id,'Синтетический','Проверяющий',:email,password_hash,'active',:admin FROM auth.users WHERE id=:owner"),
            {'id': foreign, 'email': str(foreign)+'@example.invalid', 'admin': actor == 'admin', 'owner': user_id})
        await make_company(db_session, foreign)
        current_token = jwt.encode({'sub': str(foreign)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    elif actor == 'blocked':
        await db_session.execute(text("UPDATE auth.users SET account_status='blocked' WHERE id=:id"), {'id': user_id})
    elif actor == 'no_role':
        await db_session.execute(text('UPDATE auth.company_members SET can_buy=false WHERE company_id=:id'), {'id': company})
    elif actor in ('revoked', 'switched'):
        await db_session.execute(text('DELETE FROM auth.company_members WHERE company_id=:id AND user_id=:user'), {'id': company, 'user': user_id})
        if actor == 'switched':
            await make_company(db_session, user_id)
    await db_session.commit()
    headers = {} if actor == 'anonymous' else {'Authorization': f'Bearer {current_token}'}
    base = f"/api/v2/agent-runs/{run['id']}"
    probes = [('get', base, {}), ('get', base+'/sources/request_text', {}),
        ('get', base+'/sources/request_text?original=true', {}),
        ('post', base+'/sources/request_text/invalidate', {'json': {'expected_revision': run['revision']}}),
        ('post', base+'/confirm', {'json': {'expected_revision': run['revision']}}),
        ('get', TASKS+f"/{task['task_id']}", {'params': {'company_id': str(company)}}),
        ('post', TASKS+f"/{task['task_id']}/approve", {'params': {'company_id': str(company)},
            'json': {'expected_revision': 1, 'approval': {'decision': 'approved'}, 'result_artifact': {}}})]
    for method, path, args in probes:
        response = await client.request(method, path, headers=headers, **args)
        assert response.status_code in (401, 403, 404), (actor, path, response.status_code, response.text)
        assert '5000 бумажных стаканов' not in response.text
    stored = (await db_session.execute(text('SELECT state, revision FROM agents.agent_runs WHERE id=:id'), {'id': run['id']})).mappings().one()
    assert stored['state'] == run['state'] and stored['revision'] == run['revision']


async def test_unprepared_local_whisper_is_service_unavailable(client, token, tmp_path, monkeypatch):
    from app import api
    from app.extractors import LocalTranscriber
    # Empty cache: the real worker must stop rather than download weights during a request.
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(api, "transcriber", LocalTranscriber())
    response = await client.post("/api/v1/transcribe", headers={"Authorization": f"Bearer {token}"},
        files={"file": ("synthetic.wav", real_wav(), "audio/wav")})
    assert response.status_code == 503, response.text
    response = await client.post("/api/v1/buyer-agent/runs", headers={"Authorization": f"Bearer {token}"},
        data={"request_text": "Нужно 5000 стаканов в Москву"},
        files={"files": ("synthetic.wav", real_wav(), "audio/wav")})
    assert response.status_code == 201 and response.json()["state"] == "needs_clarification"


async def test_password_session_revocation_reaches_agent_gateway(client, token, user_id, db_session):
    headers = {'Authorization': f'Bearer {token}'}
    response = await client.get('/api/v2/agent-runs/00000000-0000-4000-8000-000000000099', headers=headers)
    assert response.status_code != 401
    await db_session.execute(text('UPDATE auth.users SET token_version=1 WHERE id=:id'), {'id': user_id})
    await db_session.commit()
    assert (await client.get('/api/v2/agent-runs/00000000-0000-4000-8000-000000000099', headers=headers)).status_code == 401
