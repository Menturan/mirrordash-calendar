# mirrordash-calendar

Detailed calendar module showing upcoming events for MirrorDash.

## Features
- Supports standard iCalendar (`.ics`) subscriptions from Google Calendar, Apple iCloud, Microsoft Outlook, etc.
- Async parallel fetching of multiple calendars with caching.
- Dynamic color swatches and customizable vector icons for events.

## Installation

On the mirror's admin page, open **Modules**: the module is in the list, install it with one click.
Or paste `git+https://github.com/Menturan/mirrordash-calendar.git` under **Modules → Install a Module from GitHub**.

Developing it: `uv run pytest` runs its tests, and `uvx mirrordash-sdk validate .` checks it.

## Screenshot

![Calendar Widget Screenshot](screenshot.png)

## Troubleshooting

### Calendar events are not showing up
*   Verify that your calendar URL is public and ends with `.ics`. 
*   Google Calendar private links must be the "Secret address in iCal format" found in your Google Calendar settings.

## License
[PolyForm Noncommercial License 1.0.0](LICENSE.md)
