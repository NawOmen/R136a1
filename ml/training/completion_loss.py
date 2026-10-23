# Mask semantics based on MLX LM tuner/trainer.py, Copyright © 2024 Apple Inc.
# MIT license: MLX-LM-LICENSE. Completion-only projection is local experiment code.
"""Тот же masked CE: проецируем на словарь только позиции ответа, частями."""
import mlx.core as mx
import mlx.nn as nn

def make_completion_loss(max_completion_tokens=384,chunk_size=64):
    if max_completion_tokens<1 or chunk_size<1:raise ValueError('Размеры должны быть положительными')
    def loss(model,batch,lengths):
        text=model.language_model
        hidden=text.model(batch[:,:-1])
        steps=mx.maximum(lengths[:,0:1],1)+mx.arange(max_completion_tokens)[None,:]
        indices=mx.clip(steps-1,0,batch.shape[1]-2)
        row=mx.arange(batch.shape[0])[:,None]
        selected=hidden[row,indices]
        targets=batch[row,indices+1]
        mask=mx.logical_and(steps<=lengths[:,1:],steps<batch.shape[1])
        def projected_ce(h,t,m):
            logits=text.model.embed_tokens.as_linear(h) if text.args.tie_word_embeddings else text.lm_head(h)
            return (nn.losses.cross_entropy(logits,mx.stop_gradient(t))*mx.stop_gradient(m)).astype(mx.float32).sum()
        chunk_ce=mx.checkpoint(projected_ce)
        total=mx.array(0.0)
        for start in range(0,max_completion_tokens,chunk_size):
            end=min(start+chunk_size,max_completion_tokens)
            total=total+chunk_ce(selected[:,start:end],targets[:,start:end],mask[:,start:end])
        count=mask.sum()
        return total/count,count
    return loss
