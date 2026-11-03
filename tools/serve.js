// Local static server for docs/: node tools/serve.js [port]
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, resolve } from 'node:path';

const DOCS = resolve(import.meta.dirname, '../docs');
const PORT = Number(process.argv[2] ?? 8124);
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.ico': 'image/x-icon', '.otf': 'font/otf', '.xml': 'application/xml', '.txt': 'text/plain' };

createServer(async (req, res) => {
  try {
    const pathname = decodeURIComponent(req.url.split('?')[0]).replace(/\/+/g, '/');
    const path = normalize(join(DOCS, pathname.endsWith('/') ? `${pathname}index.html` : pathname));
    if (!path.startsWith(DOCS)) return res.writeHead(403).end();
    const body = await readFile(path);
    res.writeHead(200, { 'content-type': TYPES[extname(path)] ?? 'application/octet-stream', 'cache-control': 'no-store' }).end(body);
  } catch {
    res.writeHead(404).end('Not found');
  }
}).listen(PORT, '127.0.0.1', () => console.log(`Serving ${DOCS} at http://127.0.0.1:${PORT}/`));
