# app/run_all.py
import asyncio

from .search_bot import main as search_main
from .delivery_bot import main as delivery_main

async def main():
    await asyncio.gather(
        search_main(),
        delivery_main(),
    )

if __name__ == "__main__":
    asyncio.run(main())