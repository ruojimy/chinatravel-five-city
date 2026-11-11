// Render a series of public list pages (headless Chrome) and dump each DOM to raw/, with 3s spacing.
// Usage: node scripts/xian_gapfill_render_many.mjs --tmpl "https://hk.trip.com/hotels/list?city=10&locale=zh-CN&curr=CNY&pageIndex={p}" \
//        --outdir results/xian_gapfill_20261109/raw/hotel2 --prefix trip_list --from 1 --to 12
// Prints one JSON line per page.
import { chromium } from 'playwright';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? argv[i + 1] : d;
};

const tmpl = arg('tmpl');
const outdir = arg('outdir');
const prefix = arg('prefix', 'page');
const from = Number(arg('from', '1'));
const to = Number(arg('to', '1'));
const gap = Number(arg('gap', '3000'));
const waitMs = Number(arg('ms', '7000'));

if (!tmpl || !outdir) {
  console.log(JSON.stringify({ ok: false, error: 'usage: --tmpl --outdir --from --to' }));
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const ctx = await browser.newContext({
  locale: 'zh-CN',
  timezoneId: 'Asia/Shanghai',
  viewport: { width: 1400, height: 1000 },
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    + '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  extraHTTPHeaders: { 'Accept-Language': 'zh-CN,zh;q=0.9' },
});
const page = await ctx.newPage();

for (let p = from; p <= to; p += 1) {
  const url = tmpl.replace('{p}', String(p));
  const out = resolve(outdir, `${prefix}_p${p}.html`);
  mkdirSync(dirname(out), { recursive: true });
  let status = 0;
  try {
    const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    status = resp ? resp.status() : 0;
    await page.waitForTimeout(waitMs);
    const html = await page.content();
    const buf = Buffer.from(html, 'utf8');
    writeFileSync(out, buf);
    console.log(JSON.stringify({
      ok: true, page: p, status, bytes: buf.length,
      sha256: createHash('sha256').update(buf).digest('hex'),
      path: out, url, final_url: page.url(),
    }));
  } catch (exc) {
    console.log(JSON.stringify({ ok: false, page: p, status, error: exc.name, detail: String(exc).slice(0, 200), url }));
  }
  await sleep(gap);
}

await browser.close();
