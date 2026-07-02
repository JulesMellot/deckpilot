// Fails if the ordered-apply guard in app/static/store.js stops dropping
// stale fetch responses. Run: node tests/test_apply_path.mjs
import assert from 'node:assert/strict';
import { applyState, applyStateNow, beginStateWrite } from '../app/static/store.js';

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
