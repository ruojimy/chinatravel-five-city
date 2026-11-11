const { chromium } = require('C:/Users/xiech/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');

const OUT = path.join(process.cwd(), 'results', 'xian_gapfill_20261109', 'browser_probe');
fs.mkdirSync(OUT, { recursive: true });

const urls = [
  ['meituan_hotel', 'https://hotel.meituan.com/xian/'],
  ['meituan_main', 'https://www.meituan.com/'],
  ['dianping_hotel', 'https://www.dianping.com/xian/hotel'],
  ['qunar_touch', 'https://touch.qunar.com/hotel/'],
  ['qunar_city', 'https://hotel.qunar.com/city/xian/'],
  ['booking_search', 'https://www.booking.com/searchresults.zh-cn.html?ss=%E8%A5%BF%E5%AE%89&selected_currency=CNY'],
  ['ctrip_list', 'https://hotels.ctrip.com/hotels/list?city=10'],
];

(async () => {
  const browser = await chromium.launch({
    channel: 'msedge',
    headless: false,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const ctx = await browser.newContext({
    locale: 'zh-CN',
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
    viewport: { width: 1366, height: 900 },
  });
  for (const [name, url] of urls) {
    const page = await ctx.newPage();
    let rec = { name, url };
    try {
      const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 35000 });
      await page.waitForTimeout(5000);
      rec.status = resp ? resp.status() : null;
      rec.final_url = page.url();
      rec.title = await page.title();
      const text = await page.evaluate(() => document.body ? document.body.innerText : '');
      rec.text_len = text.length;
      rec.has_price = /(¥|￥|CNY)\s*\d+/.test(text);
      rec.sample = text.replace(/\s+/g, ' ').slice(0, 240);
      const html = await page.content();
      fs.writeFileSync(path.join(OUT, `${name}.html`), html, 'utf8');
      fs.writeFileSync(path.join(OUT, `${name}.txt`), text, 'utf8');
    } catch (e) {
      rec.error = `${e.name}: ${e.message}`.slice(0, 300);
    }
    console.log(JSON.stringify(rec));
    await page.close();
  }
  await browser.close();
})();
