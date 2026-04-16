import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.pars_aask import ParsAask
from app.services.pars_aag import AAGParser


class ParserWorker:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

        self.aask_parser = ParsAask()
        self.aag_parser = AAGParser()

    async def run_all_parsers(self):
        print(f"[WORKER] Запуск парсеров: {datetime.now()}")

        try:
            await self.aask_parser.download_and_generate_schedule()
        except Exception as e:
            print(f"[ERROR] AASK: {e}")

        try:
            await self.aag_parser.run()
        except Exception as e:
            print(f"[ERROR] AAG: {e}")

        print(f"[WORKER] Завершено: {datetime.now()}")

    def setup_jobs(self):
        self.scheduler.add_job(
            self.run_all_parsers,
            CronTrigger(hour=19, minute=1),
            name="daily_parsing",
        )

    async def start(self):
        self.setup_jobs()
        self.scheduler.start()

        print("Запущен планировщик")
        while True:
            await asyncio.sleep(3600)

async def run_parser():
    worker = ParserWorker()

    print("[WORKER] Ручной запуск парсеров")
    await worker.run_all_parsers()

async def run_worker():
    worker = ParserWorker()
    await worker.start()