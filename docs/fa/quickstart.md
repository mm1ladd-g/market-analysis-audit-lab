<div dir="rtl" lang="fa">

# شروع سریع

[فارسی](quickstart.md) · [English](../en/quickstart.md) · [مستندات](index.md)

## ۱. نمونهٔ ساختگی

به Git، Docker و Compose v2 نیاز دارید. این نمونه آفلاین، قطعی و کاملاً تخیلی است.

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

اجرای نمونه هیچ فراخوانی به ارائه‌دهنده یا API ندارد؛ ساخت تازه و بدون Cache تصویر همچنان برای دریافت تصویر پایه و وابستگی‌های پین‌شده به اینترنت نیاز دارد. فایل‌های `workspace/SYNTHETIC_DEMO.txt`، خلاصهٔ نهایی و فهرست هش را بررسی کنید.

## ۲. منبع مجاز

[حقوق منبع](legal-and-rights.md) را بخوانید. در `.env` نام، URL و ID کانال، تاریخ شروع و پایان شامل دو سر، زبان، دامنه و منبع بازار را تنظیم کنید. فقط پس از احراز مجوز، `SOURCE_RIGHTS_ACKNOWLEDGED=true` را فعال کنید.

</div>

```bash
docker compose run --rm audit-lab python -m audit_lab.cli doctor
docker compose run --rm audit-lab python -m audit_lab.cli smoke
docker compose run --rm audit-lab python -m audit_lab.cli collect
docker compose run --rm audit-lab python -m audit_lab.cli manifest
docker compose run --rm audit-lab python -m audit_lab.cli verify
```

<div dir="rtl" lang="fa">

## ۳. یک آزمون پولی

حالت API، کلید، شناسهٔ مدل موجود و تأیید هزینه را تنظیم و ابتدا یک ویدئو را بررسی کنید.

</div>

```bash
docker compose run --rm audit-lab python -m audit_lab.cli extract-claims --limit 1
```

<div dir="rtl" lang="fa">

پس از بررسی شاهد، شرط، سطح، مدل، مصرف و هش، اجرای کامل را انجام دهید:

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

فایل PDF در مسیر `workspace/reports/audit-report.pdf` و با ترتیب فارسی، سپس انگلیسی نوشته می‌شود. برای اجرای داشبورد محلی از `docker compose up` استفاده کنید؛ سرویس به‌صورت پیش‌فرض فقط روی `127.0.0.1:${HOST_PORT:-18765}` گوش می‌دهد.

پیش از انتشار، [فهرست کنترل انصاف](fairness-and-publication.md) و بازبینی انسانی الزامی است.

هنگام آماده‌سازی و بازبینی `PUBLICATION_MODE=private` بماند. برای انتشار واقعی آن را `public` کنید، Report در انتظار را بسازید، شواهد را بپذیرید، داشبورد/PDF و دفتر اختیاری را دوباره تولید و بررسی کنید، `review publication-accept` را ثبت کنید و سپس بدون تغییر اثر پذیرفته‌شده Finalize کنید. هر تغییر بعدی در Report، PDF، دفتر یا بازبینی به پذیرش انتشار و اجرای دوبارهٔ `finalize` نیاز دارد.

</div>
