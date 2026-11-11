// Render Booking search results, accepting the one-off privacy consent if shown.
// Usage: node scripts/xian_gapfill_booking.mjs --url "..." --out path.html [--ms 6000]
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
const abs = resolve(out);
mkdirSync(dirname(abs), { recursive: true });

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const ctx = await browser.newContext({
  locale: 'zh-CN',
  timezoneId: 'Asia/Shanghai',
  viewport: { width: 1400, height: 1000 },
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    + '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
});
const page = await ctx.newPage();
let status = 0;
let consentClicked = false;
try {
  const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  status = resp ? resp.status() : 0;
  await page.waitForTimeout(2500);
  if (/pipl_consent|cookie/i.test(page.url())) {
    for (const sel of ['button:has-text("全部接受")', 'button:has-text("接受")',
      'button:has-text("同意")', 'button:has-text("Accept")', '#onetrust-accept-btn-handler']) {
      const el = page.locator(sel).first();
      if (await el.count()) {
        await el.click({ timeout: 5000 }).catch(() => {});
        consentClicked = true;
        break;
      }
    }
    await page.waitForTimeout(3000);
    if (/searchresults/.test(page.url()) === false) {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
    }
  }
  await page.waitForTimeout(waitMs);
  const html = await page.content();
  const buf = Buffer.from(html, 'utf8');
  writeFileSync(abs, buf);
  console.log(JSON.stringify({
    ok: true, status, consentClicked, bytes: buf.length,
    sha256: createHash('sha256').update(buf).digest('hex'),
    path: abs, final_url: page.url(),
  }));
} catch (exc) {
  console.log(JSON.stringify({ ok: false, status, error: exc.name, detail: String(exc).slice(0, 200) }));
} finally {
  await browser.close();
}
