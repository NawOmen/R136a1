"""One remaining suffix with host pacing; no automatic repeat; canonical read-only."""
import os
os.environ['MLX_MAX_OPS_PER_BUFFER']='1';os.environ['MLX_MAX_MB_PER_BUFFER']='10';os.environ['HF_HUB_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
from pathlib import Path
import json,hashlib,subprocess,time,fcntl,re,sys,types,importlib.util,traceback
R=Path(__file__).resolve().parent;O=R/'buyer-restored-continuation-20261023';S=O/'session-v2';S.mkdir(exist_ok=False)
sys.path.insert(0,str(R))
import heavy_process_guard_v2 as guard
from coverage_iterator_v1 import make_coverage_iterator
from aligned_chat_process_v1 import aligned_process
from train_valid_only_loader_v1 import load_train_valid_only
started=time.time();state={'pid':os.getpid(),'phase':'preflight','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'planned_microbatches':676,'planned_optimizer_updates':338,'saved_original_prefix':1456,'save_every':128,'host_pause_seconds':1.0,'canonical_modified':False};handles=[]
def save(name,obj):
 p=S/name;tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n');tmp.replace(p)
def update(**kw):state.update(kw);save('state.json',state)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def shell(*cmd):return subprocess.check_output(cmd,text=True)
def memory():
 free=int(re.search(r'free percentage: (\d+)%',shell('memory_pressure','-Q')).group(1));swap=float(re.search(r'used = ([\d.]+)M',shell('sysctl','vm.swapusage')).group(1));return {'free_percent':free,'swap_used_MiB':swap,'time':time.time()}
def external():
 raw=guard.require_no_competitors();assert not any('postgres' in l.lower() and str(R).lower() in l.lower() for l in raw.splitlines()),'Own lab database active'
 import urllib.request
 data=json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/ps',timeout=5));assert data['models']==[],data
 return raw
try:
 update(phase='preflight')
 save('restart-protocol.json',{'user_authorized_unload_Ollama':True,'prior_failed_local_steps':103,'prior_suffix_checkpoint_saved':False,'restart_from_original_saved_prefix':1456,'optimizer_rng_reset':True,'exact_resume':False,'other_model_unloaded_before_start':True,'no_extra_epoch':True})
 for p in sorted(set([R/'.mlx-gpu.lock',R/'.restored-continuation-20261023.lock']+list(R.glob('.*.lock')))):
  f=p.open('a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);handles.append(f)
 save('preflight-processes.json',{'fullps':external(),'locks':[f.name for f in handles]})
 base=R/'model-9b-4bit';canonical=R/'porukam-trained-current';spec=importlib.util.spec_from_file_location('serving_verify',canonical/'serve.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.verify(base,canonical)
 assert sha(canonical/'adapters.safetensors')=='b2cf30b111109ee10439b4308cb97058ab00a85115eedd36118bbc534e52b665'
 warm=Path(json.loads((O/'preparation.json').read_text())['warm_checkpoint']);assert sha(warm)=='9b9670d64468426168b8ed376abd941d1abe0a533d0fc41633d4665f9804990d'
 inputs=[warm,O/'train.jsonl',O/'valid.jsonl',O/'schedule.json',O/'preparation.json',O/'token-check.json',canonical/'adapters.safetensors',canonical/'adapter_config.json',R/'completion_loss.py',R/'frozen_gated_kernel_v2.py',R/'aligned_chat_process_v1.py',R/'coverage_iterator_v1.py',R/'heavy_process_guard_v2.py',Path(__file__)]
 before={str(p):sha(p) for p in inputs};save('input-sha256.json',before)
 freeze=shell(sys.executable,'-m','pip','freeze');(S/'pip-freeze.txt').write_text(freeze)
 pairs=[];deadline=time.time()+600
 while True:
  a=memory();time.sleep(10);b=memory();pairs.append({'a':a,'b':b});save('memory-stability.json',pairs)
  if min(a['free_percent'],b['free_percent'])>=40 and abs(b['swap_used_MiB']-a['swap_used_MiB'])<=16:break
  if time.time()>deadline:raise RuntimeError('Stable memory free>=40/swapdelta<=16MiB per10s not reached')
 external();assert all(sha(p)==v for p,v in before.items())
 import mlx.core as mx
 mx.set_memory_limit(9*1024**3);mx.disable_compile()
 from frozen_gated_kernel_v2 import install_frozen_kernel,verify_trainable_scope
 parity,counters=install_frozen_kernel();save('kernel-parity.json',parity)
 import mlx_lm.lora as lora
 from mlx_lm.tuner import datasets,trainer
 from completion_loss import make_completion_loss
 datasets.ChatDataset.process=aligned_process
 lora.load_dataset=lambda args,tokenizer:load_train_valid_only(args,tokenizer,datasets.create_dataset)
 rows=[json.loads(x) for x in (O/'train.jsonl').read_text().splitlines()];schedule=json.loads((O/'schedule.json').read_text());assert len(rows)==676
 class Callback:
  def on_train_loss_report(self,info):
   with (S/'metrics.jsonl').open('a') as f:f.write(json.dumps(info,default=str)+'\n')
   update(phase='training_remaining_676',last_completed_metric=info,elapsed_seconds=time.time()-started)
   time.sleep(1.0)
  def on_val_loss_report(self,info):
   with (S/'validation-loss.jsonl').open('a') as f:f.write(json.dumps(info,default=str)+'\n')
 lora.get_reporting_callbacks=lambda *a,**kw:Callback()
 original=trainer.train
 def training(**kw):
  save('trainable-scope.json',verify_trainable_scope(kw['model']))
  iterator=make_coverage_iterator(trainer.iterate_batches,schedule,rows,S/'train-batches-issued.jsonl')
  update(phase='training_remaining_676',model_loaded=True)
  result=original(**kw,loss=make_completion_loss(512,64),iterate_batches=iterator)
  issued=[json.loads(x) for x in (S/'train-batches-issued.jsonl').read_text().splitlines()];assert [r['case_id'] for r in issued]==[r['case_id'] for r in schedule];assert len({r['row_index'] for r in issued})==676
  return result
 lora.train=training
 args=dict(lora.CONFIG_DEFAULTS);args.update(model=str(base),data=str(O),train=True,test=False,adapter_path=str(O/'adapter-final-v2'),resume_adapter_file=str(warm),fine_tune_type='lora',num_layers=1,lora_parameters={'rank':64,'dropout':0.05,'scale':2.0},batch_size=1,grad_accumulation_steps=2,learning_rate=5e-6,iters=676,max_seq_length=1280,mask_prompt=True,grad_checkpoint=True,save_every=128,steps_per_report=1,steps_per_eval=256,val_batches=1,seed=20261023,trust_remote_code=False,clear_cache_threshold=0,config=None)
 save('training-config.json',args);lora.run(types.SimpleNamespace(**args))
 assert all(sha(p)==v for p,v in before.items())
 update(phase='complete',finished=True,adapter_sha256=sha(O/'adapter-final-v2/adapters.safetensors'),elapsed_seconds=time.time()-started,mlx_peak_bytes=mx.get_peak_memory(),kernel_calls=counters)
except BaseException as e:
 update(phase='interrupted' if isinstance(e,KeyboardInterrupt) else 'failed',finished=False,error=repr(e),traceback=traceback.format_exc(),elapsed_seconds=time.time()-started)
 traceback.print_exc();sys.exit(1)
finally:
 if 'before' in locals():save('input-sha256-after.json',{p:sha(p) for p in before})
 for f in handles:fcntl.flock(f,fcntl.LOCK_UN);f.close()
 save('locks-released.json',{'pid':os.getpid(),'lock_handles_released':True,'actual_exit_must_be_verified_externally':True})
