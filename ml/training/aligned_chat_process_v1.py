"""Opt-in process method for a NEW run; no installed package mutation."""
def aligned_process(self, row):
    messages=row[self.chat_key]
    tools=row.get('tools',None)
    tokens=self.tokenizer.apply_chat_template(messages,tools=tools,return_dict=False,enable_thinking=False)
    if not self.mask_prompt:return tokens,0
    prefix=self.tokenizer.apply_chat_template(messages[:-1],tools=tools,add_generation_prompt=messages[-1].get('role')=='assistant',return_dict=False,enable_thinking=False)
    assert tokens[:len(prefix)]==prefix,'Nonthinking prompt is not exact prefix'
    return tokens,len(prefix)
