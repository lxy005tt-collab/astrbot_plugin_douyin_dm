from types import SimpleNamespace
from urllib.parse import urlsplit
import httpx
from .errors import BrowserError

class ModelContext:
    def __init__(self,config):self.config=config
    def get_provider_by_id(self,provider_id):
        model=self.config.get('video_model') if provider_id=='video' else self.config.get('model')
        return SimpleNamespace(get_model=lambda:model) if model else None

    async def llm_generate(self,*,chat_provider_id='chat',contexts,max_tokens=1600,**kwargs):
        config=self.config;video=chat_provider_id=='video'
        model=config.get('video_model') if video else config.get('model')
        base=(config.get('video_api_base') if video else '') or config.get('api_base')
        key=(config.get('video_api_key') if video else '') or config.get('api_key')
        if not base or not model:raise BrowserError('请先填写模型接口地址和模型名称。')
        parsed=urlsplit(base)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise BrowserError('模型接口地址应为 http/https 地址，不要把密钥放进网址。')
        messages=[message.model_dump() if hasattr(message,'model_dump') else message for message in contexts]
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=120) as client:
                response=await client.post(base.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key} if key else {},
                    json={'model':model,'messages':messages,'max_tokens':max_tokens,'stream':False})
                if not response.is_success:raise BrowserError(f'模型接口返回 HTTP {response.status_code}，请检查接口地址、密钥和模型名称。')
                payload=response.json();text=payload['choices'][0]['message']['content']
                if not isinstance(text,str) or not text.strip():raise BrowserError('模型没有返回文字。')
        except BrowserError:raise
        except (httpx.HTTPError,ValueError,KeyError,IndexError) as exc:raise BrowserError('模型接口调用失败：'+type(exc).__name__+'。') from exc
        return SimpleNamespace(role='assistant',completion_text=text)
