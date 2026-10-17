// 説明資料の各スライド（build_deck.js から呼ぶ）。数値はすべて deck_data.json（計算結果の CSV）から取り出す。
module.exports = function buildSlides(K) {
  const {
    pres, D, C, FAMILY, V, f1, f2, pct, familyOf, baseFamily, detectorLabel,
    addText, addBullets, withBreaks, addCard, addLine, addNode, addFormula, addFormulaCard, formulaSize, addFigure,
    addNumberedCard, addStat, addChip, tableHead, addStyledTable, rateCell, newContentSlide, chartBase,
    SECTION, SLIDE_W, MARGIN_X, CONTENT_W, DECK_TITLE, DECK_DATE, reps, repOf, P2, P3, APC, rank, nextPage,
  } = K;
  const P1 = D.phase1;

  // =====================================================================
  // 1. 表紙
  // =====================================================================
  {
    const slide = pres.addSlide();
    nextPage();
    slide.background = { color: C.night };
    addText(slide, '技術レポート ｜ Alignment・Overlay の監視', 0.8, 1.3, 7.4, 0.4, { fontSize: 15, bold: true, color: C.indigoLight, charSpacing: 2 });
    addText(slide, withBreaks(['Wafer面内傾向の', '異常検知・経時変化監視の', '手法比較']), 0.8, 1.8, 7.6, 2.3, { fontSize: 36, bold: true, color: C.white, valign: 'middle', lineSpacingMultiple: 1.05 });
    addText(slide, 'M3S では見えない面内形状の異常を、どの手法で・どの条件なら見つけられるか', 0.8, 4.25, 7.4, 0.7, { fontSize: 18, color: C.onDarkSub });
    addText(slide, '8つの監視手法を、同じ誤報率にそろえて同じ模擬データで比べたシミュレーションの結果説明（実データ・社内データは不使用）',
      0.8, 5.05, 7.0, 0.8, { fontSize: 13.5, color: C.indigoLight });
    addText(slide, DECK_DATE, 0.8, 6.45, 4, 0.35, { fontSize: 13, color: C.onDarkSub });

    // 右：系統ごとの平均検出率（表紙のモチーフ）
    const items = ['M1', 'M2', 'M3', 'M6', 'M4', 'OR'].map((family) => ({ family, rep: repOf(family) }));
    const x0 = 8.65;
    const y0 = 1.75;
    const rowH = 0.62;
    const maxW = 1.9;
    addText(slide, '1枚のWaferの異常の平均検出率（誤報率 1%）', 8.6, 1.2, 4.4, 0.4, { fontSize: 12, color: C.onDarkSub });
    items.forEach(({ family, rep }, i) => {
      const y = y0 + i * rowH;
      const w = rep.mean_detection * maxW / 0.6;
      addText(slide, FAMILY[family].name, x0, y, 1.35, 0.42, { fontSize: 12, color: C.onDarkSub, valign: 'middle' });
      slide.addShape(pres.shapes.RECTANGLE, { x: x0 + 1.4, y: y + 0.08, w, h: 0.28, fill: { color: family === 'M1' ? C.neutral : FAMILY[family].color }, line: { color: C.night, width: 0.5 } });
      addText(slide, pct(rep.mean_detection), x0 + 1.5 + w, y, 0.8, 0.42, { fontSize: 12.5, bold: true, color: C.white, valign: 'middle' });
    });
    addText(slide, 'OR統合 ＝ M3S・Mahalanobis・PCA T²・SPE・GPR 残差を「どれか1つでも超えたら警報」にまとめたもの', 8.6, 5.6, 4.3, 0.7, { fontSize: 11, color: C.indigoLight });
    slide.addNotes([
      'この資料では、Alignment と Overlay の計測値に含まれる Wafer 面内の傾向を、どの監視手法でどこまで見張れるかを比べた結果を説明します。',
      '従来の M3S、つまり平均の絶対値と標準偏差の3倍の和だけで管理する方法と、面内の形を使う7つの手法を、同じ誤報率にそろえて比べました。',
      `右のグラフは結論の先取りです。1枚の Wafer の異常の平均検出率は M3S が ${pct(repOf('M1').mean_detection)}、PCA T² が ${pct(repOf('M4').mean_detection)}、複数の手法を組み合わせると ${pct(repOf('OR').mean_detection)} でした。`,
      '数値はすべて乱数で作った模擬データの結果で、実データではありません。',
    ].join('\n'));
  }

  // =====================================================================
  // 2. この資料で分かること
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.intro, 'この資料で分かること', [
      '全体は7つのパートです。',
      '背景と目的で M3S 管理の弱点と6つの問いを確認し、方法で模擬データと監視手法、誤報率のそろえ方を説明します。',
      '結果は4つに分けます。1枚の Wafer の異常、経時変化、計測条件、APC 補正の影響です。',
      '最後に、6つの問いへの答えと、推奨する監視の構成をまとめます。',
    ]);
    addCard(slide, MARGIN_X, 1.55, CONTENT_W, 0.7, { fill: C.tint });
    addNode(slide, MARGIN_X + 0.45, 1.9, 0.42, C.indigo, '✓', { fontSize: 14 });
    addText(slide, 'ゴール：異常の種類・変化の速さ・計測条件に応じて、どの監視手法を選べばよいかを数値で判断できるようになる',
      MARGIN_X + 0.85, 1.55, CONTENT_W - 1.1, 0.7, { fontSize: 15, bold: true, valign: 'middle' });
    const parts = [
      ['背景と目的', 'M3S 管理の限界と6つの問い', 'p.4–5', FAMILY.M1.color],
      ['方法', '模擬Wafer、異常、監視手法、誤報率のそろえ方', 'p.6–10', FAMILY.M2.color],
      ['1枚の異常', '平均検出率、パターン別、M3S が同じ異常', 'p.11–15', FAMILY.M4.color],
      ['経時変化', '検出の速さ、成分別、時系列相関', 'p.16–20', FAMILY.M7.color],
      ['計測条件', '点数・ノイズ・配置・次数', 'p.21–24', FAMILY.M5.color],
      ['APC補正', '補正で隠れる異常、過学習', 'p.25–27', FAMILY.M3.color],
      ['まとめ', '6つの問いへの答えと推奨', 'p.28–31', FAMILY.M8.color],
    ];
    const gap = 0.2;
    const w = (CONTENT_W - 6 * gap) / 7;
    parts.forEach(([title, desc, pages, color], i) => {
      const x = MARGIN_X + i * (w + gap);
      const y = 2.6;
      addCard(slide, x, y, w, 3.5, { fill: C.gray });
      addNode(slide, x + 0.48, y + 0.55, 0.6, color, String(i + 1).padStart(2, '0'), { fontSize: 15 });
      addText(slide, title, x + 0.18, y + 1.05, w - 0.3, 0.6, { fontSize: 15, bold: true });
      addText(slide, desc, x + 0.18, y + 1.7, w - 0.3, 1.3, { fontSize: 12, color: C.muted });
      addText(slide, pages, x + 0.18, y + 3.05, w - 0.3, 0.3, { fontSize: 11, color: C.muted });
    });
    addText(slide, '想定する読者：Alignment・Overlay の工程管理の担当者とマネージャー。式は「何を見ているか」が分かる粒度で示します。',
      MARGIN_X, 6.35, CONTENT_W, 0.4, { fontSize: 13, color: C.muted });
  }

  // =====================================================================
  // 3. 結論を先に
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.intro, '結論を先に ― M3S だけでは足りず、手法の組み合わせが必要', [
      '結論を先にお伝えします。',
      `M3S が 10% 未満しか検出できなかった7種類の形状異常では、計測値の PCA T² の検出率が平均 ${V('p1_blind_t2q99')} でした。M3S は ${V('p1_blind_m3s')} です。`,
      `経時変化では、計測値を EWMA で平滑化してから PCA T² を当てる方法が最も早く、平均 ${V('p2_rmst_t2ewma')} 枚で検出しました。M3S は ${V('p2_rmst_m3sshew')} 枚です。`,
      `APC 補正の後の Overlay 残差だけを見ると、補正で消える異常は ${V('apc_s2_ovl_m3s_o3')} しか検出できず、誤報率と同じでした。補正係数を見れば ${V('apc_s2_coef_md_o3')} 検出できます。`,
      '一つの手法ですべてを見ることはできないので、得意な異常の違う手法を組み合わせることを推奨します。',
    ]);
    const w = (CONTENT_W - 2 * 0.35) / 3;
    addStat(slide, MARGIN_X, 1.6, w, 2.7, V('p1_blind_t2q99'), 'M3S が見逃す形状異常の検出率',
      `PCA T²（計測値）。M3S は ${V('p1_blind_m3s')}（7種類・全振幅の平均、誤報率 1%）`, { fill: FAMILY.M4.tint, color: FAMILY.M4.color });
    addStat(slide, MARGIN_X + w + 0.35, 1.6, w, 2.7, `${V('p2_rmst_t2ewma')} 枚`, '経時変化を検出するまでの遅延',
      `計測値の EWMA ＋ PCA T²（MEWMA）。M3S は ${V('p2_rmst_m3sshew')} 枚（同じ ARL₀ = 370）`, { fill: FAMILY.M7.tint, color: FAMILY.M7.color });
    addStat(slide, MARGIN_X + 2 * (w + 0.35), 1.6, w, 2.7, V('apc_s2_ovl_m3s_o3'), '補正後の残差での検出率',
      `補正で消える異常（3次補正・3次の放射状歪み）。誤報率と同じ＝見えない。補正係数の監視なら ${V('apc_s2_coef_md_o3')}`, { fill: C.badTint, color: C.bad });
    addCard(slide, MARGIN_X, 4.55, CONTENT_W, 2.2, { fill: C.night });
    addText(slide, '結論', MARGIN_X + 0.4, 4.7, 2, 0.4, { fontSize: 14, bold: true, color: C.indigoLight });
    addBullets(slide, [
      `1枚の判定：M3S・Mahalanobis・PCA T²・SPE・GPR 残差を OR で統合（平均検出率 ${V('p1_or_mean')}、単独の最良は ${V('p1_t2q99_mean')}）`,
      '経時変化：計測値の EWMA（λ = 0.05）＋ PCA T²・Mahalanobis。局所的な変化には PCA SPE の EWMA',
      'APC の下：補正後の残差だけでなく、補正係数（または補正前の Alignment）も監視する',
    ], MARGIN_X + 0.4, 5.15, CONTENT_W - 0.8, 1.55, { fontSize: 15.5, color: C.white, space: 9 });
  }

  // =====================================================================
  // 4. M3S 管理の限界
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s1, 'M3S 管理の限界 ― 「平均」と「ばらつき」の2つの数しか見ていない', [
      'まず背景です。日常の工程管理では、計測値の平均の絶対値と標準偏差の3倍の和、M3S を Wafer ごとに管理する方法が広く使われています。',
      'M3S は便利ですが、2つの弱点があります。',
      '1つ目は形の情報を捨てることです。同じ平均と標準偏差でも、ばらつきが面内のどこにどう並んでいるかは区別できません。右の図は、M3S がまったく同じ2枚の Wafer の例です。',
      '2つ目は、倍率や回転のような大きな正常変動があると、局所的な変形や1つの Shot のずれは M3S をほとんど変えないことです。',
    ]);
    addFormulaCard(slide, 'm3s', MARGIN_X, 1.6, 5.4, 0.95, { fill: C.tint, scale: 1.0, alt: 'M3S = |平均| + 3s' });
    addText(slide, 'X・Y それぞれの計測値の |平均| と標準偏差 s から計算する', MARGIN_X, 2.62, 5.4, 0.35, { fontSize: 12.5, color: C.muted });
    addNumberedCard(slide, MARGIN_X, 3.1, 5.4, 1.62, 1, '形の情報を捨てる',
      '同じ平均・標準偏差なら、ばらつきの並び方が違っても同じ値。計測値の位置を入れ替えただけの Wafer は M3S が厳密に同じになる', { fill: C.gray, color: FAMILY.M1.color });
    addNumberedCard(slide, MARGIN_X, 4.92, 5.4, 1.62, 2, '大きな正常変動に埋もれる',
      '倍率・回転などの正常な変動が大きいと、局所的な変形や1 Shot のずれは M3S の値をほとんど変えない', { fill: C.gray, color: FAMILY.M1.color });
    addFigure(slide, 'figure03_b10_same_m3s.png', 6.3, 1.6, 6.4, 3.3, '正常WaferとM3Sが同一の異常Waferの比較');
    addCard(slide, 6.3, 5.1, 6.4, 1.45, { fill: C.warnTint });
    addText(slide, `例：平均と標準偏差を保ったまま形を変えた異常（B10）。M3S の検出率は ${V('b10_m3s_8')} で、異常を入れる前の同じ Wafer の誤報の割合とまったく同じ。形を見る Mahalanobis 距離（4次）は ${V('b10_md4_8')} 検出した（振幅 8σ_dir）`,
      6.55, 5.1, 5.95, 1.45, { fontSize: 13, valign: 'middle' });
  }

  // =====================================================================
  // 5. 6つの問いと比較の原則
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s1, '6つの問い（RQ）と、公平に比べるための3つの原則', [
      '本研究で答える問いは6つです。',
      'RQ1 と RQ3 は1枚の Wafer の異常、RQ2 は経時変化、RQ4 は計測条件、RQ5 は APC 補正、RQ6 は組み合わせの必要性です。',
      '比べ方には3つの原則を置きました。すべての手法を同じ誤報率にそろえること、同じ模擬データを入れること、M3S を必ず基準に入れることです。',
      '誤報率をそろえないと、警報をたくさん出す手法ほど検出率が高く見えてしまうためです。',
    ]);
    const questions = [
      ['RQ1', 'M3S が見逃す面内形状の異常に、どの手法が最も有効か'],
      ['RQ2', '微小な経時変化を最も早く検知できる手法は何か'],
      ['RQ3', '異常の種類によって有効な手法はどの程度違うか'],
      ['RQ4', '計測点数やノイズで性能はどれだけ下がるか'],
      ['RQ5', 'APC 補正後の Overlay だけを見ると何を見逃すか'],
      ['RQ6', '1つの手法で十分か、組み合わせが必要か'],
    ];
    const cardW = 3.75;
    questions.forEach(([id, text], i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      const x = MARGIN_X + col * (cardW + 0.25);
      const y = 1.6 + row * 1.6;
      addCard(slide, x, y, cardW, 1.4, { fill: C.gray });
      addText(slide, id, x + 0.25, y + 0.15, 1.2, 0.4, { fontSize: 15, bold: true, color: C.indigo });
      addText(slide, text, x + 0.25, y + 0.55, cardW - 0.45, 0.8, { fontSize: 14 });
    });
    const rx = MARGIN_X + 2 * cardW + 0.6;
    const rw = SLIDE_W - MARGIN_X - rx;
    addCard(slide, rx, 1.6, rw, 4.6, { fill: C.tint });
    addText(slide, '公平に比べるための原則', rx + 0.3, 1.8, rw - 0.6, 0.4, { fontSize: 16, bold: true, color: C.indigo });
    addBullets(slide, [
      '同じ誤報率にそろえる：1枚の判定は誤報率（FPR）5%・1%・0.1%、時系列は正常時の平均連長 ARL₀ = 370',
      '同じデータを入れる：異常の種類・大きさ・手法によらず、同じ正常 Wafer と同じ異常（Common Random Numbers）',
      'M3S を基準に入れる：今の管理と比べてどれだけ良いかを示す',
    ], rx + 0.3, 2.35, rw - 0.6, 3.7, { fontSize: 14, space: 10 });
  }

  // =====================================================================
  // 6. 模擬 Wafer
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s2, '模擬Wafer ― Zernike の面内傾向 ＋ 時系列の変動 ＋ 計測誤差', [
      '次に方法です。模擬 Wafer は 300 mm、Shot は 26 × 33 mm で、外周の部分 Shot を含めて 97 Shot、Alignment のマークは 316 点です。',
      '正常な面内傾向は、X と Y それぞれ動径次数7までの Zernike 多項式、36項で作りました。上の図の左が XY の変位、中央が X と Y の成分、右が係数の分布です。',
      '係数は Wafer ごとに変わり、さらに AR(1) で時間的にゆっくり動きます。相関の強さ ρ の基準は 0.7 です。',
      '計測値には、同じ Shot の全マークに共通の誤差と、マークごとの誤差を足しました。空間自己相関は今回の対象外です。',
    ]);
    addFigure(slide, 'figure01_normal_wafer.png', MARGIN_X, 1.5, CONTENT_W, 3.3, '正常Waferの面内傾向とZernike係数の分布');
    const cards = [
      ['Wafer と計測点', '直径 300 mm、Shot 26 × 33 mm、97 Shot。Alignment は 1 Shot 4 マークで全点 316 点（外周除外 3 mm）', null],
      ['正常な面内傾向', '動径次数 7 までの Zernike（36項 × XY、Fringe 番号）。係数の大きさは高次ほど小さい（仮定）', 'zernike'],
      ['時系列の変動', 'AR(1)。定常共分散が ρ によらず同じになるよう調整。基準は ρ = 0.7', 'ar1'],
      ['計測誤差', 'Shot 共通 0.5 nm ＋ Mark 独立 1.0 nm（基準）。Phase 3 で 0.5〜3 倍を比較', null],
    ];
    const w = (CONTENT_W - 3 * 0.25) / 4;
    cards.forEach(([title, desc], i) => {
      const x = MARGIN_X + i * (w + 0.25);
      addCard(slide, x, 4.95, w, 1.85, { fill: C.gray });
      addText(slide, title, x + 0.22, 5.08, w - 0.4, 0.4, { fontSize: 14.5, bold: true, color: C.indigo });
      addText(slide, desc, x + 0.22, 5.5, w - 0.4, 1.25, { fontSize: 12.5 });
    });
  }

  // =====================================================================
  // 7. 1枚の Wafer の異常 10 種類
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s2, '1枚のWaferの異常 10種類 ― 大きさは正常なばらつき σ_dir で測る', [
      '1枚の Wafer に入れる異常は10種類です。放射状や回転の歪み、局所的な変形、片側だけの倍率、高次の成分、係数の組み合わせの異常、監視モデルで表せない高次、Scan 方向の違い、1つの Shot のずれ、そして平均と標準偏差が変わらない異常です。',
      '異常の大きさは、その異常の向きに正常な計測値を射影したときの標準偏差、σ_dir を単位にしました。1、2、4、8、16 倍の5段階です。',
      '右端の κ は、正常なばらつきの相関を使うとどれだけ見つけやすくなるかの目安です。局所変形や1 Shot のずれは κ が大きく、相関を使う手法に有利です。',
      '同じ振幅でも nm の大きさはパターンで違う点に注意してください。',
    ]);
    const rows = [
      ['B1', 'Radial 方向', '外周ほど大きい3次の放射状歪み'],
      ['B2', 'Tangential 方向', '外周ほど大きい回転'],
      ['B3', '局所的な変形', 'ガウス形の局所変形（幅 20 mm、位置は無作為）'],
      ['B4', '左右・上下非対称', '片側だけの倍率（右・左・上・下）'],
      ['B5', '高次 Zernike', 'n = 4〜5 の組み合わせ（5次多項式で表せる）'],
      ['B6', '係数の異常な組み合わせ', '相関する係数の組を、相関と逆向きに動かす'],
      ['B7', '表せない高次', 'n = 8〜9（監視モデルでも正常モデルでも表せない）'],
      ['B8', 'Scan Up/Down 依存', 'Scan 方向で符号が変わるずれ'],
      ['B9', '単一 Shot', '1 Shot の全マークが同じ向きにずれる'],
      ['B10', '平均・分散が同じ', '平均と標準偏差を保ったまま形だけを変える'],
    ];
    const table = [tableHead(['ID', '異常', '形（作り方）', 'κ'])].concat(rows.map(([id, name, desc]) => [
      { text: id, options: { bold: true, align: 'center' } },
      { text: name, options: { bold: true } },
      { text: desc },
      { text: f1(P1.kappa[id]), options: { align: 'center' } },
    ]));
    addStyledTable(slide, table, MARGIN_X, 1.55, 8.6, [0.7, 2.5, 4.6, 0.8], { fontSize: 12.5, rowH: 0.45 });
    const rx = 9.5;
    const rw = SLIDE_W - MARGIN_X - rx;
    addText(slide, '異常の大きさの単位', rx, 1.55, rw, 0.35, { fontSize: 14, bold: true, color: C.indigo });
    addFormulaCard(slide, 'sigma_dir', rx, 1.95, rw, 0.8, { fill: C.tint, scale: 0.78, alt: 'σ_dir = sqrt(dᵀ Σ_z d)、Δ = a σ_dir d' });
    addBullets(slide, [
      'd：異常の形の向き（単位ベクトル）',
      'Σ_z：正常な計測値の共分散（潜在値 ＋ 計測誤差）',
      '振幅 a = 1, 2, 4, 8, 16',
      'κ ≥ 1：相関を使うと見つけやすくなる度合い（大きいほど有利）',
    ], rx, 2.95, rw, 2.6, { fontSize: 12.5, space: 6 });
    addCard(slide, rx, 5.55, rw, 1.25, { fill: C.warnTint });
    addText(slide, `同じ振幅でも nm は違う（4σ_dir の RMS：B1 ${f1(P1.rms4.B1)} nm、B8 ${f2(P1.rms4.B8)} nm）`, rx + 0.2, 5.55, rw - 0.4, 1.25, { fontSize: 12.5, valign: 'middle' });
  }

  // =====================================================================
  // 8. 経時変化
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s2, '経時変化 ― 4つの時間変化 × 6つの面内成分を 300 枚の系列に入れる', [
      '経時変化は、300 枚の系列の 101 枚目から入れました。',
      '時間変化は4種類です。段差の Step、直線的に増える Ramp、立ち上がって飽和する Drift、周期 50 枚の周期変動です。',
      '変化する面内成分は、低次・高次の Zernike、Radial、Tangential、非対称、局所変形の6種類で、大きさは σ_dir の 0.25〜3 倍です。',
      '評価は、正常時の平均連長 ARL₀ を 370 にそろえたうえで、変化が始まってから最初に警報が出るまでの枚数で比べます。200 枚で検出できなければ 200 枚として数える RMST を主な指標にしました。',
    ]);
    const t = Array.from({ length: 301 }, (_, i) => i);
    const onset = 101;
    const profile = {
      'A1 Step': t.map((x) => (x >= onset ? 1 : 0)),
      'A2 Ramp': t.map((x) => (x >= onset ? (x - onset + 1) / 100 : 0)),
      'A3 Drift': t.map((x) => (x >= onset ? 1 - Math.exp(-(x - onset + 1) / 50) : 0)),
      'A4 周期': t.map((x) => (x >= onset ? Math.sin((2 * Math.PI * (x - onset + 1)) / 50) : 0)),
    };
    // 目盛りの文字は 50 枚ごと。PowerPoint は tickLblSkip で間引き（間引かないと狭い枠で数字が縦に折り返す）、
    // 確認用の LibreOffice は tickLblSkip を無視するので、間の文字を空にしておく
    const labels = t.map((x) => (x % 50 === 0 ? String(x) : ''));
    slide.addChart(pres.charts.LINE, Object.entries(profile).map(([name, values]) => ({ name, labels, values: values.map((v) => Number(v.toFixed(3))) })), {
      x: MARGIN_X, y: 1.55, w: 7.2, h: 4.4, ...chartBase(),
      chartColors: [FAMILY.M2.color, FAMILY.M3.color, FAMILY.M4.color, FAMILY.M8.color],
      lineSize: 2, lineDataSymbol: 'none', showLegend: true, legendPos: 'b',
      catAxisLabelFrequency: 50, catAxisMajorTickMark: 'none', valAxisCrossesAt: -1.5,
      valAxisMinVal: -1.5, valAxisMaxVal: 2.0, valAxisMajorUnit: 0.5, valAxisLabelFormatCode: '0.0',
      showValAxisTitle: true, valAxisTitle: '変化の大きさ（振幅 a の何倍か）', showCatAxisTitle: true, catAxisTitle: 'Wafer（101 枚目から変化）',
      showTitle: true, title: '時間変化の形 g(t)',
    });
    const rx = 8.1;
    const rw = SLIDE_W - MARGIN_X - rx;
    addText(slide, '変化する面内成分（6種類）', rx, 1.55, rw, 0.35, { fontSize: 14, bold: true, color: C.indigo });
    const comps = [['低次 Zernike', 'Z(2,±2)'], ['高次 Zernike', 'Z(5,±1)'], ['Radial', 'B1 と同じ形'], ['Tangential', 'B2 と同じ形'], ['非対称', '右側だけの倍率'], ['局所変形', '右上の1か所']];
    comps.forEach(([name, desc], i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      const x = rx + col * (rw / 2);
      const y = 2.0 + row * 0.5;
      addChip(slide, x, y, C.indigo, `${name}（${desc}）`, { fontSize: 11.5, w: rw / 2 });
    });
    addCard(slide, rx, 3.65, rw, 2.3, { fill: C.tint });
    addText(slide, '評価の仕方', rx + 0.25, 3.78, rw - 0.5, 0.35, { fontSize: 14, bold: true, color: C.indigo });
    addBullets(slide, [
      '全検出器を ARL₀ = 370 に校正',
      '変化点前に誤報が出た系列は除く（条件付き遅延）',
      '主な指標は RMST（未検出は 200 枚と数える）',
    ], rx + 0.25, 4.18, rw - 0.5, 1.2, { fontSize: 12.5, space: 4 });
    addFormula(slide, 'rmst', rx + 0.25, 5.42, { scale: 0.8, alt: 'RMST = E[min(D, 200)]' });
    addText(slide, '振幅：0.25・0.5・1・2・3 σ_dir、各条件 1,000 系列', MARGIN_X, 6.1, 7.2, 0.4, { fontSize: 12.5, color: C.muted });
  }

  // =====================================================================
  // 9. 8つの監視手法
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s2, '比べた8つの監視手法 ― 何を見ているかが違う', [
      '比べた監視手法は8つです。',
      'M1 の M3S は全体のばらつき、M2 の係数 SPC は多項式の係数を1つずつ、M3 の Mahalanobis 距離は係数の組み合わせを見ます。',
      'M4 と M5 は計測値の主成分分析で、T² は主な変動の方向の中の異常、SPE はそこから外れた異常を見ます。',
      'M6 の GPR 残差は、Wafer ごとの滑らかな個体差を取り除いた残りを見ます。',
      'M7 の EWMA と M8 の CUSUM は過去の Wafer を積み上げる時系列の方法で、上の統計量と組み合わせて使います。',
    ]);
    const rows = [
      ['M1', 'M3S', '計測値の |平均| + 3σ（X・Y の大きい方）', '全体のばらつきの増加'],
      ['M2', '多項式係数 SPC', '3〜5次の多項式の係数を1つずつ管理', '特定の係数の変化（解釈しやすい）'],
      ['M3', 'Mahalanobis 距離', '係数ベクトルの組み合わせ（縮小推定）', '係数の異常な組み合わせ'],
      ['M4', 'PCA T²', '計測値の主成分の中の異常', '主な変動の方向の異常'],
      ['M5', 'PCA SPE', '主成分で再構成できない残り', '局所・高次・未知の形'],
      ['M6', 'GPR 残差', '平均傾向と個体差（滑らかな GP）を除いた残り', '急な変化（Shot・Mark・Scan）'],
      ['M7', 'EWMA', '過去を指数で重み付けして平滑化（λ）', '小さな持続的変化'],
      ['M8', 'CUSUM', '基準値 k を超えた分を累積', '小さな持続的変化'],
    ];
    const table = [tableHead(['', '手法', '何を見るか', '得意な異常'])].concat(rows.map(([id, name, what, good]) => [
      { text: id, options: { bold: true, align: 'center', color: C.white, fill: { color: FAMILY[id].color } } },
      { text: name, options: { bold: true } },
      { text: what },
      { text: good },
    ]));
    addStyledTable(slide, table, MARGIN_X, 1.55, 8.4, [0.6, 2.1, 3.4, 2.3], { fontSize: 12.5, rowH: 0.52 });
    const rx = 9.3;
    const rw = SLIDE_W - MARGIN_X - rx;
    const formulas = [['md', 'M3'], ['t2', 'M4'], ['spe', 'M5'], ['gpr', 'M6'], ['ewma', 'M7'], ['cusum', 'M8']];
    formulas.forEach(([key, family], i) => {
      const y = 1.55 + i * 0.82;
      addCard(slide, rx, y, rw, 0.7, { fill: FAMILY[family].tint });
      addText(slide, family, rx + 0.12, y, 0.5, 0.7, { fontSize: 12, bold: true, color: FAMILY[family].color, valign: 'middle' });
      const size = formulaSize(key, 0.62);
      addFormula(slide, key, rx + 0.62 + (rw - 0.7 - size.w) / 2, y + (0.7 - size.h) / 2, { scale: 0.62 });
    });
    addText(slide, '設定：多項式は 3〜5次、PCA は寄与率 90・95・99%、GPR は RBF・Matérn、EWMA は λ = 0.05〜0.4、CUSUM は k = 0.25〜1 を比べた',
      MARGIN_X, 6.4, 8.4, 0.35, { fontSize: 11, color: C.muted });
  }

  // =====================================================================
  // 10. 誤報率のそろえ方
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s2, '誤報率のそろえ方 ― 正常データだけで管理限界を決める', [
      'すべての手法の管理限界は、正常データだけから経験的に決めました。',
      '1枚の判定では、5万枚の正常データのスコアの上位から限界を決め、別の5万枚で実際の誤報率を確かめました。',
      '複数の指標を OR でまとめるときは、まとめた後の誤報率が目標になるように限界を決め直しました。',
      '時系列の判定では、長い正常系列で ARL₀ が 370 になる限界を探しました。',
      `理論式だけで限界を決めると大きくずれることがあります。例えば寄与率 99% の SPE は、目標 0.1% に対して ${V('spe99_theoretical_fpr')} の誤報率になりました。`,
    ]);
    const cards = [
      ['1枚：経験的な分位点', '正常 50,000 枚のスコアの上側 α 分位点を限界にし、別の 50,000 枚で誤報率を確認（α = 5%・1%・0.1%）'],
      ['OR 統合：まとめて校正', '各指標を正常データの順位に直し、その最大値で限界を決める。統合後の誤報率が α になる'],
      ['時系列：ARL₀ = 370', '長さ 3,000 枚 × 1,000 本の正常系列で連長を求め、ARL₀ が 370 になる限界を探索。独立な系列で確認'],
      ['遅延：条件付きで数える', '変化点より前に誤報が出た系列は遅延の集計から除く（前の警報が続いて「すぐ検出」に見えるのを防ぐ）'],
    ];
    const w = 3.6;
    cards.forEach(([title, desc], i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      addNumberedCard(slide, MARGIN_X + col * (w + 0.25), 1.6 + row * 2.45, w, 2.2, i + 1, title, desc, { fill: C.gray, color: C.indigo, descSize: 14 });
    });
    const rx = MARGIN_X + 2 * w + 0.6;
    const rw = SLIDE_W - MARGIN_X - rx;
    addStat(slide, rx, 1.6, rw, 2.35, V('spe99_theoretical_fpr'), '理論式だけで決めた誤報率',
      '目標 0.1%。PCA SPE（寄与率 99%）。小さな固有値が実際より小さく推定されるため', { fill: C.badTint, color: C.bad });
    addStat(slide, rx, 4.15, rw, 2.35, `${V('fpr0001_min')}〜${V('fpr0001_max')}`, '経験的な限界の誤報率',
      `目標 0.1%、全手法の範囲（評価用の正常データ）。目標 1% では ${V('fpr001_min')}〜${V('fpr001_max')}`, { fill: C.goodTint, color: C.good, valueSize: 30 });
  }

  // =====================================================================
  // 11. 平均検出率
  // =====================================================================
  {
    // グラフは下から値の小さい順（横棒は先頭の項目が下に来る）
    const items = reps.slice().sort((a, b) => a.mean_detection - b.mean_detection);
    const slide = newContentSlide(SECTION.s3, '1枚の異常の平均検出率 ― 単独では PCA T²、組み合わせると最も高い', [
      'ここから結果です。まず1枚の Wafer の異常を、10種類 × 5段階の振幅で 1,000 回ずつ入れたときの、誤報率 1% での平均検出率です。',
      `系統ごとに最もよい設定を代表にしました。単独では PCA T²（寄与率 99%）が ${V('p1_t2q99_mean')} で最も高く、GPR 残差 ${V('p1_gpr_mean')}、Mahalanobis 距離 ${V('p1_md_mean')} が続きます。`,
      `M3S は ${V('p1_m3s_mean')}、係数 SPC は ${V('p1_spc_mean')} でした。`,
      `EWMA と CUSUM は、1枚だけの異常では今の Wafer の重みが小さいので弱くなります。5つの指標の OR 統合が ${V('p1_or_mean')} で最も高くなりました。`,
    ]);
    slide.addChart(pres.charts.BAR, [{ name: '平均検出率', labels: items.map((r) => `${FAMILY[r.family].name}`), values: items.map((r) => Number((r.mean_detection * 100).toFixed(1))) }], {
      x: MARGIN_X, y: 1.5, w: 7.4, h: 5.3, ...chartBase(), barDir: 'bar',
      chartColors: items.map((r) => FAMILY[r.family].color), showValue: true, dataLabelFormatCode: '0.0"%"', dataLabelFontSize: 11, dataLabelColor: C.ink,
      valAxisMinVal: 0, valAxisMaxVal: 70, valAxisMajorUnit: 10, valAxisLabelFormatCode: '0"%"', barGapWidthPct: 45,
      showTitle: true, title: '平均検出率（B1〜B10・1〜16σ_dir、誤報率 1%）', showLegend: false, catAxisLabelFontSize: 12,
    });
    const rx = 8.4;
    const rw = SLIDE_W - MARGIN_X - rx;
    addText(slide, '代表の設定', rx, 1.55, rw, 0.35, { fontSize: 14, bold: true, color: C.indigo });
    const REP_LABEL = {
      'OR[M3S_XY+MD_d4+T2_raw_q99+SPE_raw_q99+GPR_rbf_full]': 'M3S・MD（4次）・T²・SPE・GPR',
      T2_raw_q99: '計測値、寄与率 99%',
      GPR_rbf_full: 'RBF カーネル、個体差も含む全体',
      MD_d5: '5次の多項式の係数',
      SPE_raw_q99: '計測値、寄与率 99%',
      'MD_d5|EWMA-scalar(λ=0.4)': 'Mahalanobis（5次）の EWMA、λ = 0.4',
      'GPR_matern52_residual|CUSUM(k=1)': 'GPR 残差（Matérn）の CUSUM、k = 1',
      SPC_d4: '4次の多項式の係数',
      M3S_XY: 'X・Y の大きい方',
    };
    const rows = items.slice().reverse().map((r) => [
      { text: FAMILY[r.family].name, options: { bold: true, color: FAMILY[r.family].color } },
      { text: REP_LABEL[r.representative] || r.representative, options: { fontSize: 10.5 } },
    ]);
    addStyledTable(slide, rows, rx, 1.95, rw, [1.35, rw - 1.35], { fontSize: 11.5, rowH: 0.36 });
    addCard(slide, rx, 5.4, rw, 1.4, { fill: C.tint });
    addText(slide, `誤報率 0.1% でも順位はほぼ同じ（PCA T² ${V('p1_t2q99_mean_0001')}、M3S ${V('p1_m3s_mean_0001')}）。EWMA・CUSUM は単発の異常には弱い`,
      rx + 0.2, 5.4, rw - 0.4, 1.4, { fontSize: 12.5, valign: 'middle' });
  }

  // =====================================================================
  // 12. パターン別の検出率
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s3, '異常の種類ごとの検出率 ― 得意・不得意がはっきり分かれる', [
      '異常の種類ごとに見ると、得意・不得意がはっきり分かれます。表は振幅 4σ_dir での検出率です。',
      `M3S は Radial や非対称のような、正常な大きい変動と同じ向きの滑らかな異常では最もよく、B1 で ${f2(P1.matrix4.B1.M3S_XY)} 検出しました。`,
      `一方、局所変形と単一 Shot は PCA T²・SPE・GPR 残差がほぼ 100%、表せない高次も PCA T²・SPE が 0.9 以上検出したのに対し、M3S は ${f2(P1.matrix4.B9.M3S_XY)} 程度でした。`,
      '係数の組み合わせの異常や平均と分散が同じ異常は、Mahalanobis 距離が最もよく、どの手法も難しい種類です。',
    ]);
    addFigure(slide, 'figure05_pattern_heatmap.png', MARGIN_X, 1.5, 8.9, 5.35, '異常パターン別・手法別の検出率のヒートマップ');
    const rx = 9.7;
    const rw = SLIDE_W - MARGIN_X - rx;
    const groups = [
      ['正常変動と同じ向き', 'B1・B2・B4', 'M3S が最もよい', FAMILY.M1.color],
      ['係数の組み合わせ', 'B5・B6・B10', 'Mahalanobis が最もよい', FAMILY.M3.color],
      ['滑らかでない・局所・高次', 'B3・B7・B8・B9', 'PCA T²・SPE・GPR', FAMILY.M4.color],
    ];
    groups.forEach(([title, patterns, best, color], i) => {
      const y = 1.55 + i * 1.75;
      addCard(slide, rx, y, rw, 1.55, { fill: C.gray });
      addNode(slide, rx + 0.35, y + 0.38, 0.4, color, String(i + 1), { fontSize: 13 });
      addText(slide, title, rx + 0.7, y + 0.15, rw - 0.85, 0.5, { fontSize: 13, bold: true, valign: 'middle' });
      addText(slide, patterns, rx + 0.25, y + 0.72, rw - 0.4, 0.35, { fontSize: 12.5, color: C.muted });
      addText(slide, best, rx + 0.25, y + 1.07, rw - 0.4, 0.38, { fontSize: 13, bold: true, color });
    });
  }

  // =====================================================================
  // 13. M3S が同じ異常（B10）
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s3, 'M3S が同じ異常（B10）― 係数の組み合わせを見る手法だけが反応する', [
      '平均と標準偏差が変わらない異常、B10 を詳しく見ます。正常な指紋の一部を、別の滑らかな形に置き換え、ばらつきの総量は変えていません。',
      `M3S は2枚で値が同じなので、検出率は ${V('b10_m3s_8')} で、異常を入れる前の同じ Wafer の誤報の割合とまったく同じでした。左下の図で、点がすべて y = x の線の上に並んでいます。`,
      `係数の組み合わせを見る Mahalanobis 距離（4次）は 8σ_dir で ${V('b10_md4_8')}、係数 SPC は ${V('b10_spc4_8')} 検出しました。`,
      `一方、計測誤差の部分を見る PCA SPE や GPR 残差はほとんど反応しませんでした（${V('b10_spe99_8')}、${V('b10_gpr_8')}）。変化が滑らかな成分だけで起きているためです。`,
    ]);
    addFigure(slide, 'figure03_b10_same_m3s.png', MARGIN_X, 1.5, 8.0, 4.5, 'B10の正常Waferと異常Waferのスコア比較');
    addFormulaCard(slide, 'b10', MARGIN_X, 6.1, 8.0, 0.7, { fill: C.tint, scale: 0.85, alt: 'Δ = t u − s c_s、||c + Δ|| = ||c||' });
    const rx = 8.95;
    const rw = SLIDE_W - MARGIN_X - rx;
    const stats = [
      [V('b10_m3s_8'), 'M3S', '異常を入れる前と同じ', FAMILY.M1],
      [V('b10_md4_8'), 'Mahalanobis（4次）', '係数の組み合わせ', FAMILY.M3],
      [V('b10_t2q99_8'), 'PCA T²（99%）', '主成分の大半が誤差の方向', FAMILY.M4],
      [V('b10_spe99_8'), 'PCA SPE（99%）', '誤差の部分は変わらない', FAMILY.M5],
    ];
    addText(slide, '振幅 8σ_dir の検出率', rx, 1.5, rw, 0.35, { fontSize: 13.5, bold: true, color: C.indigo });
    stats.forEach(([value, name, desc, fam], i) => {
      const y = 1.92 + i * 1.22;
      addCard(slide, rx, y, rw, 1.08, { fill: fam.tint });
      addText(slide, value, rx + 0.2, y + 0.04, 1.4, 1.0, { fontSize: 22, bold: true, color: fam.color, valign: 'middle' });
      addText(slide, name, rx + 1.65, y + 0.14, rw - 1.8, 0.4, { fontSize: 13, bold: true, valign: 'middle' });
      addText(slide, desc, rx + 1.65, y + 0.56, rw - 1.8, 0.4, { fontSize: 11.5, color: C.muted, valign: 'middle' });
    });
  }

  // =====================================================================
  // 14. 位置の入れ替え（B10 方法1）
  // =====================================================================
  {
    const P = P1.permutation;
    const cols = [['M3S_XY', 'M1'], ['SPC_d4', 'M2'], ['MD_d5', 'M3'], ['T2_raw_q99', 'M4'], ['SPE_raw_q99', 'M5'], ['GPR_rbf_full', 'M6'], ['OR[M3S_XY+MD_d4+T2_raw_q99+SPE_raw_q99+GPR_rbf_full]', 'OR']];
    const kinds = [['rot180', '180°回転'], ['mirror_x', '左右反転'], ['mirror_y', '上下反転'], ['shuffle', '無作為な入れ替え']];
    const slide = newContentSlide(SECTION.s3, '位置を入れ替えただけの Wafer ― 原理的に見分けにくい異常もある', [
      'もう一つの B10 は、計測値の集合はそのままで、位置だけを入れ替えた Wafer です。M3S は厳密に同じです。',
      `無作為に入れ替えると滑らかな形が壊れるので、PCA T²・SPE・GPR 残差は 100% 検出しました。ところが Mahalanobis と係数 SPC は ${V('perm_shuffle_md')} でした。係数がほとんど 0 になり、普段より平らな Wafer に見えるためです。上側だけの管理限界では見逃します。`,
      `左右・上下の反転は Mahalanobis で ${V('perm_mirror_md')} 検出しましたが、180°回転は比べた全ての設定で ${V('perm_rot_max')} 以下でした。`,
      '180°回転した正常な Wafer は、正常な Wafer の分布とほとんど同じになるので、どの手法でも原理的に見つけにくい異常です。',
    ]);
    const table = [tableHead(['入れ替え方', ...cols.map(([, fam]) => FAMILY[fam].name)])].concat(kinds.map(([kind, label]) => [
      { text: label, options: { bold: true } },
      ...cols.map(([name]) => rateCell(P[kind][name] !== undefined ? P[kind][name] : null)),
    ]));
    addStyledTable(slide, table, MARGIN_X, 1.6, CONTENT_W, [2.3, ...cols.map(() => (CONTENT_W - 2.3) / cols.length)], { fontSize: 13, rowH: 0.55 });
    addText(slide, '誤報率 1% での検出率（1,000 枚）。濃いほど検出できている', MARGIN_X, 4.45, CONTENT_W, 0.3, { fontSize: 11.5, color: C.muted });
    const cards = [
      ['無作為な入れ替え', '形が壊れて「普段より平ら」になる。係数を使う手法は上側の限界では見逃す → 下側の監視も必要', C.badTint, C.bad],
      ['左右・上下の反転', `Mahalanobis（5次）で ${V('perm_mirror_md')}、PCA T² で約3割を検出。どの手法でも見分けきれない`, C.tint, C.indigo],
      ['180°回転', '奇数次の方位成分の符号が反転するだけで、正常な分布とほぼ同じ → どの手法でも見分けにくい', C.warnTint, FAMILY.M5.color],
    ];
    const w = (CONTENT_W - 2 * 0.3) / 3;
    cards.forEach(([title, desc, fill, color], i) => {
      const x = MARGIN_X + i * (w + 0.3);
      addCard(slide, x, 4.95, w, 1.85, { fill });
      addText(slide, title, x + 0.25, 5.07, w - 0.5, 0.4, { fontSize: 14.5, bold: true, color });
      addText(slide, desc, x + 0.25, 5.5, w - 0.5, 1.25, { fontSize: 12.5 });
    });
  }

  // =====================================================================
  // 15. 得意・不得意の3群
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s3, '得意・不得意の3群 ― 異常と正常なばらつきの関係で決まる', [
      '得意・不得意をまとめると3つの群に分かれます。',
      `1つ目は、Radial や非対称のように正常な大きい変動と同じ向きの滑らかな異常で、M3S が最もよく、50% 検出できる振幅は ${V('mda_m3s_b1')}〜${V('mda_m3s_b2')}σ_dir でした。方向を知っている理想的な管理図の 2.33 に近い値です。`,
      `2つ目は係数の組み合わせの異常で、Mahalanobis が最もよく、係数 SPC は相関を使えないため劣りました。B6 の 50% 検出振幅は Mahalanobis ${V('mda_md_b6')}、係数 SPC ${V('mda_spc_b6')}σ_dir です。`,
      `3つ目は滑らかでない・局所的・高次の異常で、PCA T²・SPE・GPR 残差が強く、B9 は ${V('mda_t2_b9')}σ_dir で半分を検出しました。この群で最も難しい Scan 依存の B8 は、${V('mda_t2_b8')}σ_dir 必要でした。`,
      '下の表の κ が大きい形ほど、計測誤差だけの方向に異常が乗るので、計測値を白色化する手法が有利になります。',
    ]);
    const groups = [
      { title: '① 正常変動と同じ向きの滑らかな異常', patterns: 'B1 Radial・B2 Tangential・B4 非対称', best: 'M3S（低次の Mahalanobis も同程度）', fam: 'M1',
        rows: [['B1', V('mda_m3s_b1'), P1.mda50.B1.T2_raw_q99], ['B2', V('mda_m3s_b2'), P1.mda50.B2.T2_raw_q99]], head: ['', 'M3S', 'PCA T²'] },
      { title: '② 係数の組み合わせの異常', patterns: 'B5 高次・B6 組み合わせ・B10', best: 'Mahalanobis 距離', fam: 'M3',
        rows: [['B6', V('mda_md_b6'), V('mda_spc_b6')], ['B5', P1.mda50.B5.MD_d5, P1.mda50.B5.SPC_d4]], head: ['', 'Mahalanobis', '係数SPC'] },
      { title: '③ 滑らかでない・局所・高次', patterns: 'B3 局所・B7 表せない高次・B8 Scan・B9 単一 Shot', best: 'PCA T²・SPE・GPR 残差', fam: 'M4',
        rows: [['B9', V('mda_t2_b9'), V('mda_gpr_b9')], ['B8', V('mda_t2_b8'), P1.mda50.B8.GPR_rbf_full]], head: ['', 'PCA T²', 'GPR'] },
    ];
    const w = (CONTENT_W - 2 * 0.3) / 3;
    const fmt = (v) => (v === null || v === undefined ? '—' : typeof v === 'number' ? f1(v) : v);
    groups.forEach((g, i) => {
      const x = MARGIN_X + i * (w + 0.3);
      addCard(slide, x, 1.55, w, 4.35, { fill: FAMILY[g.fam].tint });
      addText(slide, g.title, x + 0.25, 1.68, w - 0.5, 0.75, { fontSize: 15, bold: true });
      addText(slide, g.patterns, x + 0.25, 2.45, w - 0.5, 0.6, { fontSize: 12.5, color: C.muted });
      addText(slide, `最もよい：${g.best}`, x + 0.25, 3.1, w - 0.5, 0.6, { fontSize: 13.5, bold: true, color: FAMILY[g.fam].color });
      const table = [tableHead(g.head, FAMILY[g.fam].color)].concat(g.rows.map(([p, a, b]) => [
        { text: p, options: { bold: true, align: 'center' } },
        { text: fmt(a), options: { align: 'center' } },
        { text: fmt(b), options: { align: 'center' } },
      ]));
      addStyledTable(slide, table, x + 0.25, 3.8, w - 0.5, [0.8, (w - 1.3) / 2, (w - 1.3) / 2], { fontSize: 12.5, rowH: 0.4 });
      addText(slide, '50% 検出の振幅 [σ_dir]（小さいほどよい。「—」は 16σ_dir でも届かない）', x + 0.25, 5.1, w - 0.5, 0.7, { fontSize: 10.5, color: C.muted });
    });
    addCard(slide, MARGIN_X, 6.1, CONTENT_W, 0.75, { fill: C.tint });
    addText(slide, `κ（相関を使うと有利になる度合い）：B3 ${f1(P1.kappa.B3)}・B9 ${f1(P1.kappa.B9)}・B7 ${f1(P1.kappa.B7)} は大きく、B1 ${f1(P1.kappa.B1)}・B5 ${f1(P1.kappa.B5)} は 1 に近い。κ が大きいほど計測値を白色化する手法（T²・SPE・GPR）が有利`,
      MARGIN_X + 0.3, 6.1, CONTENT_W - 0.6, 0.75, { fontSize: 12.5, valign: 'middle' });
  }

  // =====================================================================
  // 16. 経時変化：検出の速さ
  // =====================================================================
  {
    const best = P2.best;
    const items = best.map((d) => rank(d)).sort((a, b) => b.mean_rmst_delay - a.mean_rmst_delay);
    const slide = newContentSlide(SECTION.s4, '経時変化の検出の速さ ― 平滑化してから見る EWMA が最も早い', [
      '次に経時変化です。土台の手法ごとに、Shewhart・EWMA・CUSUM のうち最もよい方式を並べました。数字は変化が始まってから最初に警報が出るまでの枚数、RMST で、小さいほど早く気づけます。',
      `最も早かったのは、計測値を EWMA で平滑化してから PCA T² を当てる方法で ${V('p2_rmst_t2ewma')} 枚、次が同じく Mahalanobis 距離の ${V('p2_rmst_mdewma')} 枚でした。`,
      `M3S は CUSUM にすると ${V('p2_rmst_m3scusum')} 枚、そのまま各 Wafer を判定すると ${V('p2_rmst_m3sshew')} 枚です。`,
      `変化を入れない系列でも、ARL₀ = 370 では 200 枚の間に誤報が出るので、RMST は ${V('p2_null_min')}〜${V('p2_null_max')} 枚になります。これが比べる基準です。`,
    ]);
    slide.addChart(pres.charts.BAR, [{ name: 'RMST', labels: items.map((r) => detectorLabel(r.detector)), values: items.map((r) => Number(r.mean_rmst_delay.toFixed(1))) }], {
      x: MARGIN_X, y: 1.5, w: 8.0, h: 5.3, ...chartBase(), barDir: 'bar',
      chartColors: items.map((r) => FAMILY[baseFamily(r.detector)].color), showValue: true, dataLabelFormatCode: '0.0', dataLabelFontSize: 11, dataLabelColor: C.ink,
      valAxisMinVal: 0, valAxisMaxVal: 160, valAxisMajorUnit: 20, barGapWidthPct: 45, catAxisLabelFontSize: 11,
      showTitle: true, title: '平均 RMST 遅延 [枚]（小さいほど早い。各条件 1,000 系列）', showLegend: false,
    });
    const rx = 9.0;
    const rw = SLIDE_W - MARGIN_X - rx;
    addStat(slide, rx, 1.55, rw, 2.3, `${V('p2_rmst_t2ewma')} 枚`, '計測値の EWMA ＋ PCA T²', `λ = 0.05 で平滑化した地図に T² を当てる（MEWMA）。M3S は ${V('p2_rmst_m3sshew')} 枚`, { fill: FAMILY.M4.tint, color: FAMILY.M4.color, valueSize: 34 });
    addCard(slide, rx, 4.05, rw, 2.75, { fill: C.tint });
    addText(slide, '読み方', rx + 0.25, 4.17, rw - 0.5, 0.35, { fontSize: 13.5, bold: true, color: C.indigo });
    addBullets(slide, [
      `変化なしでも RMST は ${V('p2_null_min')}〜${V('p2_null_max')} 枚（誤報で警報が出るため）`,
      'どの土台でも EWMA か CUSUM が Shewhart より早い',
      'λ・k は独立な予備評価（200 系列）で選んだ',
    ], rx + 0.25, 4.57, rw - 0.5, 2.1, { fontSize: 12.5, space: 6 });
  }

  // =====================================================================
  // 17. 変化の種類別
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s4, '変化の種類と大きさ別 ― Step は早く、周期変動は難しい', [
      '時間変化の種類と大きさ別に見たのがこの図です。上が遅延、下が 200 枚以内に検出できなかった割合です。灰色の横線は変化を入れないときの値です。',
      `1σ_dir の Step 変化は、Mahalanobis の EWMA が ${V('p2_a1_1_mdewma')} 枚、PCA T² の EWMA が ${V('p2_a1_1_t2ewma')} 枚で検出したのに対し、M3S は ${V('p2_a1_1_m3s')} 枚でした。3σ_dir では EWMA の2つが ${V('p2_a1_3_mdewma')}・${V('p2_a1_3_t2ewma')} 枚です。`,
      `Ramp は変化が小さい初めのうちは見えず、3σ_dir でも PCA T² の EWMA で ${V('p2_a2_3_t2ewma')} 枚かかりました。`,
      `周期変動は符号が入れ替わるので平滑化しても積み上がりにくく、1σ_dir では多くの検出器が変化なしの基準に近い値でした（Mahalanobis の EWMA ${V('p2_a4_1_mdewma')} 枚、変化なし ${V('p2_null_mdewma')} 枚）。3σ_dir では Mahalanobis の EWMA が ${V('p2_a4_3_mdewma')} 枚で最も早く、SPE の EWMA は ${V('p2_a4_3_speewma')} 枚と遅れました。`,
    ]);
    addFigure(slide, 'figure07_detection_delay.png', MARGIN_X, 1.45, CONTENT_W, 5.45, '変化の種類と大きさ別の検出遅延と未検出率');
  }

  // =====================================================================
  // 18. 成分ごとの最速
  // =====================================================================
  {
    const comps = [['low', '低次'], ['high', '高次'], ['radial', 'Radial'], ['tangential', 'Tangential'], ['asymmetric', '非対称'], ['local', '局所']];
    const best = P2.best;
    const slide = newContentSlide(SECTION.s4, '変化する面内成分ごとの最速の検出器 ― 1枚の異常と同じ傾向', [
      '変化する面内成分ごとに見ると、最も早い検出器が違います。表の数字は平均の RMST で、太字が各成分で最も早い検出器です。',
      `局所変形は PCA SPE の EWMA が ${V('p2_local_speewma')} 枚と圧倒的に早く、1σ_dir の Step を中央値 ${V('p2_a1_local_1_speewma')} 枚で検出しました。M3S は ${V('p2_a1_local_1_m3s')} 枚です。`,
      `Radial・非対称・Tangential のような、正常なばらつきの大きい滑らかな成分は、M3S の CUSUM が最も早く、Radial で ${V('p2_radial_m3scusum')} 枚でした。`,
      `低次と高次の Zernike 成分は Mahalanobis の EWMA が最も早く、それぞれ ${V('p2_low_mdewma')}・${V('p2_high_mdewma')} 枚でした。1枚の異常の結果と同じ傾向です。`,
    ]);
    const minOf = Object.fromEntries(comps.map(([c]) => [c, Math.min(...best.map((d) => P2.by_component[d][c]))]));
    const table = [tableHead(['検出器', ...comps.map(([, l]) => l)])].concat(best.map((d) => [
      { text: detectorLabel(d), options: { bold: true, color: FAMILY[baseFamily(d)].color } },
      ...comps.map(([c]) => {
        const v = P2.by_component[d][c];
        const isBest = v === minOf[c];
        return { text: f1(v), options: { align: 'center', bold: isBest, fill: { color: isBest ? FAMILY[baseFamily(d)].tint : C.white } } };
      }),
    ]));
    addStyledTable(slide, table, MARGIN_X, 1.6, CONTENT_W, [3.7, ...comps.map(() => (CONTENT_W - 3.7) / comps.length)], { fontSize: 12.5, rowH: 0.5 });
    addText(slide, '平均 RMST 遅延 [枚]（A1〜A4 × 0.25〜3σ_dir の平均、1,000 系列）。色付きの太字が各成分で最も早い検出器', MARGIN_X, 5.7, CONTENT_W, 0.3, { fontSize: 11.5, color: C.muted });
    addCard(slide, MARGIN_X, 6.1, CONTENT_W, 0.72, { fill: C.tint });
    addText(slide, '局所的な変化 ＝ PCA SPE の EWMA、大きな滑らかな成分 ＝ M3S の CUSUM、Zernike の成分 ＝ Mahalanobis の EWMA。1つの検出器ですべては見られない',
      MARGIN_X + 0.3, 6.1, CONTENT_W - 0.6, 0.72, { fontSize: 13, bold: true, valign: 'middle' });
  }

  // =====================================================================
  // 19. 検出の例
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s4, '1つの系列での検出の様子 ― 平滑化すると小さな変化が積み上がる', [
      '1つの系列の例です。低次の Zernike 成分が、101 枚目から直線的に増える Ramp 変化を入れました。',
      '赤い横線が ARL₀ = 370 の管理限界、灰色の縦線が変化の後の最初の警報です。',
      '各 Wafer を独立に判定する M3S や PCA T² は、ばらつきの中に変化が埋もれ、たまたま大きく出た Wafer で警報が出ます。',
      'EWMA は過去を平均するので小さな変化が積み上がりますが、最初は 0 から立ち上がるので、その分も含めて管理限界を決めています。',
      'この系列では、Mahalanobis の EWMA が変化点の前にも一度限界を超えています。こうした系列は、遅延の集計からは除いています。',
      'なお、この1系列ではたまたま M3S の方が先に警報を出しています。1,000 系列の平均（p.16）で比べると、EWMA の方が早くなります。',
    ]);
    addFigure(slide, 'figure06_temporal_example.png', MARGIN_X, 1.45, 5.2, 5.45, '1系列での各検出器の統計量と管理限界');
    const rx = 6.4;
    const rw = SLIDE_W - MARGIN_X - rx;
    addNumberedCard(slide, rx, 1.6, rw, 1.55, 1, '各 Wafer の判定（Shewhart）', 'ばらつきの中に変化が埋もれ、たまたま大きく出た Wafer で警報が出る', { fill: C.gray, color: FAMILY.M2.color });
    addNumberedCard(slide, rx, 3.35, rw, 1.55, 2, 'EWMA（λ = 0.05）', '過去を平均するので小さな変化が積み上がる。最初は 0 から立ち上がる', { fill: C.gray, color: FAMILY.M7.color });
    addNumberedCard(slide, rx, 5.1, rw, 1.6, 3, 'CUSUM（k）', 'k を超えた分を累積。高次元の多変量 CUSUM は統計量がゆっくり育ち、感度が低かった', { fill: C.gray, color: FAMILY.M8.color });
  }

  // =====================================================================
  // 20. 時系列相関 ρ
  // =====================================================================
  {
    const rho = P2.rho;
    const keys = ['0', '0.3', '0.7', '0.95'];
    // AR(1) 残差の版は ρ = 0 を計算していないので、グラフは生の計測値の版だけにし、残差の版は右のカードに示す
    const series = [
      ['T2_raw_q99|EWMA(λ=0.05)', 'PCA T²・EWMA', FAMILY.M4.color],
      ['MD_d5|EWMA(λ=0.05)', 'Mahalanobis・EWMA', FAMILY.M3.color],
      ['MD_d5|CUSUM(k=1)', 'Mahalanobis・CUSUM', FAMILY.M8.color],
      ['T2_raw_q99|Shewhart', 'PCA T²・Shewhart', C.neutral],
      ['M3S_XY|Shewhart', 'M3S・Shewhart', FAMILY.M1.color],
    ];
    const slide = newContentSlide(SECTION.s4, '正常工程の時系列相関 ρ が強いと、EWMA の利点はほぼ消える', [
      '正常な工程そのものの時系列相関、ρ を 0 から 0.95 まで変えました。',
      `ρ が大きくなると、EWMA の遅延は大きく延びました。PCA T² の EWMA は ρ = 0 で ${V('rho_t2e_0')} 枚でしたが、ρ = 0.95 では ${V('rho_t2e_95')} 枚です。一方、各 Wafer を判定する方法はほとんど変わらず、${V('rho_t2s_0')} から ${V('rho_t2s_95')} 枚でした。`,
      `前の Wafer からの予測との差、AR(1) 残差を監視する方法も試しました。高次元の CUSUM は ${V('rho_mdc_95')} から ${V('rho_mdc_95_pw')} 枚に改善しましたが、EWMA は ${V('rho_t2e_95_pw')} 枚とほぼ同じで、各 Wafer の判定は悪化しました。`,
      '正常な工程がゆっくり動くと、平滑化しても正常な変動が残り、管理限界を広げるしかなくなるためです。',
    ]);
    slide.addChart(pres.charts.LINE, series.map(([d, name]) => ({
      name, labels: keys.map((k) => `ρ = ${k}`), values: keys.map((k) => rho[d].raw[k]),
    })), {
      x: MARGIN_X, y: 1.5, w: 7.8, h: 5.3, ...chartBase(),
      chartColors: series.map((item) => item[2]), lineSize: 2.25, lineDataSymbol: 'circle', lineDataSymbolSize: 7,
      valAxisMinVal: 40, valAxisMaxVal: 180, valAxisMajorUnit: 20, showLegend: true, legendPos: 'b',
      showTitle: true, title: '平均 RMST 遅延 [枚]（A1・A2 × 低次・局所、500 系列）',
      showValAxisTitle: true, valAxisTitle: '平均 RMST 遅延 [枚]',
    });
    const rx = 8.8;
    const rw = SLIDE_W - MARGIN_X - rx;
    addStat(slide, rx, 1.55, rw, 2.3, `${V('rho_t2e_0')} → ${V('rho_t2e_95')}`, 'PCA T² の EWMA [枚]', `ρ = 0 → 0.95。Shewhart は ${V('rho_t2s_0')} → ${V('rho_t2s_95')} 枚とほぼ不変`, { fill: FAMILY.M4.tint, color: FAMILY.M4.color, valueSize: 28 });
    addCard(slide, rx, 4.05, rw, 2.75, { fill: C.tint });
    addText(slide, 'AR(1) 残差で監視すると', rx + 0.25, 4.17, rw - 0.5, 0.35, { fontSize: 13.5, bold: true, color: C.indigo });
    addBullets(slide, [
      `高次元の CUSUM は改善（${V('rho_mdc_95')} → ${V('rho_mdc_95_pw')} 枚）`,
      `EWMA はほぼ同じ（${V('rho_t2e_95_pw')} 枚）`,
      `Shewhart は悪化（${V('rho_t2s_95_pw')} 枚）。持続的な変化が始まりの1回の跳びに変わるため`,
    ], rx + 0.25, 4.57, rw - 0.5, 2.15, { fontSize: 12.5, space: 6 });
  }

  // =====================================================================
  // 21. 計測条件：因子の効き方
  // =====================================================================
  {
    const labels = { density: '計測密度（点数）', layout: '計測配置', noise_scale: '計測ノイズ', order: '監視多項式の次数' };
    const slide = newContentSlide(SECTION.s5, '計測条件の影響 ― 効くのはノイズと点数。全体の平均では打ち消し合う', [
      '次に計測条件です。計測点数、配置、ノイズ、多項式の次数を1つずつ変え、条件ごとに手法を学習し直し、管理限界も決め直しました。異常の物理的な大きさは同じです。',
      `因子の効き方を、手法とパターンの組ごとの検出率の幅の平均で比べると、ノイズ ${V('p3_sens_noise')}、点数 ${V('p3_sens_density')}、次数 ${V('p3_sens_order')}、配置 ${V('p3_sens_layout')} の順でした。`,
      `一方、全パターンの平均検出率の幅は ${V('p3_range_noise')}・${V('p3_range_density')} と小さく見えます。条件を変えると良くなるパターンと悪くなるパターンがあり、平均では打ち消し合うためです。`,
      '計測条件の評価は、異常の種類ごとに見る必要があります。',
    ]);
    const table = [tableHead(['因子', '検出率の幅（平均）', '幅の最大', '全体の平均検出率'])].concat(P3.effects.map((e) => [
      { text: labels[e.factor], options: { bold: true } },
      { text: f2(e.sensitivity), options: { align: 'center', bold: true } },
      { text: f2(e.max_cell_range), options: { align: 'center' } },
      { text: `${f2(e.min_mean_detection)}〜${f2(e.max_mean_detection)}`, options: { align: 'center' } },
    ]));
    addStyledTable(slide, table, MARGIN_X, 1.6, 7.6, [2.3, 2.3, 1.2, 1.8], { fontSize: 13, rowH: 0.55 });
    addText(slide, '幅：手法（PCA T²・GPR・Mahalanobis）× パターンごとに、水準を変えたときの検出率（全振幅の平均）の最大 − 最小', MARGIN_X, 4.45, 7.6, 0.5, { fontSize: 11.5, color: C.muted });
    const bars = P3.effects.map((e) => ({ name: labels[e.factor], value: e.sensitivity }));
    slide.addChart(pres.charts.BAR, [{ name: '幅', labels: bars.map((b) => b.name).reverse(), values: bars.map((b) => Number(b.value.toFixed(3))).reverse() }], {
      x: 8.5, y: 1.5, w: SLIDE_W - MARGIN_X - 8.5, h: 3.4, ...chartBase(), barDir: 'bar', chartColors: [C.indigo],
      showValue: true, dataLabelFormatCode: '0.00', dataLabelFontSize: 11, valAxisMinVal: 0, valAxisMaxVal: 0.2, valAxisMajorUnit: 0.05,
      showTitle: true, title: '因子の効き方', showLegend: false, catAxisLabelFontSize: 11,
    });
    addCard(slide, MARGIN_X, 5.15, CONTENT_W, 1.45, { fill: C.night });
    addText(slide, '要点', MARGIN_X + 0.35, 5.27, 2, 0.35, { fontSize: 13.5, bold: true, color: C.indigoLight });
    addText(slide, '滑らかな低次の異常は、点数やノイズを変えてもほとんど変わらない。局所的・滑らかでない異常（単一 Shot・Scan 依存・高次）は大きく下がる。配置の工夫の効果は小さい',
      MARGIN_X + 0.35, 5.65, CONTENT_W - 0.7, 0.85, { fontSize: 15, bold: true, color: C.white });
  }

  // =====================================================================
  // 22. 計測点数
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s5, '計測点数 ― 局所的な異常は「何 Shot 測るか」で決まる', [
      `計測点を全点の 316 点から 25%、80 点に減らすと、局所的・滑らかでない異常の検出率が大きく下がりました。PCA T² で、単一 Shot の異常は ${V('p3_t2_b9_full')} から ${V('p3_t2_b9_25')}、Scan 依存は ${V('p3_t2_b8_full')} から ${V('p3_t2_b8_25')} です。`,
      `一方、滑らかな低次の異常と Mahalanobis 距離はほとんど変わらず、全パターンの平均で ${V('p3_md_all_full')} から ${V('p3_md_all_25')} でした。`,
      '25% のマップでは 97 Shot のうち 20 Shot しか測らないので、無作為な1 Shot の異常がそもそも測られる確率は約2割しかありません。',
      '局所的な異常の監視には、配置の工夫よりも、どれだけ多くの Shot を測るかが効きます。',
    ]);
    addFigure(slide, 'figure08_measurement_points.png', MARGIN_X, 1.45, 8.9, 5.45, '計測点数と検出率');
    const rx = 9.75;
    const rw = SLIDE_W - MARGIN_X - rx;
    addStat(slide, rx, 1.55, rw, 2.2, `${V('p3_t2_b9_full')} → ${V('p3_t2_b9_25')}`, '単一 Shot の検出率', 'PCA T²、全点（316 点）→ 25%（80 点）', { fill: C.badTint, color: C.bad, valueSize: 28 });
    addStat(slide, rx, 3.95, rw, 2.2, `${V('p3_md_all_full')} → ${V('p3_md_all_25')}`, 'Mahalanobis の平均', '全パターンの平均。滑らかな異常は 80 点でも推定できる', { fill: FAMILY.M3.tint, color: FAMILY.M3.color, valueSize: 28 });
    addText(slide, '20 Shot しか測らないと、無作為な1 Shot の異常が測られる確率は約2割', rx, 6.3, rw, 0.6, { fontSize: 11.5, color: C.muted });
  }

  // =====================================================================
  // 23. 計測ノイズ
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s5, '計測ノイズ ― 局所的な異常に効く。減っても T² が下がることがある', [
      `ノイズを3倍にすると、局所的・高次の異常の検出率が下がりました。PCA T² で、単一 Shot は ${V('p3_t2_b9_full')} から ${V('p3_t2_b9_n3')}、Scan 依存は ${V('p3_t2_b8_full')} から ${V('p3_t2_b8_n3')} です。M3S と Mahalanobis はほとんど変わりませんでした。`,
      `意外だったのは、ノイズを半分にすると PCA T² の単一 Shot の検出率が逆に ${V('p3_t2_b9_n05')} に下がったことです。GPR 残差は ${V('p3_gpr_b9_n05')} まで上がっています。`,
      `原因は主成分の数の決め方です。寄与率 99% で決めると、主成分の数は基準ノイズの ${V('p3_k_t2_n1')} 個から、ノイズ半分では ${V('p3_k_t2_n05')} 個に減りました。計測誤差の方向が T² から外れ、局所的な異常は SPE の側に移ります。`,
      'T² だけに頼らず、SPE や GPR 残差と必ず組み合わせることが必要です。',
    ]);
    addFigure(slide, 'figure09_measurement_noise.png', MARGIN_X, 1.45, 8.9, 5.45, '計測ノイズと検出率');
    const rx = 9.75;
    const rw = SLIDE_W - MARGIN_X - rx;
    addStat(slide, rx, 1.55, rw, 2.2, `${V('p3_t2_b9_full')} → ${V('p3_t2_b9_n3')}`, '単一 Shot（PCA T²）', 'ノイズ 1倍 → 3倍', { fill: C.badTint, color: C.bad, valueSize: 28 });
    addCard(slide, rx, 3.95, rw, 2.85, { fill: C.warnTint });
    addText(slide, '寄与率 99% の主成分の数', rx + 0.25, 4.07, rw - 0.5, 0.35, { fontSize: 13, bold: true });
    const comps = P3.pca_components;
    addStyledTable(slide, [tableHead(['ノイズ', '主成分'], FAMILY.M5.color), ...['0.5', '1', '2', '3'].map((k) => [
      { text: `${k}×`, options: { align: 'center' } }, { text: String(comps[k]), options: { align: 'center', bold: true } }])], rx + 0.25, 4.5, rw - 0.5, [1.1, rw - 1.6], { fontSize: 12, rowH: 0.36 });
    addText(slide, '寄与率で決めると、ノイズで T² の性質が変わる', rx + 0.25, 6.35, rw - 0.5, 0.4, { fontSize: 11.5, color: C.muted });
  }

  // =====================================================================
  // 24. 配置・次数・経時変化
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s5, '配置・多項式の次数・経時変化への影響', [
      `同じ 80 点で、実計測風・均等・D 最適・I 最適の配置を比べると、差は小さく、手法とパターンの組ごとの差は最大でも ${V('p3_layout_max')} でした。D 最適や I 最適は係数の推定精度を上げる配置ですが、異常検知では異常のある場所を測っているかの方が効きます。`,
      `監視多項式の次数は、表したい異常の形を表せる次数が必要です。Mahalanobis 距離は、n = 4〜5 の Zernike の異常 B5 を、3次では ${V('p3_md_b5_o3')}、5次では ${V('p3_md_b5_o5')} 検出しました。`,
      `経時変化の検知は、点数やノイズの影響が小さく、PCA T² の EWMA は全点 ${V('p3t_t2_full')} 枚に対し、25% で ${V('p3t_t2_25')} 枚、ノイズ3倍で ${V('p3t_t2_n3')} 枚でした。複数の Wafer を平均するので、計測の間引きにある程度強いと考えられます。`,
    ]);
    const lay = P3.layout;
    const layoutNames = [['realistic', '実計測風'], ['uniform', '均等'], ['d_optimal', 'D最適'], ['i_optimal', 'I最適']];
    const temporalT2 = (level) => P3.temporal[level]['T2_raw_q99|EWMA(λ=0.05)'];
    const w = (CONTENT_W - 2 * 0.3) / 3;
    const center = (text) => ({ text, options: { align: 'center' } });
    const cards = [
      { title: '計測配置（同じ 80 点）', fam: 'M2', value: `最大 ${V('p3_layout_max')}`, label: '手法 × パターンごとの検出率の差',
        head: ['配置', 'T²', 'MD', 'GPR'], colW: [1.3, (w - 1.8) / 3, (w - 1.8) / 3, (w - 1.8) / 3],
        rows: layoutNames.map(([k, l]) => [{ text: l, options: { bold: true } }, center(f2(lay[k].T2_raw_q99)), center(f2(lay[k].MD_d5)), center(f2(lay[k].GPR_rbf_full))]),
        note: '平均検出率（B1〜B10・1〜16σ_dir）。配置による差は小さい' },
      { title: '監視多項式の次数', fam: 'M3', value: `${V('p3_md_b5_o3')} → ${V('p3_md_b5_o5')}`, label: 'B5（n = 4〜5）の検出率：3次 → 5次',
        head: ['異常', '3次', '5次'], colW: [1.7, (w - 2.2) / 2, (w - 2.2) / 2],
        rows: [
          [{ text: 'B5 高次 Zernike', options: { bold: true } }, center(V('p3_md_b5_o3')), center(V('p3_md_b5_o5'))],
          [{ text: 'B4 非対称', options: { bold: true } }, center(V('p3_md_b4_o3')), center(V('p3_md_b4_o5'))],
        ],
        note: 'Mahalanobis 距離の検出率（1〜16σ_dir の平均）。表したい形を表せる次数が必要。必要以上に高い次数は、低次の異常の感度を少し下げる' },
      { title: '経時変化の検知', fam: 'M7', value: `${V('p3t_t2_full')} → ${V('p3t_t2_25')} 枚`, label: 'PCA T² の EWMA：全点 → 25%',
        head: ['条件', 'RMST [枚]'], colW: [1.9, w - 2.4],
        rows: [
          [{ text: '全点', options: { bold: true } }, center(V('p3t_t2_full'))],
          [{ text: '50%', options: { bold: true } }, center(f1(temporalT2('density0.5_realistic_noise1_orderown')))],
          [{ text: '25%', options: { bold: true } }, center(V('p3t_t2_25'))],
          [{ text: 'ノイズ 0.5 倍', options: { bold: true } }, center(V('p3t_t2_n05'))],
          [{ text: 'ノイズ 3 倍', options: { bold: true } }, center(V('p3t_t2_n3'))],
        ],
        note: `間引きの影響は1枚の判定より小さい。局所成分の SPE の EWMA はノイズ 3 倍で ${V('p3t_spe_local_full')} → ${V('p3t_spe_local_n3')} 枚と遅れる` },
    ];
    cards.forEach((card, i) => {
      const x = MARGIN_X + i * (w + 0.3);
      addCard(slide, x, 1.6, w, 5.2, { fill: FAMILY[card.fam].tint });
      addText(slide, card.title, x + 0.25, 1.75, w - 0.5, 0.4, { fontSize: 15, bold: true, color: FAMILY[card.fam].color });
      addText(slide, card.value, x + 0.25, 2.25, w - 0.5, 0.8, { fontSize: 28, bold: true, color: FAMILY[card.fam].color, valign: 'middle' });
      addText(slide, card.label, x + 0.25, 3.1, w - 0.5, 0.6, { fontSize: 12.5, bold: true });
      const table = [tableHead(card.head, FAMILY[card.fam].color)].concat(card.rows);
      addStyledTable(slide, table, x + 0.25, 3.7, w - 0.5, card.colW, { fontSize: 11.5, rowH: 0.36 });
      const noteY = 3.7 + table.length * 0.36 + 0.2;
      addText(slide, card.note, x + 0.25, noteY, w - 0.5, 6.65 - noteY, { fontSize: 11.5, color: C.muted });
    });
  }

  // =====================================================================
  // 25. APC 補正のモデル
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s6, 'APC 補正の影響 ― 補正前・補正係数・補正後残差の3か所で監視', [
      '最後の結果は APC 補正の影響です。Wafer ごとの補正を理想化したモデルで調べました。',
      `Alignment の ${V('apc_n_align')} 点に多項式を当てはめて補正量を決め、別の Overlay 検証点 ${V('apc_n_overlay')} 点で、補正の後に残るずれを Overlay 残差としました。補正に使う点と評価する点を分けています。`,
      '補正の次数は1次、3次、5次です。監視する場所は、補正前の Alignment、推定した補正係数、補正後の Overlay 残差の3か所です。',
      '異常は、補正で消えるもの、消えないもの、Alignment の計測の外れ値の4種類を入れました。',
    ]);
    const boxes = [
      ['潜在的なずれ', '正常な面内傾向 ＋ 異常', C.gray, C.ink],
      [`Alignment 計測（${V('apc_n_align')} 点）`, '① 補正前を監視', FAMILY.M2.tint, FAMILY.M2.color],
      ['補正係数（多項式）', '② 補正量を監視', FAMILY.M3.tint, FAMILY.M3.color],
      [`Overlay 残差（${V('apc_n_overlay')} 点）`, '③ 補正後を監視', FAMILY.M4.tint, FAMILY.M4.color],
    ];
    const bw = 2.65;
    const gap = (CONTENT_W - 4 * bw) / 3;
    boxes.forEach(([title, sub, fill, color], i) => {
      const x = MARGIN_X + i * (bw + gap);
      addCard(slide, x, 1.6, bw, 1.5, { fill, line: color === C.ink ? C.line : color });
      addText(slide, title, x + 0.15, 1.72, bw - 0.3, 0.75, { fontSize: 14, bold: true, align: 'center', valign: 'middle' });
      addText(slide, sub, x + 0.15, 2.5, bw - 0.3, 0.45, { fontSize: 12.5, bold: true, color, align: 'center', valign: 'middle' });
      if (i < boxes.length - 1) addLine(slide, x + bw + 0.05, 2.35, x + bw + gap - 0.05, 2.35, { color: C.neutral, width: 2, arrow: true });
    });
    addFormulaCard(slide, 'apc', MARGIN_X, 3.35, CONTENT_W, 0.75, { fill: C.tint, scale: 0.9, alt: 'r = (f_O + ε_O) − X_O ĉ、ĉ = argmin ||y_A − X_A c||²' });
    const rows = [
      ['S1', '低次補正で消える', 'X 方向だけの倍率（1次）', '1次以上で消える'],
      ['S2', '高次補正で消える', '3次の放射状歪み', '3次以上で消える'],
      ['S3', '補正で表せない', 'n = 8〜9 の Zernike・局所変形・単一 Shot', 'どの次数でも残る'],
      ['S4', '計測の外れ値', 'Alignment の1マークだけの外れ値（実際のずれはない）', '補正が引っ張られる'],
    ];
    const table = [tableHead(['', 'シナリオ', '異常', '補正で'])].concat(rows.map(([id, cat, desc, note]) => [
      { text: id, options: { bold: true, align: 'center' } }, { text: cat, options: { bold: true } }, { text: desc }, { text: note, options: { align: 'center' } },
    ]));
    addStyledTable(slide, table, MARGIN_X, 4.3, CONTENT_W, [0.7, 2.6, 6.0, CONTENT_W - 9.3], { fontSize: 12.5, rowH: 0.45 });
    addText(slide, `「ノイズを過学習する条件」として、Alignment を ${V('apc_n_align_sparse')} 点・計測誤差 3 倍にした条件も比べた`, MARGIN_X, 6.6, CONTENT_W, 0.3, { fontSize: 11.5, color: C.muted });
  }

  // =====================================================================
  // 26. 補正で隠れる異常
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s6, '補正で消える異常は、補正後の Overlay 残差では見えない', [
      'Figure 10 の下の3つの表は、補正次数ごとの、監視する場所と異常の組み合わせの検出率です。',
      `補正で消える異常は、補正後の Overlay 残差では見えなくなりました。線形の異常は全ての補正次数で、3次の放射状歪みは3次以上の補正で、残差の M3S の検出率が ${V('apc_s2_ovl_m3s_o3')} まで下がりました。誤報率と同じです。`,
      `同じ異常を、補正前の Alignment の M3S は ${V('apc_s2_align_m3s')}、補正係数の Mahalanobis は ${V('apc_s2_coef_md_o3')} 検出しました。`,
      `補正で表せない局所変形は残差に残り、3次補正のときの残差の PCA T² で ${V('apc_s3local_ovl_t2_o3')} 検出しました。このときの真の残差の大きさは、補正で消える異常では正常時（${V('apc_normal_rms_o3')} nm）とほぼ同じでした。`,
    ]);
    addFigure(slide, 'figure10_apc_comparison.png', MARGIN_X, 1.45, 8.6, 5.45, 'APC補正前後の比較と監視対象ごとの検出率');
    const rx = 9.4;
    const rw = SLIDE_W - MARGIN_X - rx;
    const stats = [
      [V('apc_s2_ovl_m3s_o3'), '補正後の残差（M3S）', '3次補正・3次の放射状歪み', C.badTint, C.bad],
      [V('apc_s2_coef_md_o3'), '補正係数（Mahalanobis）', '同じ異常', FAMILY.M3.tint, FAMILY.M3.color],
      [V('apc_s3local_ovl_t2_o3'), '補正後の残差（PCA T²）', '補正で表せない局所変形', FAMILY.M4.tint, FAMILY.M4.color],
    ];
    stats.forEach(([value, name, desc, fill, color], i) => {
      const y = 1.55 + i * 1.62;
      addCard(slide, rx, y, rw, 1.45, { fill });
      addText(slide, value, rx + 0.25, y + 0.1, rw - 0.5, 0.65, { fontSize: 28, bold: true, color, valign: 'middle' });
      addText(slide, name, rx + 0.25, y + 0.78, rw - 0.5, 0.35, { fontSize: 13, bold: true });
      addText(slide, desc, rx + 0.25, y + 1.13, rw - 0.5, 0.35, { fontSize: 11.5, color: C.muted });
    });
    addText(slide, '検出率は 1〜16σ_dir の平均、誤報率 1%', rx, 6.4, rw, 0.3, { fontSize: 10.5, color: C.muted });
  }

  // =====================================================================
  // 27. 経時変化の隠蔽と過学習
  // =====================================================================
  {
    const T = APC.temporal;
    const rowsDef = [
      ['alignment:T2|EWMA(λ=0.1)', '補正前 Alignment の PCA T²', 'M2'],
      ['coefficient:MD|EWMA(λ=0.1)', '補正係数の Mahalanobis', 'M3'],
      ['overlay:T2|EWMA(λ=0.1)', '補正後残差の PCA T²', 'M4'],
      ['overlay:SPE|EWMA(λ=0.1)', '補正後残差の PCA SPE', 'M5'],
    ];
    const slide = newContentSlide(SECTION.s6, 'ドリフトも隠れる。点が少ないと高次補正は誤差を取り込む', [
      `Wafer ごとの3次補正の下で、Ramp 変化を EWMA で監視しました。補正で消える低次と Radial の変化は、補正後の残差では変化なしと同じ程度の遅延、例えば ${V('apc_t_low_ovl_t2')} 枚にとどまり、事実上見えませんでした。`,
      `同じ変化を、補正前の Alignment の PCA T² は ${V('apc_t_low_align_t2')} 枚、補正係数の Mahalanobis は ${V('apc_t_low_coef_md')} 枚で検出しています。`,
      `一方、点の少ない Alignment に5次の補正をすると、計測誤差を補正に取り込み、正常時の真の残差は ${V('apc_sparse_rms_o3')} nm から ${V('apc_sparse_rms_o5')} nm に増えました。残差のばらつきが増えるので、局所変形の検出率も ${V('apc_sparse_s3local_t2_o3')} から ${V('apc_sparse_s3local_t2_o5')} に下がりました。`,
      '補正後の残差だけを監視すると、補正で追従できている変化に気づけません。補正係数と残差を並べて監視する必要があります。',
    ]);
    addText(slide, 'Ramp 変化の平均 RMST 遅延 [枚]（3次補正、0.5〜2σ_dir、300 系列）', MARGIN_X, 1.55, 7.2, 0.35, { fontSize: 13.5, bold: true, color: C.indigo });
    const table = [tableHead(['監視する場所（EWMA）', '低次', 'Radial', '局所'])].concat(rowsDef.map(([d, name, fam]) => [
      { text: name, options: { bold: true, color: FAMILY[fam].color } },
      ...['low', 'radial', 'local'].map((c) => ({ text: f1(T[d][c]), options: { align: 'center' } })),
    ]));
    addStyledTable(slide, table, MARGIN_X, 1.95, 7.2, [2.7, 1.5, 1.5, 1.5], { fontSize: 12.5, rowH: 0.5 });
    addText(slide, `低次・Radial は補正で消える変化、局所は残る変化。変化なしの系列の RMST は ${f1(APC.temporal_null[0])}〜${f1(APC.temporal_null[1])} 枚で、補正後残差の低次・Radial はこれと同じ程度＝見えていない`, MARGIN_X, 4.55, 7.2, 0.7, { fontSize: 11.5, color: C.muted });
    addCard(slide, MARGIN_X, 5.3, 7.2, 1.5, { fill: C.tint });
    addText(slide, '補正係数（補正量）の経時変化と補正後の残差を両方監視すれば、「補正で追従できている変化」と「補正で取り切れない変化」を区別できる',
      MARGIN_X + 0.25, 5.3, 6.7, 1.5, { fontSize: 13.5, bold: true, valign: 'middle' });
    const rx = 8.2;
    const rw = SLIDE_W - MARGIN_X - rx;
    addText(slide, '過学習の条件（Alignment 40 点・誤差 3 倍）', rx, 1.55, rw, 0.35, { fontSize: 13.5, bold: true, color: C.indigo });
    addStat(slide, rx, 1.95, rw, 2.25, `${V('apc_sparse_rms_o3')} → ${V('apc_sparse_rms_o5')} nm`, '正常時の真の残差 RMS', '3次 → 5次補正。高次補正が計測誤差を取り込み、重ね合わせ自体が悪くなる', { fill: C.badTint, color: C.bad, valueSize: 26 });
    addStat(slide, rx, 4.4, rw, 2.4, `${V('apc_sparse_s3local_t2_o3')} → ${V('apc_sparse_s3local_t2_o5')}`, '局所変形の検出率', '残差の PCA T²、3次 → 5次補正。残差のばらつきが増えて、異常も見えにくくなる', { fill: C.warnTint, color: FAMILY.M5.color, valueSize: 26 });
  }

  // =====================================================================
  // 28. 6つの問いへの答え
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s7, '6つの問いへの答え', [
      'ここまでの結果を、6つの問いへの答えとしてまとめます。',
      `RQ1、M3S が見逃す形状異常には計測値の PCA T² が最も有効で、平均 ${V('p1_blind_t2q99')} でした。ただし平均と分散が同じ形の変化には Mahalanobis が最もよく、種類によって違います。`,
      `RQ2、経時変化は計測値の EWMA と PCA T² の組み合わせが最も早く、${V('p2_rmst_t2ewma')} 枚でした。ただし工程の時系列相関が強いと利点は小さくなります。`,
      'RQ3、異常の種類による違いは大きく、3つの群に分かれました。RQ4、点数とノイズは局所的な異常に強く効き、配置の差は小さい結果でした。',
      `RQ5、補正後の Overlay だけでは補正で消える異常とそのドリフトを見逃します。RQ6、1つの手法では足りず、組み合わせると平均 ${V('p1_or_mean')} まで上がりました。`,
    ]);
    const rows = [
      ['RQ1', 'M3S が見逃す形状異常に有効な手法', `計測値の PCA T²（7種類の平均 ${V('p1_blind_t2q99')}、M3S ${V('p1_blind_m3s')}）。平均・分散が同じ形の変化は Mahalanobis（${V('b10_md4_8')}）`],
      ['RQ2', '経時変化を最も早く検知する手法', `計測値の EWMA ＋ PCA T²（${V('p2_rmst_t2ewma')} 枚、M3S ${V('p2_rmst_m3sshew')} 枚）。局所は SPE の EWMA。ρ が大きいと利点が小さい`],
      ['RQ3', '異常の種類による違い', '大きい。正常変動と同じ向き＝M3S、係数の組み合わせ＝Mahalanobis、局所・高次＝T²・SPE・GPR'],
      ['RQ4', '計測点数・ノイズの影響', `局所的な異常で大きい（単一 Shot：${V('p3_t2_b9_full')} → 25% で ${V('p3_t2_b9_25')}、ノイズ3倍で ${V('p3_t2_b9_n3')}）。配置の差は小さい`],
      ['RQ5', 'APC 後の Overlay だけで見逃すもの', `補正で消える異常とそのドリフト（${V('apc_s2_ovl_m3s_o3')}＝誤報並み）。補正係数・補正前 Alignment が必要`],
      ['RQ6', '1つの手法で十分か', `不十分。5指標の OR 統合で ${V('p1_or_mean')}（単独の最良 ${V('p1_t2q99_mean')}）`],
    ];
    const table = [tableHead(['', '問い', '答え（模擬データの結果）'])].concat(rows.map(([id, q, a]) => [
      { text: id, options: { bold: true, align: 'center', color: C.indigo } }, { text: q, options: { bold: true } }, { text: a },
    ]));
    addStyledTable(slide, table, MARGIN_X, 1.55, CONTENT_W, [0.85, 3.4, CONTENT_W - 4.25], { fontSize: 12.5, rowH: [0.45, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8] });
  }

  // =====================================================================
  // 29. 推奨する監視の構成
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s7, '推奨する監視の構成 ― 1枚の判定・経時変化・APC の3層で組み合わせる', [
      '結果に基づく推奨は、3つの層の組み合わせです。',
      `1つ目の層は1枚の判定で、M3S・Mahalanobis・PCA T²・SPE・GPR 残差を OR でまとめ、まとめた後の誤報率で限界を決めます。平均検出率は ${V('p1_or_mean')} でした。ただしこの組み合わせは Phase 1 の結果を見て選んだので、少し有利に出ている可能性があります。`,
      '2つ目の層は経時変化で、計測値を EWMA で平滑化した地図に PCA T² や Mahalanobis を当て、局所的な変化には SPE の EWMA を加えます。',
      '3つ目の層は APC の下での監視で、補正係数と補正後の残差を並べて見ます。',
      '警報が出たら、係数 SPC や GPR 残差の地図で、どの係数・どの Shot が原因かを確かめる使い方を想定しています。',
    ]);
    const layers = [
      { title: '1枚の判定（突発的な異常）', fam: 'OR', items: ['M3S・Mahalanobis・PCA T²・SPE・GPR 残差を OR で統合', '統合した後の誤報率で管理限界を決める', `平均検出率 ${V('p1_or_mean')}（単独の最良 ${V('p1_t2q99_mean')}）`] },
      { title: '経時変化（継続的な変化）', fam: 'M7', items: ['計測値の EWMA（λ = 0.05）＋ PCA T²・Mahalanobis（MEWMA）', '局所的な変化には PCA SPE の EWMA を加える', '工程の時系列相関が強いときは効果が小さい'] },
      { title: 'APC の下での監視', fam: 'M3', items: ['補正係数（または補正前 Alignment）と補正後残差を並べる', '補正で追従できる変化 ／ 取り切れない変化を区別', '補正次数は Alignment の点数・誤差に合わせる'] },
    ];
    const w = (CONTENT_W - 2 * 0.3) / 3;
    layers.forEach((layer, i) => {
      const x = MARGIN_X + i * (w + 0.3);
      addCard(slide, x, 1.6, w, 3.8, { fill: FAMILY[layer.fam].tint });
      addNode(slide, x + 0.5, 2.1, 0.62, FAMILY[layer.fam].color, String(i + 1), { fontSize: 18 });
      addText(slide, layer.title, x + 0.95, 1.78, w - 1.15, 0.65, { fontSize: 15, bold: true, valign: 'middle' });
      addBullets(slide, layer.items, x + 0.3, 2.7, w - 0.55, 2.6, { fontSize: 15, space: 12 });
    });
    addCard(slide, MARGIN_X, 5.65, CONTENT_W, 1.15, { fill: C.gray });
    addText(slide, '警報の後：係数 SPC（どの係数が動いたか）と GPR 残差の地図（どの Shot・Mark が外れたか）で原因を確かめる。下側の異常（普段より平ら）は別の判定が必要',
      MARGIN_X + 0.3, 5.65, CONTENT_W - 0.6, 1.15, { fontSize: 14, valign: 'middle' });
  }

  // =====================================================================
  // 30. 限界と次のステップ
  // =====================================================================
  {
    const slide = newContentSlide(SECTION.s7, '限界と次のステップ', [
      '最後に、この検証の限界と次のステップです。',
      '正常な工程の大きさ、計測ノイズ、時系列相関 ρ = 0.7、ARL₀ = 370 などの数値は仮定です。実データで正常モデルを学習し直す必要があります。',
      'APC は Wafer ごとの補正を理想化したもので、ロットをまたぐフィードバック制御は入れていません。',
      'ρ の比較や Phase 3 と APC の経時変化は条件を絞って計算しました。全条件の拡大版の設定は用意してありますが、まだ実行していません。',
      '次のステップとして、実データでの検証、下側の異常の監視、多変量 CUSUM の参照値の決め方、主成分の数の決め方の見直しを考えています。',
    ]);
    const cards = [
      ['仮定の確認', ['正常工程の大きさ・計測ノイズの値', '時系列相関 ρ = 0.7、ARL₀ = 370', '実計測マップに準じた配置の決め方'], C.warnTint, FAMILY.M5.color],
      ['モデルと規模の限界', ['APC は Wafer ごとの補正を理想化（ロット間の R2R は未評価）', 'ρ・Phase 3・APC の経時変化は縮小した条件', '拡大版（full_experiment.yaml）は未実行'], C.badTint, C.bad],
      ['次のステップ', ['実データ（複数ロット）で正常モデルを学習し直して比較', '下側の異常の監視、多変量 CUSUM の参照値', '主成分の数を固定した PCA、R2R APC の下での監視'], C.goodTint, C.good],
    ];
    const w = (CONTENT_W - 2 * 0.3) / 3;
    cards.forEach(([title, items, fill, color], i) => {
      const x = MARGIN_X + i * (w + 0.3);
      addCard(slide, x, 1.6, w, 3.9, { fill });
      addText(slide, title, x + 0.3, 1.8, w - 0.6, 0.45, { fontSize: 17, bold: true, color });
      addBullets(slide, items, x + 0.3, 2.45, w - 0.6, 2.9, { fontSize: 15, space: 14 });
    });
    addCard(slide, MARGIN_X, 5.75, CONTENT_W, 1.05, { fill: C.tint });
    addText(slide, '確認済みのこと：自動テスト 59 件（誤報率の校正、異常の大きさ、乱数の再現性など）。資料とレポートの数値は同じ計算結果の CSV から自動で入れており、手で書き写していない',
      MARGIN_X + 0.3, 5.75, CONTENT_W - 0.6, 1.05, { fontSize: 13.5, valign: 'middle' });
  }

  // =====================================================================
  // 31. まとめ
  // =====================================================================
  {
    const slide = pres.addSlide();
    nextPage();
    slide.background = { color: C.night };
    addText(slide, 'まとめ', 0.8, 0.9, 6, 0.6, { fontSize: 30, bold: true, color: C.white });
    const points = [
      ['M3S だけでは足りない', `M3S が見逃す形状異常を、計測値の PCA T² は ${V('p1_blind_t2q99')} 検出（M3S ${V('p1_blind_m3s')}）。平均・分散が同じ形の変化は M3S では原理的に見えない`],
      ['異常の種類で手法を選ぶ', '正常変動と同じ向き＝M3S、係数の組み合わせ＝Mahalanobis、局所・高次＝PCA T²・SPE・GPR 残差'],
      ['経時変化は平滑化してから見る', `計測値の EWMA ＋ PCA T² が最速（${V('p2_rmst_t2ewma')} 枚、M3S ${V('p2_rmst_m3sshew')} 枚）。局所的な変化は SPE の EWMA`],
      ['補正の後だけ見ない', '補正で消える異常とドリフトは、補正後の Overlay 残差では見えない。補正係数も監視する'],
      ['組み合わせる', `5指標の OR 統合で平均検出率 ${V('p1_or_mean')}。1枚の判定・経時変化・APC の3層で監視する`],
    ];
    points.forEach(([title, desc], i) => {
      const y = 1.75 + i * 0.98;
      addNode(slide, 1.15, y + 0.32, 0.5, C.indigoLight, String(i + 1), { fontSize: 15, color: C.night });
      addText(slide, title, 1.65, y, 3.9, 0.65, { fontSize: 16, bold: true, color: C.white, valign: 'middle' });
      addText(slide, desc, 5.6, y, 7.0, 0.8, { fontSize: 13.5, color: C.onDarkSub, valign: 'middle' });
    });
    addText(slide, `資料の数値：模擬データによるシミュレーション（${DECK_TITLE}、技術レポート reports/technical_report.md）`, 0.8, 6.75, 11.5, 0.35, { fontSize: 11, color: C.indigoLight });
    slide.addNotes([
      'まとめです。',
      'M3S だけでは、面内の形の異常の多くを見逃します。平均と分散が同じ形の変化は、M3S では原理的に見えません。',
      '異常の種類によって得意な手法が違うので、種類に応じて選ぶ、あるいは組み合わせることが必要です。',
      '経時変化は、計測値を平滑化してから多変量の統計量を当てる方法が最も早く気づけます。',
      'APC の下では、補正の後の残差だけでなく、補正係数も監視してください。',
      'これらは模擬データの結果なので、実データで正常モデルを学習し直して確かめることが次のステップです。',
    ].join('\n'));
  }
};
