from pathlib import Path
import json,hashlib
from transformers import AutoTokenizer
R=Path(__file__).resolve().parent;O=R/'buyer-restored-fullpass-20261023'
t=AutoTokenizer.from_pretrained(str(R/'model-9b-4bit'),local_files_only=True,trust_remote_code=False)
checks=[]
for split in ['train','valid']:
 for row in map(json.loads,(O/(split+'.jsonl')).read_text().splitlines()):
  m=row['messages'];tokens=t.apply_chat_template(m,return_dict=False,enable_thinking=False);prefix=t.apply_chat_template(m[:-1],return_dict=False,add_generation_prompt=True,enable_thinking=False)
  assert tokens[:len(prefix)]==prefix
  assert len(tokens)<=1280 and 0<len(tokens)-len(prefix)<=512,(row['case_id'],len(tokens),len(tokens)-len(prefix))
  checks.append({'split':split,'case_id':row['case_id'],'tokens':len(tokens),'completion':len(tokens)-len(prefix)})
(O/'token-check.json').write_text(json.dumps({'rows':len(checks),'max_tokens':max(c['tokens'] for c in checks),'max_completion':max(c['completion'] for c in checks),'checks':checks}))
print('CPU token checks passed',len(checks),max(c['tokens'] for c in checks),max(c['completion'] for c in checks))
