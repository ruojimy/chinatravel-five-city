// Reconstruct page 8 table rows using text coordinates.
import fs from "node:fs";

const pdfjs = await import("file:///C:/Users/xiech/Downloads/计算机软件工程概论/.ppt-build/node_modules/pdfjs-dist/legacy/build/pdf.mjs");
const src = "C:/Users/xiech/Downloads/计算机软件工程概论/参考论文/CHINATRAVEL(1).pdf";
const data = new Uint8Array(fs.readFileSync(src));
const doc = await pdfjs.getDocument({ data, useSystemFonts: true }).promise;
const page = await doc.getPage(8);
const content = await page.getTextContent();

const items = content.items
    .filter((it) => it.str && it.str.trim())
    .map((it) => ({ x: it.transform[4], y: it.transform[5], s: it.str.trim() }));

// group rows by y (tolerance 2.5)
const rows = [];
for (const it of items.sort((a, b) => b.y - a.y || a.x - b.x)) {
  let row = rows.find((r) => Math.abs(r.y - it.y) < 2.5);
  if (!row) { row = { y: it.y, cells: [] }; rows.push(row); }
  row.cells.push(it);
}
for (const r of rows) {
  r.cells.sort((a, b) => a.x - b.x);
  console.log(`y=${r.y.toFixed(1)} | ` + r.cells.map((c) => `${c.x.toFixed(0)}:${c.s}`).join("  "));
}
