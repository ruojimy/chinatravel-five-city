/**
 * 美团 / 大众点评 半自动登录（只读、人工过验证）。
 * 用法：node scripts/xian_ota_login.cjs [--wait 1200]
 *   - 打开持久化 Chrome profile，用户在窗口里扫码/登录/人工完成滑块
 *   - 检测到登录态后保存 storageState 到 .secrets/ota_state.json
 *   - 脚本不做任何验证码/滑块/字体加密的自动绕过
 */
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const profile = path.join(ROOT, '.cache_ota', 'profile');
const statePath = path.join(ROOT, '.secrets', 'ota_state.json');
const waitSeconds = (() => {
  const i = process.argv.indexOf('--wait');
  return i > -1 ? Number(process.argv[i + 1]) : 1200;
})();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cookieNames(ctx, url) {
  try {
    return (await ctx.cookies(url)).map((c) => c.name).filter(Boolean).sort();
  } catch {
    return [];
  }
}

async function hasLoggedUI(page) {
  try {
    const text = await page.evaluate(() => document.body.innerText.slice(0, 6000));
    return /退出登录|我的订单|个人中心|我的点评|我的收藏|账号设置/.test(text);
  } catch {
    return false;
  }
}

(async () => {
  fs.mkdirSync(profile, { recursive: true });
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  const ctx = await chromium.launchPersistentContext(profile, {
    headless: false,
    channel: process.env.PW_CHANNEL || 'chrome',
    viewport: { width: 1360, height: 920 },
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const first = ctx.pages()[0] || (await ctx.newPage());
  await first.goto('https://www.dianping.com/xian/ch10',
    { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
  const second = await ctx.newPage();
  await second.goto('https://www.meituan.com/',
    { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
  console.log('BROWSER_OPENED 大众点评 + 美团 两个标签页');
  console.log('请在窗口里扫码/登录；若出现滑块验证，请人工完成。脚本不会自动过验证。');

  const deadline = Date.now() + waitSeconds * 1000;
  let saved = false;
  while (Date.now() < deadline) {
    const dNames = await cookieNames(ctx, 'https://www.dianping.com');
    const mNames = await cookieNames(ctx, 'https://www.meituan.com');
    const dCookie = dNames.includes('dper');
    const dUI = await hasLoggedUI(first);
    const mUI = await hasLoggedUI(second);
    if (dCookie || dUI || mUI) {
      await ctx.storageState({ path: statePath });
      fs.writeFileSync(
        statePath.replace(/\.json$/, '.meta.json'),
        JSON.stringify({
          saved_at: new Date().toISOString(),
          login_signal: { dianping_dper: dCookie, dianping_ui: dUI, meituan_ui: mUI },
          dianping_cookie_names: dNames,
          meituan_cookie_names: mNames,
          note: '仅记录 cookie 名称，不记录值；登录态数据只用于低速只读试点',
        }, null, 1)
      );
      console.log(`LOGIN_OK dper=${dCookie} dp_ui=${dUI} mt_ui=${mUI} state=${statePath}`);
      saved = true;
      break;
    }
    await sleep(5000);
  }
  if (!saved) console.log('LOGIN_TIMEOUT 未完成登录；窗口保留，完成后重跑本脚本');
  await sleep(1000);
  await ctx.close().catch(() => {});
  process.exit(saved ? 0 : 2);
})();
