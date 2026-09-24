"""Fixed labels for charts and the PDF. Agent-written text is not translated."""

LABELS = {
    "en": {
        "views_title": "Views per {unit} (article + redirects)",
        "index_title": "Share of language edition, index (start = 100)",
        "spike": "news spike",
        "month": "month", "day": "day",
        "period": "Period", "langs": "Languages", "source": "Source",
        "source_text": "Wikimedia Pageviews API, human traffic (agent=user), all access",
        "generated": "Generated",
        "col_series": "Topic [lang]", "col_median": "Median views / {unit}",
        "col_growth": "Trend, %/yr*", "col_yoy": "Recent vs prior*",
        "col_spikes": "Spikes", "col_verdict": "Verdict", "col_conf": "Confidence",
        "col_rank": "Rank", "col_score": "Score",
        "footnote": "* measured on share of all views of that language edition "
                    "(removes overall Wikipedia traffic changes). Trend = Sen's slope, "
                    "significance = Mann-Kendall with autocorrelation correction. "
                    "Recent vs prior = last {win} {unit}s vs previous {win}.",
        "recommendation": "Recommendation", "next_steps": "Next steps",
        "assumptions": "Assumptions & limitations",
        "growing": "growing", "declining": "declining", "flat": "flat",
        "unclear": "unclear", "high": "high", "medium": "medium", "low": "low",
        "missing": "no data",
        "wiki_trend": "Overall traffic of the language editions (not topic-specific)",
        "caveats": [
            "Page views measure curiosity, not willingness to pay.",
            "Human traffic only (agent=user); bot filtering is imperfect.",
            "Views of redirects (old names, spelling variants) are included.",
            "Language edition ≠ country (e.g. English Wikipedia is read worldwide).",
            "One article is a proxy for a topic; related articles are not included unless listed.",
            "Attention moving to search snippets, AI answers and apps is invisible here.",
        ],
    },
    "uk": {
        "views_title": "Перегляди за {unit} (стаття + редиректи)",
        "index_title": "Частка від мовного розділу, індекс (початок = 100)",
        "spike": "новинний сплеск",
        "month": "міс.", "day": "день",
        "period": "Період", "langs": "Мови", "source": "Джерело",
        "source_text": "Wikimedia Pageviews API, лише люди (agent=user), усі платформи",
        "generated": "Створено",
        "col_series": "Тема [мова]", "col_median": "Медіана, перегл. / {unit}",
        "col_growth": "Тренд, %/рік*", "col_yoy": "Останній vs попередній*",
        "col_spikes": "Сплески", "col_verdict": "Висновок", "col_conf": "Довіра",
        "col_rank": "Ранг", "col_score": "Бал",
        "footnote": "* розраховано на частці від усіх переглядів мовного розділу "
                    "(прибирає загальні зміни трафіку Wikipedia). Тренд = нахил Сена, "
                    "значущість = тест Манна-Кендалла з поправкою на автокореляцію. "
                    "Останній vs попередній = останні {win} ({unit}) проти попередніх {win}.",
        "recommendation": "Рекомендація", "next_steps": "Наступні кроки",
        "assumptions": "Припущення та обмеження",
        "growing": "зростає", "declining": "спадає", "flat": "стабільно",
        "unclear": "неоднозначно", "high": "висока", "medium": "середня", "low": "низька",
        "missing": "немає даних",
        "wiki_trend": "Загальний трафік мовних розділів (не стосується теми)",
        "caveats": [
            "Перегляди показують цікавість, а не готовність платити.",
            "Лише людський трафік (agent=user); фільтрація ботів неідеальна.",
            "Перегляди редиректів (старі назви, варіанти написання) враховано.",
            "Мовний розділ ≠ країна (напр. англійську Вікіпедію читають у всьому світі).",
            "Одна стаття — це наближення теми; суміжні статті не враховано, якщо їх не додано.",
            "Увагу, що переходить у пошукові сніпети, AI-відповіді та застосунки, тут не видно.",
        ],
    },
}


def labels(lang: str) -> dict:
    return LABELS.get(lang, LABELS["en"])
