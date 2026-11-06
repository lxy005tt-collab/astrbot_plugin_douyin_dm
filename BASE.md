上游：lxy005tt-collab/astrbot_plugin_douyin_dm
目标基线：main @ 63898dd67eac657608999292aa52eb05460f084e
来源参考：工作树 explore.mjs 评论回执差异（538b...）、tests/comment_publish_checks.mjs、activities.py 评论并发锁与 missing comment_id 降级、tests/test_comment_receipts.py。
独立分支：fix/comment-receipts
测试：node tests/comment_publish_checks.mjs；python -m pytest -q tests/test_comment_receipts.py（6 passed）。
