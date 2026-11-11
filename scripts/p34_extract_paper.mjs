// Extract text from the ChinaTravel paper and locate the results table.
import { createRequire } from "node:module";
import fs from "node:fs";

const require = createRequire("C:/Users/xiech/Downloads/计算机软件工程概论/.ppt-build/node_modules/");
const pdfjs = await import("file:///C:/Users/xiech/Downloads/计算机软件工程概论/.ppt-build/node_modules/pdfjs-dist/legacy/build/pdf.mjs");

const src = "C:/Users/xiech/Downloads/计算机软件工程概论/参考论文/CHINATRAVEL(1).pdf";
const out = "C:/Users/xiech/Downloads/计算机软件工程概论/reproduction/results/p33_native_planner/paper_text.txt";
const data = new Uint8Array(fs.readFileSync(src));
const doc = await pdfjs.getDocument({ data, useSystemFonts: true }).promise;
const pages = [];
for (let i = 1; i <= doc.numPages; i++) {
  const page = await doc.getPage(i);
  const content = await page.getTextContent();
  const text = content.items.map((it) => it.str).join(" ");
  pages.push(`\n===== PAGE ${i} =====\n${text}`);
}
fs.writeFileSync(out, pages.join(""), "utf8");
console.log("pages", doc.numPages, "chars", pages.join("").length);
for (let i = 0; i < pages.length; i++) {
  if (/RuleNeSy|LLMNeSy|Rule[Nn]eSy|All[- ]?pass|LPR/.test(pages[i])) {
    console.log("HIT page", i + 1, pages[i].slice(0, 200).replace(/\s+/g, " "));
  }
}
