"""Restart proof on an explicitly isolated synthetic Compose project only.

Provide E2E_BUYER_PASSWORD via environment. Leaves one unfinished synthetic task
for subsequent backup/restore verification. Does not call a model or grant approval.
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid


def isolated_endpoints(project, auth_url, llm_url):
    # These probes use direct, local published ports. A remote Docker daemon or
    # reverse proxy cannot establish that the supplied URL belongs to this project.
    context = json.loads(subprocess.check_output(
        ['docker', 'context', 'inspect'], text=True))[0]
    endpoint = (os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None) or context['Endpoints']['docker']['Host']
    if not endpoint.startswith(('unix://', 'npipe://')):
        raise ValueError('Проверка рестарта требует локальный Docker daemon')
    selected = {}
    urls = {}
    for service, url, port in [('gateway-auth', auth_url, '8001/tcp'), ('llm-gateway', llm_url, '8003/tcp')]:
        identifiers = subprocess.check_output(['docker', 'ps', '-q', '--filter',
            'label=com.docker.compose.project=' + project, '--filter',
            'label=com.docker.compose.service=' + service], text=True).split()
        if len(identifiers) != 1:
            raise ValueError('Нужен один работающий ' + service + ' в выделенном проекте')
        container = json.loads(subprocess.check_output(['docker', 'inspect', identifiers[0]], text=True))[0]
        labels = container['Config'].get('Labels') or {}
        if not container['State']['Running'] or labels.get('com.docker.compose.project') != project or labels.get('com.docker.compose.service') != service:
            raise ValueError('Контейнер не принадлежит выделенному проекту')
        if service == 'gateway-auth' and 'ENABLE_DEMO_SEED=true' not in container['Config'].get('Env', []):
            raise ValueError('Auth должен принадлежать синтетическому стенду с ENABLE_DEMO_SEED=true')
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Для restart-пробы нужен прямой loopback HTTP URL сервиса')
        bindings = container['NetworkSettings']['Ports'].get(port) or []
        hosts = ('127.0.0.1', '::1') if parsed.hostname == 'localhost' else (parsed.hostname,)
        host = next((host for host in hosts if any(int(b['HostPort']) == (parsed.port or 80) and
            b['HostIp'] in (('', '0.0.0.0', '127.0.0.1') if host == '127.0.0.1' else ('::', '::1'))
            for b in bindings)), None)
        if host is None:
            raise ValueError('URL не совпадает с опубликованным портом ' + service)
        selected[service] = identifiers[0]
        literal = '[' + host + ']' if ':' in host else host
        urls[service] = f'http://{literal}:{parsed.port or 80}'
    return selected['llm-gateway'], urls['gateway-auth'], urls['llm-gateway']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Перенаправление restart-пробы запрещено', headers, fp)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True)
    p.add_argument('--auth-url',required=True)
    p.add_argument('--llm-url',required=True)
    a=p.parse_args()
    import re
    if not re.fullmatch(r'r136-s15[a-z0-9-]{0,42}', a.project) or os.environ.get('ENABLE_DEMO_SEED')!='true':
        p.error('Нужен выделенный синтетический проект r136-s15*')
    identifier, a.auth_url, a.llm_url = isolated_endpoints(a.project, a.auth_url, a.llm_url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def http(base,path,data=None,token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request(base+path, data=json.dumps(data).encode() if data is not None else None,headers=headers)
        with opener.open(req,timeout=15) as response:return json.load(response)
    login=http(a.auth_url,'/api/v1/auth/login',{'email':'demo@demo.ru','password':os.environ['E2E_BUYER_PASSWORD']})
    token=login['access_token'];me=http(a.auth_url,'/api/v1/auth/me',token=token)
    company=next(c for c in me['companies'] if c['membership']['can_buy'])
    assert company['inn'].startswith('000'), 'Только синтетические компании'
    task=http(a.llm_url,'/api/v2/agent-tasks',{'company_id':company['id'],'scenario_type':'buyer_investigation',
        'input':{'need':'Синтетическая закупка 100 коробок'},'source_refs':[{'type':'text','id':'request_text','version':1}],
        'idempotency_key':str(uuid.uuid4())},token)
    path='/api/v2/agent-tasks/'+task['task_id'];scope='?company_id='+company['id']
    before=http(a.llm_url,path+'/start'+scope,{'expected_revision':1},token)
    # Recheck immediately before restarting, without ever selecting a different target.
    if (identifier, a.auth_url, a.llm_url) != isolated_endpoints(a.project, a.auth_url, a.llm_url):
        raise ValueError('Сервисы выделенного проекта изменились до рестарта')
    subprocess.run(['docker','restart',identifier],check=True,stdout=subprocess.DEVNULL)
    for _ in range(60):
        try:
            http(a.llm_url,'/health');break
        except (OSError,urllib.error.HTTPError):time.sleep(1)
    else:raise RuntimeError('LLM Gateway не восстановился за 60 секунд')
    after=http(a.llm_url,path+scope,token=token)
    keys=['task_id','state','input_revision','idempotency_key','attempts','linked_run_id','approval','result_artifact']
    for key in keys:assert key in before and key in after and before[key]==after[key],key
    assert after['state']=='running' and not after['approval']
    try:
        http(a.llm_url,path+'/resume'+scope,{'expected_revision':1},token)
    except urllib.error.HTTPError as error:assert error.code==409
    else:raise AssertionError('Живой heartbeat не должен позволять дублировать исполнение')
    print(json.dumps({'restart_verified':True,'task_id':task['task_id'],'state':after['state'],
        'approval':None,'early_resume_status':409},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
