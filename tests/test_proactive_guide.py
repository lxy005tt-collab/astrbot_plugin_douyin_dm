"""Exercise the actual hook without loading the AstrBot application."""
import ast
import types
import unittest
from pathlib import Path


class Tools:
    def __init__(self, tools=()):
        self.func_list = list(tools)

    def get_tool(self, name):
        return next((t for t in self.func_list if t.name == name), None)

    def add_tool(self, tool):
        self.func_list.append(tool)

    def remove_tool(self, name):
        self.func_list = [t for t in self.func_list if t.name != name]


class Part:
    def __init__(self, text):
        self.text = text

    def mark_as_temp(self):
        return self


class GuideTests(unittest.IsolatedAsyncioTestCase):
    async def run_hook(self, marker=True, permitted=True, comments=False):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "douyin_activity_guide")
        node.decorator_list = []
        ns = {"native_activities": types.SimpleNamespace(allowed=lambda *_: permitted),
              "TextPart": Part}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), ns)
        tools = Tools([types.SimpleNamespace(name=name, active=True) for name in
                       ["douyin_watch_recommended", "douyin_comment_watched"]])
        plugin = types.SimpleNamespace(
            context=types.SimpleNamespace(get_llm_tool_manager=lambda: tools),
            config={"allow_public_comments": comments},
        )
        event = types.SimpleNamespace(get_extra=lambda key, default=False: marker)
        req = types.SimpleNamespace(func_tool=Tools(), extra_user_content_parts=[])
        await ns["douyin_activity_guide"](plugin, event, req)
        return req

    async def test_schedule_guidance_and_comments_off(self):
        req = await self.run_hook()
        self.assertIn("已有主动聊天定时调度", req.extra_user_content_parts[0].text)
        self.assertIn("本轮只浏览和聊天，不发表评论", req.extra_user_content_parts[0].text)
        self.assertEqual([t.name for t in req.func_tool.func_list],
                         ["douyin_watch_recommended"])

    async def test_comments_opt_in(self):
        req = await self.run_hook(marker=False, comments=True)
        self.assertIsNotNone(req.func_tool.get_tool("douyin_comment_watched"))
        self.assertIn("评论开关开启", req.extra_user_content_parts[0].text)

    async def test_no_permission_keeps_no_tools_or_guidance(self):
        req = await self.run_hook(permitted=False)
        self.assertEqual(req.func_tool.func_list, [])
        self.assertEqual(req.extra_user_content_parts, [])

    async def test_ordinary_chat_uses_original_guidance(self):
        req = await self.run_hook(marker=False)
        self.assertNotIn("已有主动聊天定时调度", req.extra_user_content_parts[0].text)
        self.assertIn("想刷抖音时", req.extra_user_content_parts[0].text)


if __name__ == "__main__":
    unittest.main()
