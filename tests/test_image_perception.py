import importlib.abc, importlib.util, sys, types
from pathlib import Path
PKG='astrbot_plugin_douyin_dm_test'
root=Path(__file__).resolve().parents[1]
pkg=types.ModuleType(PKG); pkg.__path__=[str(root)]; sys.modules[PKG]=pkg
class ContentPart: pass
class Message: pass
class TextPart: pass
class ImageURLPart: pass
class BrowserError(Exception): pass
NAMED={'astrbot.core.agent.message':{'ContentPart':ContentPart,'Message':Message,'TextPart':TextPart},'astrbot.core.message.components':{'Plain':type('Plain',(),{})},'httpx':{}}
LOCAL={PKG+'.mimi_douyin.wire':{'ImageURLPart':ImageURLPart,'Message':Message,'TextPart':TextPart},PKG+'.mimi_douyin.errors':{'BrowserError':BrowserError},PKG+'.bridge':{'BrowserError':BrowserError},PKG+'.video_transcription':{'_Owner':type('_Owner',(),{})}}
class F(importlib.abc.MetaPathFinder,importlib.abc.Loader):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='astrbot' or fullname.startswith('astrbot.') or fullname.startswith(PKG+'.') or fullname=='httpx':return importlib.util.spec_from_loader(fullname,self)
  return None
 def create_module(self,spec):
  m=types.ModuleType(spec.name); m.__path__=[]
  for k,v in (NAMED.get(spec.name) or LOCAL.get(spec.name) or {}).items():setattr(m,k,v)
  return m
 def exec_module(self,m):return None
sys.meta_path.insert(0,F())
def load(name):
 s=importlib.util.spec_from_file_location(PKG+'.'+name,root/(name+'.py'));m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);return m

ip=load('mimi_douyin/image_perception')
p=ip._positions(2000,edge=1536,overlap=128)
assert isinstance(p,list) and len(p)>=2
assert ip.MAX_IMAGES==100 and ip.BATCH_IMAGES==6
assert isinstance(ip._ocr_evidence({'segments':[]}),(str,list,dict))
