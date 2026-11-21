"""Turn an RRULE into a short phrase such as "every day" or "Monday, Wednesday and Friday".

Only the common rules are described; anything else gives None (the list then shows the icon only)."""
from babel.dates import get_day_names

# English fallbacks, used when the mirror gives no translation for a key
DEFAULTS = {
    "rrule_every_day": "every day",
    "rrule_every_n_days": "every {n} days",
    "rrule_every_weekday_name": "every {day}",
    "rrule_weekdays": "weekdays",
    "rrule_every_other_week": "every other week",
    "rrule_every_other_day_name": "every other {day}",
    "rrule_every_month": "every month",
    "rrule_every_year": "every year",
    "and": "and",
}

DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]  # index = date.weekday()
# Parts of a rule that do not change how it reads (or that we ignore on purpose)
HARMLESS = {"FREQ", "INTERVAL", "BYDAY", "WKST", "COUNT", "UNTIL"}


def describe_rrule(rrule, dtstart, lang: str, translate) -> str | None:
    """rrule: an icalendar vRecur (or a dict of lists), dtstart: a date or datetime,
    translate: a function (key, default) -> text."""
    rule = {str(k).upper(): v for k, v in rrule.items()}
    if not set(rule) <= HARMLESS:
        return None  # BYSETPOS, BYMONTHDAY, BYHOUR, ...

    def first(key, default):
        value = rule.get(key, [default])
        return value[0] if isinstance(value, (list, tuple)) else value

    def t(key, **values):
        return translate(key, DEFAULTS[key]).format(**values)

    freq = str(first("FREQ", "")).upper()
    try:
        interval = int(first("INTERVAL", 1))
    except (TypeError, ValueError):
        return None
    days = rule.get("BYDAY", [])
    days = [str(d).upper() for d in (days if isinstance(days, (list, tuple)) else [days])]
    if any(d not in DAY_CODES for d in days):
        return None  # ordinals such as 2TH or -1FR

    if freq == "DAILY" and not days:
        return t("rrule_every_day") if interval == 1 else t("rrule_every_n_days", n=interval)

    if freq == "WEEKLY" and interval in (1, 2):
        names = get_day_names("wide", locale=lang)
        if not days:
            if interval == 2:
                return t("rrule_every_other_week")
            days = [DAY_CODES[dtstart.weekday()]]
        days = sorted(set(days), key=DAY_CODES.index)
        if len(days) == 1:
            day = names[DAY_CODES.index(days[0])]
            return t("rrule_every_weekday_name" if interval == 1 else "rrule_every_other_day_name", day=day)
        if interval == 2:
            return t("rrule_every_other_week")
        if days == DAY_CODES[:5]:
            return t("rrule_weekdays")
        listed = [names[DAY_CODES.index(d)] for d in days]
        return f"{', '.join(listed[:-1])} {t('and')} {listed[-1]}"

    if interval == 1 and not days:
        if freq == "MONTHLY":
            return t("rrule_every_month")
        if freq == "YEARLY":
            return t("rrule_every_year")
    return None
