// Serves docs/, loads a Skyrim save into the page with headless Chrome over CDP, and writes screenshots.
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir, mkdtemp } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { extname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

const DOCS = resolve(import.meta.dirname, '../docs');
const OUT = resolve(import.meta.dirname, '../research/shots');
const SAVE = process.argv[2];
const TAG = process.argv[3] ?? '';
const CHROME = process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.otf': 'font/otf' };

const server = createServer(async (req, res) => {
  const path = join(DOCS, decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/\/$/, '/index.html'));
  try {
    const body = await readFile(path);
    res.writeHead(200, { 'content-type': TYPES[extname(path)] ?? 'application/octet-stream' }).end(body);
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const SITE = `http://127.0.0.1:${server.address().port}/`;

await mkdir(OUT, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), 'skyrim-shot-'));
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=9334', `--user-data-dir=${profile}`, '--hide-scrollbars', 'about:blank']);

let targets;
for (let i = 0; i < 50 && !targets; i++) {
  await new Promise(r => setTimeout(r, 200));
  targets = await fetch('http://127.0.0.1:9334/json/list').then(r => r.json()).catch(() => null);
}
const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r, { once: true }));

let seq = 0;
const pending = new Map();
const waiters = [];
ws.addEventListener('message', ({ data }) => {
  const m = JSON.parse(data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === 'Runtime.exceptionThrown') console.log('PAGE EXCEPTION', m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type)) console.log('PAGE', m.params.type, m.params.args.map(a => a.value ?? a.description).join(' '));
  for (let k = waiters.length - 1; k >= 0; k--) if (waiters[k].method === m.method) waiters.splice(k, 1)[0].resolve(m);
});
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq;
  pending.set(id, m => (m.error ? rej(new Error(`${method}: ${m.error.message}`)) : res(m.result)));
  ws.send(JSON.stringify({ id, method, params }));
});
const once = method => new Promise(resolve => waiters.push({ method, resolve }));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const evaluate = expr => send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }).then(r => r.result.value);

async function shot(name, width, height, full = true) {
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  await sleep(400);
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: full });
  await writeFile(join(OUT, `${TAG}${name}.png`), Buffer.from(data, 'base64'));
  console.log('wrote', name);
}

try {
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 1000, deviceScaleFactor: 1, mobile: false });
  const loaded = once('Page.loadEventFired');
  await send('Page.navigate', { url: SITE });
  await loaded;
  await sleep(500);
  await shot('01-empty', 1400, 1000, false);

  const { root } = await send('DOM.getDocument');
  const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: '#file' });
  await send('DOM.setFileInputFiles', { nodeId, files: [resolve(SAVE)] });
  await sleep(1500);
  console.log('results visible:', await evaluate(`!document.getElementById('results').hidden`), '| error:', await evaluate(`document.getElementById('error').hidden ? '' : document.getElementById('error').textContent`));
  console.log('edition:', await evaluate(`document.getElementById('edition').textContent`), '| warnings:', await evaluate(`document.getElementById('warnings').innerText`));
  console.log('tallies:', await evaluate(`[...document.querySelectorAll('.tally')].map(t => t.innerText.replace(/\\n+/g, ' ')).join(' | ')`));
  console.log('pins:', await evaluate(`document.querySelectorAll('.pin').length`), 'items:', await evaluate(`document.querySelectorAll('.item').length`));
  await shot('02-results', 1400, 1000, false);
  await evaluate(`window.scrollTo(0, 0); document.querySelector('.tally-help')?.click()`);
  console.log('walker open:', await evaluate(`document.getElementById('walker').open`));
  await shot('02c-walker', 1400, 1000, false);
  await evaluate(`document.getElementById('walker').close()`);
  await evaluate(`document.getElementById('map').scrollIntoView({ block: 'start' })`);
  await sleep(300);

  const right = await evaluate(`(() => {
    let best = null;
    for (const img of document.querySelectorAll('.pin img')) {
      const r = img.getBoundingClientRect();
      const x = r.x + r.width / 2, y = r.y + r.height / 2;
      if (y > 0 && y < innerHeight && document.elementFromPoint(x, y) === img && (!best || x > best.x)) best = { x, y };
    }
    return best;
  })()`);
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: right.x, y: right.y });
  await sleep(200);
  console.log('right-edge tooltip gap (px, expect ~12):', await evaluate(`(() => { const t = document.getElementById('tip').getBoundingClientRect(); return Math.round(${right.x} - t.right); })()`));
  await shot('02b-tooltip-right', 1400, 1000, false);
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 5, y: 5 });

  const pin = await evaluate(`(() => {
    const order = [...document.querySelectorAll('.item')].map(n => n.id.slice(5));
    let best = null;
    for (const img of document.querySelectorAll('.pin img')) {
      const r = img.getBoundingClientRect();
      const x = r.x + r.width / 2, y = r.y + r.height / 2;
      const ids = img.closest('.pin').dataset.ids;
      const rank = order.indexOf(ids.split(' ')[0]);
      if (y > 0 && y < innerHeight && document.elementFromPoint(x, y) === img && (!best || rank > best.rank)) best = { x, y, ids, rank };
    }
    return { ...best, scrollBefore: scrollY };
  })()`);
  for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x: pin.x, y: pin.y, button: 'left', clickCount: 1 });
  await sleep(1000);
  console.log('pin click:', pin.ids, '| active:', await evaluate(`[...document.querySelectorAll('.item.active')].map(n => n.id).join(',')`),
    '| active row in view:', await evaluate(`(() => { const r = document.querySelector('.item.active')?.getBoundingClientRect(); return !!r && r.top >= 0 && r.bottom <= innerHeight; })()`));
  await shot('03a-pin-click', 1400, 1000, false);

  await evaluate(`document.querySelector('.item').click()`);
  await sleep(700);
  await shot('03-focus', 1400, 1000, false);

  await evaluate(`document.getElementById('show-found').click(); document.querySelectorAll('.chip[aria-pressed="false"]').forEach(c => c.click())`);
  await sleep(300);
  console.log('all kinds + collected, items:', await evaluate(`document.querySelectorAll('.item').length`), '| realm markers:', await evaluate(`[...document.querySelectorAll('.pin.realm em')].map(e => e.textContent).join(', ')`));
  await shot('04-all-kinds', 1400, 1000, false);

  await evaluate(`document.getElementById('show-found').click()`);
  await send('Emulation.setDeviceMetricsOverride', { width: 400, height: 860, deviceScaleFactor: 1, mobile: true });
  await sleep(500);
  console.log('mobile horizontal overflow:', await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`));
  await shot('05-mobile', 400, 860, false);
} finally {
  ws.close();
  chrome.kill();
  server.close();
}
