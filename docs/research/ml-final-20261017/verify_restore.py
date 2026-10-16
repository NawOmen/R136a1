"""Verify uploaded/downloaded split archive and optionally extract into a NEW empty directory."""
from pathlib import Path,PurePosixPath
import json,hashlib,tarfile,io,sys
P=Path(__file__).resolve().parent
assets=json.loads((P/'assets-manifest.json').read_text())['parts'];expected={r['path']:r for r in json.loads((P/'files-manifest.json').read_text())['files']}
for a in assets:
 p=P/a['name'];assert p.stat().st_size==a['bytes'];h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 assert h.hexdigest()==a['sha256'],a['name']
class Reader(io.RawIOBase):
 def __init__(self):self.i=0;self.f=None
 def readable(self):return True
 def read(self,n=-1):
  if self.f is None:
   if self.i==len(assets):return b''
   self.f=(P/assets[self.i]['name']).open('rb');self.i+=1
  b=self.f.read(n)
  if b:return b
  self.f.close();self.f=None;return self.read(n)
seen=set();dest=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else None
if dest:dest.mkdir(exist_ok=False)
with tarfile.open(fileobj=Reader(),mode='r|') as t:
 for m in t:
  q=PurePosixPath(m.name);assert m.isfile() and not q.is_absolute() and '..' not in q.parts and m.name in expected and m.name not in seen
  h=hashlib.sha256();n=0;f=t.extractfile(m);out=None
  if dest:
   target=dest/str(q);target.parent.mkdir(parents=True,exist_ok=True);out=target.open('xb')
  while b:=f.read(8*1024**2):h.update(b);n+=len(b);out.write(b) if out else None
  if out:out.close()
  assert n==expected[m.name]['bytes'] and h.hexdigest()==expected[m.name]['sha256'],m.name
  seen.add(m.name)
assert seen==set(expected)
report={'verified_parts':len(assets),'verified_files':len(seen),'all_asset_sha256':True,'all_archived_file_sha256':True,'safe_regular_paths_only':True,'restore_directory':str(dest) if dest else None}
(P/'local-archive-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
