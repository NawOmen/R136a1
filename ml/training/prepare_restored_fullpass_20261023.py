from pathlib import Path
import zipfile,json,hashlib,random
R=Path(__file__).resolve().parent
O=R/'buyer-restored-fullpass-20261023';O.mkdir(exist_ok=False)
def sha(b):return hashlib.sha256(b).hexdigest()
def write(n,v): (O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
records=[];splits={'train':[],'valid':[]}
for archive,prefix,bank in [('porukam-buyer-marketplace-dataset-v3.zip','buyer-marketplace-v3','marketplace'),('porukam-buyer-business-fields-v1.zip','buyer-business-fields-v1','business')]:
 with zipfile.ZipFile(R/archive) as z:
  m=json.loads(z.read(prefix+'/manifest.json'))
  for split in splits:
   b=z.read(prefix+'/'+split+'.jsonl');expected=m.get('sha256',{}).get(split) or m['splits'][split]['sha256'];assert sha(b)==expected
   rows=[json.loads(x) for x in b.splitlines()];count=m['splits'][split];count=count['count'] if isinstance(count,dict) else count;assert len(rows)==count
   for row in rows:assert row['synthetic'] and row['messages'][-1]['role']=='assistant';json.loads(row['messages'][-1]['content'])
   splits[split]+=rows
   records.append({'archive':archive,'archive_sha256':sha((R/archive).read_bytes()),'member':prefix+'/'+split+'.jsonl','sha256':expected,'rows':len(rows),'bank':bank})
assert len(splits['train'])==2132 and len(splits['valid'])==588
source=lambda r:sha(json.dumps(r['messages'][:-1],ensure_ascii=False,sort_keys=True).encode())
assert not {source(r) for r in splits['train']} & {source(r) for r in splits['valid']}
for split,rows in splits.items():
 assert len({r['case_id'] for r in rows})==len(rows)
 (O/(split+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
indices=list(range(2132));random.Random(20261023).shuffle(indices)
schedule=[{'step':s,'row_index':i,'case_id':splits['train'][i]['case_id'],'bank':'marketplace' if i<1472 else 'business'} for s,i in enumerate(indices,1)]
write('schedule.json',schedule)
write('preparation.json',{'source_archives':records,'train':2132,'valid':588,'excluded_unrestored_prose':28,'train_valid_prompt_exact_nonoverlap':True,'closed_test_not_opened':True,'one_pass_only':True,'optimizer_reset':True,'learning_rate':5e-6,'hypothesis':'Additional low-rate rehearsal of recovered synthetic corpus; quality improvement unproven; no automatic extra epochs','canonical_adapter_preserved':True})
print(O)
