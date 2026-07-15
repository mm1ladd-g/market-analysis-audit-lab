<div dir="rtl" lang="fa">

# مرجع تنظیمات

[فارسی](configuration.md) · [English](../en/configuration.md) · [مستندات](index.md)

تنظیمات از Environment و `.env` خوانده می‌شوند. `.env` را Commit نکنید؛ دستور `doctor` فقط خلاصهٔ پاک‌سازی‌شده چاپ می‌کند.

## منبع

- `ANALYST_NAME`، `YOUTUBE_CHANNEL_URL` و `YOUTUBE_CHANNEL_ID`: هویت منبع واقعی و الزامی؛ URL و ID کنترل متقابل می‌شوند.
- `SOURCE_MODE=provided` برای ورودی مجاز اپراتور و `youtube` برای Adapter پلتفرمِ دارای Gate است؛ `PROVIDED_SOURCES_DIR` محل Import را تعیین می‌کند.
- `START_DATE` و `END_DATE`: بازهٔ ISO شامل دو سر؛ `MAX_AUDIT_DAYS` و `MAX_SCAN_ITEMS` محافظ حجم هستند.
- `SOURCE_RIGHTS_ACKNOWLEDGED`: ثبت تأیید اپراتور، نه مجوز حقوقی.
- `SUBTITLE_LANGUAGES`: ترتیب ترجیح زیرنویس؛ `REQUIRE_SUBTITLES_FOR_AUDIT` مانع ساخت شاهد خیالی می‌شود.
- `STRICT_SOURCE_CHANNEL`: رد فرادادهٔ کانال دیگر؛ `COLLECT_THUMBNAILS` پیش‌فرض خاموش است.
- `TRANSCRIPTION_FALLBACK`، مدل، زبان/Prompt و اندازهٔ Chunk، گفتاربه‌متنِ صوت مجاز را کنترل می‌کنند؛ `RETAIN_RAW_AUDIO` پیش‌فرض خاموش است.

## دامنه و بازار

- `AUDIT_SCOPE_CATEGORIES`: شناسه‌های دسته؛ فایل‌های `CATEGORY_OVERRIDES_FILE` و `ASSET_MAP_FILE` ورودی نسخه‌بندی‌شدهٔ روش‌شناسی هستند.
- `PRICE_OUTCOME_ONLY`: زمینهٔ غیرقیمتی را از امتیاز بیرون نگه می‌دارد.
- `INTERNATIONAL_MARKET_PROVIDER`: مقدار `csv` برای دادهٔ دقیق/مجاز یا `yfinance` برای Proxy شفاف.
- `MARKET_CSV_DIR` و `REPORT_DEFAULT_LANGUAGE`.
- `PUBLICATION_MODE` پیش‌فرض `private` و `PUBLIC_CLAIM_LEDGER` خاموش است، زیرا شاهد می‌تواند متن رونویسی را بازنمایی کند.

`PUBLICATION_MODE` واقعاً اعمال می‌شود: `private` صفحه را پیش‌نمایش محلی می‌نامد و دانلود PDF/دفتر را می‌بندد. در حالت `public`، فرمان `review accept` باید با هش فعلی مجموعه، پیامد و امتیاز منطبق باشد؛ پس از بازتولید و بررسی داشبورد، PDF و هر دفتر عمومی اختیاری، `review publication-accept` باید دقیقاً همین آثار ارائه را به هش متصل کند. `finalize` عمومی و دانلودها تا زمانی که هر دو ایست بازرسی فعلی نباشند مسدود می‌مانند. `PUBLIC_CLAIM_LEDGER=true` اجازه‌ای جداگانه است و Container وبِ امن و پیش‌فرض عمداً دفتر خصوصی تحلیل را Mount نمی‌کند.

## OpenAI

- `AUDIT_MODE=api`، `OPENAI_API_KEY` و `API_COST_ACKNOWLEDGED=true` برای کار پولی لازم‌اند.
- شناسهٔ دقیق و موجود مدل استخراج و امتیاز را تنظیم کنید؛ واژهٔ «جدیدترین» برای سابقهٔ بازتولید مناسب نیست.
- Concurrency، Timeout، Retry و قیمت اختیاری را محافظه‌کارانه تنظیم و قیمت رسمی را هر بار بررسی کنید.

`WORKSPACE_DIR` باید یک Volume اختصاصی و کنترل‌شده باشد، نه ریشهٔ مخزن، Home یا Web Root.

</div>
