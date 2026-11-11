/**
 * 12306 车次采集：复用已登录的 storageState，抓西安 ↔ 9 个原版城市的双向车次。
 * 用法：NODE_PATH=<playwright node_modules> node scripts/xian_12306_query.mjs --run results/<run_id> [--dates 3]
 * 会话失效（返回非 0 或跳登录）时退出码 3，提示重新登录；不尝试任何验证码绕过。
 */
import path from 'node:path';
import fs from 'node:fs';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const ROOT = path.resolve(__dirname, '..');
const STATE = path.join(ROOT, '.secrets', '12306_state.json');

// 西安两个主要车站 + 9 个原版城市主站
const XI_AN = [['XAY', '西安'], ['EAY', '西安北']];
const OTHERS = [
  ['BJP', '北京'], ['SHH', '上海'], ['NJH', '南京'], ['SZH', '苏州'], ['HZH', '杭州'],
  ['SZQ', '深圳'], ['CDW', '成都'], ['WHN', '武汉'], ['GZQ', '广州'],
];

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

function isoDate(offsetDays) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function parseDuration(text) {
  const m = /^(\d+):(\d+)$/.exec(text || '');
  return m ? Math.round((Number(m[1]) + Number(m[2]) / 60) * 100) / 100 : null;
}

async function stationMap(request) {
  const res = await request.get('https://kyfw.12306.cn/otn/resources/js/framework/station_name.js');
  const body = await res.text();
  const map = new Map();
  for (const chunk of body.split('@')) {
    const parts = chunk.split('|');
    if (parts.length >= 3 && parts[2]) map.set(parts[2], parts[1]);
  }
  return map;
}

async function query(request, from, to, date, endpoint) {
  const url = `https://kyfw.12306.cn/otn/leftTicket/${endpoint}?leftTicketDTO.train_date=${date}`
    + `&leftTicketDTO.from_station=${from}&leftTicketDTO.to_station=${to}&purpose_codes=ADULT`;
  const res = await request.get(url, { headers: { Referer: 'https://kyfw.12306.cn/otn/leftTicket/init' } });
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { /* html login page */ }
  return { url, text, data };
}

(async () => {
  const runDir = path.resolve(ROOT, arg('run', ''));
  const days = Number(arg('dates', '3'));
  if (!arg('run', '')) { console.log('MISSING_RUN'); process.exit(1); }
  if (!fs.existsSync(STATE)) { console.log('NO_SESSION 请先运行 scripts/xian_12306_login.cjs 登录'); process.exit(2); }

  const rawDir = path.join(runDir, 'raw_api');
  const outDir = path.join(runDir, 'staging', 'api_12306');
  fs.mkdirSync(rawDir, { recursive: true });
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || 'chrome', headless: true });
  const ctx = await browser.newContext({ storageState: STATE });
  const request = ctx.request;
  const stations = await stationMap(request);

  let endpoint = null;
  const dates = Array.from({ length: days }, (_, i) => isoDate(i + 1));
  const items = [];
  const log = [];
  const seen = new Set();

  for (const date of dates) {
    for (const [code, city] of OTHERS) {
      for (const [xcode, xname] of XI_AN) {
        for (const [from, to, label] of [[xcode, code, `${xname}→${city}`], [code, xcode, `${city}→${xname}`]]) {
          if (!endpoint) {
            for (const candidate of ['queryZ', 'queryA', 'query']) {
              const probe = await query(request, from, to, date, candidate);
              if (probe.data && Array.isArray(probe.data?.data?.result)) { endpoint = candidate; }
              log.push({ date, from, to, candidate, ok: Boolean(probe.data?.data?.result), code: probe.data?.httpstatus });
              if (endpoint) break;
            }
            if (!endpoint) { console.log('SESSION_INVALID 需重新登录'); await browser.close(); process.exit(3); }
          }
          const { url, text, data } = await query(request, from, to, date, endpoint);
          const rows = data?.data?.result || [];
          const file = path.join(rawDir, `12306_${date}_${from}_${to}.json`);
          fs.writeFileSync(file, text, 'utf8');
          const rel = path.relative(ROOT, file).split(path.sep).join('/');
          for (const row of rows) {
            const f = row.split('|');
            const trainId = f[3];
            if (!trainId || seen.has(`${date}|${trainId}|${f[6]}|${f[7]}`)) continue;
            seen.add(`${date}|${trainId}|${f[6]}|${f[7]}`);
            const fromName = stations.get(f[6]) || f[6];
            const toName = stations.get(f[7]) || f[7];
            items.push({
              kind: 'train',
              name: trainId,
              aliases: [],
              data: {
                TrainID: trainId,
                TrainType: /^[GDC]/.test(trainId) ? '高铁' : /^[ZTK]/.test(trainId) ? '普速' : null,
                From: fromName,
                To: toName,
                BeginTime: f[8],
                EndTime: f[9],
                Duration: parseDuration(f[10]),
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
              evidence: { raw_path: rel, quote: trainId, locator: `${date} ${label} ${f[6]}->${f[7]}` },
              notes: `余票接口 ${endpoint}；票价不由该接口提供，Cost 留空；查询日期 ${date}`,
            });
          }
          log.push({ date, from, to, endpoint, rows: rows.length, raw: rel });
        }
      }
    }
  }

  fs.writeFileSync(path.join(outDir, 'items.jsonl'), items.map((i) => JSON.stringify(i)).join('\n') + '\n', 'utf8');
  fs.writeFileSync(path.join(outDir, 'api_log.jsonl'), log.map((l) => JSON.stringify(l)).join('\n') + '\n', 'utf8');
  fs.writeFileSync(path.join(outDir, 'api_summary.json'), JSON.stringify({
    endpoint, dates, items: items.length, calls: log.length,
  }, null, 1), 'utf8');
  console.log('OK items=' + items.length + ' calls=' + log.length + ' endpoint=' + endpoint);
  await browser.close();
})();
