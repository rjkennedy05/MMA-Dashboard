from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SCOREBOARD_URLS = (
    "https://site.api.espn.com/apis/site/v2/sports/mma/"
    "{league}/scoreboard",
    "https://site.web.api.espn.com/apis/site/v2/sports/mma/"
    "{league}/scoreboard",
)
FIGHTCENTER_URL = (
    "https://site.web.api.espn.com/apis/common/v3/sports/mma/"
    "{league}/fightcenter/{event_id}"
)
CORE_EVENTS_URL = (
    "https://sports.core.api.espn.com/v2/sports/mma/leagues/"
    "{league}/events"
)
CORE_EVENT_URL = CORE_EVENTS_URL + "/{event_id}"
CORE_COMPETITION_URL = (
    CORE_EVENT_URL + "/competitions/{competition_id}"
)
CORE_ATHLETE_URL = (
    "https://sports.core.api.espn.com/v2/sports/mma/leagues/"
    "{league}/athletes/{athlete_id}"
)
SUPPORTED_LEAGUES = {"pfl", "ufc"}


class EspnMmaError(RuntimeError):
    """Raised when ESPN returns an unusable MMA response."""


class EspnMmaNoFightCardError(EspnMmaError):
    """Raised for ESPN listings that do not represent a published fight card."""


class EspnMmaClient:
    def __init__(
        self,
        league: str = "pfl",
        session: requests.Session | None = None,
        timeout: int = 45,
    ) -> None:
        normalized_league = str(league).strip().casefold()
        if normalized_league not in SUPPORTED_LEAGUES:
            raise ValueError(
                "ESPN MMA league must be either 'pfl' or 'ufc'."
            )
        self.league = normalized_league
        self.session = session or self._build_session()
        self.timeout = timeout
        self.request_count = 0
        self.event_source = "not_run"
        self.fightcenter_fallbacks = 0
        self.headers = {
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.espn.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
        }

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.6,
            # A 403 is a host-level denial, not a transient response. Retrying
            # it only delays the fallback and can intensify rate limiting.
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                params=params,
                timeout=self.timeout,
            )
            self.request_count += 1
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise EspnMmaError(f"ESPN MMA request failed: {error}") from error
        except ValueError as error:
            raise EspnMmaError(
                "ESPN MMA returned a non-JSON response."
            ) from error

        if not isinstance(payload, dict):
            raise EspnMmaError("ESPN MMA response is not a JSON object.")
        return payload

    def get_events_for_season(self, season: int) -> list[dict[str, Any]]:
        errors: list[str] = []
        for source_index, url_template in enumerate(SCOREBOARD_URLS):
            try:
                payload = self._get_json(
                    url_template.format(league=self.league),
                    {"dates": str(season)},
                )
            except EspnMmaError as error:
                errors.append(str(error))
                continue

            events = payload.get("events")
            if isinstance(events, list) and events:
                normalized_events = [
                    event for event in events if isinstance(event, dict)
                ]
                dated_events = [
                    event
                    for event in normalized_events
                    if self._date_from_event(event) is not None
                ]
                season_events = [
                    event
                    for event in dated_events
                    if self._date_from_event(event).year == season
                ]
                # Some ESPN MMA scoreboard deployments ignore the requested
                # year and return only the current card. Never accept that as
                # a historical season response.
                if season_events:
                    self.event_source = (
                        "site_scoreboard"
                        if source_index == 0
                        else "web_scoreboard"
                    )
                    return season_events
                if normalized_events and not dated_events:
                    # Retain compatibility with sparse test/provider rows that
                    # genuinely omit dates; the importer will validate them.
                    self.event_source = (
                        "site_scoreboard"
                        if source_index == 0
                        else "web_scoreboard"
                    )
                    return normalized_events

            calendar_events = self._calendar_events(payload, season)
            if calendar_events:
                self.event_source = (
                    "site_calendar"
                    if source_index == 0
                    else "web_calendar"
                )
                return calendar_events

            if isinstance(events, list):
                if events:
                    errors.append(
                        f"ESPN MMA scoreboard ignored season {season}."
                    )
                    continue
                self.event_source = (
                    "site_scoreboard"
                    if source_index == 0
                    else "web_scoreboard"
                )
                return []
            errors.append("ESPN MMA scoreboard is missing its events list.")

        try:
            events = self._get_core_events_for_season(season)
        except EspnMmaError as core_error:
            errors.append(str(core_error))
            raise EspnMmaError(
                "All ESPN MMA event sources failed: " + " | ".join(errors)
            ) from core_error
        self.event_source = "core_events"
        return [
            event
            for event in events
            if (
                (event_date := self._date_from_event(event)) is not None
                and event_date.year == season
            )
        ]

    def get_events_in_window(
        self,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        if end < start:
            raise ValueError("ESPN MMA event window ends before it starts.")

        # Broad Core `dates` queries can return only a partial first page even
        # when the requested window spans years, and Core currently ignores its
        # MMA `season` filter. History backfills must use the season-aware site
        # scoreboard/calendar discovery path one year at a time. Core remains
        # the per-season fallback and fight-detail hydrator.
        if (end - start).days > 370:
            events_by_id: dict[str, dict[str, Any]] = {}
            for season in range(start.year, end.year + 1):
                for event in self.get_events_for_season(season):
                    event_id = event.get("id")
                    if event_id is not None:
                        events_by_id[str(event_id)] = event

            edge_start = start - timedelta(days=1)
            edge_end = end + timedelta(days=1)
            events = [
                event
                for event in events_by_id.values()
                if (
                    (event_date := self._date_from_event(event)) is not None
                    and edge_start <= event_date <= edge_end
                )
            ]
            self.event_source = "season_sweep"
            return events

        date_range = f"{start:%Y%m%d}-{end:%Y%m%d}"
        errors: list[str] = []
        for source_index, url_template in enumerate(SCOREBOARD_URLS):
            try:
                payload = self._get_json(
                    url_template.format(league=self.league),
                    {"dates": date_range},
                )
            except EspnMmaError as error:
                errors.append(str(error))
                continue

            events = payload.get("events")
            if isinstance(events, list) and events:
                self.event_source = (
                    "site_scoreboard"
                    if source_index == 0
                    else "web_scoreboard"
                )
                return [
                    event for event in events if isinstance(event, dict)
                ]
            errors.append("ESPN MMA scoreboard returned an empty or missing events list.")

        try:
            events = self._get_core_events(start=start, end=end)
        except EspnMmaError as core_error:
            errors.append(str(core_error))
            raise EspnMmaError(
                "All ESPN MMA event sources failed: " + " | ".join(errors)
            ) from core_error
        self.event_source = "core_events"
        return events

    @staticmethod
    def _date_from_event(event: dict[str, Any]) -> date | None:
        raw = str(event.get("date") or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date()

    def _core_event_from_item(
        self,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        if item.get("id") and item.get("name") and item.get("date"):
            return item
        ref = str(item.get("$ref") or "")
        match = re.search(r"/events/(\d+)", ref)
        if not match:
            return None
        return self._get_json(
            CORE_EVENT_URL.format(
                league=self.league,
                event_id=match.group(1),
            )
        )

    def _get_core_collection(
        self,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        payload = self._get_json(
            CORE_EVENTS_URL.format(league=self.league),
            params,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise EspnMmaError(
                "ESPN Core event collection is missing its items list."
            )
        events: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            event = self._core_event_from_item(item)
            if event:
                events.append(event)
        return events

    def _get_core_events_for_season(
        self,
        season: int,
    ) -> list[dict[str, Any]]:
        return self._get_core_collection(
            {"season": str(season), "limit": "100"}
        )

    def _get_core_events(
        self,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        edge_start = start - timedelta(days=1)
        edge_end = end + timedelta(days=1)

        if (end - start).days > 370:
            events_by_id: dict[str, dict[str, Any]] = {}
            for season in range(start.year, end.year + 1):
                for event in self._get_core_events_for_season(season):
                    event_id = event.get("id")
                    if event_id is not None:
                        events_by_id[str(event_id)] = event
            return [
                event
                for event in events_by_id.values()
                if (
                    (event_date := self._date_from_event(event)) is not None
                    and edge_start <= event_date <= edge_end
                )
            ]

        date_range = f"{start:%Y%m%d}-{end:%Y%m%d}"
        try:
            events = self._get_core_collection(
                {"dates": date_range, "limit": "100"}
            )
        except EspnMmaError:
            events_by_id: dict[str, dict[str, Any]] = {}
            for season in range(start.year, end.year + 1):
                for event in self._get_core_events_for_season(season):
                    event_id = event.get("id")
                    if event_id is not None:
                        events_by_id[str(event_id)] = event
            events = list(events_by_id.values())

        # ESPN timestamps are UTC while dashboard dates are Central Time.
        # Keep a one-day edge buffer; the caller performs the authoritative
        # timezone-aware window filter.
        filtered = [
            event
            for event in events
            if (
                (event_date := self._date_from_event(event)) is not None
                and edge_start <= event_date <= edge_end
            )
        ]
        if filtered:
            return filtered

        # Some Core deployments ignore the `dates` query and return the
        # first page of the all-time collection. Use the explicit season
        # collection before concluding that the current window is empty.
        events_by_id: dict[str, dict[str, Any]] = {}
        for season in range(start.year, end.year + 1):
            for event in self._get_core_events_for_season(season):
                event_id = event.get("id")
                if event_id is not None:
                    events_by_id[str(event_id)] = event
        return [
            event
            for event in events_by_id.values()
            if (
                (event_date := self._date_from_event(event)) is not None
                and edge_start <= event_date <= edge_end
            )
        ]

    @staticmethod
    def _calendar_events(
        payload: dict[str, Any],
        season: int,
    ) -> list[dict[str, Any]]:
        events_by_id: dict[str, dict[str, Any]] = {}
        for league in payload.get("leagues") or []:
            if not isinstance(league, dict):
                continue
            for row in league.get("calendar") or []:
                if not isinstance(row, dict):
                    continue
                event_ref = row.get("event") or {}
                if not isinstance(event_ref, dict):
                    continue
                ref = str(event_ref.get("$ref") or "")
                match = re.search(r"/events/(\d+)", ref)
                start_date = str(row.get("startDate") or "")
                if not match or not start_date.startswith(f"{season:04d}-"):
                    continue
                event_id = match.group(1)
                events_by_id[event_id] = {
                    "id": event_id,
                    "name": row.get("label"),
                    "date": row.get("startDate"),
                }
        return list(events_by_id.values())

    def get_events(
        self,
        first_season: int,
        last_season: int,
    ) -> list[dict[str, Any]]:
        events_by_id: dict[str, dict[str, Any]] = {}
        for season in range(first_season, last_season + 1):
            for event in self.get_events_for_season(season):
                event_id = event.get("id")
                if event_id is not None:
                    events_by_id[str(event_id)] = event
        return list(events_by_id.values())

    def get_fightcenter(self, event_id: str) -> dict[str, Any]:
        try:
            payload = self._get_json(
                FIGHTCENTER_URL.format(
                    league=self.league,
                    event_id=event_id,
                )
            )
            cards = payload.get("cards")
            if not isinstance(cards, dict):
                raise EspnMmaError(
                    f"ESPN fightcenter {event_id} is missing its cards object."
                )
            return payload
        except EspnMmaError:
            self.fightcenter_fallbacks += 1
            return self._get_core_fightcenter(event_id)

    def _get_core_fightcenter(self, event_id: str) -> dict[str, Any]:
        event = self._get_json(
            CORE_EVENT_URL.format(
                league=self.league,
                event_id=event_id,
            )
        )
        competitions: list[dict[str, Any]] = []
        for item in event.get("competitions") or []:
            if not isinstance(item, dict):
                continue
            competition = item
            if not competition.get("id"):
                ref = str(competition.get("$ref") or "")
                match = re.search(r"/competitions/(\d+)", ref)
                if not match:
                    continue
                competition = self._get_json(
                    CORE_COMPETITION_URL.format(
                        league=self.league,
                        event_id=event_id,
                        competition_id=match.group(1),
                    )
                )
            competition = self._hydrate_core_competitors(competition)
            competitions.append(competition)

        if not competitions:
            raise EspnMmaNoFightCardError(
                f"ESPN Core event {event_id} has no fight competitions."
            )
        return {"cards": {"core": {"competitions": competitions}}}

    def _hydrate_core_competitors(
        self,
        competition: dict[str, Any],
    ) -> dict[str, Any]:
        hydrated = dict(competition)
        competitors: list[dict[str, Any]] = []
        for item in competition.get("competitors") or []:
            if not isinstance(item, dict):
                continue
            competitor = dict(item)
            athlete = competitor.get("athlete") or {}
            if not isinstance(athlete, dict):
                athlete = {}
            if isinstance(athlete, dict) and not (
                athlete.get("displayName") or athlete.get("fullName")
            ):
                ref = str(athlete.get("$ref") or "")
                match = re.search(r"/athletes/(\d+)", ref)
                if match:
                    athlete = self._get_json(
                        CORE_ATHLETE_URL.format(
                            league=self.league,
                            athlete_id=match.group(1),
                        )
                    )
            competitor["athlete"] = athlete
            competitors.append(competitor)
        hydrated["competitors"] = competitors
        return hydrated
