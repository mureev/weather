"""Screenshots at iPhone size, light and dark. `python -m tests.shoot`"""
import asyncio
import os
import pathlib
import subprocess
import sys
import time

from playwright.async_api import async_playwright

OUT = pathlib.Path("screenshots")
OUT.mkdir(exist_ok=True)

async def shoot(mode="ok", port=8098):
    env = dict(os.environ, YW_MOCK=mode, PORT=str(port))
    p = subprocess.Popen([sys.executable,"-m","tests.mock_server"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.5)
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium"
                if pathlib.Path("/opt/pw-browsers/chromium").exists() else None)
            for scheme in ("dark","light"):
                ctx = await b.new_context(viewport={"width":393,"height":852},
                    device_scale_factor=2, color_scheme=scheme, locale="ru-RU")
                pg = await ctx.new_page()
                await pg.goto(f"http://127.0.0.1:{port}/weather/", wait_until="networkidle")
                await pg.wait_for_timeout(900)
                await pg.screenshot(path=str(OUT/f"{mode}-{scheme}.png"), full_page=True)
                await ctx.close()
            await b.close()
    finally:
        p.terminate()
        p.wait(timeout=10)

if __name__ == "__main__":
    for m in (sys.argv[1:] or ["ok"]):
        asyncio.run(shoot(m))
        print("shot", m)
