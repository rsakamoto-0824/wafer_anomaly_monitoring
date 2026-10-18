"""計測テーブルの標準の項目名（ユーザーの Overlay計測ルール）と、ファイルの列への自動対応づけ。

項目名は大文字・小文字を区別する（ルールの表記どおり）。完全に一致する列がなければ、
大文字・小文字と前後の空白だけを無視して1つに決まる列を候補にする（画面で確認・変更できる）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    meaning: str
    unit: str
    required: bool


STANDARD_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("Wafer", "Wafer の ID", "文字列", True),
    ColumnSpec("DateTime", "計測日時（時間の順番に使う）", "日時", False),
    ColumnSpec("shotNo", "Shot 番号", "整数", False),
    ColumnSpec("Direction", "Scan 方向（1 または 2）", "コード", False),
    ColumnSpec("Xmm", "Shot 中心の X 座標（Wafer 中心が原点）", "mm", True),
    ColumnSpec("Ymm", "Shot 中心の Y 座標（Wafer 中心が原点）", "mm", True),
    ColumnSpec("Radius", "Shot 中心の半径（確認だけに使う）", "mm", False),
    ColumnSpec("markNo", "Shot 内の Mark 番号", "整数", False),
    ColumnSpec("markXmm", "Shot 中心から見た Mark の X 座標", "mm", True),
    ColumnSpec("markYmm", "Shot 中心から見た Mark の Y 座標", "mm", True),
    ColumnSpec("measX", "X 方向の計測値", "nm", True),
    ColumnSpec("measY", "Y 方向の計測値", "nm", True),
    ColumnSpec("StsX", "X の状態（0 = 有効、−1 = 未測定）", "コード", False),
    ColumnSpec("StsY", "Y の状態（0 = 有効、−1 = 未測定）", "コード", False),
)
COLUMN_NAMES = tuple(spec.name for spec in STANDARD_COLUMNS)
REQUIRED_COLUMNS = tuple(spec.name for spec in STANDARD_COLUMNS if spec.required)


def auto_mapping(file_columns) -> dict[str, str | None]:
    """標準の項目名 → ファイルの列名（見つからなければ None）。"""
    columns = [str(column) for column in file_columns]
    mapping: dict[str, str | None] = {}
    for name in COLUMN_NAMES:
        if name in columns:
            mapping[name] = name
            continue
        loose = [column for column in columns if column.strip().lower() == name.lower()]
        mapping[name] = loose[0] if len(loose) == 1 else None
    return mapping


def missing_required(mapping: dict[str, str | None]) -> list[str]:
    return [name for name in REQUIRED_COLUMNS if not mapping.get(name)]


def duplicated_targets(mapping: dict[str, str | None]) -> list[str]:
    """同じファイルの列が2つ以上の項目に割り当てられている列名。"""
    used = [column for column in mapping.values() if column]
    return sorted({column for column in used if used.count(column) > 1})
