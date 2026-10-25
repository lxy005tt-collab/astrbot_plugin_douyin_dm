"""Portable paths and discoverable, plugin-owned browser dependencies."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys

from .errors import BrowserError

PLAYWRIGHT_VERSION = '1.64.1'


def local_path(value, base):
    path=Path(os.path.expandvars(os.path.expanduser(str(value))))
    return (path if path.is_absolute() else Path(base)/path).resolve()


def find_executable(name, explicit='', base=None):
    if explicit:
        found=shutil.which(str(explicit))
        candidate=Path(found) if found else local_path(explicit,base or Path.cwd())
        return str(candidate) if candidate.is_file() else ''
    found=shutil.which(name)
    if found:return str(Path(found).resolve())
    candidates=[]
    if sys.platform=='win32':
        if name=='node':
            for key in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
                if os.environ.get(key):candidates.append(Path(os.environ[key])/'nodejs/node.exe')
        if name in ('ffmpeg','ffprobe') and os.environ.get('LOCALAPPDATA'):
            root=Path(os.environ['LOCALAPPDATA'])/'Microsoft/WinGet/Packages'
            if root.is_dir():
                candidates.extend(root.glob(f'Gyan.FFmpeg*/ffmpeg-*/bin/{name}.exe'))
    else:
        candidates.extend(Path(root)/name for root in ('/usr/local/bin','/usr/bin','/opt/homebrew/bin'))
    return next((str(path.resolve()) for path in candidates if path.is_file()),'')


class RuntimeEnvironment:
    def __init__(self,config,data_dir,plugin_dir=None):
        self.config=config
        self.data_dir=Path(data_dir).resolve()
        self.plugin_dir=Path(plugin_dir or Path(__file__).parent/'browser').resolve()
        self.project_dir=Path(__file__).parent.parent.resolve()
        self.managed_dir=self.data_dir/'runtime'

    @property
    def media_dir(self):return local_path(self.config.get('media_dir') or 'media',self.data_dir)

    @property
    def profile_dir(self):return local_path(self.config.get('browser_profile') or 'browser-profile',self.data_dir)

    @property
    def node(self):return find_executable('node',self.config.get('node_binary',''),self.data_dir)

    @property
    def ffmpeg(self):return find_executable('ffmpeg',self.config.get('ffmpeg_binary',''),self.data_dir)

    @property
    def ffprobe(self):
        explicit=self.config.get('ffprobe_binary','')
        if explicit:return find_executable('ffprobe',explicit,self.data_dir)
        sibling=Path(self.ffmpeg).with_name('ffprobe.exe' if sys.platform=='win32' else 'ffprobe') if self.ffmpeg else None
        return str(sibling) if sibling and sibling.is_file() else find_executable('ffprobe')

    @property
    def playwright_package(self):
        explicit=self.config.get('playwright_package','')
        if explicit:
            path=local_path(explicit,self.data_dir)
            return path/'package.json' if path.is_dir() else path
        managed=self.managed_dir/'browser/package.json'
        for candidate in (managed,self.project_dir/'package.json',self.project_dir.parent.parent.parent/'package.json'):
            if (candidate.parent/'node_modules/playwright/package.json').is_file():return candidate
        return managed

    @property
    def browser_cache(self):return self.managed_dir/'browsers'

    def process_env(self):
        env=os.environ.copy()
        env['PLAYWRIGHT_BROWSERS_PATH']=str(self.browser_cache)
        return env

    def npm_cli(self):
        candidates=[]
        if self.node:candidates.append(Path(self.node).parent/'node_modules/npm/bin/npm-cli.js')
        npm=shutil.which('npm')
        if npm:
            path=Path(npm).resolve()
            if path.suffix=='.js':candidates.append(path)
            candidates.append(path.parent/'node_modules/npm/bin/npm-cli.js')
        return next((str(path) for path in candidates if path.is_file()),'')

    def system_browser(self):
        explicit=self.config.get('browser_executable','')
        kind=self.config.get('browser_type','自动选择')
        if explicit:
            path=local_path(explicit,self.data_dir)
            return {'executable':str(path),'channel':'','ready':path.is_file(),'label':'自定义浏览器'}
        choices=[]
        if kind in ('自动选择','Edge'):
            for command in ('msedge','microsoft-edge','microsoft-edge-stable'):
                if found:=shutil.which(command):choices.append(('msedge',Path(found),'Edge'))
            if sys.platform=='win32':
                for key in ('ProgramFiles(x86)','ProgramFiles','LOCALAPPDATA'):
                    if os.environ.get(key):choices.append(('msedge',Path(os.environ[key])/'Microsoft/Edge/Application/msedge.exe','Edge'))
            if sys.platform=='darwin':choices.append(('msedge',Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'),'Edge'))
        if kind in ('自动选择','Chrome'):
            for command in ('google-chrome','google-chrome-stable','chrome'):
                if found:=shutil.which(command):choices.append(('chrome',Path(found),'Chrome'))
            if sys.platform=='win32':
                for key in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
                    if os.environ.get(key):choices.append(('chrome',Path(os.environ[key])/'Google/Chrome/Application/chrome.exe','Chrome'))
            if sys.platform=='darwin':choices.append(('chrome',Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),'Chrome'))
        if kind=='自动选择':
            for command in ('chromium','chromium-browser'):
                if found:=shutil.which(command):choices.append(('',Path(found),'Chromium'))
        for channel,path,label in choices:
            if path.is_file():return {'channel':'','executable':str(path),'path':str(path),'ready':True,'label':label}
        return {'channel':'','executable':'','ready':False,'label':kind if kind!='自动选择' else '未找到浏览器'}

    def settings(self):
        browser=self.system_browser()
        return {**self.config,'node_binary':self.node,'playwright_package':str(self.playwright_package),
            'media_cache_registry':str(self.data_dir/'media-cache.sqlite3'),
            'browser_profile':str(self.profile_dir),'media_dir':str(self.media_dir),
            'browser_channel':browser['channel'],'browser_executable':browser['executable'],
            'playwright_browsers_path':str(self.browser_cache)}

    async def run(self,args,timeout=20,env=None):
        process=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,env=env or self.process_env(),
            creationflags=0x08000000 if os.name=='nt' else 0)
        try:output,_=await asyncio.wait_for(process.communicate(),timeout)
        except BaseException:
            if process.returncode is None:process.kill();await process.wait()
            raise
        return process.returncode,output.decode('utf-8',errors='replace')

    async def diagnose(self):
        dependencies=[]
        node=self.node;node_ready=False
        if node:
            try:
                code,version=await self.run([node,'--version'])
                node_ready=code==0 and int(version.strip().lstrip('v').split('.')[0])>=20
            except (OSError,ValueError,asyncio.TimeoutError):version='无法运行'
        else:version=''
        dependencies.append({'id':'node','name':'Node.js 20+','ready':node_ready,'path':node,'version':version.strip(),
            'hint':'自动查找系统 PATH；找不到时安装 Node.js 或在插件配置中指定路径。','url':'https://nodejs.org/en/download'})
        probe={}
        if node_ready and self.playwright_package.is_file():
            try:
                code,output=await self.run([node,str(self.plugin_dir/'runtime_probe.mjs'),str(self.playwright_package)])
                if code==0:probe=json.loads(output)
            except (OSError,ValueError,asyncio.TimeoutError):pass
        dependencies.append({'id':'playwright','name':'Playwright','ready':bool(probe.get('ready')),
            'path':str(self.playwright_package),'version':probe.get('version',''),
            'hint':'可安装到本插件的数据目录，不依赖其他插件。','url':'https://playwright.dev/docs/browsers'})
        browser=self.system_browser()
        if (not browser['ready'] and not self.config.get('browser_executable')
                and self.config.get('browser_type','自动选择') in ('自动选择','Chromium') and probe.get('chromium_installed')):
            browser={'label':'插件 Chromium','ready':True,'path':probe.get('chromium_executable'),'channel':'','executable':''}
        dependencies.append({'id':'browser','name':browser['label'],'ready':browser['ready'],'path':browser.get('path',browser['executable']),
            'version':'','hint':'优先使用已安装的 Edge/Chrome，也可下载插件自用 Chromium。'})
        for name,label,path in [('ffmpeg','FFmpeg',self.ffmpeg),('ffprobe','FFprobe',self.ffprobe)]:
            ready=False;version=''
            if path:
                try:
                    code,output=await self.run([path,'-version'])
                    ready=code==0;version=output.splitlines()[0] if output else ''
                except (OSError,asyncio.TimeoutError):pass
            dependencies.append({'id':name,'name':label,'ready':ready,'path':path,'version':version,
                'hint':'自动查找系统 PATH、同目录程序及 Windows WinGet 安装位置。视频处理需要这两个程序。','url':'https://ffmpeg.org/download.html'})
        return {'dependencies':dependencies,'browser_ready':node_ready and bool(probe.get('ready')) and browser['ready'],
            'video_ready':all(row['ready'] for row in dependencies if row['id'] in ('ffmpeg','ffprobe')),
            'media_dir':str(self.media_dir),'media_dir_setting':self.config.get('media_dir',''),
            'default_media_dir':str(self.data_dir/'media'),'browser_profile':str(self.profile_dir),
            'browser_type':self.config.get('browser_type','自动选择'),'npm_available':bool(self.npm_cli()),
            'headless':bool(self.config.get('browser_headless',False))}

    async def install(self,component):
        node=self.node
        if not node:raise BrowserError('未找到 Node.js，请先安装 Node.js 20+，再重新检测。')
        code,version=await self.run([node,'--version'])
        if code or int(version.strip().lstrip('v').split('.')[0])<20:raise BrowserError('需要 Node.js 20 或更新版本。')
        self.managed_dir.mkdir(parents=True,exist_ok=True)
        if component=='playwright':
            npm=self.npm_cli()
            if not npm:raise BrowserError('未找到 npm，请安装包含 npm 的 Node.js 发行版。')
            target=self.managed_dir/'browser';target.mkdir(parents=True,exist_ok=True)
            package=target/'package.json'
            if package.exists() and json.loads(package.read_text('utf-8-sig')).get('name')!='mimi-douyin-browser-runtime':
                raise BrowserError('运行目录中已有其他 package.json，请先检查该目录。')
            package.write_text(json.dumps({'name':'mimi-douyin-browser-runtime','version':'1.0.0','private':True,
                'dependencies':{'playwright':PLAYWRIGHT_VERSION}},indent=2),encoding='utf-8')
            args=[node,npm,'install','--prefix',str(target),'--cache',str(self.managed_dir/'npm-cache'),
                '--ignore-scripts','--no-audit','--no-fund','--registry=https://registry.npmjs.org']
            timeout=240
        elif component=='chromium':
            if not self.playwright_package.is_file():raise BrowserError('请先安装 Playwright 依赖。')
            _,probe=await self.run([node,str(self.plugin_dir/'runtime_probe.mjs'),str(self.playwright_package)])
            package=json.loads(probe).get('cli')
            if not package:raise BrowserError('请先安装 Playwright 依赖。')
            args=[node,package,'install','chromium'];timeout=600
        else:raise BrowserError('仅支持安装 Playwright 或 Chromium。')
        code,output=await self.run(args,timeout)
        (self.managed_dir/'install.log').write_text(output,encoding='utf-8')
        if code:raise BrowserError('依赖安装未完成，请检查网络和插件 runtime/install.log。')
        return {'component':component,'installed':True,'managed_dir':str(self.managed_dir)}


def browse_directories(value=''):
    if not value:
        if sys.platform=='win32':
            mask=ctypes.windll.kernel32.GetLogicalDrives()
            roots=[f'{chr(65+index)}:/' for index in range(26) if mask & (1<<index)]
        else:roots=['/']
        return {'path':'','parent':None,'directories':[{'name':root,'path':root} for root in roots]}
    path=Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():raise BrowserError('请选择绝对目录路径。')
    path=path.resolve()
    if not path.is_dir():raise BrowserError('目录不存在，请选择上一级目录或输入要新建的目录。')
    try:
        directories=[]
        for item in path.iterdir():
            try:
                if item.is_dir():directories.append({'name':item.name,'path':str(item.resolve())})
            except OSError:continue
        directories.sort(key=lambda item:item['name'].casefold())
    except OSError as exc:raise BrowserError('没有权限读取该目录。') from exc
    return {'path':str(path),'parent':str(path.parent) if path.parent!=path else '',
        'directories':directories[:300],'truncated':len(directories)>300}
