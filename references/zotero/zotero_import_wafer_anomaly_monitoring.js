// Wafer 面内傾向の異常検知手法の比較検証（2026-10-13）の技術レポートで引用した参考文献を Zotero に登録する。
//
// 使い方（詳しくは同じフォルダの README.md）:
//   Zotero の［ツール］→［開発］→［JavaScriptを実行］を開き、「Run as async」にチェックを入れて、
//   このファイルの中身をすべて貼り付けて「Run」を押す。
//
// することは次の3つだけ。既存の項目の中身・タグ・コレクションを消したり書き換えたりはしない。
//   1. manifest.json の items（21件）のうち、まだ Zotero に無い文献を登録する。
//      「未読」タグを付け、本文ファイル（references/sources/ の PDF、2件）はコピーせずリンクで添付する。
//      本文を取得できなかった文献（有料論文・書籍）は書誌だけを登録し、「その他」に理由を書く。
//      テーマのコレクション（01_半導体プロセス・02_フォトニクス・光学シミュレーション・03_機械学習・04_統計）にも入れる。
//      既に Zotero にある文献は作らず、足りない添付だけ補う（「未読」タグは付けない）。
//   2. 1の文献を、案件のコレクション「2026-10-13_Wafer面内傾向の異常検知手法比較」に入れる（無ければ1階層で作る）。
//   3. manifest.json の existing_references（今回は0件）も案件のコレクションに入れる。
//
// 何度実行してもよい。同じ文献（Import-ID・DOI・URL・題名のどれかが一致）があれば新しく作らない。
// 結果は同じフォルダの result.json に書き出し、画面にも表示する。

var IMPORT_DIRECTORY = "/Users/sakamoto/04_プログラミング/ClaudeCode/GitHub/wafer_anomaly_monitoring/references/zotero";
var MANIFEST_PATH = IMPORT_DIRECTORY + "/manifest.json";
var RESULT_PATH = IMPORT_DIRECTORY + "/result.json";
var SURVEY_NOTE = "案件: Alignment・Overlay の Wafer 面内傾向に対する経時変化・異常検知手法の比較検証（2026-10-13、wafer_anomaly_monitoring リポジトリの技術レポート）";

var result = {
  status: "running",
  step: "開始",
  case_collection: null,
  created_case_collection: false,
  created: 0,
  reused: 0,
  unread_tagged: 0,
  linked_files: 0,
  existing_files: 0,
  existing_references_added: 0,
  existing_references_not_found: [],
  missing_files: [],
  field_warnings: [],
  failures: [],
  items: [],
  summary: ""
};

async function writeResult() {
  result.updated_at = new Date().toISOString();
  await Zotero.File.putContentsAsync(RESULT_PATH, JSON.stringify(result, null, 2));
}

function normalizeText(value) {
  return value ? String(value).normalize("NFC") : "";
}

function normalizeDOI(value) {
  return normalizeText(value).trim().toLowerCase();
}

function normalizeURL(value) {
  return normalizeText(value).trim().replace(/\/+$/, "").toLowerCase();
}

// 大文字小文字・記号・空白の違いを無視してタイトルを比べる
function normalizeTitle(value) {
  return normalizeText(value).toLowerCase().replace(/[^a-z0-9぀-ヿ一-鿿]+/g, "");
}

function fieldOf(item, name) {
  try {
    return item.getField(name) || "";
  }
  catch (error) {
    return "";
  }
}

function importIDOf(item) {
  let match = fieldOf(item, "extra").match(/^Import-ID:\s*(\S+)/m);
  return match ? match[1] : null;
}

// 項目の種類に無い欄は飛ばして記録する（特許の日付は issueDate など、種類ごとに欄の名前が違うため）
function setFieldSafely(item, record, field, value) {
  if (value === null || value === undefined || value === "") return;
  try {
    item.setField(field, value);
  }
  catch (error) {
    result.field_warnings.push({ key: record.key, field: field, error: String(error) });
  }
}

async function fileExists(path) {
  try {
    return await IOUtils.exists(path);
  }
  catch (error) {
    return Zotero.File.pathToFile(path).exists();
  }
}

try {
  result.step = "manifest.json の読み込み";
  var manifest = JSON.parse(await Zotero.File.getContentsAsync(MANIFEST_PATH));
  if (!manifest.case_collection || !manifest.unread_tag || !Array.isArray(manifest.items)) {
    throw new Error("manifest.json に case_collection・unread_tag・items が必要です");
  }
  var libraryID = Zotero.Libraries.userLibraryID;

  result.step = "既存の項目の確認";
  // タグ検索は使わず、ライブラリ全体を走査して照合する（タグを消されても二重登録しないため）
  var allItems = (await Zotero.Items.getAll(libraryID, true, false)).filter(item => item.isRegularItem() && !item.deleted);
  var byImportID = new Map();
  var byDOI = new Map();
  var byURL = new Map();
  var byTitle = new Map();
  for (let item of allItems) {
    let importID = importIDOf(item);
    if (importID) byImportID.set(importID, item);
    let doi = normalizeDOI(fieldOf(item, "DOI"));
    if (doi) byDOI.set(doi, item);
    let url = normalizeURL(fieldOf(item, "url"));
    if (url) byURL.set(url, item);
    let title = normalizeTitle(fieldOf(item, "title"));
    if (title && !byTitle.has(title)) byTitle.set(title, item);
  }
  await writeResult();

  result.step = "コレクションの確認";
  function findTopLevelCollection(name) {
    return Zotero.Collections.getByLibrary(libraryID, true).find(candidate => candidate.name === name && !candidate.parentID);
  }
  // テーマのコレクションは既存のものだけを使う（無ければ止める）
  var themeCollections = new Map();
  for (let name of new Set(manifest.items.map(record => record.collection))) {
    let found = findTopLevelCollection(name);
    if (!found) throw new Error("テーマのコレクションが見つかりません: " + name);
    themeCollections.set(name, found);
  }
  // 案件のコレクションは無ければ1階層で作る
  var caseCollection = findTopLevelCollection(manifest.case_collection);
  if (!caseCollection) {
    caseCollection = new Zotero.Collection();
    caseCollection.libraryID = libraryID;
    caseCollection.name = manifest.case_collection;
    await caseCollection.saveTx();
    result.created_case_collection = true;
  }
  result.case_collection = manifest.case_collection;
  await writeResult();

  result.step = "新しい文献の登録";
  for (let record of manifest.items) {
    try {
      // 書籍のように DOI・URL が無い文献も二重に作らないよう、最後に題名でも照合する
      let item = byImportID.get(record.importId)
        || (record.fields.DOI ? byDOI.get(normalizeDOI(record.fields.DOI)) : null)
        || (record.fields.url ? byURL.get(normalizeURL(record.fields.url)) : null)
        || byTitle.get(normalizeTitle(record.title));
      let isNew = !item;
      if (isNew) {
        item = new Zotero.Item(record.itemType);
        item.libraryID = libraryID;
        item.setField("title", record.title);
        setFieldSafely(item, record, "date", record.date);
        for (let [field, value] of Object.entries(record.fields)) {
          setFieldSafely(item, record, field, value);
        }
        if (record.creators.length) item.setCreators(record.creators);
        let extra = ["Import-ID: " + record.importId];
        if (record.file) extra.push("元ファイル: " + record.file);
        if (record.status === "not_obtained") extra.push("本文未取得: " + record.reason);
        extra.push(SURVEY_NOTE);
        item.setField("extra", extra.join("\n"));
        for (let tag of record.tags) item.addTag(tag);
        item.addTag(manifest.unread_tag);
        result.unread_tagged += 1;
      }
      // コレクションは足すだけにする（既存の所属は外さない）
      item.addToCollection(themeCollections.get(record.collection).id);
      item.addToCollection(caseCollection.id);
      await item.saveTx();
      if (isNew) {
        result.created += 1;
        byImportID.set(record.importId, item);
      }
      else {
        result.reused += 1;
      }

      if (record.file) {
        let path = normalizeText(manifest.base + "/" + record.file);
        if (!(await fileExists(path))) {
          result.missing_files.push(path);
        }
        else {
          let attachments = await Zotero.Items.getAsync(item.getAttachments());
          let already = attachments.some(attachment => attachment.isAttachment() && normalizeText(attachment.getFilePath()) === path);
          if (already) {
            result.existing_files += 1;
          }
          else {
            await Zotero.Attachments.linkFromFile({ file: path, parentItemID: item.id });
            result.linked_files += 1;
          }
        }
      }
      result.items.push({ key: record.key, zotero_key: item.key, status: isNew ? "created" : "reused" });
    }
    catch (error) {
      result.failures.push({ key: record.key, error: String(error) });
    }
    await writeResult();
  }

  result.step = "登録済みの文献を案件のコレクションへ追加";
  for (let reference of manifest.existing_references || []) {
    try {
      // 特許は同じ題名が多いので、題名より先に URL で照合する
      let item = (reference.doi ? byDOI.get(normalizeDOI(reference.doi)) : null)
        || (reference.url ? byURL.get(normalizeURL(reference.url)) : null)
        || (reference.title ? byTitle.get(normalizeTitle(reference.title)) : null);
      if (!item) {
        result.existing_references_not_found.push(reference.key);
        continue;
      }
      if (!item.inCollection(caseCollection.id)) {
        item.addToCollection(caseCollection.id);
        await item.saveTx();
      }
      result.existing_references_added += 1;
    }
    catch (error) {
      result.failures.push({ key: reference.key, error: String(error) });
    }
  }

  result.step = "完了";
  result.status = result.failures.length ? "completed_with_errors" : "completed";
}
catch (error) {
  result.status = "failed";
  result.failures.push({ step: result.step, error: String(error) });
}
result.summary = `新規登録 ${result.created} 件（うち「未読」タグ ${result.unread_tagged} 件）、登録済みの再利用 ${result.reused} 件、`
  + `登録済みの参考文献を案件コレクションへ ${result.existing_references_added} 件、`
  + `ファイルのリンク添付 ${result.linked_files} 件（添付済み ${result.existing_files} 件）、失敗 ${result.failures.length} 件`;
await writeResult();
return result;
