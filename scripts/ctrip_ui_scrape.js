const { chromium } = require('C:/Users/xiech/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');

const ROOT = process.cwd();
const RUN = path.join(ROOT, 'results', 'xian_gapfill_20261109');
const OUT = path.join(RUN, 'staging', 'ctrip_ui');
const RAW = path.join(RUN, 'raw', 'ctrip_ui');
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(RAW, { recursive: true });

const args = process.argv.slice(2);
const getArg = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const LIMIT = parseInt(getArg('--limit', '5'), 10);
const OFFSET = parseInt(getArg('--offset', '0'), 10);
const WAIT = parseInt(getArg('--wait', '4500'), 10);

const targetsPath = path.join(RUN, 'targets', 'no_candidate.json');
const targets = JSON.parse(fs.readFileSync(targetsPath, 'utf8'));

function norm(s) {
  return (s || '').toLowerCase().replace(/西安/g, '').replace(/[（）()\s·、,，.。\-—_]/g, '');
}
function branchTokens(s) {
  const m = (s || '').match(/[（(]([^）)]+)[）)]/);
  if (!m) return [];
  return m[1].split(/[店路站区县街巷号栋楼]/).map(x => x.trim()).filter(x => x.length >= 2);
}
function matchType(target, card) {
  const tn = norm(target), cn = norm(card);
  if (!tn || !cn) return null;
  if (tn === cn) return 'exact';
  const tb = norm(target.replace(/[（(].*?[）)]/g, ''));
  const cb = norm(card.replace(/[（(].*?[）)]/g, ''));
  if (tb.length >= 4 && tb === cb) {
    const tt = branchTokens(target), ct = branchTokens(card);
    if (tt.length && ct.length) {
      return tt.some(x => ct.some(y => y.includes(x) || x.includes(y))) ? 'base_branch' : null;
    }
    return 'base_exact';
  }
  if (tn.length >= 8 && cn.includes(tn)) return 'contain';
  return null;
}

(async () => {
  const done = new Set();
  const itemsPath = path.join(OUT, 'items.jsonl');
  if (fs.existsSync(itemsPath)) {
    for (const line of fs.readFileSync(itemsPath, 'utf8').split('\n')) {
      if (line.trim()) { try { done.add(JSON.parse(line).name); } catch (e) {} }
    }
  }
  const batch = targets.filter(t => !done.has(t.name)).slice(OFFSET, OFFSET + LIMIT);
  if (!batch.length) { console.log(JSON.stringify({ batch: 0 })); process.exit(0); }

  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  let matched = 0, noMatch = 0;
  const log = (o) => fs.appendFileSync(path.join(OUT, 'run_log.jsonl'), JSON.stringify(o) + '\n', 'utf8');

  for (const t of batch) {
    const q = encodeURIComponent(t.name);
    const url = `https://hotels.ctrip.com/hotels/list?flexType=1&fixedDate=0&cityId=10&provinceId=12&countryId=1&cityName=%E8%A5%BF%E5%AE%89&destName=%E8%A5%BF%E5%AE%89&searchWord=${q}&searchType=&checkin=2026-11-09&checkout=2026-11-10&crn=1&listFilters=29~1*29*1~1*2&curr=CNY&locale=zh-CN&directSearch=1&old=1&v2_mod=25&v2_version=E`;
    let rec = { hotel: t.name, url };
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await page.waitForTimeout(WAIT);
      const cards = await page.evaluate(() => [...document.querySelectorAll('[data-offline-hotelid]')].map(c => {
        const n = c.querySelector('.hotelName');
        const txt = (c.innerText || '').replace(/\s+/g, ' ').trim();
        const prices = [...txt.matchAll(/¥\s*(\d+)/g)].map(m => +m[1]);
        return { id: c.getAttribute('data-offline-hotelid'), name: n ? n.innerText.trim() : null, prices, text: txt };
      }));
      rec.cards = cards.length;
      let hit = null, mt = null;
      for (const c of cards) {
        if (!c.name || !c.prices.length) continue;
        const m = matchType(t.name, c.name);
        if (m) { hit = c; mt = m; break; }
      }
      if (hit) {
        const price = hit.prices[hit.prices.length - 1];
        const quote = `¥${price}`;
        const rawName = `ctrip_ui_${hit.id}_${Date.now()}.html`;
        const rawPath = path.join(RAW, rawName);
        fs.writeFileSync(rawPath, await page.content(), 'utf8');
        const item = {
          kind: 'accommodation', name: t.name, data: { price },
          source: {
            url: page.url(), publisher: '携程',
            authority: 'travel_marketplace_display',
            licence_status: 'public_page_reuse_unverified',
            observed_at: new Date().toISOString(),
          },
          evidence: {
            raw_path: path.relative(ROOT, rawPath).replace(/\\/g, '/'),
            quote, locator: `ctrip_ui_card:${hit.id}`,
            identity_basis: `${mt};card=${hit.name}`,
          },
          notes: `ui_search=${t.name}; card=${hit.name}; hotel_id=${hit.id}`,
        };
        fs.appendFileSync(itemsPath, JSON.stringify(item) + '\n', 'utf8');
        matched++;
        rec.result = 'matched'; rec.card = hit.name; rec.price = price; rec.match = mt;
      } else {
        noMatch++;
        rec.result = 'no_match';
        rec.top = cards.slice(0, 3).map(c => c.name);
      }
    } catch (e) {
      rec.result = 'error'; rec.error = e.message.slice(0, 200);
    }
    log(rec);
    console.log(JSON.stringify(rec));
    await page.waitForTimeout(800);
  }
  await page.close();
  console.log(JSON.stringify({ batch: batch.length, matched, noMatch }));
  process.exit(0);
})();
