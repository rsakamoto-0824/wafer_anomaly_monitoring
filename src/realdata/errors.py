"""画面に出すエラーと中止の例外。"""
from __future__ import annotations


class UserFacingError(Exception):
    """利用者に見せるエラー。「何が起きたか／なぜか／次にどうすればよいか」の3点を必ず持つ。"""

    def __init__(self, what: str, why: str, next_step: str):
        super().__init__(f"{what}\n理由：{why}\n対処：{next_step}")
        self.what = what
        self.why = why
        self.next_step = next_step


class AnalysisCancelled(Exception):
    """利用者が「中止」を押した。"""


def check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled("中止しました")
