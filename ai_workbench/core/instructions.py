"""Application-owned, localized model instructions."""

from datetime import date
from typing import Literal


UiLanguage = Literal["en", "zh-CN"]
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def date_instruction(language: UiLanguage, day: date) -> str:
    if language == "zh-CN":
        weekday = "一二三四五六日"[day.weekday()]
        return f"当前日期：{day.year}年{day.month}月{day.day}日（星期{weekday}）。"
    return f"Current date: {day.isoformat()} ({WEEKDAYS[day.weekday()]})."
