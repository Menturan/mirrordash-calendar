import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mirrordash_calendar.plugin import CalendarModule
from mirrordash_calendar.recurrence_text import describe_rrule

TRANSLATIONS = Path(__file__).parent.parent / "mirrordash_calendar" / "translations"
MONDAY = datetime.date(2026, 6, 1)


@pytest.fixture(autouse=True)
def mock_plugin_datetime():
    """Now is Wed 3 Jun 2026 08:00 (as in test_calendar.py)."""
    class DatetimeMeta(type):
        def __instancecheck__(cls, instance):
            return isinstance(instance, datetime.datetime)

    class MockDatetime(datetime.datetime, metaclass=DatetimeMeta):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2026, 6, 3, 8, 0, 0, tzinfo=tz)

    with patch("mirrordash_calendar.plugin.datetime", MockDatetime):
        yield


def translator(lang):
    texts = json.loads((TRANSLATIONS / f"{lang}.json").read_text())
    return lambda key, default=None: texts.get(key, default if default is not None else key)


def rule(text):
    from icalendar import vRecur
    return vRecur.from_ical(text)


@pytest.mark.parametrize("text, en, sv", [
    ("FREQ=DAILY", "every day", "varje dag"),
    ("FREQ=DAILY;INTERVAL=3", "every 3 days", "var 3:e dag"),
    ("FREQ=WEEKLY;BYDAY=MO", "every Monday", "varje måndag"),
    ("FREQ=WEEKLY", "every Monday", "varje måndag"),  # DTSTART is a Monday
    ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "weekdays", "vardagar"),
    ("FREQ=WEEKLY;BYDAY=MO,WE,FR", "Monday, Wednesday and Friday", "måndag, onsdag och fredag"),
    ("FREQ=WEEKLY;INTERVAL=2", "every other week", "varannan vecka"),
    ("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO", "every other Monday", "varannan måndag"),
    ("FREQ=MONTHLY", "every month", "varje månad"),
    ("FREQ=YEARLY", "every year", "varje år"),
    ("FREQ=DAILY;COUNT=5", "every day", "varje dag"),
])
def test_describe_rrule(text, en, sv):
    assert describe_rrule(rule(text), MONDAY, "en", translator("en")) == en
    assert describe_rrule(rule(text), MONDAY, "sv", translator("sv")) == sv


@pytest.mark.parametrize("text", [
    "FREQ=MONTHLY;BYSETPOS=2;BYDAY=TH",
    "FREQ=MONTHLY;BYDAY=2TH",
    "FREQ=MONTHLY;BYMONTHDAY=1,15",
    "FREQ=MONTHLY;INTERVAL=2",
    "FREQ=DAILY;BYHOUR=9,17",
    "FREQ=WEEKLY;INTERVAL=3",
    "FREQ=HOURLY",
])
def test_describe_rrule_complex_rules_give_none(text):
    assert describe_rrule(rule(text), MONDAY, "en", translator("en")) is None


def ics(*events):
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(
        f"BEGIN:VEVENT\n{e}\nEND:VEVENT" for e in events) + "\nEND:VCALENDAR"


def make_module(feeds, view="list", **extra):
    module = CalendarModule({
        "globals": {"timezone": "Europe/Stockholm", "language": "en"},
        "calendars": [{"name": f"Cal{i}", "url": f"http://example.com/{i}.ics"} for i in range(len(feeds))],
        "layout": view,
        "translations": json.loads((TRANSLATIONS / "en.json").read_text()),
        **extra,
    })
    module.render_template = MagicMock(return_value="<div></div>")
    module.fetch = AsyncMock(side_effect=[(f.encode(), None) for f in feeds])
    return module


async def rows(feeds, **kw):
    module = make_module(feeds, **kw)
    await module.render()
    groups = module.render_template.call_args[1]["grouped_events"]
    return [ev for g in groups for ev in g["events"]]


DAILY = """UID:daily@x
DTSTART:20260603T170000Z
DTEND:20260603T180000Z
RRULE:FREQ=DAILY
SUMMARY:Daily"""


@pytest.mark.asyncio
async def test_daily_series_collapses_to_one_row():
    evs = await rows([ics(DAILY)])
    assert len(evs) == 1
    assert evs[0]["repeat"] is True and evs[0]["repeat_text"] == "every day"
    assert evs[0]["date"] == datetime.date(2026, 6, 3)


@pytest.mark.asyncio
async def test_weekly_timed_series_collapses():
    weekly = """UID:w@x
DTSTART:20260601T080000Z
DTEND:20260601T090000Z
RRULE:FREQ=WEEKLY;BYDAY=MO
SUMMARY:Weekly"""
    evs = await rows([ics(weekly)], maximum_days=14)
    assert len(evs) == 1
    assert evs[0]["date"] == datetime.date(2026, 6, 8)
    assert evs[0]["repeat_text"] == "every Monday"


@pytest.mark.asyncio
async def test_weekly_allday_series_collapses():
    weekly = """UID:wa@x
DTSTART;VALUE=DATE:20260604
DTEND;VALUE=DATE:20260605
RRULE:FREQ=WEEKLY
SUMMARY:Thursday thing"""
    evs = await rows([ics(weekly)], maximum_days=14)
    assert len(evs) == 1
    assert evs[0]["date"] == datetime.date(2026, 6, 4)
    assert evs[0]["repeat_text"] == "every Thursday"


@pytest.mark.asyncio
async def test_ended_occurrence_today_shows_tomorrow():
    early = DAILY.replace("T170000Z", "T050000Z").replace("T180000Z", "T060000Z")  # 07:00-08:00 local, over at 08:00
    evs = await rows([ics(early)])
    assert [e["date"] for e in evs] == [datetime.date(2026, 6, 4)]


@pytest.mark.asyncio
async def test_all_mode_keeps_every_occurrence():
    evs = await rows([ics(DAILY)], recurring="all")
    assert len(evs) == 8
    assert all("repeat" not in e for e in evs)


@pytest.mark.asyncio
async def test_max_events_counts_collapsed_rows():
    single = "UID:s{n}@x\nDTSTART:20260605T100000Z\nDTEND:20260605T110000Z\nSUMMARY:Single {n}"
    evs = await rows([ics(DAILY, single.format(n=1), single.format(n=2))], max_events=3)
    assert sorted(e["summary"] for e in evs) == ["Daily", "Single 1", "Single 2"]


@pytest.mark.asyncio
async def test_moved_occurrence_is_part_of_the_series():
    moved = """UID:daily@x
RECURRENCE-ID:20260604T170000Z
DTSTART:20260604T190000Z
DTEND:20260604T200000Z
SUMMARY:Daily (moved)"""
    evs = await rows([ics(DAILY, moved)])
    assert len(evs) == 1 and evs[0]["summary"] == "Daily"
    # Only the moved one is left in the window: it is the series' row, with the master's text
    only_moved = ics(DAILY.replace("RRULE:FREQ=DAILY", "RRULE:FREQ=DAILY;COUNT=2"), moved)
    evs = await rows([only_moved], max_events=10)
    assert [e["summary"] for e in evs] == ["Daily"]
    module = make_module([only_moved])
    found = module.process_calendar_data(
        only_moved.encode(), {"name": "c"}, datetime.date(2026, 6, 4),
        datetime.datetime(2026, 6, 4, tzinfo=module.tz), datetime.datetime(2026, 6, 5, tzinfo=module.tz))
    assert [(e["summary"], e["rule_text"]) for e in found] == [("Daily (moved)", "every day")]


@pytest.mark.asyncio
async def test_same_uid_in_two_calendars_is_not_merged():
    evs = await rows([ics(DAILY), ics(DAILY)])
    assert len(evs) == 2


@pytest.mark.asyncio
async def test_non_recurring_and_uidless_events_are_untouched():
    single = "UID:one@x\nDTSTART:20260605T100000Z\nDTEND:20260605T110000Z\nSUMMARY:One"
    no_uid = "DTSTART:20260605T120000Z\nDTEND:20260605T130000Z\nSUMMARY:No UID"
    evs = await rows([ics(single, no_uid)])
    assert len(evs) == 2 and all("repeat" not in e for e in evs)


@pytest.mark.asyncio
async def test_complex_rule_gets_icon_only():
    monthly = """UID:m@x
DTSTART:20260604T100000Z
DTEND:20260604T110000Z
RRULE:FREQ=MONTHLY;BYDAY=1TH
SUMMARY:First Thursday"""
    evs = await rows([ics(monthly)])
    assert evs[0]["repeat"] is True and evs[0]["repeat_text"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["week", "month"])
async def test_grid_views_are_unaffected(view):
    module = make_module([ics(DAILY)], view=view)
    await module.render()
    weeks = module.render_template.call_args[1]["weeks"]
    cells = [d for w in weeks for d in w["days"] if d["events"]]
    assert len(cells) > 1
    assert all("repeat" not in e for d in cells for e in d["events"])
