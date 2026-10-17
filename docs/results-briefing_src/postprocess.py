"""pptxgenjs の出力を整える後処理（説明資料用）。

1. フォント指定を直す（和文 BIZ UDGothic は日本語の文字セット、欧文は Arial）
2. 1つの段落に重複して書かれた段落プロパティ <a:pPr> を先頭の1つだけ残す
3. グラフの空欄の点（値なし）を取り除く（散布図・折れ線で系列ごとに点を分けるため）
4. PowerPoint for Mac が修復対象にする部品を正規化する
   - [Content_Types].xml から、実在しない部品（slideMaster2 以降）の Override を除く
   - ノートマスターを最小構成（スライド画像とノート本文のプレースホルダーだけ）にする
   - 各ノートから、マスターと番号が合わないスライド番号のプレースホルダーを除く（ノート本文は残す）
   - ノートマスター専用のテーマ（theme2.xml）と関係定義を作る
5. スライド内の図形ID（重複することがある）を通し番号に振り直す
6. ZIP を DEFLATE で再圧縮する（pptxgenjs は無圧縮で書き出すため）

使い方: python postprocess.py <入力.pptx> <出力.pptx>
"""

import re
import sys
import zipfile
from pathlib import Path

JAPANESE_FONT = "BIZ UDGothic"
LATIN_FONT = "Arial"
CODE_FONT = "Courier New"
JAPANESE_CHARSET = "-128"

FONT_TRIPLE = re.compile(
    r'<a:latin typeface="(?P<face>[^"]+)"[^>]*/>'
    r'(?:\s*<a:ea typeface="[^"]*"[^>]*/>)?'
    r'(?:\s*<a:cs\s+typeface="[^"]*"[^>]*/>)?'
)
EMPTY_CHART_POINT = re.compile(r'<c:pt idx="\d+"><c:v></c:v></c:pt>')
PARAGRAPH = re.compile(r"<a:p>(.*?)</a:p>", re.S)
PARAGRAPH_PROPS = re.compile(r"<a:pPr\b[^>]*/>|<a:pPr\b[^>]*>.*?</a:pPr>", re.S)
SHAPE = re.compile(r"<p:sp>.*?</p:sp>", re.S)
NOTES_THEME = "ppt/theme/theme2.xml"
NOTES_MASTER_KEEP = ("sldImg", "body")


def placeholder_type(shape_xml):
    match = re.search(r'<p:ph type="([^"]+)"', shape_xml)
    return match.group(1) if match else None


def minimal_notes_master(xml):
    """ノートマスターのプレースホルダーを、スライド画像とノート本文だけにする"""
    xml = SHAPE.sub(lambda m: m.group(0) if placeholder_type(m.group(0)) in NOTES_MASTER_KEEP else "", xml)
    # 本文プレースホルダーの見本テキスト（5段落）を空の1段落にする
    return re.sub(r'(<p:ph type="body"[^>]*/></p:nvPr></p:nvSpPr>.*?<a:lstStyle/>).*?(</p:txBody>)',
                  r'\1<a:p><a:endParaRPr lang="ja-JP"/></a:p>\2', xml, flags=re.S)


def renumber_shape_ids(xml):
    """pptxgenjs は表の図形IDを他の図形と重複させることがあるので、スライド内で通し番号に振り直す"""
    counter = iter(range(1, 100000))
    return re.sub(r'<p:cNvPr id="\d+"', lambda m: f'<p:cNvPr id="{next(counter)}"', xml)


def remove_notes_slide_number(xml):
    return SHAPE.sub(lambda m: "" if placeholder_type(m.group(0)) == "sldNum" else m.group(0), xml)


def fix_content_types(xml, names):
    def keep(match):
        return match.group(0) if match.group(1) in names else ""
    xml = re.sub(r'<Override PartName="/([^"]+)"[^>]*/>', keep, xml)
    if NOTES_THEME not in xml:
        xml = xml.replace("</Types>", f'<Override PartName="/{NOTES_THEME}" '
                          'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/></Types>')
    return xml


def fix_fonts(xml):
    def replace(match):
        face = match.group("face")
        if face == JAPANESE_FONT:
            latin = LATIN_FONT
        elif face == CODE_FONT:
            latin = CODE_FONT
        else:
            return match.group(0)
        return (f'<a:latin typeface="{latin}"/>'
                f'<a:ea typeface="{JAPANESE_FONT}" charset="{JAPANESE_CHARSET}"/>'
                f'<a:cs typeface="{latin}"/>')

    return FONT_TRIPLE.subn(replace, xml)


def dedupe_paragraph_props(xml):
    removed = 0

    def fix_paragraph(match):
        nonlocal removed
        body = match.group(1)
        props = list(PARAGRAPH_PROPS.finditer(body))
        if len(props) <= 1:
            return match.group(0)
        first = props[0]
        rest = PARAGRAPH_PROPS.sub("", body[first.end():])
        removed += len(props) - 1
        return "<a:p>" + body[:first.end()] + rest + "</a:p>"

    return PARAGRAPH.sub(fix_paragraph, xml), removed


def main(src, dst):
    src, dst = Path(src), Path(dst)
    font_count = 0
    props_removed = 0
    empty_points = 0
    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        # [Content_Types].xml は先頭に置く必要がある
        order = [n for n in names if n == "[Content_Types].xml"] + [n for n in names if n != "[Content_Types].xml"]
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
            names_after = set(names) | {NOTES_THEME}
            for name in order:
                data = zin.read(name)
                if name == "[Content_Types].xml":
                    data = fix_content_types(data.decode("utf-8"), names_after).encode("utf-8")
                elif name == "ppt/notesMasters/notesMaster1.xml":
                    data = minimal_notes_master(data.decode("utf-8")).encode("utf-8")
                elif name == "ppt/notesMasters/_rels/notesMaster1.xml.rels":
                    data = data.decode("utf-8").replace("../theme/theme1.xml", "../theme/theme2.xml").encode("utf-8")
                elif re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", name):
                    data = remove_notes_slide_number(data.decode("utf-8")).encode("utf-8")
                is_target = re.match(r"ppt/(slides/slide\d+|charts/chart\d+)\.xml$", name)
                if is_target:
                    xml = data.decode("utf-8")
                    xml, n_fonts = fix_fonts(xml)
                    font_count += n_fonts
                    if name.startswith("ppt/charts/"):
                        # lineDash に配列を渡すと "solid,dash" のような不正な値になり、PowerPoint が修復対象にする
                        bad_dash = re.search(r'<a:prstDash val="[^"]*,[^"]*"', xml)
                        if bad_dash:
                            sys.exit(f"不正な線種の指定があります（{name}）: {bad_dash.group(0)}")
                        xml, n_empty = EMPTY_CHART_POINT.subn("", xml)
                        empty_points += n_empty
                    if name.startswith("ppt/slides/"):
                        xml, n_removed = dedupe_paragraph_props(xml)
                        xml = renumber_shape_ids(xml)
                        props_removed += n_removed
                    data = xml.encode("utf-8")
                info = zin.getinfo(name)
                new_info = zipfile.ZipInfo(name, date_time=info.date_time)
                new_info.compress_type = zipfile.ZIP_DEFLATED
                new_info.external_attr = info.external_attr
                zout.writestr(new_info, data)
            if NOTES_THEME not in names:
                theme = zin.read("ppt/theme/theme1.xml")
                zout.writestr(zipfile.ZipInfo(NOTES_THEME, date_time=zin.getinfo("ppt/theme/theme1.xml").date_time), theme,
                              compress_type=zipfile.ZIP_DEFLATED)
    print(f"フォント指定の修正: {font_count} 箇所 / 重複した段落プロパティの削除: {props_removed} 箇所 / グラフの空欄の点の削除: {empty_points} 個")
    print(f"サイズ: {src.stat().st_size:,} → {dst.stat().st_size:,} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("使い方: python postprocess.py <入力.pptx> <出力.pptx>")
    main(sys.argv[1], sys.argv[2])
