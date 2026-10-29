"""CPU validation of canonical fields, evidence and actual category profiles."""
import json,hashlib,sys,types,importlib,importlib.util
from pathlib import Path
from transformers import AutoTokenizer
R=Path(__file__).resolve().parent;P=R/'buyer-marketplace-v3';A=Path('/Users/assweg/Desktop/b2b/R136a1/services/marketplace/app');pkg=types.ModuleType('lab_marketplace_contracts');pkg.__path__=[str(A)];sys.modules[pkg.__name__]=pkg
registry=importlib.import_module('lab_marketplace_contracts.category_registry');validator=importlib.import_module('lab_marketplace_contracts.category_characteristics');D=registry.registry_snapshot();leaves={x['id']:(g,x) for g in D['groups'] for x in g['leaves']}
spec=importlib.util.spec_from_file_location('raw_schema_marketplace','/Users/assweg/Desktop/b2b/R136a1/services/llm-gateway/app/schemas.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
tok=AutoTokenizer.from_pretrained(str(R/'model-9b-8bit'),local_files_only=True);seen=set();report={}
for split in ['train','valid','test']:
 lengths=[];answers=[];coverage={}
 for row in map(json.loads,(P/(split+'.jsonl')).read_text().splitlines()):
  user=row['messages'][1]['content'];assert user not in seen;seen.add(user);gold=s.RawExtraction.model_validate_json(row['messages'][-1]['content']);group,leaf=leaves[row['category_id_metadata']];assert leaf['admission_profile_key']!='medical_unsupported' and gold.category==leaf['label'];allowed=set(leaf['technical_profile']['fields'])|{'quantity_units','delivery_city','lead_time_days','budget_rub'}
  sources={x['source_id']:x['untrusted_text'] for x in json.loads(user.split('\n',1)[1])}
  for fact in gold.facts:
   if fact.key in {'quantity_units','lead_time_days'}:assert isinstance(fact.value,(int,float)) and not isinstance(fact.value,bool)
   assert fact.key in allowed and fact.evidence in sources[fact.source_id]
   assert not fact.original_unit or fact.original_unit in sources[fact.source_id]
   if fact.key in D['characteristic_fields']:
    f=D['characteristic_fields'][fact.key];assert (isinstance(fact.value,str) if f['type']=='text' else isinstance(fact.value,(int,float)) and not isinstance(fact.value,bool)),(row['case_id'],fact.key,fact.value)
  values=row['source_characteristics'];extracted={x.key:x.value for x in gold.facts if x.key in leaf['technical_profile']['fields']};assert extracted==values
  errors=validator.validate_profile_values(group['label'],leaf['label'],extracted,require_product_fields=True)
  if row['profile_complete_expected']:assert not errors,(row['case_id'],errors)
  if row['expected_missing_field']:assert errors,(row['case_id'],'missing requirement not caught')
  full=tok.apply_chat_template(row['messages'],return_dict=False);offset=len(tok.apply_chat_template(row['messages'][:-1],add_generation_prompt=True,return_dict=False));lengths.append(len(full));answers.append(len(full)-offset+1);coverage[row['category_id_metadata']]=coverage.get(row['category_id_metadata'],0)+1
 assert len(coverage)==46
 report[split]={'count':len(lengths),'covered_leaves':len(coverage),'min_tokens':min(lengths),'max_tokens':max(lengths),'max_completion_tokens':max(answers),'per_category_count':coverage,'checks_passed':True,'sha256':hashlib.sha256((P/(split+'.jsonl')).read_bytes()).hexdigest()}
report['scope']={'explicit_category_only':True,'human_expert_reviewed':False,'model_evaluated':False,'gateway_roundtrip_evaluated':False,'model_memory_probe_required':True};(P/'dataset-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:{a:b for a,b in v.items() if a!='per_category_count'} for k,v in report.items()},ensure_ascii=False))
