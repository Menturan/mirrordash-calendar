import asyncio
import logging
import os
import hashlib
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo
import httpx
from icalendar import Calendar
import recurring_ical_events

logger = logging.getLogger("mirrordash.modules.mirrordash_calendar")

from babel.dates import format_date as babel_format_date

def format_date(d: date, lang: str) -> str:
    """Format a date string in an elegant, localized way using Babel."""
    pattern = "EEEE d MMM" if lang == "sv" else "EEEE, MMM d"
    try:
        formatted = babel_format_date(d, format=pattern, locale=lang)
        return formatted.upper()
    except Exception as e:
        logger.warning(f"Babel format failed for locale '{lang}': {e}. Using fallback.")
        return d.strftime("%A, %B %d").upper()

class CalendarModule:
    def __init__(self, config):
        self.config = config
        self.name = "mirrordash_calendar"
        self.interval = config.get("interval", 300)
        
        # Writable directories
        self.data_dir = config.get("data_dir")
        self.cache_dir = config.get("cache_dir")
        
        # Translations
        self.translations = config.get("translations", {})
        
        # Event Bus
        self.event_bus = config.get("event_bus")
        
        # Resolve config parameters
        global_cfg = config.get("globals", {})
        self.lang = global_cfg.get("language", "en")
        self.time_format = config.get("time_format") or global_cfg.get("time_format", "24h")
        self.max_events = config.get("max_events", 10)
        self.maximum_days = config.get("maximum_days", 7)
        # Resolve calendars config safely
        self.calendars_cfg = []
        raw_calendars = config.get("calendars", [])
        
        if isinstance(raw_calendars, str):
            raw_calendars = raw_calendars.strip()
            if raw_calendars.startswith("[") or raw_calendars.startswith("{"):
                try:
                    import json
                    raw_calendars = json.loads(raw_calendars)
                except Exception:
                    logger.warning("Failed to parse calendars string as JSON")
                    raw_calendars = []
            elif raw_calendars.startswith("http://") or raw_calendars.startswith("https://"):
                raw_calendars = [{"name": "Calendar", "url": raw_calendars}]
            else:
                logger.warning("Invalid calendars config string: '%s'", raw_calendars)
                raw_calendars = []
                
        if isinstance(raw_calendars, list):
            for cal in raw_calendars:
                if isinstance(cal, str):
                    cal = cal.strip()
                    if cal.startswith("http://") or cal.startswith("https://"):
                        self.calendars_cfg.append({
                            "name": "Calendar",
                            "url": cal,
                            "color": "#ffffff",
                            "icon": "calendar"
                        })
                elif isinstance(cal, dict):
                    url = cal.get("url")
                    if url and isinstance(url, str):
                        self.calendars_cfg.append({
                            "name": cal.get("name", "Calendar"),
                            "url": url.strip(),
                            "color": cal.get("color", "#ffffff"),
                            "icon": cal.get("icon", "calendar")
                        })
        else:
            logger.warning("Calendars config must be a list of sources or a single URL string")

        
        # Timezone
        timezone_name = global_cfg.get("timezone", "Europe/Stockholm")
        try:
            self.tz = ZoneInfo(timezone_name)
            logger.info("CalendarModule timezone set to %s", timezone_name)
        except Exception as e:
            self.tz = ZoneInfo("UTC")
            logger.warning("Invalid timezone '%s': %s. Falling back to UTC.", timezone_name, e)
            
        logger.info("Initializing CalendarModule: language=%s, time_format=%s, max_events=%d, lookahead_days=%d", 
                    self.lang, self.time_format, self.max_events, self.maximum_days)

    def translate(self, key: str, default: str = None) -> str:
        if not hasattr(self, "translations") or not self.translations:
            return default if default is not None else key
        val = self.translations.get(key)
        if val is not None:
            return val
        return default if default is not None else key

    async def fetch_feed(self, client: httpx.AsyncClient, url: str) -> bytes:
        """Fetch ICS feed from URL, saving to cache if successful, or falling back to cache if down."""
        cache_filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ".ics"
        cache_path = os.path.join(self.cache_dir, cache_filename) if self.cache_dir else None
        
        try:
            logger.info(f"Fetching calendar feed: {url}")
            response = await client.get(url, timeout=10.0, follow_redirects=True)
            if response.status_code == 200:
                data = response.content
                if cache_path:
                    try:
                        def save_to_file():
                            with open(cache_path, "wb") as f:
                                f.write(data)
                        await asyncio.to_thread(save_to_file)
                        logger.debug(f"Saved calendar cache to {cache_path}")
                    except Exception as ce:
                        logger.warning(f"Could not save calendar cache: {ce}")
                return data
            else:
                logger.warning(f"Calendar feed returned status {response.status_code} for {url}")
        except Exception as e:
            logger.warning(f"Failed to fetch calendar feed {url}: {e}")
            
        # Fallback to cache if request failed
        if cache_path and os.path.exists(cache_path):
            try:
                logger.info(f"Using cached calendar data for {url}")
                def read_from_file():
                    with open(cache_path, "rb") as f:
                        return f.read()
                return await asyncio.to_thread(read_from_file)
            except Exception as re:
                logger.error(f"Failed to read calendar cache from {cache_path}: {re}")
                
        return b""

    def process_calendar_data(self, ics_data: bytes, cal_cfg: dict, today_date: date, start_dt: datetime, end_dt: datetime) -> list[dict]:
        """Parse raw ICS data, expand recurring rules, and structure events list."""
        if not ics_data:
            return []
            
        try:
            cal = Calendar.from_ical(ics_data)
        except Exception as e:
            logger.error(f"Failed to parse iCalendar data: {e}")
            return []
            
        events = []
        try:
            # Expand recurring events between start_dt and end_dt
            occurrences = recurring_ical_events.of(cal).between(start_dt, end_dt)
        except Exception as e:
            logger.error(f"Error expanding recurring events: {e}")
            return []
            
        for event in occurrences:
            dtstart = event.get('dtstart')
            dtend = event.get('dtend')
            
            if not dtstart:
                continue
                
            summary = str(event.get('summary', ''))
            
            # Determine start & end datetime objects in self.tz timezone
            ev_start = dtstart.dt
            if dtend:
                ev_end = dtend.dt
            else:
                # If dtend is missing, default to 1 hour after start (or same day for all-day)
                if isinstance(ev_start, datetime):
                    ev_end = ev_start + timedelta(hours=1)
                else:
                    ev_end = ev_start + timedelta(days=1)
                    
            all_day = False
            
            # Convert start and end to datetime.datetime in self.tz
            if isinstance(ev_start, datetime):
                # Timed event
                if ev_start.tzinfo is None:
                    # Naive datetime: assume it is in configured local timezone
                    start_aware = ev_start.replace(tzinfo=self.tz)
                else:
                    start_aware = ev_start.astimezone(self.tz)
                    
                if ev_end.tzinfo is None:
                    end_aware = ev_end.replace(tzinfo=self.tz)
                else:
                    end_aware = ev_end.astimezone(self.tz)
            else:
                # All-day event (represented as datetime.date)
                all_day = True
                start_aware = datetime.combine(ev_start, time.min, tzinfo=self.tz)
                end_aware = datetime.combine(ev_end, time.min, tzinfo=self.tz)
                
            # Filter out events that have already ended
            now_tz = datetime.now(self.tz)
            if end_aware <= now_tz:
                continue
                
            # Find which local dates (in self.tz) this event intersects
            # Local window dates: [today_date, today_date + maximum_days]
            start_local_date = start_aware.date()
            if all_day:
                # All-day event ends at midnight of ev_end. Date range is [ev_start, ev_end)
                end_local_date = ev_end - timedelta(days=1)
            else:
                # For timed events, the date range spans from start to end date.
                # If the end is exactly at midnight, we exclude the end day.
                if end_aware.time() == time.min and end_aware > start_aware:
                    end_local_date = (end_aware - timedelta(days=1)).date()
                else:
                    end_local_date = end_aware.date()
                    
            # Loop through dates in lookahead window and check for intersections
            for d_idx in range(self.maximum_days + 1):
                d = today_date + timedelta(days=d_idx)
                if start_local_date <= d <= end_local_date:
                    # Format time strings
                    if all_day:
                        time_str = self.translate("all_day", "All Day")
                    else:
                        # Event starts at start_aware, ends at end_aware.
                        # Check if start/end happens on this exact day d
                        s_time = start_aware.strftime("%H:%M") if self.time_format == "24h" else start_aware.strftime("%I:%M %p").lstrip('0')
                        e_time = end_aware.strftime("%H:%M") if self.time_format == "24h" else end_aware.strftime("%I:%M %p").lstrip('0')
                        
                        if start_local_date == d and end_local_date == d:
                            time_str = f"{s_time} - {e_time}"
                        elif start_local_date == d:
                            # Starts today, ends tomorrow
                            time_str = f"{s_time} →"
                        elif end_local_date == d:
                            # Started yesterday, ends today
                            time_str = f"→ {e_time}"
                        else:
                            # Ongoing multi-day event
                            time_str = self.translate("all_day", "All Day")
                            
                    events.append({
                        "summary": summary,
                        "start_dt": start_aware,
                        "end_dt": end_aware,
                        "all_day": all_day,
                        "calendar_name": cal_cfg.get("name"),
                        "calendar_color": cal_cfg.get("color", "#ffffff"),
                        "calendar_icon": cal_cfg.get("icon", "calendar"),
                        "date": d,
                        "time_str": time_str
                    })
                    
        return events

    async def run_loop(self, broadcast_func):
        """The main lifecycle loop. Fetch feeds, parse occurrences, group, and broadcast."""
        logger.info(f"Starting {self.name} run loop")
        while True:
            try:
                # 1. Fetch all feeds in parallel using httpx client
                ics_contents = []
                async with httpx.AsyncClient(verify=True) as client:
                    tasks = [self.fetch_feed(client, cal.get("url")) for cal in self.calendars_cfg]
                    ics_contents = await asyncio.gather(*tasks)
                    
                # 2. Process all events
                now_tz = datetime.now(self.tz)
                today_date = now_tz.date()
                
                # Start window is today at 00:00:00
                window_start = datetime.combine(today_date, time.min, tzinfo=self.tz)
                # End window is today + maximum_days at 23:59:59
                window_end = datetime.combine(today_date + timedelta(days=self.maximum_days), time.max, tzinfo=self.tz)
                
                all_events = []
                for idx, cal_cfg in enumerate(self.calendars_cfg):
                    if idx < len(ics_contents):
                        cal_events = self.process_calendar_data(
                            ics_contents[idx],
                            cal_cfg,
                            today_date,
                            window_start,
                            window_end
                        )
                        all_events.extend(cal_events)
                        
                # 3. Sort events
                # Rule: Sort by local event date, then all-day events first, then start time, then title
                # To sort all-day first, we map all_day to 0, timed to 1.
                all_events.sort(key=lambda x: (
                    x["date"],
                    0 if x["all_day"] else 1,
                    x["start_dt"],
                    x["summary"]
                ))
                
                # 4. Limit to max_events
                display_events = all_events[:self.max_events]
                
                # 5. Group by local date
                grouped_events = []
                current_date = None
                current_group = None
                
                for ev in display_events:
                    ev_date = ev["date"]
                    if ev_date != current_date:
                        current_date = ev_date
                        
                        # Determine day label
                        diff_days = (ev_date - today_date).days
                        if diff_days == 0:
                            day_label = self.translate("today", "Today").upper()
                        elif diff_days == 1:
                            day_label = self.translate("tomorrow", "Tomorrow").upper()
                        else:
                            day_label = format_date(ev_date, self.lang)
                            
                        current_group = {
                            "day_label": day_label,
                            "events": []
                        }
                        grouped_events.append(current_group)
                        
                    current_group["events"].append(ev)
                    
                # 6. Render dynamic HTML using Jinja2 template
                html = self.render_template(
                    "widget.html",
                    grouped_events=grouped_events,
                    last_checked=datetime.now().strftime("%H:%M")
                )
                
                # 7. Broadcast HTML update to the UI
                logger.info(f"Broadcasting update for {self.name} with {len(display_events)} upcoming events")
                await broadcast_func(self.name, html)
                
            except asyncio.CancelledError:
                logger.info(f"Stopping {self.name} run loop.")
                raise
            except Exception as e:
                logger.error(f"Error in module {self.name} run_loop: {e}", exc_info=True)
                
            await asyncio.sleep(self.interval)
