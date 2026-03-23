import asyncio
from app.services.starting_parsers import run_parser, run_worker

if __name__ == "__main__":
    asyncio.run(run_parser())
    asyncio.run(run_worker())
