const strusky = (() => {
  const INPUT_RE = /input\s+\$(\w+)\s+as\s+(\w+)/;
  const OUTPUT_RE = /output\s+\$(\w+)\s+as\s+(\w+):?\s*(.*)/;

  function parseInputSpecs(content) {
    const specs = [];
    const lines = content.split('\n');
    for (const line of lines) {
      const m = line.trim().match(INPUT_RE);
      if (m) {
        specs.push({ name: m[1], type: m[2] });
      }
    }
    return specs;
  }

  function parseOutputSpecs(content) {
    const specs = [];
    const lines = content.split('\n');
    for (const line of lines) {
      const m = line.trim().match(OUTPUT_RE);
      if (m) {
        specs.push({ name: m[1], type: m[2], register: m[3] || '' });
      }
    }
    return specs;
  }

  function serve(code, input, opts = {}) {
    const endpoint = opts.endpoint || '/api/serve';
    const timeout = opts.timeout || 60000;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    return fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, input }),
      signal: controller.signal,
    }).then(r => {
      clearTimeout(timer);
      return r.json();
    }).catch(e => {
      clearTimeout(timer);
      if (e.name === 'AbortError') throw new Error('Request timed out');
      throw e;
    });
  }

  return { parseInputSpecs, parseOutputSpecs, serve };
})();
