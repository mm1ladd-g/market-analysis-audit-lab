<div dir="rtl" lang="fa">

# رفع اشکال

[فارسی](troubleshooting.md) · [English](../en/troubleshooting.md) · [مستندات](index.md)

با `doctor` و `status` شروع و هرگز `.env` یا بستهٔ خصوصی را در Issue نگذارید.

- تنظیم منبع ناقص: نام، URL/ID، تاریخ و تأیید حقوق را بررسی کنید.
- مرز تاریخ ثابت نشده: پس از برآورد حجم، `MAX_SCAN_ITEMS` را افزایش دهید.
- زیرنویس نیست: ترتیب زبان را بررسی یا رونویسی مجاز بدهید؛ شاهد نسازید.
- OpenAI رد می‌شود: حالت API، کلید، مدل موجود و تأیید هزینه.
- Rate Limit: Concurrency کمتر و Cache موفق را حفظ کنید.
- دارایی پشتیبانی نیست: Asset Map و منبع دفاع‌پذیر؛ Proxy را حدس نزنید.
- CSV خراب: Timezone، OHLC، Sort، Duplicate، Interval و Gap.
- پنجره ناقص: صبر یا `insufficient_data`؛ بی‌صدا کوتاه نکنید.
- هش ناسازگار: انتشار را متوقف و Byte دقیق را بازیابی یا مرحله را بازسازی کنید.
- فارسی خراب: UTF-8، Font/OFL، RTL و LTR بودن Chart/Hash.

`--force` ممکن است هزینه کند و باید ثبت شود.

</div>
