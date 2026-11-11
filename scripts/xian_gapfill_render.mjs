// Render a public page in headless Chromium and dump the DOM to disk for evidence.
// Usage: node scripts/xian_gapfill_render.mjs --url "..." --out results/.../x.html [--wait "text=¥"] [--ms 6000]
// Prints one JSON line: ok, status, bytes, sha256, path, final_url.
import { chromium } from 'playwright';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? argv[i + 1] : d;
};

const url = arg('url');
const out = arg('out');
const waitMs = Number(arg('ms', '6000'));
const selector = arg('wait', '');

if (!url || !out) {
  console.log(JSON.stringify({ ok: false, error: 'usage: --url --out' }));
  process.exit(2);
}

const abs = resolve(out);
mkdirSync(dirname(abs), { recursive: true });

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const ctx = await browser.newContext({
  locale: 'zh-CN',
  timezoneId: 'Asia/Shanghai',
  viewport: { width: 1366, height: 900 },
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    + '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  extraHTTPHeaders: { 'Accept-Language': 'zh-CN,zh;q=0.9' },
});
const page = await ctx.newPage();
let status = 0;
try {
  const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  status = resp ? resp.status() : 0;
  if (selector) {
    await page.waitForSelector(selector, { timeout: 20000 }).catch(() => {});
  }
  await page.waitForTimeout(waitMs);
  const html = await page.content();
  const buf = Buffer.from(html, 'utf8');
  writeFileSync(abs, buf);
  console.log(JSON.stringify({
    ok: true,
    status,
    bytes: buf.length,
    sha256: createHash('sha256').update(buf).digest('hex'),
    path: abs,
    url,
    final_url: page.url(),
  }));
} catch (exc) {
  console.log(JSON.stringify({ ok: false, status, error: exc.name, detail: String(exc).slice(0, 300), url }));
} finally {
  await browser.close();
}
