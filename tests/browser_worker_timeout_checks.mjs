// Offline checks for browser worker RPC timeout boundaries.
import assert from 'node:assert/strict';
import {actionTimeout, withTimeout} from '../mimi_douyin/browser/rpc_timeouts.mjs';

assert.equal(actionTimeout('open'), 60000);
assert.equal(actionTimeout('browse'), 95000);
assert.equal(actionTimeout('comment'), 95000);
assert.equal(actionTimeout('download'), 120000);
assert.equal(actionTimeout('post_info'), 90000);
assert.equal(actionTimeout('close'), 10000);
assert.equal(actionTimeout('snapshot'), 45000);
assert.equal(actionTimeout(''), 45000);
assert.equal(await withTimeout(Promise.resolve('ok'), 100, 'status'), 'ok');
await assert.rejects(
  () => withTimeout(new Promise(() => {}), 5, 'browse'),
  /browser action hard timeout: browse/,
);
