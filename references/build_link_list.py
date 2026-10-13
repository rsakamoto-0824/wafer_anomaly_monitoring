"""references.json から参考文献・参考リンクの一覧（Markdown）を作る。

使い方: python3 build_link_list.py  → 参考文献リンク.md
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS_LABEL = {
    "obtained": "本文取得済み（正規の入手先から取得し内容を確認）",
    "not_obtained": "本文未取得",
}


def authors_text(ref):
    names = [a.split(",")[0] for a in ref.get("authors", [])]
    return ", ".join(names[:3]) + (" ほか" if len(names) > 3 else "")


def main():
    data = json.loads((HERE / "references.json").read_text(encoding="utf-8"))
    lines = [
        "# 参考文献・参考リンク",
        "",
        "技術レポート「Alignment・Overlay の Wafer 面内傾向に対する経時変化・異常検知手法の比較検証」（`reports/technical_report.md`）で引用した文献の一覧。",
        f"正本は `references.json`。書誌は Crossref などで実在を確認した。確認日：{data['checked_on']}。",
        "",
        "| 文献 | 状態 | リンク | 使った箇所 |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for ref in data["references"]:
        link = ref.get("url") or (f"ISBN {ref['isbn']}" if ref.get("isbn") else "")
        status = STATUS_LABEL[ref["status"]]
        if ref["status"] == "obtained":
            status += f"：{ref['reason']}（{ref['source_url']}）"
        lines.append(f"| {authors_text(ref)}（{ref['year']}）{ref['title']} | {status} | {link} | {ref['used_for']} |")
    lines += ["", "## 未取得の文献", ""]
    for ref in data["references"]:
        if ref["status"] == "not_obtained":
            doi = f"、DOI {ref['doi']}" if ref.get("doi") else ""
            lines.append(f"- {authors_text(ref)}（{ref['year']}）{ref['title']}{doi}：{ref['reason']}")
    (HERE / "参考文献リンク.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(HERE / "参考文献リンク.md")


if __name__ == "__main__":
    main()
