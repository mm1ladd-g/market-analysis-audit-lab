<div dir="rtl" lang="fa">

# استقرار

[فارسی](deployment.md) · [English](../en/deployment.md) · [مستندات](index.md)

پیش‌فرض پشتیبانی‌شده Localhost است. اتصال را روی `127.0.0.1` نگه دارید. برای سرویس عمومی، Reverse Proxy یا Tunnel بازبینی‌شده با TLS، احراز هویت، مجوز، محدودیت، Header امن، Log پاک، Monitoring، Backup و مسیر اصلاح اضافه کنید.

Compose وظایف را جدا می‌کند: Worker پروفایل‌دار `audit-lab` فقط هنگام دستور صریح، Workspace کامل و Secretهای تنظیم‌شده را می‌گیرد؛ سرویس پیش‌فرض `audit-web` فقط `workspace/reports` را Read-only می‌بیند، Root filesystem آن Read-only است، فقط به Localhost وصل می‌شود و کلید OpenAI دریافت نمی‌کند. این دو سرویس را برای راحتی یکی نکنید. برای اینکه Port منتشرشده در Docker Desktop و Linux یکسان کار کند، Viewer از شبکهٔ عادی Docker استفاده می‌کند؛ هرگاه محدودیت خروجی لازم است، Firewall میزبان یا سیاست شبکهٔ مخصوص Deployment را اعمال کنید.

مخزن، Home، Docker Socket، `.env` یا Workspace دیگر را Mount نکنید. شواهد خام و Cache بیرون Static Root، Debug و Directory Index خاموش، CORS/Trusted Host/Egress محدود و Health بدون اطلاعات حساس باشد. Tunnel به‌تنهایی Authorization نیست. Cache، Bot، Link Preview و Log دسترسی را بررسی کنید. عمومی کردن داشبورد یک «انتشار» و مشمول کنترل حقوق، حریم و انصاف است.

</div>
