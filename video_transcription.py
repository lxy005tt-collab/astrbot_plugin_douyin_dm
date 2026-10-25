"""AstrBot adapter for the standalone perception engine."""
from astrbot.core.agent.message import ContentPart, Message
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
        return await self.context.llm_generate(**kwargs)

class _Owner:
    def __init__(self,owner):self.owner=owner;self.context=_Context(owner.context)
    def __getattr__(self,name):return getattr(self.owner,name)

async def _audio_parts(owner,paths):return await _engine._audio_parts(owner,paths)
async def _visual_paths(owner,paths):return await _engine._visual_paths(owner,paths)
async def transcribe_video(owner,sources):
    return await _engine.transcribe_video(_Owner(owner),sources,audio_factory=_audio_parts,visual_factory=_visual_paths)
