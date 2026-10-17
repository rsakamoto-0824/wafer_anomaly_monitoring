// Wafer 面内傾向の異常検知・経時変化監視の比較検証 ― 結果の説明資料（PowerPoint）を pptxgenjs で生成する。
// 使い方: NODE_PATH="$(npm root -g)" node build_deck.js <出力パス>
// 前提: deck_data.json（prepare_data.py の出力）と formulas/（render_formulas.py の出力）が同じフォルダにあり、
//       ../../results/figures/ に計算結果の図がある。
// 見た目は「技術レポートPowerPoint」テンプレート（濃紺の表紙とまとめ、白地の本文）に合わせる。

const path = require('path');
const fs = require('fs');
const pptxgen = require('pptxgenjs');

const BASE_DIR = __dirname;
const OUTPUT_PATH = process.argv[2] || path.join(BASE_DIR, 'deck_raw.pptx');
const FIGURE_DIR = path.join(BASE_DIR, '..', '..', 'results', 'figures');
const D = JSON.parse(fs.readFileSync(path.join(BASE_DIR, 'deck_data.json'), 'utf8'));
const formulaSizes = JSON.parse(fs.readFileSync(path.join(BASE_DIR, 'formulas', 'formulas.json'), 'utf8'));

// ---- 定数 ----
const SLIDE_W = 13.333;
const SLIDE_H = 7.5;
const MARGIN_X = 0.6;
const CONTENT_W = SLIDE_W - MARGIN_X * 2;
const FONT = 'BIZ UDGothic';
const DECK_TITLE = 'Wafer面内傾向の異常検知・経時変化監視の手法比較';
const DECK_DATE = '2026年10月13日';
const TITLE_FONT_PT = 26;
const TITLE_MIN_FONT_PT = 22;

// 手法の色は、技術レポートの図と同じ意味にそろえる（M3S＝灰、係数SPC＝青、Mahalanobis＝橙、T²＝緑、SPE＝黄、GPR＝桃、EWMA＝深緑、CUSUM＝紫、OR＝赤）
const C = {
  night: '1C1B3A',
  indigo: '2F3470',
  indigoLight: '9EA5E0',
  tint: 'EEEFF7',
  ink: '1E1C33',
  muted: '5E6275',
  line: 'B9BDD0',
  grid: 'E4E6EF',
  gray: 'F2F3F7',
  neutral: '8A8FA8',
  white: 'FFFFFF',
  onDarkSub: 'CDD0EA',
  good: '178F6C',
  goodTint: 'D8F0E7',
  bad: 'C2413B',
  badTint: 'F8E0DE',
  warnTint: 'FBF0D3',
};
const FAMILY = {
  M1: { color: '52514E', tint: 'E9E8E4', name: 'M3S' },
  M2: { color: '2A78D6', tint: 'DCEAF9', name: '係数SPC' },
  M3: { color: 'D9612F', tint: 'FBE5DA', name: 'Mahalanobis' },
  M4: { color: '178F6C', tint: 'D8F0E7', name: 'PCA T²' },
  M5: { color: 'C98A00', tint: 'FBF0D3', name: 'PCA SPE' },
  M6: { color: 'C24F7E', tint: 'F7E1EA', name: 'GPR残差' },
  M7: { color: '0E6B0E', tint: 'DCEFDC', name: 'EWMA' },
  M8: { color: '4A3AA7', tint: 'E6E3F6', name: 'CUSUM' },
  OR: { color: 'C2413B', tint: 'F8E0DE', name: 'OR統合' },
};

const V = (key) => {
  const item = D.v[key];
  if (!item) throw new Error(`report_values にキーがありません: ${key}`);
  return item.text;
};
const R = (key) => D.v[key].raw;
const f1 = (v) => v.toFixed(1);
const f2 = (v) => v.toFixed(2);
const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;

const familyOf = (name) => {
  if (name.startsWith('OR')) return 'OR';
  if (name.includes('|EWMA')) return 'M7';
  if (name.includes('|CUSUM')) return 'M8';
  for (const [prefix, family] of [['M3S', 'M1'], ['SPC', 'M2'], ['MD', 'M3'], ['T2', 'M4'], ['SPE', 'M5'], ['GPR', 'M6']]) {
    if (name.startsWith(prefix)) return family;
  }
  return 'M1';
};
const baseFamily = (detector) => familyOf(detector.split('|')[0]);
const schemeLabel = (detector) => {
  if (detector.includes('|EWMA')) return `EWMA（λ=${detector.match(/λ=([\d.]+)/)[1]}）`;
  if (detector.includes('|CUSUM')) return `CUSUM（k=${detector.match(/k=([\d.]+)/)[1]}）`;
  return 'Shewhart';
};
const BASE_LABEL = {
  M3S_XY: 'M3S', SPC_d4: '係数SPC（4次）', MD_d5: 'Mahalanobis（5次）', T2_raw_q99: 'PCA T²（99%）',
  SPE_raw_q99: 'PCA SPE（99%）', GPR_rbf_full: 'GPR残差',
};
const detectorLabel = (detector) => `${BASE_LABEL[detector.split('|')[0]] || detector.split('|')[0]}・${schemeLabel(detector)}`;

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.author = 'Claude Code';
pres.title = DECK_TITLE;
pres.lang = 'ja-JP';

let pageNumber = 0;

// ---- 文字の補助関数 ----

// "x_{1}" を下付き、"x^{2}" を上付きのランに変換する
function parseRich(text, baseOptions = {}) {
  const runs = [];
  const pattern = /([_^])\{([^}]*)\}/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) runs.push({ text: text.slice(last, match.index), options: { ...baseOptions } });
    const key = match[1] === '_' ? 'subscript' : 'superscript';
    runs.push({ text: match[2], options: { ...baseOptions, [key]: true } });
    last = pattern.lastIndex;
  }
  if (last < text.length) runs.push({ text: text.slice(last), options: { ...baseOptions } });
  return runs;
}

function toRuns(item, baseOptions = {}) {
  if (typeof item === 'string') return parseRich(item, baseOptions);
  if (Array.isArray(item)) return item.flatMap((part) => toRuns(part, baseOptions));
  const { text, breakLine, ...rest } = item;
  const runs = parseRich(text, { ...baseOptions, ...rest });
  if (breakLine && runs.length) runs[runs.length - 1].options.breakLine = true;
  return runs;
}

function addText(slide, content, x, y, w, h, options = {}) {
  const plain = typeof content === 'string' && !/[_^]\{/.test(content);
  slide.addText(plain ? content : toRuns(content), {
    x, y, w, h,
    fontFace: FONT, fontSize: 15, color: C.ink, margin: 0, valign: 'top',
    isTextBox: true, lang: 'ja-JP',
    ...options,
  });
}

function paragraphs(items, { bullet = true, space = 8, indent = 16, color, fontSize, bold } = {}) {
  const runs = [];
  items.forEach((item, index) => {
    const base = {};
    if (color) base.color = color;
    if (fontSize) base.fontSize = fontSize;
    if (bold) base.bold = true;
    const itemRuns = toRuns(item, base);
    itemRuns.forEach((run, j) => {
      if (j === 0) {
        run.options.bullet = bullet ? { indent } : false;
        run.options.paraSpaceAfter = space;
      }
      if (j === itemRuns.length - 1 && index < items.length - 1) run.options.breakLine = true;
    });
    runs.push(...itemRuns);
  });
  return runs;
}

function addBullets(slide, items, x, y, w, h, options = {}) {
  const { bullet, space, indent, ...textOptions } = options;
  slide.addText(paragraphs(items, { bullet, space, indent, color: textOptions.color, fontSize: textOptions.fontSize }), {
    x, y, w, h,
    fontFace: FONT, fontSize: 15, color: C.ink, margin: 0, valign: 'top',
    isTextBox: true, lang: 'ja-JP',
    ...textOptions,
  });
}

function withBreaks(lines) {
  return lines.map((line, j) => ({ text: line, breakLine: j < lines.length - 1 }));
}

// ---- 図形の補助関数 ----

function addCard(slide, x, y, w, h, { fill = C.tint, line, radius = 0.1, shadow = false } = {}) {
  const options = {
    x, y, w, h, rectRadius: radius,
    fill: { color: fill },
    line: line ? { color: line, width: 1 } : { color: fill, width: 0.5 },
  };
  if (shadow) options.shadow = { type: 'outer', color: '000000', opacity: 0.12, blur: 6, offset: 2, angle: 90 };
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, options);
}

// 始点・終点から、正の長さと回転角で線を描く（負の幅・高さを使わない）
function addLine(slide, x1, y1, x2, y2, { color = C.line, width = 1.5, dash, arrow = false } = {}) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.hypot(dx, dy);
  let angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  if (angle < 0) angle += 360;
  const lineOptions = { color, width };
  if (dash) lineOptions.dashType = dash;
  if (arrow) lineOptions.endArrowType = 'triangle';
  slide.addShape(pres.shapes.LINE, {
    x: (x1 + x2) / 2 - length / 2, y: (y1 + y2) / 2, w: length, h: 0,
    rotate: angle, line: lineOptions,
  });
}

function addNode(slide, cx, cy, diameter, fill, label, { color = C.white, fontSize = 16, lineColor } = {}) {
  slide.addShape(pres.shapes.OVAL, {
    x: cx - diameter / 2, y: cy - diameter / 2, w: diameter, h: diameter,
    fill: { color: fill }, line: { color: lineColor || fill, width: lineColor ? 1.25 : 0.5 },
  });
  if (label) {
    addText(slide, label, cx - diameter / 2, cy - diameter / 2, diameter, diameter, {
      align: 'center', valign: 'middle', fontSize, bold: true, color,
    });
  }
}

function formulaSize(key, scale = 1) {
  const size = formulaSizes[key];
  if (!size) throw new Error(`数式画像がありません: ${key}`);
  return { w: size.w * scale, h: size.h * scale };
}

function addFormula(slide, key, x, y, { scale = 1, alt = '' } = {}) {
  const size = formulaSize(key, scale);
  slide.addImage({ path: path.join(BASE_DIR, 'formulas', formulaSizes[key].file), x, y, w: size.w, h: size.h, altText: alt || key });
  return size;
}

function addFormulaCard(slide, key, x, y, w, h, { fill = C.tint, scale = 1, alt = '' } = {}) {
  addCard(slide, x, y, w, h, { fill });
  const size = formulaSize(key, scale);
  addFormula(slide, key, x + (w - size.w) / 2, y + (h - size.h) / 2, { scale, alt });
}

// PNG の縦横比を保ったまま、枠に収まる大きさで貼る（横は中央）
function pngSize(file) {
  const header = fs.readFileSync(file).subarray(16, 24);
  return { w: header.readUInt32BE(0), h: header.readUInt32BE(4) };
}

function addFigure(slide, name, x, y, maxW, maxH, alt) {
  const file = path.join(FIGURE_DIR, name);
  const px = pngSize(file);
  const scale = Math.min(maxW / px.w, maxH / px.h);
  const w = px.w * scale;
  const h = px.h * scale;
  slide.addImage({ path: file, x: x + (maxW - w) / 2, y, w, h, altText: alt });
  return { w, h };
}

function addNumberedCard(slide, x, y, w, h, num, title, desc, { fill = C.gray, color = C.indigo, descSize = 13 } = {}) {
  addCard(slide, x, y, w, h, { fill });
  addNode(slide, x + 0.42, y + 0.42, 0.46, color, String(num), { fontSize: 15 });
  addText(slide, title, x + 0.8, y + 0.17, w - 0.95, 0.5, { fontSize: 15.5, bold: true, valign: 'middle' });
  addText(slide, desc, x + 0.3, y + 0.8, w - 0.55, h - 0.9, { fontSize: descSize });
}

// 大きな数字と短い説明（結論のカードなど）
function addStat(slide, x, y, w, h, value, label, sub, { fill = C.tint, color = C.indigo, valueSize = 40 } = {}) {
  addCard(slide, x, y, w, h, { fill });
  addText(slide, value, x + 0.3, y + 0.2, w - 0.6, 0.9, { fontSize: valueSize, bold: true, color, valign: 'middle' });
  addText(slide, label, x + 0.3, y + 1.15, w - 0.6, 0.45, { fontSize: 15, bold: true });
  if (sub) addText(slide, sub, x + 0.3, y + 1.62, w - 0.6, h - 1.72, { fontSize: 12.5, color: C.muted });
}

function addChip(slide, x, y, color, label, { fontSize = 12, w = 2.4 } = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: y + 0.06, w: 0.22, h: 0.22, rectRadius: 0.04, fill: { color }, line: { color, width: 0.5 } });
  addText(slide, label, x + 0.32, y, w - 0.32, 0.34, { fontSize, valign: 'middle' });
}

function tableHead(labels, fill = C.indigo) {
  return labels.map((t) => ({ text: t, options: { bold: true, color: C.white, fill: { color: fill }, align: 'center' } }));
}

function addStyledTable(slide, rows, x, y, w, colW, { fontSize = 12.5, rowH = 0.42 } = {}) {
  slide.addTable(rows, {
    x, y, w, colW,
    fontFace: FONT, fontSize, color: C.ink, valign: 'middle', margin: [0.04, 0.1, 0.04, 0.1],
    border: { type: 'solid', color: C.grid, pt: 0.75 }, rowH: Array.isArray(rowH) ? rowH : rows.map(() => rowH),
  });
}

// 検出率（0〜1）を濃淡で示すセル
function rateCell(value, { digits = 2, highlight = false } = {}) {
  if (value === null || value === undefined) return { text: '—', options: { align: 'center', color: C.muted } };
  const level = Math.max(0, Math.min(1, value));
  const fill = level >= 0.8 ? '2F3470' : level >= 0.5 ? '6C74C0' : level >= 0.2 ? 'C9CDEE' : 'F2F3F7';
  const color = level >= 0.5 ? C.white : C.ink;
  return { text: value.toFixed(digits), options: { align: 'center', fill: { color: fill }, color, bold: highlight } };
}

// ---- スライド共通 ----

// 文字幅のおおよその見積もり（全角 1em、半角 0.58em）。タイトルが1行に収まる文字サイズを決めるのに使う
function estimateWidthInch(text, fontSizePt) {
  let em = 0;
  for (const ch of text) em += ch.codePointAt(0) > 0x2E80 ? 1.0 : 0.58;
  return (em * fontSizePt) / 72;
}

function titleFontSize(title) {
  let size = TITLE_FONT_PT;
  while (size > TITLE_MIN_FONT_PT && estimateWidthInch(title, size) > CONTENT_W) size -= 1;
  if (estimateWidthInch(title, size) > CONTENT_W) console.warn(`タイトルが長すぎます: ${title}`);
  return size;
}

function newContentSlide(kicker, title, notes, { source } = {}) {
  const slide = pres.addSlide();
  pageNumber += 1;
  slide.background = { color: C.white };
  addText(slide, kicker, MARGIN_X, 0.36, 9, 0.3, { fontSize: 12, bold: true, color: C.indigo, charSpacing: 1 });
  addText(slide, title, MARGIN_X, 0.64, CONTENT_W, 0.72, { fontSize: titleFontSize(title), bold: true, valign: 'middle' });
  addText(slide, source || `${DECK_TITLE}（模擬データによるシミュレーション）`, MARGIN_X, 7.02, 11.4, 0.3, { fontSize: 9.5, color: C.muted });
  addText(slide, String(pageNumber), SLIDE_W - 1.1, 7.02, 0.5, 0.3, { fontSize: 10, color: C.muted, align: 'right' });
  if (notes) slide.addNotes(notes.join('\n'));
  return slide;
}

function chartBase() {
  return {
    catAxisLabelColor: C.muted, valAxisLabelColor: C.muted,
    catAxisLabelFontFace: FONT, valAxisLabelFontFace: FONT,
    catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
    catAxisLineShow: true, catAxisLineColor: C.line,
    valAxisLineShow: false,
    valGridLine: { color: C.grid, size: 0.75 },
    catGridLine: { style: 'none' },
    dataLabelFontFace: FONT, titleFontFace: FONT, legendFontFace: FONT,
    catAxisTitleFontFace: FONT, valAxisTitleFontFace: FONT,
    catAxisTitleColor: C.muted, valAxisTitleColor: C.muted,
    catAxisTitleFontSize: 11, valAxisTitleFontSize: 11,
    titleColor: C.ink, titleFontSize: 13,
    legendFontSize: 11, legendColor: C.ink,
  };
}

const SECTION = {
  intro: 'INTRODUCTION',
  s1: '01  背景と目的',
  s2: '02  シミュレーションの方法',
  s3: '03  結果：1枚のWaferの異常',
  s4: '04  結果：経時変化',
  s5: '05  結果：計測条件の影響',
  s6: '06  結果：APC補正の影響',
  s7: '07  まとめ',
};

const reps = D.representatives;
const repOf = (family) => reps.find((r) => r.family === family);
const P2 = D.phase2;
const P3 = D.phase3;
const APC = D.apc;
const rank = (detector) => P2.ranking.find((r) => r.detector === detector);

require('./slides.js')({
  pres, D, C, FAMILY, V, R, f1, f2, pct, familyOf, baseFamily, schemeLabel, detectorLabel, BASE_LABEL,
  addText, addBullets, withBreaks, addCard, addLine, addNode, addFormula, addFormulaCard, formulaSize, addFigure,
  addNumberedCard, addStat, addChip, tableHead, addStyledTable, rateCell, newContentSlide, chartBase,
  SECTION, SLIDE_W, SLIDE_H, MARGIN_X, CONTENT_W, FONT, DECK_TITLE, DECK_DATE, reps, repOf, P2, P3, APC, rank,
  nextPage: () => { pageNumber += 1; return pageNumber; },
});

pres.writeFile({ fileName: OUTPUT_PATH }).then((file) => console.log(`書き出し: ${file}（${pageNumber} 枚）`));
