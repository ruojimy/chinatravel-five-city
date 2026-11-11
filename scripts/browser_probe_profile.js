const { chromium } = require('C:/Users/xiech/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');

const OUT = path.join(process.cwd(), 'results', 'xian_gapfill_20261109', 'browser_probe_profile');
fs.mkdirSync(OUT, { recursive: true });
const PROFILE = 'C:/Users/xiech/AppData/Local/Microsoft/Edge/User Data';

const urls = [
  ['meituan_hotel', 'https://hotel.meituan.com/xian/'],
  ['ctrip_list', 'https://hotels.ctrip.com/hotels/list?city=10'],
  ['booking_search', 'https://www.booking.com/searchresults.zh-cn.html?ss=%E8%A5%BF%E5%AE%89&selected_currency=CNY'],
  ['qunar_city', 'https://hotel.qunar.com/city/xian/'],
];

(async () => {
  let ctx;
  try {
    ctx = await chromium.launchPersistentContext(PROFILE, {
      channel: 'msedge',
      headless: false,
      args: ['--disable-blink-features=AutomationControlled'],
      viewport: { width: 1366, height: 900 },
      locale: 'zh-CN',
    });
  } catch (e) {
    console.log(JSON.stringify({ error: `${e.name}: ${e.message}`.slice(0, 500) }));
    process.exit(1);
  }
  for (const [name, url] of urls) {
    const page = await ctx.newPage();
    const rec = { name, url };
    try {
      const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 40000 });
      await page.waitForTimeout(6000);
      rec.status = resp ? resp.status() : null;
      rec.final_url = page.url();
      rec.title = await page.title();
      const text = await page.evaluate(() => document.body ? document.body.innerText : '');
      rec.text_len = text.length;
      rec.has_price = /(¥|￥|CNY)\s*\d+/.test(text);
      rec.login_wall = /登录|验证码|扫码/.test(text.slice(0, 400));
      rec.sample = text.replace(/\s+/g, ' ').slice(0, 200);
      fs.writeFileSync(path.join(OUT, `${name}.html`), await page.content(), 'utf8');
      fs.writeFileSync(path.join(OUT, `${name}.txt`), text, 'utf8');
    } catch (e) {
      rec.error = `${e.name}: ${e.message}`.slice(0, 300);
    }
    console.log(JSON.stringify(rec));
    await page.close();
  }
  await ctx.close();
})();
