# Offline checks for comment share card parsing; no network or live account.
import importlib.abc
import importlib.util
import sys
import types
from pathlib import Path

PKG = 'astrbot_plugin_douyin_dm_test'
root = Path(__file__).resolve().parents[1]
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(root)]
sys.modules[PKG] = pkg

class ContentPart: pass
class Message: pass
class TextPart: pass
class Plain: pass
class ImageURLPart: pass
class BrowserError(Exception): pass
class _Owner: pass

NAMED = {
    'astrbot.core.agent.message': {'ContentPart': ContentPart, 'Message': Message, 'TextPart': TextPart},
    'astrbot.core.message.components': {'Plain': Plain},
    'astrbot.core.platform.astr_message_event': {'AstrMessageEvent': type('AstrMessageEvent', (), {})},
    'astrbot.core.platform.astrbot_message': {'AstrBotMessage': type('AstrBotMessage', (), {}), 'MessageMember': type('MessageMember', (), {})},
    'astrbot.core.platform.message_type': {'MessageType': type('MessageType', (), {})},
    'astrbot.core.platform.platform': {'Platform': type('Platform', (), {})},
    'astrbot.core.platform.platform_metadata': {'PlatformMetadata': type('PlatformMetadata', (), {})},
}
LOCAL_NAMED = {
    PKG + '.mimi_douyin.wire': {'ImageURLPart': ImageURLPart, 'Message': Message, 'TextPart': TextPart},
    PKG + '.mimi_douyin.errors': {'BrowserError': BrowserError},
    PKG + '.video_transcription': {'_Owner': _Owner},
}

class StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('astrbot.') or fullname.startswith(PKG + '.'):
            return importlib.util.spec_from_loader(fullname, self)
        return None
    def create_module(self, spec):
        mod = types.ModuleType(spec.name)
        mod.__path__ = []
        attrs = NAMED.get(spec.name) or LOCAL_NAMED.get(spec.name) or {}
        for key, value in attrs.items():
            setattr(mod, key, value)
        return mod
    def exec_module(self, module):
        return None
sys.meta_path.insert(0, StubFinder())

spec = importlib.util.spec_from_file_location(PKG + '.comment_share', root / 'comment_share.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

share_text = "\u5206\u4eab @\u7532 \u7684\u8bc4\u8bba\n\u6765\u81ea\u89c6\u9891"
assert module.is_comment_share({'comment_share': True}) is True
assert module.is_comment_share({'className': 'MessageItemCommentShare'}) is True
assert module.is_comment_share({'text': share_text}) is True
assert module.is_comment_share({'text': 'plain text'}) is False
card = module.split_comment_card({
    'comment_share': {'comment_id': 'c1', 'author': '\u7532', 'text': '\u4e59\u8bf4\u5f97\u5bf9',
                      'content_type': 1, 'aweme_title': '\u793a\u4f8b\u4f5c\u54c1', 'aweme_id': 'a1'},
    'text': share_text,
})
assert card['kind'] == 'comment_share'
assert card['comment_id'] == 'c1'
assert card['author'] == '\u7532'
assert card['text'] == '\u4e59\u8bf4\u5f97\u5bf9'
assert '\u7532' in module.format_comment_card(card)
