// Fails if the ordered-apply guard in app/static/app.js stops dropping stale
// fetch responses. Run: node tests/test_apply_path.mjs
// ponytail: slices the guard out of app.js by marker; import it properly once
// the UI moves to ES modules (roadmap step 2).
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const src = readFileSync(new URL('../app/static/app.js', import.meta.url), 'utf8');
const block = src.slice(src.indexOf('let stateWriteSeq'), src.indexOf('async function refresh'));
const { beginStateWrite, applyState, applyStateNow } = new Function(
  `${block}; return { beginStateWrite, applyState, applyStateNow };`
)();

let value = null;

// A fetch takes its ticket, then a WebSocket write lands before it resolves:
// the fetch response must be dropped.
const fetchTicket = beginStateWrite();
applyStateNow(() => { value = 'ws'; });
assert.equal(applyState(fetchTicket, () => { value = 'stale-fetch'; }), false);
assert.equal(value, 'ws');

// A fetch with no interleaved write still lands.
assert.equal(applyState(beginStateWrite(), () => { value = 'fetch'; }), true);
assert.equal(value, 'fetch');

console.log('apply path ok');
