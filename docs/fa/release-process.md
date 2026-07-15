<div dir="rtl" lang="fa">

# فرایند Release

[فارسی](release-process.md) · [English](../en/release-process.md) · [مستندات](index.md)

۱. نسخه، طرح‌واره، پرامپت/سیاست، مستندات، Citation و Changelog را Freeze کنید.

۲. نبود نمونهٔ واقعی، شخص، کانال، دامنهٔ خصوصی، رسانه، رونویسی، Report، Workspace، Secret، Cookie، Cache و مسیر محلی را ثابت کنید.

۳. برابری فایل دو زبان، Link، RTL، دسترس‌پذیری، آزمون، Demo و Build از Clone پاک را اجرا کنید.

۴. اسکن Secret کل تاریخچه، تحلیل ایستا، License، SBOM، آسیب‌پذیری تصویر و `docker history`.

۵. از Commit برچسب‌خورده و Dependency/Base پین‌شده بسازید؛ غیر `root` و Localhost را بررسی کنید.

۶. هش Demo و تست خرابی را کنترل و پیوند شرایط Provider/OpenAI را تازه کنید.

۷. بازبینی حقوق، حریم، امنیت و روش را تکمیل و یک Tag حاشیه‌نویسی‌شده با قالب `vMAJOR.MINOR.PATCH` روی `main` ایجاد کنید. Workflow نسخه را با `pyproject.toml` تطبیق می‌دهد و Archive مبدأ، بستهٔ Python، Image چندمعماری نسخه‌دار، SBOM وابستگی و Container، فهرست مجوز، گزارش آسیب‌پذیری، Attestation منشأ و SHA-256 را می‌سازد.

Workflow ابتدا Candidate چندمعماری را فقط با Digest و بدون Tag عمومی نسخه یا `latest` می‌فرستد. منیفست‌های دقیق amd64 و arm64 را Inventory، SBOM، اسکن و بازرسی می‌کند و فقط پس از موفقیت همهٔ Gateها Tag نسخهٔ تغییرناپذیر را اعمال می‌کند. همان Digest تأییدشده فقط پس از موفقیت Release به `latest` ارتقا می‌یابد. Attestation مبتنی بر OIDC گیت‌هاب هم Digest کانتینر و هم فایل‌های دریافت‌شدنی را پوشش می‌دهد. امضای رمزنگاری‌شدهٔ Git Tag توصیه می‌شود، اما با Tag حاشیه‌نویسی‌شده و Attestation منشأ یکسان نیست.

در شکست بحرانی Release نکنید و فایل منتشرشده را بی‌صدا جایگزین نکنید.

</div>
