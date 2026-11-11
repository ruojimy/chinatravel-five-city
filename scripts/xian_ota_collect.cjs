/**
 * 美团 / 大众点评 登录后「低速只读」试点采集。
 * 用法：node scripts/xian_ota_collect.cjs --run results/<run_id> --platform dianping|meituan --names <utf8 文件> --kind restaurant --limit 10
 *
 * 边界（不可放宽）：
 *   - 只复用用户自己登录的 storageState，不做任何验证码/滑块/字体加密的自动绕过
 *   - 每次请求间隔 >= 3 秒，单轮 <= limit 个实体
 *   - 只保存渲染后的 DOM 快照作原文，不调用私有接口
 *   - 全部条目标 reference_only / provider_terms_pending_review
 *   - 出现验证页立即停止并记录，不重试、不换 UA、不换账号
 */
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const STATE = path.join(ROOT, '.secrets', 'ota_state.json');
const HOME = {
  dianping: 'https://www.dianping.com/xian/ch10',
  meituan: 'https://www.meituan.com/',
};

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--')
    ? process.argv[i + 1] : fallback;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const runDir = path.resolve(ROOT, arg('run', ''));
  const platform = arg('platform', 'dianping');
  const namesFile = arg('names', '');
  const kind = arg('kind', 'restaurant');
  const limit = Number(arg('limit', '10'));
  if (!arg('run', '') || !namesFile) { console.log('MISSING_ARGS'); process.exit(1); }
  if (!fs.existsSync(STATE)) { console.log('NO_SESSION 请先登录'); process.exit(2); }

  const namesPath = path.isAbsolute(namesFile) ? namesFile : path.join(ROOT, namesFile);
  const names = fs.readFileSync(namesPath, 'utf8').split(/\r?\n/)
    .map((s) => s.trim()).filter(Boolean).slice(0, limit);
  const rawDir = path.join(runDir, 'raw_ota');
  const outDir = path.join(runDir, 'staging', `ota_${platform}`);
  fs.mkdirSync(rawDir, { recursive: true });
  fs.mkdirSync(outDir, { recursive: true });

  // 复用用户已登录的持久化 profile + 有头浏览器（headless 新 context 会触发点选验证）
  const ctx = await chromium.launchPersistentContext(path.join(ROOT, '.cache_ota', 'profile'), {
    headless: false, channel: 'chrome', viewport: { width: 1280, height: 860 },
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  const items = [];
  const log = [];
  let blocked = false;

  for (const name of names) {
    await page.goto(HOME[platform], { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
    const body = await page.evaluate(() => document.body.innerText.slice(0, 3000)).catch(() => '');
    if (/身份核实|请拖动|滑块|安全验证|captcha/i.test(body)) {
      log.push({ name, ok: false, reason: 'verification_page_user_action_required' });
      blocked = true;
      break;
    }
    // 在页面里用搜索框输入实体名（不构造私有接口）
    const box = await page.$('input[placeholder*="搜索商户名"], input[placeholder*="搜索"]');
    if (!box) {
      log.push({ name, ok: false, reason: 'search_input_not_found' });
    } else {
      await box.fill(name).catch(() => {});
      await box.press('Enter').catch(() => {});
      await page.waitForTimeout(4000);
      // 只进入名称匹配的结果卡片，避免把推荐位商户张冠李戴
      const candidates = await page.evaluate(() =>
        [...document.querySelectorAll('a[href*="/shop/"]')].map((a) => ({
          href: a.href, text: (a.innerText || '').trim().slice(0, 120),
        }))).catch(() => []);
      const match = candidates.find((c) => c.text && (c.text.includes(name) || name.includes(c.text)));
      let shop = false;
      if (match) {
        await page.goto(match.href, { waitUntil: 'domcontentloaded', timeout: 40000 }).catch(() => {});
        await page.waitForTimeout(4000);
        shop = true;
      }
      const after = await page.evaluate(() => document.body.innerText.slice(0, 3000)).catch(() => '');
      if (/身份核实|请拖动|滑块|安全验证/i.test(after)) {
        log.push({ name, ok: false, reason: 'verification_page_after_search' });
        blocked = true;
        break;
      }
      const text = await page.evaluate(() => document.body.innerText.slice(0, 30000)).catch(() => '');
      const hours = /(\d{2}:\d{2})\s*[-~至]\s*(\d{2}:\d{2})/.exec(text);
      const start = /(\d{2}:\d{2})\s*开始营业/.exec(text);
      const price = /人均\s*[¥￥]?\s*(\d+(?:\.\d+)?)/.exec(text);
      const cuisine = /(川菜|陕菜|西北菜|火锅|烧烤|小吃快餐|清真|日料|粤菜|湘菜|面馆|家常菜)/.exec(text);
      const file = path.join(rawDir, `ota_${platform}_${log.length}_${Date.now()}.html`);
      fs.writeFileSync(file, await page.content(), 'utf8');
      const rel = path.relative(ROOT, file).split(path.sep).join('/');
      const data = {};
      if (hours && Number(hours[1].slice(0, 2)) < 24 && Number(hours[2].slice(0, 2)) < 24) {
        data.opentime = hours[1]; data.endtime = hours[2];
      } else if (start && Number(start[1].slice(0, 2)) < 24) {
        data.opentime = start[1]; // 详情页只给「开始营业」，endtime 保持 null，不估算
      }
      if (cuisine) data.cuisine = cuisine[1];
      const rawText = fs.readFileSync(file, 'utf8');
      if (Object.keys(data).length && shop && rawText.includes(name)) {
        items.push({
          kind, name, aliases: [], data,
          source: {
            url: HOME[platform], publisher: platform === 'dianping' ? '大众点评' : '美团',
            authority: 'travel_marketplace_display',
            licence_status: 'provider_terms_pending_review',
            trust_status: 'reference_only', published_at: null, observed_at: null,
          },
          evidence: { raw_path: rel, quote, locator: '登录态渲染页 innerText' },
          notes: `登录后低速只读试点；页面可见文本提取，未破解字体/接口加密；人均文本=${price ? price[0] : '不可读'}；许可状态待审`,
        });
      }
      log.push({ name, ok: Object.keys(data).length > 0, fields: Object.keys(data),
                 price_readable: Boolean(price), shop_page: Boolean(shop), raw_path: rel });
    }
    await sleep(3000);
  }

  fs.writeFileSync(path.join(outDir, 'enrich_ota.jsonl'),
    items.map((i) => JSON.stringify(i)).join('\n') + '\n', 'utf8');
  fs.writeFileSync(path.join(outDir, 'api_log.jsonl'),
    log.map((l) => JSON.stringify(l)).join('\n') + '\n', 'utf8');
  console.log(JSON.stringify({ platform, attempted: names.length, items: items.length,
    blocked, out: path.relative(ROOT, path.join(outDir, 'enrich_ota.jsonl')).split(path.sep).join('/') }, null, 1));
  await ctx.close().catch(() => {});
  process.exit(blocked ? 3 : 0);
})();
