<div dir="rtl" lang="fa">

# توسعه و آزمون

[فارسی](development-and-testing.md) · [English](../en/development-and-testing.md) · [مستندات](index.md)

</div>

```bash
python -m unittest discover -s tests -v
python -m audit_lab.cli demo --workspace ./workspace
python -m audit_lab.cli verify-final --synthetic-demo --workspace ./workspace
```

<div dir="rtl" lang="fa">

آزمون پیش‌فرض آفلاین و ساختگی است؛ آزمون شبکه/پولی باید Opt-in و بودجه‌دار باشد. مرز تاریخ، کانال اشتباه، منشأ Caption، حذف و Duplicate، خط مرجع، خروجی مدل خراب، تزریق پرامپت، Cache، Gap/Timezone/Proxy، ترتیب رویداد، مخرج، خرابی هش/ZIP، Redaction، RTL، XSS و فایل مخرب را تست کنید.

Provider جدید باید دادهٔ عادی با منشأ کامل و Fixture محلی بدهد. دسته از تنظیمات می‌آید، نه Hardcode شخص. تغییر روش، پرامپت، طرح‌واره یا سیاست به Version، Regression، Migration و مستندات دو زبان نیاز دارد. Golden Result را بدون توضیح معنایی تغییر ندهید.

</div>
