"""references.json から Zotero 取り込み用の manifest.json を作る。

使い方: python3 build_zotero_manifest.py
- 新しく登録する可能性がある文献（status = obtained / not_obtained）は items に入れる。
  既に Zotero にあれば（Import-ID・DOI・URL・題名のどれかが一致）作らずに案件コレクションへ入れるだけになる。
  本文ファイルがあればリンクで添付する。
- 既に Zotero にあると分かっている文献（status = existing）は existing_references に入れ、案件コレクションに追加するだけにする。
- タグは5系統（種別/・分野/・所属/・掲載誌/・ライブラリ/）だけを使う。
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCES_DIR = HERE.parent
UNREAD_TAG = "未読"
IMPORT_PREFIX = "wafer-anomaly-monitoring:"

# 文献ごとのテーマのコレクションとタグ。所属は本文または書誌で確認できたものだけ付ける
CLASSIFICATION = {
    "page1954": ("04_統計", ["種別/論文", "掲載誌/Biometrika", "分野/統計"]),
    "roberts1959": ("04_統計", ["種別/論文", "掲載誌/Technometrics", "分野/統計"]),
    "lucas1990": ("04_統計", ["種別/論文", "掲載誌/Technometrics", "分野/統計"]),
    "lowry1992": ("04_統計", ["種別/論文", "掲載誌/Technometrics", "分野/統計"]),
    "crosier1988": ("04_統計", ["種別/論文", "掲載誌/Technometrics", "分野/統計"]),
    "jackson1979": ("04_統計", ["種別/論文", "掲載誌/Technometrics", "分野/統計"]),
    "box1954": ("04_統計", ["種別/論文", "掲載誌/Annals of Mathematical Statistics", "分野/統計"]),
    "macgregor1995": ("04_統計", ["種別/論文", "掲載誌/Control Engineering Practice", "分野/統計"]),
    "qin2003": ("04_統計", ["種別/論文", "掲載誌/Journal of Chemometrics", "分野/統計"]),
    "ledoit2004": ("04_統計", ["種別/論文", "掲載誌/Journal of Multivariate Analysis", "分野/統計"]),
    "alwan1988": ("04_統計", ["種別/論文", "掲載誌/JBES", "分野/統計"]),
    "woodall2004": ("04_統計", ["種別/論文", "掲載誌/Journal of Quality Technology", "分野/統計"]),
    "colosimo2010": ("04_統計", ["種別/論文", "掲載誌/IJPR", "分野/統計"]),
    "rasmussen2006": ("03_機械学習", ["種別/書籍", "分野/機械学習"]),
    "noll1976": ("02_フォトニクス・光学シミュレーション", ["種別/論文", "掲載誌/JOSA", "分野/光学"]),
    "hanley1982": ("04_統計", ["種別/論文", "掲載誌/Radiology", "分野/統計"]),
    "wilson1927": ("04_統計", ["種別/論文", "掲載誌/JASA", "分野/統計"]),
    "montgomery2001": ("04_統計", ["種別/書籍", "分野/統計"]),
    "atkinson2007": ("04_統計", ["種別/書籍", "分野/実験計画法"]),
    "adel2007": ("01_半導体プロセス", ["種別/論文", "掲載誌/SPIE Proceedings", "分野/オーバーレイ・EPE"]),
    "pike2012": ("01_半導体プロセス", ["種別/論文", "掲載誌/SPIE Proceedings", "分野/オーバーレイ・EPE"]),
}


def creators_of(ref):
    creator_type = "inventor" if ref["itemType"] == "patent" else "author"
    creators = []
    for name in ref.get("authors", []):
        last, _, first = name.partition(", ")
        creators.append({"lastName": last, "firstName": first, "creatorType": creator_type})
    return creators


def fields_of(ref):
    item_type = ref["itemType"]
    fields = {"url": ref.get("url", ""), "DOI": ref.get("doi", "")}
    if item_type == "journalArticle":
        fields.update({"publicationTitle": ref.get("venue", ""), "volume": ref.get("volume", ""),
                       "issue": ref.get("issue", ""), "pages": ref.get("pages", "")})
    elif item_type == "conferencePaper":
        fields.update({"proceedingsTitle": ref.get("venue", ""), "pages": ref.get("pages", ""),
                       "publisher": "SPIE" if "SPIE" in ref.get("venue", "") else ""})
    elif item_type == "patent":
        fields.pop("DOI")
        fields.update({"patentNumber": ref.get("number", ""), "assignee": ref.get("assignee", ""),
                       "country": ref.get("number", "")[:2], "issueDate": ref.get("date", "")})
    elif item_type == "book":
        fields.update({"publisher": ref.get("publisher", ""), "edition": ref.get("edition", ""), "ISBN": ref.get("isbn", "")})
    elif item_type == "bookSection":
        fields.pop("DOI")
        fields.update({"bookTitle": ref.get("venue", ""), "pages": ref.get("pages", ""), "publisher": "Academic Press"})
    return {k: v for k, v in fields.items() if v}


def import_id(ref):
    source = ref.get("file")
    if source and (REFERENCES_DIR / source).exists():
        digest = hashlib.sha256((REFERENCES_DIR / source).read_bytes()).hexdigest()
    else:
        digest = hashlib.sha256((ref["key"] + "|" + ref["title"]).encode("utf-8")).hexdigest()
    return IMPORT_PREFIX + digest


def main():
    data = json.loads((REFERENCES_DIR / "references.json").read_text(encoding="utf-8"))
    items, existing = [], []
    for ref in data["references"]:
        if ref["status"] == "existing":
            existing.append({"key": ref["key"], "doi": ref.get("doi", ""), "url": ref.get("url", ""), "title": ref["title"]})
            continue
        collection, tags = CLASSIFICATION[ref["key"]]
        record = {
            "key": ref["key"], "itemType": ref["itemType"], "title": ref["title"], "collection": collection,
            "tags": tags, "creators": creators_of(ref), "date": str(ref.get("date", ref.get("year", ""))),
            "fields": fields_of(ref), "importId": import_id(ref),
            "status": ref["status"], "reason": ref.get("reason", ""),
        }
        if ref.get("file"):
            record["file"] = ref["file"]
        items.append(record)
    manifest = {"base": str(REFERENCES_DIR), "case_collection": data["case_collection"], "unread_tag": UNREAD_TAG,
                "items": items, "existing_references": existing}
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest.json: 登録候補 {len(items)} 件（本文あり {sum('file' in i for i in items)} 件）、登録済み {len(existing)} 件")


if __name__ == "__main__":
    main()
