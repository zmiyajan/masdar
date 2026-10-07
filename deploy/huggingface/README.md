---
title: Masdar · مصدر
emoji: ⚖️
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
license: apache-2.0
short_description: Arabic search over Saudi regulations, with citations
---

# Masdar · مصدر

**محرّك بحث عربي في الأنظمة السعودية.** اكتب سؤالك بالعربية، فصحى أو لهجة، فتحصل على المادة النظامية
بنصّها الساري بعد تطبيق التعديلات، مع اسم النظام ورقم المادة وحالتها ورابط صفحتها في بوابة هيئة الخبراء.
يغطي نظام العمل ونظام حماية البيانات الشخصية ونظام الشركات.

**Arabic-first retrieval over Saudi regulations** for HR, legal and compliance teams. Ask in Arabic
and get the exact governing article from the Labor Law, the Personal Data Protection Law (PDPL) or
the Companies Law: its text in force after amendments, its status (in force, amended, or needs
review) and a link to the official source.

- **Web app:** this page.
- **API:** `/api/search?q=...&k=5&law=labor-law`, documented at `/docs`.
- **Agents:** the same search is available as an MCP server (`masdar-mcp`) when run locally.

> ليس استشارة قانونية — تحقق دائماً من المصدر الرسمي.
> Not legal advice. Always check the official source.

Source code, dataset and evaluation: <https://github.com/zmiyajan/masdar>
