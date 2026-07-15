<div dir="rtl" lang="fa">

# شروع سریع

[فارسی](quickstart.md) · [English](../en/quickstart.md) · [مستندات](index.md)

## ۱. اجرای نمونهٔ ساختگی

پیش‌نیازها: Git، Docker Engine یا Desktop، نسخهٔ ۲ Docker Compose و فضای کافی برای تصویر و `workspace/`.

</div>

```bash
git clone https://github.com/mm1ladd-g/market-analysis-audit-lab.git
cd market-analysis-audit-lab
umask 077 && cp .env.example .env
docker compose build
docker compose run --rm audit-lab python -m audit_lab.cli demo
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
docker compose run --rm audit-lab python -m audit_lab.cli finalize --synthetic-demo --workspace /workspace
docker compose run --rm audit-lab python -m audit_lab.cli verify-final --synthetic-demo --workspace /workspace
```

<div dir="rtl" lang="fa">

اجرای نمونه قطعی، تخیلی و بدون فراخوانی ارائه‌دهنده یا API است. ساخت تازه و بدون حافظهٔ نهان همچنان برای دریافت تصویر پایه و وابستگی‌ها به شبکه نیاز دارد. این تنها اجرای نخست پشتیبانی‌شده است. `workspace/SYNTHETIC_DEMO.txt`، `workspace/final_audit_summary.json` و `workspace/final_audit/file_hashes.csv` را بررسی کنید.

## ۲. تنظیم منبع مجاز

[حقوق و مجوزها](legal-and-rights.md) را بخوانید. در `.env` مقدار غیرخالی `ANALYST_NAME`، `YOUTUBE_CHANNEL_URL`، `YOUTUBE_CHANNEL_ID`، بازهٔ شامل هر دو سر `START_DATE`/`END_DATE`، دامنهٔ دسته‌ها، زبان‌های زیرنویس، ارائه‌دهندهٔ بازار، `AUDIT_RELATIONSHIP_DISCLOSURE` و `CORRECTION_CONTACT` را تنظیم کنید. فقط هنگامی `SOURCE_RIGHTS_ACKNOWLEDGED=true` را تأیید کنید که گردآوری و پردازش مجاز باشد.

</div>

```bash
docker compose run --rm audit-lab python -m audit_lab.cli doctor
docker compose run --rm audit-lab python -m audit_lab.cli smoke
```

<div dir="rtl" lang="fa">

## ۳. گردآوری و ثابت‌کردن شواهد

</div>

```bash
docker compose run --rm audit-lab python -m audit_lab.cli collect
docker compose run --rm audit-lab python -m audit_lab.cli manifest
docker compose run --rm audit-lab python -m audit_lab.cli verify
```

<div dir="rtl" lang="fa">

پیش از ادامه دفتر موارد واردشده و حذف‌شده را بررسی کنید. زیرنویس گمشده، شناسهٔ نادرست کانال، دستهٔ ناشناخته، شناسهٔ تکراری و مورد بیرون از بازه باید قابل‌مشاهده بمانند.

## ۴. یک آزمون پولی

مقدار `AUDIT_MODE=api`، `OPENAI_API_KEY`، شناسهٔ مدل‌های در‌دسترس و `API_COST_ACKNOWLEDGED=true` را تنظیم کنید. متغیرهای قیمت فقط برآورد اختیاری‌اند؛ قیمت رسمی جاری را شخصاً بررسی کنید.

</div>

```bash
docker compose run --rm audit-lab python -m audit_lab.cli extract-claims --limit 1
```

<div dir="rtl" lang="fa">

فایل ادعا، خطوط شاهد، شرط‌ها، سطوح، امتیازپذیری، مصرف، شناسهٔ مدل و هش‌ها را بررسی و سپس استخراج باقی ویدئوها را اجرا کنید.

## ۵. پیامدها، امتیازدهی، گزارش و راستی‌آزمایی

</div>

```bash
docker compose run --rm audit-lab python -m audit_lab.cli extract-claims
docker compose run --rm audit-lab python -m audit_lab.cli fetch-outcomes
docker compose run --rm audit-lab python -m audit_lab.cli score
docker compose run --rm audit-lab python -m audit_lab.cli report
docker compose run --rm audit-lab python -m audit_lab.cli review accept \
  --reviewer "نام بازبین" --notes "شواهد، امتیاز، ترجمه و محدودیت‌ها بررسی شد"
docker compose run --rm audit-lab python -m audit_lab.cli report
docker compose run --rm audit-lab python scripts/generate_audit_report.py --workspace /workspace
# پیش از ادامه، dashboard_data.json، فایل PDF و دفتر عمومی اختیاری را بررسی کنید.
docker compose run --rm audit-lab python -m audit_lab.cli review publication-accept \
  --reviewer "نام بازبین" --notes "داشبورد، PDF و دفتر عمومی اختیاری بررسی شد"
docker compose run --rm audit-lab python -m audit_lab.cli finalize
docker compose run --rm audit-lab python -m audit_lab.cli verify-final
```

<div dir="rtl" lang="fa">

فایل PDF در `workspace/reports/audit-report.pdf` با ترتیب فارسی و سپس انگلیسی نوشته می‌شود. داشبورد محلی را با `docker compose up` اجرا کنید؛ سرویس به‌طور پیش‌فرض فقط روی `127.0.0.1:${HOST_PORT:-18765}` گوش می‌دهد.

هنگام آماده‌سازی و بازبینی، `PUBLICATION_MODE=private` را حفظ کنید. برای انتشار واقعی آن را `public` کنید، گزارش در انتظار را بسازید، شواهد را بپذیرید، داشبورد/PDF و دفتر اختیاری را دوباره تولید و بررسی کنید، `review publication-accept` را ثبت کنید و سپس بدون تغییر فایل پذیرفته‌شده نهایی‌سازی را انجام دهید. هر تغییر بعدی در گزارش، PDF، دفتر یا بازبینی به پذیرش انتشار و اجرای دوبارهٔ `finalize` نیاز دارد. انتشار را خودکار نکنید؛ ابتدا [فهرست کنترل انتشار منصفانه](fairness-and-publication.md) را کامل کنید.

</div>
