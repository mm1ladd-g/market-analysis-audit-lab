<div dir="rtl" lang="fa">

# نصب

[فارسی](installation.md) · [English](../en/installation.md) · [مستندات](index.md)

مسیر بازتولیدپذیر، Docker Compose روی macOS، Linux یا Windows/WSL2 است. در Linux اجرای Rootless ترجیح دارد.

</div>

```bash
git clone https://github.com/mm1ladd-g/market-analysis-audit-lab.git
cd market-analysis-audit-lab
umask 077 && cp .env.example .env
docker compose build
docker compose run --rm audit-lab python -m audit_lab.cli doctor
```

<div dir="rtl" lang="fa">

سرویس باید پیش‌فرض روی `127.0.0.1` باشد. چند گیگابایت فضای آزاد در نظر بگیرید؛ زیرنویس، دادهٔ دقیقه‌ای، Cache و آرشیو حجم را افزایش می‌دهند. گفتاربه‌متن محلی به CPU/GPU بیشتری نیاز دارد.

توسعهٔ محلی با نسخهٔ اعلام‌شدهٔ Python و Dependency Lock ممکن است، اما مسیر اصلی بازتولید نیست. هنگام بازتولید Release، وابستگی را خودسرانه Upgrade نکنید.

برای Upgrade، Changelog را بخوانید، Workspace را پشتیبان بگیرید، Tag دقیق را دریافت، تصویر را بدون Secret بسازید، آزمون و Demo را اجرا و بستهٔ قبلی را Verify کنید. حذف Container، Bind Mount و Backup را پاک نمی‌کند.

</div>
