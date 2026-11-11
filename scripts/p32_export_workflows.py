"""Export the two subagent workflow scripts (as run) for audit.

The prompts are read from results/p32_llm_96/prompts/*.txt and embedded as JS string
literals; the workflow body mirrors the calls made through the harness workflow tool.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P32 = ROOT / "results/p32_llm_96"
OUT = ROOT / "scripts/p32_workflows"
OUT.mkdir(exist_ok=True)

STATIC_BODY = """
const base = "results/p32_llm_96";
const uids = args.uids || (() => {
  const out = [];
  for (const p of ["E", "D", "N"]) for (let i = 1; i <= 32; i++) out.push(p + String(i).padStart(2, "0"));
  return out;
})();
const chunkSize = 6;

const TEMPLATE = %s;

function promptFor(uid) {
  return TEMPLATE
      .split("{PACK}").join(`${base}/packs/${uid}_static.json`)
      .split("{OUT}").join(`${base}/out/${uid}_static.json`)
      .split("{UID}").join(uid);
}

phase("static");
const results = [];
for (let i = 0; i < uids.length; i += chunkSize) {
  const group = uids.slice(i, i + chunkSize);
  const part = await parallel(group.map((uid) => async () => {
    const text = await agent(promptFor(uid), { label: `${uid} static`, phase: "static" });
    return { uid, ok: !!text, text: text || null };
  }));
  results.push(...part);
  log(`static ${Math.min(i + chunkSize, uids.length)}/${uids.length}`);
}
return {done: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).map(r => r.uid)};
"""

FINAL_BODY = """
const base = "results/p32_llm_96";
const uids = args.uids || (() => {
  const out = [];
  for (const p of ["E", "D", "N"]) for (let i = 1; i <= 32; i++) out.push(p + String(i).padStart(2, "0"));
  return out;
})();
const chunkSize = 6;

const TEMPLATE = %s;

function promptFor(uid) {
  return TEMPLATE
      .split("{PACK}").join(`${base}/packs/${uid}_final.json`)
      .split("{STATIC}").join(`${base}/out/${uid}_static.json`)
      .split("{OUT}").join(`${base}/out/${uid}_final.json`)
      .split("{UID}").join(uid);
}

phase("final");
const results = [];
for (let i = 0; i < uids.length; i += chunkSize) {
  const group = uids.slice(i, i + chunkSize);
  const part = await parallel(group.map((uid) => async () => {
    const text = await agent(promptFor(uid), { label: `${uid} final`, phase: "final" });
    return { uid, ok: !!text, text: text || null };
  }));
  results.push(...part);
  log(`final ${Math.min(i + chunkSize, uids.length)}/${uids.length}`);
}
return {done: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).map(r => r.uid)};
"""


def main():
    for name, body in (("static", STATIC_BODY), ("final", FINAL_BODY)):
        prompt = (P32 / "prompts" / f"{name}.txt").read_text(encoding="utf-8")
        js = "// Auto-exported from results/p32_llm_96/prompts/%s.txt — run with the harness workflow tool.\n" % name
        js += body % json.dumps(prompt, ensure_ascii=False)
        (OUT / f"p32_workflow_{name}.js").write_text(js, encoding="utf-8")
        print(name, len(js))


if __name__ == "__main__":
    main()
