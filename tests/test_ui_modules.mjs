// Loads the whole UI module graph under node with a stubbed DOM. Fails on any
// broken import/export pair, strict-mode violation, or top-level runtime
// error — the mistakes a no-build-step module split can silently ship.
// Run: node tests/test_ui_modules.mjs

// ponytail: Proxy-based DOM stub, not jsdom — link and load errors are the
// target, rendering is exercised in the browser.
const stub = new Proxy(function () {}, {
  get(target, prop) {
    if (prop === Symbol.toPrimitive) return () => '';
    if (prop === 'hidden') return true; // keyboard handler treats modals as closed
    return stub;
  },
  set: () => true,
  apply: () => stub,
  construct: () => stub,
});

globalThis.document = stub;
globalThis.window = stub;
globalThis.location = { protocol: 'http:', host: 'test', hostname: 'test' };
globalThis.requestAnimationFrame = () => 0;
globalThis.WebSocket = class {
  addEventListener() {}
};
// Resolving with an empty snapshot lets initializeApp run its full happy
// path (refresh → renderState → setupWebSocket) against the stubbed DOM.
globalThis.fetch = () => Promise.resolve({ ok: true, status: 200, json: async () => ({}), text: async () => '' });

// initializeApp catches its own errors and reports via console.error; treat
// any of those as a failure too.
let runtimeError = null;
const realError = console.error;
console.error = (...args) => {
  runtimeError = args;
  realError(...args);
};

try {
  await import('../app/static/app.js');
} catch (error) {
  realError('UI module graph failed to load:', error);
  process.exit(1);
}
// initializeApp runs un-awaited at module top level; let it settle.
await new Promise((resolve) => setTimeout(resolve, 100));
if (runtimeError) {
  realError('UI failed during startup against the stub DOM.');
  process.exit(1);
}
console.log('ui modules ok');
process.exit(0); // reconnect/clock timers would otherwise keep node alive
