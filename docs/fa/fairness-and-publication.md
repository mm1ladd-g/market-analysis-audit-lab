<div dir="rtl" lang="fa">

# انصاف، اصلاح و حق پاسخ

[فارسی](fairness-and-publication.md) · [English](../en/fairness-and-publication.md) · [مستندات](index.md)

پیش از تحلیل، موضوع، بازه، دامنه، قواعد ورود، Provider، Proxy، سیاست امتیاز، بلوغ پنجره و تعارض را ثابت کنید و مستقل، سفارشی، حمایتی یا تبلیغاتی بودن را اعلام کنید. پس از دیدن نتیجه، دامنه را بی‌سروصدا تغییر ندهید.

پیش از انتشار، هش‌ها، حذف‌ها، دستهٔ ناشناخته، Trigger، Invalidation، ترتیب مسیر، تصمیم حساس به Proxy، مخرج، ترجمه و شاهد را بازبینی کنید. بازبین، نسخهٔ مدل/روش/منبع و محدودیت را نشان دهید؛ یافتهٔ شواهد را از نظر تبلیغاتی جدا و حداقل شاهد مجاز را منتشر کنید. به شخص نام‌برده فرصت معقول برای اصلاح خطای منبع و پاسخ بدهید، بدون واگذاری کنترل روش.

## ایست بازرسی انسانیِ متصل به هش

`PUBLICATION_MODE=public` فقط یک Gate فنی است و به‌خودی‌خود انصاف را ثابت نمی‌کند. پس از بازبینی شواهد و ارائه، یک انسان نام‌دار باید پذیرش صریح ثبت کند:

</div>

```bash
docker compose run --rm audit-lab python -m audit_lab.cli review status
docker compose run --rm audit-lab python -m audit_lab.cli review accept \
  --reviewer "نام بازبین" --notes "دامنه، شاهد، ترجمه، مخرج و محدودیت‌ها بررسی شد"
docker compose run --rm audit-lab python -m audit_lab.cli report
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
# پیش از ادامه، dashboard_data.json، فایل PDF و دفتر عمومی اختیاری را بررسی کنید.
docker compose run --rm audit-lab python -m audit_lab.cli review publication-accept \
  --reviewer "نام بازبین" --notes "داشبورد، PDF و دفتر عمومی اختیاری بررسی شد"
docker compose run --rm audit-lab python -m audit_lab.cli finalize
docker compose run --rm audit-lab python -m audit_lab.cli verify-final
```

<div dir="rtl" lang="fa">

دفتر بازبینی، رویدادها را با زنجیرهٔ هش نگه می‌دارد و پذیرش را به حالت عمومی، Manifest مجموعه، دفتر ادعا، Snapshot/فایل پیامد، اجرای امتیازدهی و دفتر امتیاز متصل می‌کند. تغییر حالت یا هر فایل، پذیرش را قدیمی می‌کند. برای پس‌گرفتن مجوز از `review revoke` استفاده کنید و دفتر را دستی ویرایش نکنید. نام و یادداشت بازبین در بستهٔ خصوصی می‌ماند و در DTO عمومی داشبورد برگردانده نمی‌شود.

پس از ایست بازرسی شواهد، داشبورد، PDF و هر دفتر ادعای عمومیِ صریحاً فعال‌شده را بازتولید و بررسی کنید. `review publication-accept` ایست بازرسی دوم و متصل به هش را دقیقاً برای همین آثار ارائه ثبت می‌کند. در حالت عمومی، `finalize` هر دو ایست بازرسی را الزامی می‌کند، پوشه و ZIP نهایی تازه‌ساخته‌شده را راستی‌آزمایی می‌کند و فقط پس از آن Manifest انتشار را فعال می‌کند. داشبورد عمومی و دانلودها فقط تا زمانی ارائه می‌شوند که بایت‌های فعلی با آن Manifest منطبق باشند. جایگزینی یا حذف اثر منتشرشده باعث بسته‌شدن امن دسترسی می‌شود. اجرای دوبارهٔ `report`، بازتولید PDF یا تغییر هر یک از دفترهای بازبینی، پیش از ازسرگیری انتشار به `review publication-accept` جدید و سپس اجرای موفق دوبارهٔ `finalize` نیاز دارد.

مسیر اصلاح، Audit ID، تاریخ، نسخه و Changelog آشکار باشد. بستهٔ منتشرشده را جایگزین نکنید؛ نسخهٔ جدید با هش قبلی، نوع خطا و اثر بر ادعا و مخرج منتشر کنید. انتقاد نیک‌نیت لزوماً امتیاز را تغییر نمی‌دهد؛ خطای شواهد تغییر می‌دهد.

</div>
