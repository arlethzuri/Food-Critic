from playwright.sync_api import sync_playwright

START_URL = "https://public.cdpehs.com/UTEnvPbl/VW_EST_PUBLIC/ShowVW_EST_PUBLICTablePage.aspx"

with sync_playwright() as p:
    # Run headful so you can physically watch the window open
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    print("Navigating to target URL...")
    page.goto(START_URL)
    page.wait_for_load_state("networkidle")
    
    # 1. Check where we actually landed
    print(f"\n[INFO] Current URL: {page.url}")
    print(f"[INFO] Page Title: {page.title()}")
    
    # 2. Take a physical screenshot
    page.screenshot(path="debug_screenshot.png")
    print("[INFO] Saved viewport screenshot to 'debug_screenshot.png'")
    
    # 3. Scan the DOM for potential search or welcome button elements
    print("\n[INFO] Scanning for interactive elements...")
    elements = page.locator("input, button, a").all()
    for idx, el in enumerate(elements):
        try:
            tag = el.evaluate("el => el.tagName")
            id_val = el.get_attribute("id") or ""
            name_val = el.get_attribute("name") or ""
            val_val = el.get_attribute("value") or ""
            alt_val = el.get_attribute("alt") or ""
            text_val = el.inner_text().strip().replace('\n', ' ')
            
            # Filter elements matching typical portal navigation keywords
            if any(x in (id_val + name_val + val_val + alt_val + text_val).lower() for x in ["search", "clear", "welcome", "agree", "accept"]):
                print(f"[{idx}] <{tag}> | ID: {id_val} | Name: {name_val} | Value: {val_val} | Alt: {alt_val} | Text: '{text_val}'")
        except Exception:
            pass

    browser.close()