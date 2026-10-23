"""合并丢件：只看「本地新增的顶层符号」，并全树反查引用。

判定链：
  A. local_defs = PRE 里有定义、BASE 里没有定义（合并前本地新写的符号）
  B. 该符号在 HEAD 同一文件里既无定义也无出现 -> 候选丢失
  C. 一次 git grep 全树（HEAD）反查候选名：
       还有别的文件引用 -> CRASH（定义了但没了，调用方还在）
       没人引用        -> DEAD （纯死代码/测试被拆，不崩但回归网漏）
"""
import re, json, subprocess

REPO = '/data/openpilot'  # 设备上的仓根（ai/ 与 openpilot/ 同层）
PRE, BASE = 'd1155add38', '9e002fb2dc'

def git(*a, inp=None):
  return subprocess.run(['git','-C',REPO,*a], capture_output=True, text=True, input=inp, check=True).stdout

def tree(rev):
  out={}
  for ln in git('ls-tree','-r',rev).splitlines():
    meta,path = ln.split('\t',1); mode,typ,sha = meta.split()
    if typ=='blob': out[path]=sha
  return out

def batch(shas):
  blobs={}; p=subprocess.run(['git','-C',REPO,'cat-file','--batch'],input=''.join(s+'\n' for s in shas).encode(),capture_output=True)
  d=p.stdout; i=0
  while i<len(d):
    nl=d.index(b'\n',i); parts=d[i:nl].decode().split()
    if len(parts)==3:
      sha,size=parts[0],int(parts[2]); blobs[sha]=d[nl+1:nl+1+size]; i=nl+1+size+1
    else: i=nl+1
  return blobs

t_pre,t_base,t_head = tree(PRE),tree(BASE),tree('HEAD')
changed = sorted(set(git('diff','--name-only',BASE,PRE).splitlines()) & set(t_pre) & set(t_base) & set(t_head))
need = sorted({r[p] for r in (t_pre,t_base,t_head) for p in changed})
blobs = batch(need)

def txt(sha):
  b=blobs.get(sha,b'')
  return None if b'\0' in b[:8000] else b.decode('utf-8','replace')

DEF = re.compile(r'^(?:async\s+)?def\s+([A-Za-z_]\w*)|^class\s+([A-Za-z_]\w*)|^([A-Z][A-Z0-9_]{3,})\s*(?::[^=]*)?=', re.M)
def defs(s):
  return {a or b or c for a,b,c in DEF.findall(s)}

rows=[]
for p in changed:
  pre,base,head = txt(t_pre[p]),txt(t_base[p]),txt(t_head[p])
  if pre is None or base is None or head is None: continue
  local = defs(pre) - defs(base)
  if not local: continue
  head_defs = defs(head)
  gone = sorted(d for d in local if d not in head_defs and not re.search(r'\b'+re.escape(d)+r'\b', head))
  if gone:
    rows.append({'path':p,'status':'full-revert' if t_head[p]==t_base[p] else 'partial','gone':gone})

names = sorted({n for r in rows for n in r['gone']})
print(f'候选丢失顶层符号: {len(names)} 个，涉及 {len(rows)} 文件')
open('/tmp/gone_names.txt','w').write('\n'.join(names)+'\n')
grep = subprocess.run(['git','-C',REPO,'grep','-n','-w','-F','-f','/tmp/gone_names.txt','HEAD','--','*.py','*.cc','*.h','*.hpp','*.json','*.yaml','*.md'],
                      capture_output=True,text=True)
ref={}
for ln in grep.stdout.splitlines():
  path=ln.split(':',1)[0][5:]
  m=re.search(r'\b(' + '|'.join(map(re.escape,names)) + r')\b', ln) if names else None
  if not m: continue
  n=m.group(1)
  owner={r['path'] for r in rows if n in r['gone']}
  if path in owner: continue
  ref.setdefault(n,set()).add(path)

crash=[r for r in rows if any(n in ref for n in r['gone'])]
dead=[r for r in rows if not any(n in ref for n in r['gone'])]
crash.sort(key=lambda r:-len(r['gone'])); dead.sort(key=lambda r:-len(r['gone']))
print(f'\n=== CRASH 级（符号没了但别的文件还在引用）: {len(crash)} 文件 ===')
for r in crash:
  live=[n for n in r['gone'] if n in ref]
  print(f'{r["status"]:12s} {r["path"]}')
  for n in live[:6]:
    print(f'     {n}  <- 仍被 {len(ref[n])} 处引用: {sorted(ref[n])[0]}')
print(f'\n=== DEAD 级（无外部引用）: {len(dead)} 文件 ===')
for r in dead[:20]:
  print(f'{r["status"]:12s} {r["path"]}  [{",".join(r["gone"][:6])}]')
json.dump({'crash':crash,'dead':dead,'refs':{k:sorted(v) for k,v in ref.items()}},
          open('/data/openpilot/ai/docs/artifacts/merge_loss_symbols.json','w'),ensure_ascii=False,indent=1)
print('\n-> ai/docs/artifacts/merge_loss_symbols.json')
