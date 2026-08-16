"""The clock that ticks behind the web application.

Every few seconds it opens a fresh session, rings the due lesson alarms and
gives the morning round its chance to run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import datetime

from fastapi import FastAPI

from invoicing.alarms import LessonAlarmClock
from invoicing.constant import ALARM_CHECK_INTERVAL_SECONDS
from invoicing.push import WebPushSender
from invoicing.storage.database import InvoiceDatabase
from invoicing.web.daily import MorningRound
from invoicing.web.store_queries import StoreQueries


class TickingAlarmClock:
    """Ticks against the given database for the lifetime of the app."""

    def __init__(
        self,
        database: InvoiceDatabase,
        check_seconds: int = ALARM_CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._database = database
        self._check_seconds = check_seconds

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncGenerator[None]:
        """Tick from application start-up until shutdown."""
        ticking = asyncio.create_task(self.run_forever())
        yield
        ticking.cancel()
        with suppress(asyncio.CancelledError):
            await ticking

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.ring_once)
            except Exception:
                logging.getLogger(__name__).exception("Weckrunde fehlgeschlagen")
            await asyncio.sleep(self._check_seconds)

    def ring_once(self) -> None:
        with self._database.session() as session:
            settings = StoreQueries(session).app_settings()
            now = datetime.now()
            send = WebPushSender(session, settings).send_to_all
            LessonAlarmClock(session, settings, send).ring_all_due(now)
            MorningRound(session, settings, send).run(now)
