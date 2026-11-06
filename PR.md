# 修复评论提交回执与并发状态一致性

## 触发条件与行为变化
此前浏览器端缺失状态字段可能落入 failed，提交调用抛错会直接离开且没有消费已开始监听的服务端回执，清理异常也可能覆盖 sent；评论目标和响应匹配条件较宽。Python 入口对返回 sent 但缺少评论 ID 的响应仍可记成 sent。

现在浏览器只接受精确作品路径及 HTTPS 最终目标；回执须匹配 Douyin host、发布路径、POST、作品 ID 和正文。明确服务端拒绝为 failed，证据不完整为 unknown。派发报错后仍读取已监听的回执，确认评论 ID 后保持 sent；cleanup 异常不会覆盖已确认结果。Python 将评论调用串行化，并把缺 ID 的 sent 降为 unknown；未知提交保留去重标记，不自动重试。

## 离线验证
- `node tests/comment_publish_checks.mjs`：通过，覆盖真实 publishComment 导出入口的合成 transport mock。
- `python -m pytest -q tests/test_comment_receipts.py`：6 passed。

测试不启动浏览器、不登录站点、不发送真实评论。
