// worker.js: owns the in-memory Relate database (WebAssembly build).
// The page sends {id, statement, params}; the worker answers {id, result} with the parsed envelope.
let db = null;
const ready = (async () => {
  const relate = await import(new URL('./relate/relate.js', import.meta.url).href);
  await relate.default({ module_or_path: new URL('./relate/relate_bg.wasm', import.meta.url).href });
  db = new relate.RelateDb();
  return relate;
})();

self.onmessage = async (event) => {
  const { id, statement, params } = event.data;
  try {
    await ready;
    const t0 = performance.now();
    const envelope = JSON.parse(db.execute(statement, params ? JSON.stringify(params) : null));
    envelope.ms = performance.now() - t0;
    self.postMessage({ id, result: envelope });
  } catch (err) {
    self.postMessage({ id, result: { error: String(err && err.message ? err.message : err) } });
  }
};
