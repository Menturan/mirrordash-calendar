# mirrordash-calendar
 
Detailed calendar module showing upcoming events for MirrorDash.

## Features
- Supports standard iCalendar (`.ics`) subscriptions from Google Calendar, Apple iCloud, Microsoft Outlook, etc.
- Async parallel fetching of multiple calendars with caching.
- Dynamic color swatches and customizable vector icons for events.

## Installation
 
Install in editable mode for local development:
```bash
uv pip install -e .
```

## Configuration & API Keys / Feeds

To configure calendars on your mirror, retrieve the public/private iCal subscription URL:

### 1. Google Calendar
- Open [Google Calendar](https://calendar.google.com).
- Under "My calendars", click the three dots next to the calendar you want to sync and select **Settings and sharing**.
- Scroll to the bottom of the settings page.
- Copy the **Secret address in iCal format** (for private calendars) or the **Public address in iCal format** (if the calendar is public).
- Paste this URL in the Visual Configuration Dashboard under the "Calendars" array section of the Module tab.

### 2. Microsoft Outlook
- Open [Outlook Web](https://outlook.live.com).
- Go to Settings (gear icon) -> **Calendar** -> **Shared calendars**.
- Under "Publish a calendar", select the calendar and choose permissions (e.g. "Can view all details"), then click **Publish**.
- Copy the generated **ICS** link and paste it into the mirror configuration.

## Screenshot

![Calendar Widget Screenshot](screenshot.png)
