# AstrBot 主动回复接入

独立版不用看这一页，它已经有自己的主动活动调度。

这个补丁用于本项目配套维护的 `astrbot_plugin_proactive_chat`，上游项目是：
https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat

目标是已带本项目“自主玩耍”模块的配套版本，不能直接套用到没有这些模块的上游原版。

补丁只改三处：让现有主动任务选到抖音工具、接收后端核实的完整媒体读取记录、按真实读取范围核对活动描述。不新建定时任务，不放开群聊的账号操作权限。

补丁和上游原有 AGPL 协议文本放在单独的接入包中，主插件安装包和独立版不包含该项目的源码。请保留接入包中的 `PROACTIVE_LICENSE.txt`。

维护者可以在配套主动回复插件目录检查并应用补丁：

```bash
git apply --check /你的补丁目录/astrbot-proactive-douyin.patch
git apply /你的补丁目录/astrbot-proactive-douyin.patch
```

如果检查不通过，先对照自己插件的版本和本地修改，不要强行覆盖文件。应用后重新加载主动回复插件，再到抖音接入设置里打开自主浏览。

本地已在现有配套版本上应用并验证。普通 AstrBot 用户仍可在私聊中使用抖音观看工具；自动触发需要相应的主动回复接入。
