"""Process-local eval dispatch ONLY for entirely frozen GatedDeltaNet modules."""
def install_frozen_kernel():
 import mlx.core as mx
 from mlx.utils import tree_flatten
 import mlx_lm.models.gated_delta as gd
 from mlx_lm.models.qwen3_5 import GatedDeltaNet
 checks=[]
 for dtype in [mx.float32,mx.bfloat16]:
  T=65;v=mx.sin(mx.arange(T*2*32,dtype=mx.float32)).reshape(1,T,2,32)*.03;q=mx.cos(mx.arange(T*32,dtype=mx.float32)).reshape(1,T,1,32)*.03;k=q*.7;g=mx.ones((1,T,2),dtype=mx.float32)*.95;b=mx.ones((1,T,2),dtype=mx.float32)*.2
  q=q.astype(dtype);k=k.astype(dtype);v=v.astype(dtype);g=g.astype(dtype);b=b.astype(dtype)
  initial=mx.zeros((1,2,32,32),dtype=mx.float32)
  a,sa=gd.gated_delta_ops(q,k,v,g,b,state=initial);c,sc=gd.gated_delta_kernel(q,k,v,g,b,initial);mx.eval(a,sa,c,sc)
  dy=mx.max(mx.abs(a.astype(mx.float32)-c.astype(mx.float32))).item();ds=mx.max(mx.abs(sa-sc)).item();tol=1e-5 if dtype==mx.float32 else 1e-3;assert dy<tol and ds<tol,(dy,ds,tol)
  # Trainable downstream linear weights see the same frozen features within tolerance.
  w=mx.ones((32,2),dtype=mx.float32)*.01
  f=lambda w,features:mx.sum((features.astype(mx.float32)@w)**2)
  ga=mx.grad(f)(w,a);gc=mx.grad(f)(w,c);mx.eval(ga,gc);dg=mx.max(mx.abs(ga-gc)).item();assert dg<tol
  checks.append({'dtype':str(dtype),'output_max_abs_delta':dy,'state_max_abs_delta':ds,'downstream_gradient_max_abs_delta':dg,'tolerance':tol})
 original=GatedDeltaNet.__call__;counts={'frozen_kernel_calls':0}
 def frozen_call(self,*args,**kwargs):
  trainable=tree_flatten(self.trainable_parameters())
  if trainable:return original(self,*args,**kwargs)
  previous=self.training
  try:
   self._set_training_mode(False)
   counts['frozen_kernel_calls']+=1
   return original(self,*args,**kwargs)
  finally:self._set_training_mode(previous)
 GatedDeltaNet.__call__=frozen_call
 return {'small_gpu_parity':checks,'scope':'only modules with zero trainableparameters; lastLoRAtrainingmode unchanged','limitations':'Numerical tolerances, not bitexact/fullmodelgradient/longtermstability proof'},counts

def verify_trainable_scope(model):
 from mlx.utils import tree_flatten
 paths=[name for name,_ in tree_flatten(model.trainable_parameters())]
 assert paths and all('layers.31.' in name for name in paths),paths
 assert all('lora_' in name for name in paths),paths
 return {'trainable_paths':paths,'all_only_last_full_attention_block31':True,'frozen_gated_modules':24}
