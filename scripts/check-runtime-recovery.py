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
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True)
    p.add_argument('--auth-url',required=True)
    p.add_argument('--llm-url',required=True)
    a=p.parse_args()
    if not a.project.startswith('r136-s15') or os.environ.get('ENABLE_DEMO_SEED')!='true':
        p.error('Нужен выделенный синтетический проект r136-s15*')
    def http(base,path,data=None,token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request(base+path, data=json.dumps(data).encode() if data is not None else None,headers=headers)
        with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)
    login=http(a.auth_url,'/api/v1/auth/login',{'email':'demo@demo.ru','password':os.environ['E2E_BUYER_PASSWORD']})
    token=login['access_token'];me=http(a.auth_url,'/api/v1/auth/me',token=token)
    company=next(c for c in me['companies'] if c['membership']['can_buy'])
    assert company['inn'].startswith('000'), 'Только синтетические компании'
    task=http(a.llm_url,'/api/v2/agent-tasks',{'company_id':company['id'],'scenario_type':'buyer_investigation',
        'input':{'need':'Синтетическая закупка 100 коробок'},'source_refs':[{'type':'text','id':'request_text','version':1}],
        'idempotency_key':str(uuid.uuid4())},token)
    path='/api/v2/agent-tasks/'+task['task_id'];scope='?company_id='+company['id']
    before=http(a.llm_url,path+'/start'+scope,{'expected_revision':1},token)
    identifiers=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+a.project,
        '--filter','label=com.docker.compose.service=llm-gateway'],text=True).split()
    assert len(identifiers)==1,'Нужен один LLM Gateway в выделенном проекте'
    subprocess.run(['docker','restart',identifiers[0]],check=True,stdout=subprocess.DEVNULL)
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
