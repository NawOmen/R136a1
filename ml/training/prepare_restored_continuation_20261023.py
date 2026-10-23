from pathlib import Path
import json,hashlib,shutil
R=Path(__file__).resolve().parent;P=R/'buyer-restored-fullpass-20261023';O=R/'buyer-restored-continuation-20261023';O.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
checkpoint=P/'adapter-final/0001456_adapters.safetensors'
assert sha(checkpoint)=='9b9670d64468426168b8ed376abd941d1abe0a533d0fc41633d4665f9804990d'
old=json.loads((P/'schedule.json').read_text());rows=[json.loads(s) for s in (P/'train.jsonl').read_text().splitlines()]
suffix=old[1456:];selected=[rows[e['row_index']] for e in suffix];assert len(selected)==676
schedule=[dict(e,step=i+1,row_index=i,original_step=e['step'],original_row_index=e['row_index']) for i,e in enumerate(suffix)]
assert len({e['case_id'] for e in old[:1456]+schedule})==2132
(O/'train.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in selected))
shutil.copyfile(P/'valid.jsonl',O/'valid.jsonl')
(O/'schedule.json').write_text(json.dumps(schedule,ensure_ascii=False,indent=2)+'\n')
checks=json.loads((P/'token-check.json').read_text());ids={r['case_id'] for r in selected};checks['checks']=[c for c in checks['checks'] if c['split']=='valid' or c['case_id'] in ids];checks['rows']=len(checks['checks']);assert checks['rows']==1264
(O/'token-check.json').write_text(json.dumps(checks,ensure_ascii=False)+'\n')
protocol={'train':676,'valid':588,'original_schedule':str(P/'schedule.json'),'original_schedule_sha256':sha(P/'schedule.json'),'source_train_sha256':sha(P/'train.jsonl'),'warm_checkpoint':str(checkpoint),'warm_checkpoint_sha256':sha(checkpoint),'saved_prefix':1456,'suffix_original_steps':[1457,2132],'original_unpersisted_metric_steps_reprocessed':[1457,1471],'full_order_binding_verified':True,'optimizer_reset':True,'rng_reset':True,'exact_continuous_resume':False,'save_every':128,'runtime_hypothesis':'One-second host pause after each completed step, before next step. No loss/model math changes. Reduced continuous GPU duty is unproven mitigation, not a watchdog fix.','prior_error':'Metal Impacting Interactivity','os_evidence':'No matching explanatory GPU diagnostic report found; exact trigger unknown. Prior swap stable, no recorded memory-allocation error.','no_automatic_retry_or_extra_epochs':True,'canonical_preserved':True}
(O/'preparation.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
s=(R/'start_restored_fullpass_20261023.py').read_text()
s=s.replace("One recovered-corpus LoRA pass; canonical model is read-only; no automatic repeat.","One remaining suffix with host pacing; no automatic repeat; canonical read-only.")
s=s.replace("O=R/'buyer-restored-fullpass-20261023'","O=R/'buyer-restored-continuation-20261023'")
s=s.replace(".restored-fullpass-20261023.lock",".restored-continuation-20261023.lock")
s=s.replace("'planned_microbatches':2132,'planned_optimizer_updates':1066","'planned_microbatches':676,'planned_optimizer_updates':338,'saved_original_prefix':1456,'save_every':128,'host_pause_seconds':1.0")
s=s.replace("inputs=[O/'train.jsonl'","warm=Path(json.loads((O/'preparation.json').read_text())['warm_checkpoint']);assert sha(warm)=='9b9670d64468426168b8ed376abd941d1abe0a533d0fc41633d4665f9804990d'\n inputs=[warm,O/'train.jsonl'")
s=s.replace('assert len(rows)==2132','assert len(rows)==676').replace('training_one_pass_2132','training_remaining_676').replace("iters=2132","iters=676").replace("save_every=16","save_every=128")
s=s.replace("resume_adapter_file=str(canonical/'adapters.safetensors')","resume_adapter_file=str(warm)")
s=s.replace("==2132\n  return result","==676\n  return result")
s=s.replace("elapsed_seconds=time.time()-started)\n  def on_val_loss_report", "elapsed_seconds=time.time()-started)\n   time.sleep(1.0)\n  def on_val_loss_report")
assert 'iters=2132' not in s and 'save_every=16' not in s and 'time.sleep(1.0)' in s
(R/'start_restored_continuation_20261023.py').write_text(s)
print('Prepared',len(selected),'suffix rows; CPU token bindings',checks['rows'])
