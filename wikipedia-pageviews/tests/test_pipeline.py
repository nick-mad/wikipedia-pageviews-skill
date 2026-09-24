"""End-to-end on recorded API responses (no network)."""

import datetime as dt
import json

import pytest

from wpv import analysis, cli, report, summary


def build(client):
    topic = analysis.parse_topic("Intermittent fasting=Q1666254,pl:Głodówka lecznicza")
    return analysis.build(client, [topic], ["pl", "cs"], dt.date(2024, 9, 1),
                          dt.date(2026, 8, 31))


def test_topic_parsing():
    t = analysis.parse_topic("Astro=Q333, q544 ,uk:Сонячна система")
    assert t == {"label": "Astro", "qids": ["Q333", "Q544"],
                 "titles": {"uk": ["Сонячна система"]}}
    with pytest.raises(ValueError):
        analysis.parse_topic("Astro=astronomy")


def test_period_defaults_to_last_24_complete_months():
    s, e, notes = analysis.resolve_period("monthly", None, None, None, None,
                                          today=dt.date(2026, 9, 24))
    assert (s, e) == (dt.date(2024, 9, 1), dt.date(2026, 8, 31))
    s, e, notes = analysis.resolve_period("monthly", None, None, "2010-01", "2026-12",
                                          today=dt.date(2026, 9, 24))
    assert s == dt.date(2015, 7, 1) and e == dt.date(2026, 8, 31) and len(notes) == 2


def test_build_normalises_and_flags_stand_in(offline_client):
    a = build(offline_client)
    pl, cs = a["series"]
    assert len(a["timeline"]) == 24
    # views per million = views / project views * 1e6
    assert pl["per_million"][0] == pytest.approx(pl["views"][0] / pl["project_views"][0] * 1e6,
                                                 rel=1e-3)
    assert pl["articles"][0]["explicit"] is True
    assert pl["metrics"]["confidence"]["level"] != "high"  # stand-in caps confidence
    assert cs["articles"][0]["title"] == "Přerušovaný půst"
    assert cs["metrics"]["verdict"] in {"declining", "unclear", "flat", "growing"}
    json.dumps(a)  # serialisable


def test_missing_language_is_reported_not_dropped(offline_client):
    topic = analysis.parse_topic("IF=Q1666254")
    a = analysis.build(offline_client, [topic], ["pl", "cs"], dt.date(2024, 9, 1),
                       dt.date(2026, 8, 31))
    pl = a["series"][0]
    assert pl["metrics"] is None and "no pl.wikipedia article" in pl["missing"]
    assert "NO DATA" in summary.render(a)


def test_summary_mentions_key_figures(offline_client):
    text = summary.render(build(offline_client))
    assert "VERDICT" in text and "confidence" in text and "p" in text
    assert "EXPLICIT stand-in" in text


def test_report_rejects_invented_numbers(offline_client, tmp_path, capsys):
    a = build(offline_client)
    (tmp_path / "analysis.json").write_text(json.dumps(a))
    m = a["series"][1]["metrics"]
    good = f"Czech interest fell {m['growth_pct_per_year']:.1f}% per year."
    base = ["report", str(tmp_path), "--headline", "IF in pl vs cs",
            "--recommendation", "Test Czech later."]
    assert cli.main(base + ["--summary", good + " It will triple by 2030 to 5000 views."]) == 2
    err = capsys.readouterr().err
    assert "5000" in err and "2030" in err  # 2030 is a prediction, not data
    assert cli.main(base + ["--summary", good]) == 0
    assert (tmp_path / "report.pdf").exists()


@pytest.mark.parametrize("text,expected", [
    ("29 778 переглядів", [29778.0]),
    ("p=0,732", [0.732]),
    ("-4,7%", [-4.7]),
    ("1,234 views", [1234.0, 1.234]),
    ("12K views", [12000.0]),
    ("1.5 млн", [1_500_000.0]),
])
def test_number_extraction(text, expected):
    assert report.extract_numbers(text)[0][1] == pytest.approx(expected)


def test_rounded_figures_are_accepted():
    known = {29778.0, -4.73, 0.0321}
    ok = "29,778 or 29 800 or 30K views; -4.7% or -5%; p=0.03"
    assert report.unverified(ok, known) == []
    assert report.unverified("31,000 views, -6%", known) == ["31,000", "-6"]


def test_correct_derived_comparisons_pass_wrong_ones_fail(offline_client):
    a = build(offline_client)
    known = report.known_numbers(a)
    pl, cs = (s["metrics"]["median_views"] for s in a["series"])
    hi, lo = max(pl, cs), min(pl, cs)
    right = f"{(hi / lo - 1) * 100:.0f}% more views"
    wrong = "88% more views"  # not derivable from this data
    assert report.unverified(right, known) == []
    assert report.unverified(wrong, known) != []
    assert report.unverified("see `/tmp/x-144b-4710/report.pdf`", known) == []
