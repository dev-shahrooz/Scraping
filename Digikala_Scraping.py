# -*- coding: utf-8 -*-
"""
دیجی‌کالا - آیفون‌ها: پیمایش صفحه به صفحه با لاگ و دیباگ مرحله‌به‌مرحله
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time, json, re, os
from urllib.parse import urljoin

# ======== تنظیمات ========
BASE_URL = "https://www.digikala.com"
CATEGORY_URL = "https://www.digikala.com/search/category-mobile-phone/apple/?sort=1&page={page}"
OUT_FILE = "digikala_apple_phones_all_pages.json"
MAX_PAGES = 10            # چند صفحه برود؟
HEADLESS = True           # برای دیدن مرورگر: False
SAVE_DEBUG_EVERY_PAGE = False  # اگر True باشد از هر صفحه HTML/PNG ذخیره می‌کند
# =========================

PERSIAN_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٬", "0123456789,")  # ارقام + ویرگول فارسی

def to_int_price(text: str):
    if not text:
        return None
    t = text.strip().translate(PERSIAN_MAP)
    if any(bt in t for bt in ("%", "ناموجود", "مشاهده", "رایگان", "free")):
        return None
    has_unit = ("تومان" in t) or ("ریال" in t)
    nums = re.findall(r"\d[\d,]{4,}", t) if has_unit else re.findall(r"\d[\d,]{6,}", t)
    if not nums:
        return None
    try:
        return int(nums[-1].replace(",", ""))
    except:
        return None

def setup_driver():
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1400,900")
    return webdriver.Chrome(options=opts)

def save_artifacts(driver, prefix):
    """HTML و اسکرین‌شات ذخیره کن برای دیباگ."""
    try:
        with open(f"{prefix}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception as e:
        print(f"  [debug] نوشتن HTML خطا: {e}")
    try:
        driver.save_screenshot(f"{prefix}.png")
    except Exception as e:
        print(f"  [debug] گرفتن اسکرین‌شات خطا: {e}")

def close_popups_best_effort(driver):
    """پاپ‌آپ‌ها/بنرها را ببند (best-effort)"""
    xps = [
        "//button[contains(text(),'باشه') or contains(text(),'قبول') or contains(text(),'بستن') or contains(text(),'لغو') or contains(text(),'رد کردن')]",
        "//*[@aria-label='بستن' or @aria-label='close' or @aria-label='Close']",
        "//*[@data-testid='modal-close' or @data-testid='close-button']",
        "//div[@role='dialog']//button",
    ]
    hit = False
    for xp in xps:
        try:
            els = driver.find_elements(By.XPATH, xp)
            for el in els[:3]:
                el.click()
                time.sleep(0.2)
                hit = True
        except:  # noqa
            pass
    # پاک کردن اوورلی به‌عنوان آخرین راه
    js_remove = r"""
    (function(){
      try{
        const sels=['[role="dialog"]','.modal,.MuiModal-root,.MuiDialog-root,.overlay,.Backdrop,.backdrop','#modal-root,#modal,#popup,#newsletter,#cookie'];
        let n=0; for(const s of sels){ document.querySelectorAll(s).forEach(e=>{e.remove(); n++;}); }
        document.body.style.overflow='auto'; return n;
      }catch(e){return 0;}
    })();
    """
    try:
        removed = driver.execute_script(js_remove)
        if removed:
            hit = True
    except:  # noqa
        pass
    return hit

def log_counts(driver, label=""):
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href^='/product/']")
    cards_by_testid = driver.find_elements(By.XPATH, "//*[@data-testid='product-card']")
    cards_custom = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'product-list_') and @data-product-index]//a[starts-with(@href,'/product/')]/div[@data-testid='product-card']/ancestor::a[1]"
    )
    print(f"  [{label}] anchors: {len(anchors)} | product-card: {len(cards_by_testid)} | our-cards: {len(cards_custom)}")
    return len(anchors), len(cards_by_testid), len(cards_custom)

def extract_price_from_card(card_el):
    # 1) قیمت اصلی
    for el in card_el.find_elements(By.XPATH, ".//*[@data-testid='price-final']"):
        p = to_int_price(el.text)
        if p: return p
    # 2) کلاس‌های price
    for el in card_el.find_elements(By.XPATH, ".//*[contains(@class,'price')]"):
        p = to_int_price(el.text)
        if p: return p
    # 3) fallback
    return to_int_price(card_el.text or "")

def extract_products_from_dom(driver):
    """فقط کارت‌هایی که خودِ دیجی‌کالا به‌صورت product-card داده استخراج می‌کنیم."""
    items, seen = [], set()
    cards = driver.find_elements(By.XPATH, "//*[@data-testid='product-card']/ancestor::a[1]")
    for a in cards:
        href = a.get_attribute("href")
        if not href or href in seen:
            continue
        seen.add(href)
        # عنوان
        name = ""
        for xp in [".//h3", ".//h2", ".//*[@data-testid='product-title']"]:
            els = a.find_elements(By.XPATH, xp)
            if els:
                name = re.sub(r"\s+", " ", (els[0].text or "").strip())
                if name:
                    break
        if not name:
            name = re.sub(r"\s+", " ", (a.text or "").strip())
        # قیمت
        price = extract_price_from_card(a)
        items.append({
            "name": name if name else href.rsplit("/", 1)[-1],
            "url": urljoin(BASE_URL, href),
            "price": price,
            "currency": "IRR"
        })
    return items

def scrape_page(driver, page_num, save_debug=False):
    url = CATEGORY_URL.format(page=page_num)
    print(f"\n🟩 صفحه {page_num} → {url}")
    driver.get(url)

    # صبر تا کارت‌ها حاضر شوند (یا حداقل body بیاید)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except:
        print("  [warn] body دیر آمد.")
    closed = close_popups_best_effort(driver)
    if closed:
        print("  [info] پاپ‌آپ‌ها/اوورلی‌ها بسته/حذف شد.")

    # قبل از استخراج: شمارش عناصر کلیدی
    log_counts(driver, label="before-wait")

    # صبر مخصوص کارت‌ها
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.XPATH, "//*[@data-testid='product-card']"))
        )
    except:
        print("  [warn] product-card دیده نشد.")
    time.sleep(1.0)

    # شمارش مجدد و ذخیره‌ی دیباگ در صورت نیاز
    a_cnt, pc_cnt, oc_cnt = log_counts(driver, label="after-wait")
    if save_debug or (pc_cnt == 0 and oc_cnt == 0):
        prefix = f"page{page_num:02d}"
        save_artifacts(driver, prefix)
        print(f"  [debug] {prefix}.html و {prefix}.png ذخیره شد.")

    # استخراج
    products = extract_products_from_dom(driver)
    print(f"  [ok] محصولاتِ استخراج‌شده در DOM این صفحه: {len(products)}")
    # نمونه‌ی 3 مورد برای بررسی
    for i, p in enumerate(products[:3], 1):
        print(f"    #{i} {p['name'][:60]} ... | price={p['price']} | url={p['url']}")
    return products

def main():
    driver = setup_driver()
    all_by_url = {}
    try:
        for page in range(1, MAX_PAGES + 1):
            products = scrape_page(driver, page, save_debug=SAVE_DEBUG_EVERY_PAGE)
            # ادغام
            new_added = 0
            for p in products:
                if p["url"] not in all_by_url:
                    all_by_url[p["url"]] = p
                    new_added += 1
            print(f"  [sum] صفحه {page}: {len(products)} مورد، جدید اضافه شد: {new_added}, مجموع کل: {len(all_by_url)}")

            # شرط توقف: اگر هیچ محصولی اضافه نشد، ادامه دادن بی‌فایده است
            if new_added == 0:
                print("  🚩 محصول جدیدی اضافه نشد. پیمایش متوقف شد.")
                break
            time.sleep(0.8)
    finally:
        driver.quit()

    all_products = list(all_by_url.values())
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_products, f, ensure_ascii=False, indent=2)
    print(f"\n📦 مجموع نهایی: {len(all_products)}")
    print(f"📝 فایل خروجی: {OUT_FILE}")

if __name__ == "__main__":
    main()
