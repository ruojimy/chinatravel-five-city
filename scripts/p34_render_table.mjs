// Render page 8 of the paper to PNG for visual table reading.
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire("C:/Users/xiech/Downloads/计算机软件工程概论/.ppt-build/node_modules/");
const { createCanvas } = require("@napi-rs/canvas");

const pdfjs = await import("file:///C:/Users/xiech/Downloads/计算机软件工程概论/.ppt-build/node_modules/pdfjs-dist/legacy/build/pdf.mjs");
const src = "C:/Users/xiech/Downloads/计算机软件工程概论/参考论文/CHINATRAVEL(1).pdf";
const data = new Uint8Array(fs.readFileSync(src));
const doc = await pdfjs.getDocument({ data, useSystemFonts: true }).promise;
const page = await doc.getPage(8);
const viewport = page.getViewport({ scale: 2.6 });
const canvas = createCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
const ctx = canvas.getContext("2d");
await page.render({ canvasContext: ctx, viewport }).promise;
const out = "C:/Users/xiech/Downloads/计算机软件工程概论/reproduction/results/p33_native_planner/paper_table3.png";
fs.writeFileSync(out, canvas.toBuffer("image/png"));
console.log("wrote", out, canvas.width, canvas.height);
