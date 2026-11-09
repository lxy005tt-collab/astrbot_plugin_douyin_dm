// Bounded RPC execution for the browser worker command queue.
// A single stuck Playwright action must leave the queue able to serve later commands.
export const RPC_TIMEOUT_MS = Object.freeze({
  open: 60000,
  browse: 95000,
  comment: 95000,
  download: 120000,
  post_info: 90000,
  close: 10000,
  default: 45000,
});

export function actionTimeout(action) {
  return RPC_TIMEOUT_MS[String(action || '')] ?? RPC_TIMEOUT_MS.default;
}

export async function withTimeout(promise, timeoutMs, action = 'action') {
  const limit = Math.max(1, Number(timeoutMs) || RPC_TIMEOUT_MS.default);
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error('browser action hard timeout: ' + action)),
          limit,
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
