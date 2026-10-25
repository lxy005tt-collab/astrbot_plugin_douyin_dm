import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from fastapi import FastAPI,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings,DEFAULTS
from .errors import BrowserError
from .runtime import RuntimeEnvironment,browse_directories
from .service import DouyinService
from .cache import media_settings,validate_media_settings

def create_app(data_dir):
    config=Settings(data_dir);service=None;session=secrets.token_urlsafe(32)
    web=Path(__file__).parent/'web'
    @asynccontextmanager
    async def lifespan(app):
        nonlocal service
        service=DouyinService(config);app.state.service=service
        await service.start()
        try:yield
        finally:await service.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def local_session(request,call_next):
        host=request.url.hostname
        if host not in ('127.0.0.1','localhost','::1'):
            return JSONResponse({'status':'error','message':'此设置页只允许本机访问。'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return JSONResponse({'status':'error','message':'不允许跨站操作。'},status_code=403)
        if request.url.path.startswith('/api/') and not secrets.compare_digest(request.cookies.get('mimi_session',''),session):
            return JSONResponse({'status':'error','message':'请先打开本地设置首页。'},status_code=401)
        return await call_next(request)

    @app.exception_handler(BrowserError)
    async def error(request,exc):return JSONResponse({'status':'error','message':str(exc)})

    def ok(data):return {'status':'ok','data':data}

    @app.get('/')
    async def home():
        response=FileResponse(web/'index.html')
        response.set_cookie('mimi_session',session,httponly=True,samesite='strict')
        return response
    app.mount('/assets',StaticFiles(directory=web),name='assets')

    @app.get('/api/status')
    async def status():
        return ok({'bot':service.status(),'settings':config.public(),'runtime':await service.runtime.diagnose(),
                   'install':service.install_state,'cache_cleanup':service.cache.status(),'standalone':True})

    @app.post('/api/settings')
    async def save(request:Request):
        payload=await request.json()
        if not isinstance(payload,dict):raise BrowserError('设置应为对象。')
        changes={key:value for key,value in payload.items() if key in DEFAULTS}
        changes.update(validate_media_settings(payload))
        for key,value in changes.items():
            default=DEFAULTS[key]
            if isinstance(default,bool) and not isinstance(value,bool):raise BrowserError('开关应为布尔值。')
            if isinstance(default,str) and not isinstance(value,str):raise BrowserError('文字设置格式不正确。')
            if isinstance(default,list) and (not isinstance(value,list) or not all(isinstance(item,str) for item in value)):
                raise BrowserError('白名单应为会话标识列表。')
        for name in ('poll_seconds','merge_seconds','max_download_mb','max_model_video_mb','max_post_images','autonomy_interval_minutes'):
            if name in changes:
                try:changes[name]=int(changes[name])
                except (ValueError,TypeError):raise BrowserError('间隔或大小应为整数。')
                if changes[name]<0 or changes[name]>10000:raise BrowserError('间隔或大小不在允许范围。')
        for name in ('api_base','video_api_base'):
            if changes.get(name):
                url=urlsplit(changes[name])
                if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise BrowserError('模型地址应为 http/https 地址，密钥请放在单独的密钥框。')
        for name in ('api_key','video_api_key'):
            if name in changes and not changes[name]:changes.pop(name)
        # 新填的视频密钥优先：只有本次没有带新密钥时，勾选“使用聊天密钥”才清空旧值。
        if payload.get('use_chat_video_key') is True and not str(changes.get('video_api_key','')).strip():
            changes['video_api_key']=''
        async with service.action_lock:
            if service.job_lock.locked():raise BrowserError('正在处理私信，请等本轮完成后再保存。')
            proposed=RuntimeEnvironment({**config,**changes},config.data_dir)
            try:
                directory=proposed.media_dir
                if directory.exists() and not directory.is_dir():
                    raise BrowserError('保存目录是一个文件，请选择文件夹，或换一个目录。')
                directory.mkdir(parents=True,exist_ok=True)
                probe=directory/('.mimi-write-check-'+secrets.token_hex(8))
                try:
                    with probe.open('x',encoding='utf8') as file:file.write('')
                finally:
                    try:
                        if probe.exists():probe.unlink()
                    except OSError:
                        pass
            except BrowserError:
                raise
            except OSError as exc:
                raise BrowserError(f'保存目录无法写入：{exc.strerror or exc}。请换一个可写目录。') from exc
            before=dict(config);old_media=service.media_dir
            restart=any(name in changes and changes[name]!=config.get(name) for name in
                        ('node_binary','playwright_package','browser_type','browser_headless','browser_executable','browser_profile'))
            running=bool(service.browser.process and service.browser.process.returncode is None)
            previous_runtime={'media_dir':old_media,'max_download_mb':config.get('max_download_mb',64)}
            next_runtime={'media_dir':str(directory),'max_download_mb':changes.get('max_download_mb',config.get('max_download_mb',64))}
            if running and not restart:await service.browser.call('configure',next_runtime)
            config.update(changes)
            try:config.save_config()
            except Exception:
                config.clear();config.update(before)
                if running and not restart:await service.browser.call('configure',previous_runtime)
                raise
            if running and restart:await service.browser.close()
            service.browser.config=service.runtime.settings()
            service.cache.settings_changed()
            return ok({'message':'设置已保存。','restart_needed':restart})

    @app.post('/api/browse')
    async def browse(request:Request):
        payload=await request.json();value=payload.get('path','')
        if not isinstance(value,str):raise BrowserError('目录路径应为文字。')
        try:return ok(await asyncio.to_thread(browse_directories,value))
        except OSError:raise BrowserError('目录无法读取，请检查路径与权限。')

    @app.post('/api/control')
    async def control(request:Request):return ok(await service.control((await request.json()).get('action','')))

    @app.post('/api/model/test')
    async def test_model():
        await service.context.llm_generate(contexts=[{'role':'user','content':'连接测试，只回复 OK。'}],max_tokens=20)
        return ok({'message':'聊天模型接口连接正常。'})

    @app.post('/api/install')
    async def install(request:Request):
        component=(await request.json()).get('component')
        if component not in ('playwright','chromium'):raise BrowserError('只支持安装 Playwright 或 Chromium。')
        if service.install_task and not service.install_task.done():return ok(service.install_state)
        service.install_state={'running':True,'message':'正在安装 '+component+'。'}
        async def run():
            try:
                await service.runtime.install(component);service.install_state={'running':False,'message':'安装完成。','success':True}
            except asyncio.CancelledError:raise
            except Exception as exc:service.install_state={'running':False,'message':str(exc)[:400],'success':False}
        service.install_task=asyncio.create_task(run());return ok(service.install_state)

    @app.get('/api/install/status')
    async def install_status():return ok(service.install_state)

    @app.post('/api/watch')
    async def watch():return ok(await service.explore_once())

    @app.post('/api/comment')
    async def comment(request:Request):
        payload=await request.json()
        async with service.action_lock:return ok(await service.activities.comment(payload.get('url',''),payload.get('text','')))

    return app
