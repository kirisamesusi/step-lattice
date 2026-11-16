"""Smoke-test the standalone preview in Chromium. Screenshots go to the OS temp folder."""
from pathlib import Path
import tempfile
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    chrome = p.chromium.launch(channel="chrome", args=["--enable-webgl",
                              "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    page = chrome.new_page(viewport={"width": 1440, "height": 970}, offline=True)
    page_errors = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.goto((root / "DDR-R1-3D.html").as_uri(), wait_until="load")
    page.locator("#viewport[data-status=ready]").wait_for(timeout=30_000)
    page.locator("#viewport canvas").wait_for()
    target = Path(tempfile.gettempdir()) / "ddr-r1-browser"
    target.mkdir(exist_ok=True)
    for view in ["full", "frame", "module", "sensor", "rear", "center"]:
        page.locator(f'button[data-view="{view}"]').click()
        assert page.locator(f'button[data-view="{view}"]').get_attribute("aria-pressed") == "true"
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        page.screenshot(path=str(target / f"{view}.png"))
    page.locator('button[data-view="full"]').click()
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    point = page.evaluate("""() => {
        const pixel = new THREE.Vector3(445, 222, 43).project(camera);
        const rect = renderer.domElement.getBoundingClientRect();
        return [rect.left + (pixel.x+1)*rect.width/2, rect.top + (1-pixel.y)*rect.height/2];
    }""")
    page.mouse.click(*point)
    assert "AR-PC" in page.locator("#selected").inner_text()
    page.locator('button[data-view="module"]').click()
    page.locator("#module").select_option("L")
    assert page.locator("#module").input_value() == "L"
    page.locator('button[data-view="full"]').click()
    page.locator("#explode").click()
    assert page.locator("#explode").get_attribute("aria-pressed") == "true"
    page.screenshot(path=str(target / "exploded.png"))
    viewport = page.locator("#viewport canvas").bounding_box()
    x = viewport["x"] + viewport["width"]/2
    y = viewport["y"] + viewport["height"]/2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 80, y + 40, steps=7)
    page.mouse.up()
    page.mouse.wheel(0, -150)
    page.locator("#home").click()
    assert not page_errors, page_errors
    print(f"Six views, part selection, module selection, explosion, orbit, zoom, reset passed. Screenshots: {target}")
    chrome.close()
