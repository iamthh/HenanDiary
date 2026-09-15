"""日报生成器测试：mock AI，验证素材→Prompt→解析→落库的接线。"""

from __future__ import annotations

import pytest

from report import generator
from storage import db

FAKE_OUTPUT = """## 今日概览
写了一天代码。

## 主要工作块
- 09:00-12:00 开发采集模块

## 时间分布
编码 70%，沟通 30%。

```json
{"overview": "写了一天代码", "blocks": [{"topic": "采集", "start": "09:00", "end": "12:00"}], "distribution": [{"category": "编码", "percent": 70}]}
```"""


class _FakeAI:
    def __init__(self, output=FAKE_OUTPUT) -> None:
        self.output = output
        self.prompts: list[str] = []

    def analyze_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.output


@pytest.fixture
def with_materials() -> None:
    db.init_db()
    db.save_screenshot_analysis("2026-09-15T09:00:00", "在写采集代码")
    db.save_screenshot_analysis("2026-09-15T10:00:00", "在改bug")


def test_generates_and_saves_report(with_materials) -> None:
    fake = _FakeAI()
    row = generator.generate_daily_report("2026-09-15", ai=fake)

    assert row["date"] == "2026-09-15"
    assert "## 今日概览" in row["content_md"]
    assert '"overview"' in row["content_json"]
    # Prompt 带上了当日全部素材
    assert "在写采集代码" in fake.prompts[0] and "在改bug" in fake.prompts[0]
    assert "共 2 条" in fake.prompts[0]


def test_skips_when_no_materials(with_materials) -> None:
    result = generator.generate_daily_report("2026-09-16", ai=_FakeAI())
    assert result["skipped"] is True
    assert db.get_daily_report("2026-09-16") is None


def test_invalid_json_falls_back_without_blocking(with_materials) -> None:
    broken = FAKE_OUTPUT.replace('{"overview"', '{broken')
    generator.generate_daily_report("2026-09-15", ai=_FakeAI(broken))
    row = db.get_daily_report("2026-09-15")
    assert row["content_json"] == "{}"
    assert "## 今日概览" in row["content_md"]  # 正文照常落库


def test_no_json_block_falls_back(with_materials) -> None:
    generator.generate_daily_report("2026-09-15", ai=_FakeAI("纯markdown，没有json"))
    assert db.get_daily_report("2026-09-15")["content_json"] == "{}"


def test_regenerate_overwrites(with_materials) -> None:
    generator.generate_daily_report("2026-09-15", ai=_FakeAI())
    fake2 = _FakeAI("## 今日概览\n第二版")
    row = generator.generate_daily_report("2026-09-15", ai=fake2)
    assert "第二版" in row["content_md"]
    assert len(db.list_daily_reports()) == 1
