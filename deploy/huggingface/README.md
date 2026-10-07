---
title: Masdar · مصدر
emoji: ⚖️
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
license: apache-2.0
short_description: Search, quoted answers and contract checks over Saudi law
---

# Masdar · مصدر

**محرّك عربي للأنظمة السعودية.** يغطي نظام العمل ونظام حماية البيانات الشخصية ونظام الشركات بنصّها
**الساري** بعد تطبيق التعديلات، ويقدّم ثلاث خدمات:

- **البحث:** اكتب سؤالك فصحى أو لهجة، فتحصل على المواد مرتّبة مع حالتها ورابط مصدرها الرسمي.
- **الجواب:** جملة مقتبسة حرفياً من المادة مع الاستشهاد بها، أو «لا توجد جملة تجيب بثقة» بدل التخمين.
- **فحص العقود:** الصق عقد عمل أو سياسة، فيُعلَّم كل بند يخالف حداً في نظام العمل مع ذكر المادة.

لا يستخدم أي نموذج لغة أو API: كل شيء يعمل محلياً.

**Arabic-first search, quoted answers and contract checking over Saudi regulations in force**, for
HR, legal and compliance teams. Local models only: no LLM, no API key, nothing generated.

- **Web app:** this page.
- **API:** `/api/search`, `/api/answer`, `POST /api/check`, documented at `/docs`.
- **Agents:** the same tools are available as an MCP server (`masdar-mcp`) when run locally.

> ليس استشارة قانونية — تحقق دائماً من المصدر الرسمي.
> Not legal advice. Always check the official source.

Source code, dataset and evaluation: <https://github.com/zmiyajan/masdar>
