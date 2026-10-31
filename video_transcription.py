"""AstrBot adapter for the standalone perception engine."""
from copy import deepcopy
from types import SimpleNamespace

from astrbot.core.agent.message import ContentPart, Message
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
from .bridge import BrowserError
from .mimi_douyin import perception as _engine
from .mimi_douyin.perception import (TEXT_MODE, NATIVE_MODE, DEFAULT_PROMPT, SCHEMA_PROMPT,
    VideoTranscript, AudioTranscript, format_transcript, uses_text_transcription)

class AudioFilePart(ContentPart):
    type:str='file'
    file:dict[str,str]

class _Context:
    def __init__(self,context):self.context=context
    def get_provider_by_id(self,provider_id):return self.context.get_provider_by_id(provider_id)
    async def llm_generate(self,**kwargs):
        kwargs['contexts']=[Message.model_validate(message.model_dump() if hasattr(message,'model_dump') else message)
                            for message in kwargs['contexts']]
        provider=self.get_provider_by_id(kwargs['chat_provider_id'])
        if isinstance(provider,ProviderOpenAIOfficial):
            # AstrBot drops tool_choice when no FunctionTool is supplied. These
            # visual/audio calls only produce descriptions, never execute tools.
            # Reuse the configured SDK client so credentials/proxy stay native.
            extra=deepcopy(provider.provider_config.get('custom_extra_body') or {})
            extra.pop('tools',None);extra.pop('tool_choice',None)
            completion=await provider.client.chat.completions.create(
                model=provider.get_model(),
                messages=[message.model_dump(mode='json') for message in kwargs['contexts']],
                max_tokens=kwargs.get('max_tokens',2200),stream=False,
                tools=[],tool_choice='none',extra_body=extra,
            )
            if not completion.choices:
                raise BrowserError('视频识别接口没有返回候选内容。')
            message=completion.choices[0].message
            if message.tool_calls:
                raise BrowserError('视频识别接口仅应返回识别内容，却返回了工具调用；未把它当作视频描述。')
            content=message.content
            if isinstance(content,list):
                content=''.join(part.get('text','') for part in content
                    if isinstance(part,dict) and part.get('type')=='text')
            if not isinstance(content,str) or not content.strip():
                raise BrowserError('视频识别接口没有返回可用的画面或声音描述。')
            return SimpleNamespace(role='assistant',completion_text=content)
        return await self.context.llm_generate(**kwargs)

class _Owner:
    def __init__(self,owner):self.owner=owner;self.context=_Context(owner.context)
    def __getattr__(self,name):return getattr(self.owner,name)

async def _audio_parts(owner,paths):return await _engine._audio_parts(owner,paths)
async def _visual_paths(owner,paths):return await _engine._visual_paths(owner,paths)
async def transcribe_video(owner,sources):
    return await _engine.transcribe_video(_Owner(owner),sources,audio_factory=_audio_parts,visual_factory=_visual_paths)
