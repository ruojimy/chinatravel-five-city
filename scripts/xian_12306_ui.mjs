/**
 * 12306 车次采集（UI 渲染路径）：接口返回的是加密串，改为在查询页触发真实查询后
 * 直接读取渲染表格，DOM 快照作为原文证据。
 * 用法：node scripts/xian_12306_ui.mjs --run results/<run_id> [--dates 1] [--all-stations]
 * 退出码 3 = 会话失效（需要用户重新登录）。
 */
import path from 'node:path';
import fs from 'node:fs';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const STATE = path.join(ROOT, '.secrets', '12306_state.json');

const XI_AN = [['XAY', '西安'], ['EAY', '西安北']];
const OTHERS = [
  ['BJP', '北京'], ['SHH', '上海'], ['NJH', '南京'], ['SZH', '苏州'], ['HZH', '杭州'],
  ['SZQ', '深圳'], ['CDW', '成都'], ['WHN', '武汉'], ['GZQ', '广州'],
];

const arg = (name, fallback) => {
  const i = process.argv.indexOf('--' + name);
  return i > -1 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : fallback;
};
const flag = (name) => process.argv.includes('--' + name);
const isoDate = (offset) => {
  const d = new Date(Date.now() + offset * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

function splitLines(cell) {
  const lines = cell.split('\n').map((s) => s.trim()).filter(Boolean);
  const timeIdx = lines.findIndex((s) => /^\d{2}:\d{2}$/.test(s));
  if (timeIdx < 2) return null;
  const [begin, end] = [lines[timeIdx], lines[timeIdx + 1]];
  const duration = lines[timeIdx + 2];
  const m = /^(\d+):(\d+)$/.exec(duration || '');
  return {
    train: lines[0],
    from: lines[timeIdx - 2],
    to: lines[timeIdx - 1],
    begin,
    end,
    hours: m ? Math.round((Number(m[1]) + Number(m[2]) / 60) * 100) / 100 : null,
  };
}

(async () => {
  const runArg = arg('run', '');
  if (!runArg) { console.log('MISSING_RUN'); process.exit(1); }
  if (!fs.existsSync(STATE)) { console.log('NO_SESSION 先跑 scripts/xian_12306_login.cjs'); process.exit(2); }
  const runDir = path.resolve(ROOT, runArg);
  const days = Number(arg('dates', '1'));
  const stations = flag('all-stations') ? XI_AN : [XI_AN[0]];
  const rawDir = path.join(runDir, 'raw_api');
  const outDir = path.join(runDir, 'staging', 'api_12306ui');
  fs.mkdirSync(rawDir, { recursive: true });
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || 'chrome', headless: true });
  const ctx = await browser.newContext({ storageState: STATE });
  const page = await ctx.newPage();
  await page.goto('https://kyfw.12306.cn/otn/leftTicket/init', { waitUntil: 'domcontentloaded' });

  const items = [];
  const log = [];
  const seen = new Set();
  let sessionDead = false;

  for (let d = 0; d < days && !sessionDead; d++) {
    const date = isoDate(d + 1);
    for (const [code, city] of OTHERS) {
      for (const [xcode, xname] of stations) {
        for (const [from, to, fromName, toName, label] of [
          [xcode, code, xname, city, `${xname}→${city}`],
          [code, xcode, city, xname, `${city}→${xname}`],
        ]) {
          await page.evaluate(({ from, to, fromName, toName, date }) => {
            document.querySelector('#fromStation').value = from;
            document.querySelector('#fromStationText').value = fromName;
            document.querySelector('#toStation').value = to;
            document.querySelector('#toStationText').value = toName;
            document.querySelector('#train_date').value = date;
          }, { from, to, fromName, toName, date }).catch(() => {});
          await page.click('#query_ticket').catch(() => {});
          await page.waitForTimeout(4500);

          const url = page.url();
          if (/login|passport/.test(url)) { sessionDead = true; break; }

          const rows = await page.evaluate(() => {
            const out = [];
            for (const tr of document.querySelectorAll('#queryLeftTable tr')) {
              const td = tr.querySelector('td');
              if (td && td.innerText.trim()) out.push(td.innerText.trim());
            }
            return out;
          });
          if (!rows.length) {
            const body = await page.evaluate(() => document.body.innerText.slice(0, 400));
            if (/登录|验证/.test(body) && !/车次/.test(body)) { sessionDead = true; break; }
          }

          const file = path.join(rawDir, `12306ui_${date}_${from}_${to}.html`);
          fs.writeFileSync(file, await page.content(), 'utf8');
          const rel = path.relative(ROOT, file).split(path.sep).join('/');
          let kept = 0;
          for (const cell of rows) {
            const parsed = splitLines(cell);
            if (!parsed || !/^[GDCZTKYS]\d+/.test(parsed.train)) continue;
            const key = `${date}|${parsed.train}|${parsed.from}|${parsed.to}`;
            if (seen.has(key)) continue;
            seen.add(key);
            kept += 1;
            items.push({
              kind: 'train',
              name: parsed.train,
              aliases: [],
              data: {
                TrainID: parsed.train,
                TrainType: /^[GDC]/.test(parsed.train) ? '高铁' : /^[ZTK]/.test(parsed.train) ? '普速' : null,
                From: parsed.from,
                To: parsed.to,
                BeginTime: parsed.begin,
                EndTime: parsed.end,
                Duration: parsed.hours,
                Cost: null,
              },
              source: {
                url: 'https://kyfw.12306.cn/otn/leftTicket/init',
                publisher: '中国铁路12306',
                authority: 'carrier_published_schedule',
                licence_status: 'public_timetable_session_access',
                trust_status: 'official_operator',
                published_at: null,
                observed_at: null,
              },
              evidence: { raw_path: rel, quote: parsed.train, locator: `${date} ${label} 表格行` },
              notes: `查询页渲染表格快照；接口返回加密串，故以 DOM 为原文；票价不在本表，Cost 留空；查询日期 ${date}`,
            });
          }
          log.push({ date, from, to, fromName, toName, label, rows: rows.length, kept, raw: rel });
        }
      }
    }
  }

  fs.writeFileSync(path.join(outDir, 'items.jsonl'), items.map((i) => JSON.stringify(i)).join('\n') + '\n', 'utf8');
  fs.writeFileSync(path.join(outDir, 'api_log.jsonl'), log.map((l) => JSON.stringify(l)).join('\n') + '\n', 'utf8');
  fs.writeFileSync(path.join(outDir, 'api_summary.json'),
    JSON.stringify({ items: items.length, queries: log.length, session_dead: sessionDead }, null, 1), 'utf8');
  console.log(`OK items=${items.length} queries=${log.length} session_dead=${sessionDead}`);
  await browser.close();
  process.exit(sessionDead ? 3 : 0);
})();
