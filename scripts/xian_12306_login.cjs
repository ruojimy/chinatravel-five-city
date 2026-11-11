/**
 * 12306 会话检测/保存：复用同一个持久化 profile，验证会话真的能查票后再存 storageState。
 * 用法：node scripts/xian_12306_login.cjs [--wait 300]
 *   退出码 0 = 已登录并保存；2 = 未登录（窗口保留给用户操作，超时后退出）。
 */
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const profile = path.join(ROOT, '.cache_12306', 'profile');
const statePath = path.join(ROOT, '.secrets', '12306_state.json');
const LOGIN_URL = 'https://kyfw.12306.cn/otn/leftTicket/init';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const waitSeconds = (() => {
  const i = process.argv.indexOf('--wait');
  return i > -1 ? Number(process.argv[i + 1]) : 300;
})();

function isoDate(offset) {
  const d = new Date(Date.now() + offset * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function probe(page) {
  // 在页面上下文里直接打余票接口，能拿到 result 数组才算真的登录可用
  return page.evaluate(async (date) => {
    for (const ep of ['queryZ', 'queryA', 'query']) {
      try {
        const r = await fetch(`/otn/leftTicket/${ep}?leftTicketDTO.train_date=${date}`
          + '&leftTicketDTO.from_station=XAY&leftTicketDTO.to_station=BJP&purpose_codes=ADULT',
          { credentials: 'include' });
        const t = await r.text();
        let j = null;
        try { j = JSON.parse(t); } catch { /* login page */ }
        if (j && Array.isArray(j?.data?.result)) {
          return { ok: true, endpoint: ep, rows: j.data.result.length, status: j.httpstatus };
        }
      } catch { /* try next */ }
    }
    return { ok: false };
  }, isoDate(1));
}

(async () => {
  fs.mkdirSync(profile, { recursive: true });
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  const ctx = await chromium.launchPersistentContext(profile, {
    headless: false,
    channel: process.env.PW_CHANNEL || 'chrome',
    viewport: { width: 1280, height: 900 },
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  if (!page.url().startsWith('https://kyfw.12306.cn')) {
    await page.goto(LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
  }

  const cookies = await ctx.cookies('https://kyfw.12306.cn');
  const names = cookies.map((c) => c.name).sort();
  console.log('COOKIES ' + names.join(','));
  console.log('TK_PRESENT ' + names.includes('tk'));

  const deadline = Date.now() + waitSeconds * 1000;
  let saved = false;
  while (Date.now() < deadline) {
    const result = await probe(page).catch(() => ({ ok: false }));
    if (result.ok) {
      await ctx.storageState({ path: statePath });
      fs.writeFileSync(
        statePath.replace(/\.json$/, '.meta.json'),
        JSON.stringify({
          saved_at: new Date().toISOString(),
          endpoint: result.endpoint,
          sample_rows: result.rows,
          cookie_names: (await ctx.cookies('https://kyfw.12306.cn')).map((c) => c.name).sort(),
        }, null, 1)
      );
      console.log(`LOGIN_OK endpoint=${result.endpoint} rows=${result.rows} state=${statePath}`);
      saved = true;
      break;
    }
    await sleep(5000);
  }
  if (!saved) console.log('LOGIN_TIMEOUT 窗口保留中，完成登录后重跑本脚本');
  await sleep(1000);
  await ctx.close().catch(() => {});
  process.exit(saved ? 0 : 2);
})();
