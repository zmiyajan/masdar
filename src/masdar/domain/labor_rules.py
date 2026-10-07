"""The Labor Law limits the contract checker enforces (v1: quantitative rules only).

Every rule is pinned to the article whose **text in force** states its limit,
never to memory or to the portal's original wording: several limits changed
by amendment (probation 90 → 180 days, employer notice 30 → 60 days,
maternity leave 10 → 12 weeks, marriage leave 3 → 5 days, paternity leave
1 → 3 days). ``tests/integration/test_labor_rules_pinned.py`` re-reads each
article from the committed snapshots and fails if its heading, status, the
``source_phrase`` or the limit no longer match, so an amendment breaks a test
instead of silently misreporting. See ADR-0010.
"""

from masdar.domain.amendments import ArticleStatus
from masdar.domain.compliance import Comparator, Rule
from masdar.domain.quantities import Quantity, Unit

LABOR_LAW = "نظام العمل"

_DAYS = frozenset({Unit.DAY, Unit.WEEK, Unit.MONTH})
_DAYS_EXACT = frozenset({Unit.DAY, Unit.WEEK})
_HOURS = frozenset({Unit.HOUR})
_PERCENT = frozenset({Unit.PERCENT})

_PER_DAY = ("يومياً", "يومي", "يومية", "في اليوم", "باليوم", "اليوم الواحد", "كل يوم")
_PER_WEEK = ("أسبوعياً", "أسبوعي", "أسبوعية", "في الأسبوع", "بالأسبوع", "الأسبوع الواحد", "كل أسبوع")
_WORK = ("ساعات العمل", "ساعات عمل", "ساعات الدوام", "الدوام", "دوام", "يعمل", "تعمل", "العمل")
# Art. 100 (rotation), Art. 108 (senior posts, guards, cleaners) and Art. 106
# (stocktaking, seasons) allow longer hours; their wording in a clause means
# the ceiling of Art. 98 may not apply.
_HOURS_EXCEPTIONS = (
    "مناوبة",
    "مناوبات",
    "تناوب",
    "بالتناوب",
    "وردية",
    "ورديات",
    "نوبات",
    "منصب",
    "مناصب",
    "حراسة",
    "نظافة",
    "الجرد",
    "المواسم",
    "موسمية",
    # Art. 106: emergencies and unusual pressure of work.
    "الضرورة",
    "ضرورة",
    "ظروف عارضة",
    "ضغط عمل",
    "طارئة",
    "طارئ",
    "استثنائية",
)
# Leave clauses also state carry-over caps, balances, splits and cash in lieu;
# none of those is the length of the entitlement.
_NOT_ENTITLEMENT = ("الجزء", "جزء", "تجزئة", "تجزئتها", "تقسيم", "رصيد", "بدل نقدي", "بدلاً نقدياً")
# Overtime and rest periods are counted in hours too, but are not the working day.
_NOT_REGULAR_HOURS = ("إضافية", "إضافي", "راحة", "استراحة", "للراحة")
_OVERTIME = (
    "ساعات إضافية",
    "ساعات العمل الإضافية",
    "العمل الإضافي",
    "الوقت الإضافي",
    "أجر إضافي",
    "أجراً إضافياً",
    "عمل إضافي",
)
_ANNUAL_LEAVE = ("إجازة سنوية", "إجازة اعتيادية", "إجازته السنوية", "إجازتها السنوية")
_CONDITION_WORDS = ("بعد", "مرور", "انقضاء", "قبل", "إكمال", "إتمام", "أمضى", "يمضي", "خلال")
_LEAVE = ("إجازة", "إجازته", "إجازتها", "إجازات", "الإجازات")

PROBATION_MAX = Rule(
    rule_id="probation-max",
    article_id="labor-law:53",
    article_heading="المادة الثالثة والخمسون",
    article_status=ArticleStatus.AMENDED,
    law_title=LABOR_LAW,
    topic="فترة التجربة",
    source_phrase="على ألا يزيد مجموع المدة في جميع الأحوال على (مائة وثمانين) يوماً",
    cues=(("تجربة", "التجربة", "تجريبية", "تجريبي", "فترة الاختبار"),),
    comparator=Comparator.MAXIMUM,
    limit=Quantity(180, Unit.DAY),
    units=_DAYS,
    cumulative=True,
)

NOTICE_EMPLOYER_MIN = Rule(
    rule_id="notice-employer-min",
    article_id="labor-law:75",
    article_heading="المادة الخامسة والسبعون",
    article_status=ArticleStatus.AMENDED,
    law_title=LABOR_LAW,
    topic="مهلة إشعار صاحب العمل بإنهاء العقد",
    source_phrase="إذا كان الإنهاء من طرف صاحب العمل، فيجب عليه أن يوجه إشعاراً كتابيًّا "
    "بذلك للعامل قبل (ستين) يوماً على الأقل من تاريخ الإنهاء",
    cues=(
        ("إشعار", "إشعاراً", "إخطار", "إنذار", "مهلة"),
        # Only the employer's side can breach Art. 75: a shorter notice owed by
        # the worker is more favourable to the worker and valid under Art. 8.
        (
            "أي من الطرفين",
            "لأي من الطرفين",
            "كل من الطرفين",
            "كلا الطرفين",
            "يحق للشركة",
            "يحق لصاحب العمل",
            "يحق للمنشأة",
            "يجوز للشركة",
            "يجوز لصاحب العمل",
            "يجوز للمنشأة",
            "رغبة الشركة",
            "رغبة صاحب العمل",
            "رغبة المنشأة",
            "للشركة إنهاء",
            "لصاحب العمل إنهاء",
            "للمنشأة إنهاء",
            "تلتزم الشركة بإشعار",
            "يلتزم صاحب العمل بإشعار",
            "تلتزم المنشأة بإشعار",
            "تلتزم الشركة بإخطار",
            "يلتزم صاحب العمل بإخطار",
            "تلتزم المنشأة بإخطار",
            "يلتزم الطرف الأول",
            "يحق للطرف الأول",
            "على الطرف الأول",
            "على الشركة",
            "على صاحب العمل",
            "على المنشأة",
            "من قبل الشركة",
            "من قبل صاحب العمل",
            "من قبل المنشأة",
            "من طرف صاحب العمل",
            "من جانب صاحب العمل",
            "من جانب الشركة",
        ),
    ),
    comparator=Comparator.MINIMUM,
    limit=Quantity(60, Unit.DAY),
    units=_DAYS,
    # Art. 75(1)(b) governs indefinite contracts paid monthly; a fixed-term
    # contract or a non-monthly wage has other rules.
    requires_for_violation=(("غير محدد المدة", "غير محددة المدة", "مفتوح المدة"),),
    blocks_violation=(
        "اليومية",
        "باليومية",
        "بالقطعة",
        "بالساعة",
        "الأجر الأسبوعي",
        "غير شهري",
        # Either party may end the contract during probation (Art. 53).
        "خلال فترة التجربة",
        "أثناء فترة التجربة",
        "في فترة التجربة",
        "خلال التجربة",
        "أثناء التجربة",
        "خلال الفترة التجريبية",
    ),
)

ANNUAL_LEAVE_MIN = Rule(
    rule_id="annual-leave-min",
    article_id="labor-law:109",
    article_heading="المادة التاسعة بعد المائة",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="الإجازة السنوية",
    source_phrase="يستحق العامل عن كل عام إجازة سنوية لا تقل مدتها عن واحد وعشرين يومًا",
    cues=(_ANNUAL_LEAVE,),
    comparator=Comparator.MINIMUM,
    limit=Quantity(21, Unit.DAY),
    units=_DAYS_EXACT,
    # The longer leave after five years is judged by the next rule.
    excludes=_NOT_ENTITLEMENT,
    skip_after=(
        *_CONDITION_WORDS,
        "تزاد إلى",
        "تزداد إلى",
        "ترتفع إلى",
        "تصبح",
        "ترحيل",
        "تأجيل",
        "طلب",
        "تقديم",
        "استخدام",
    ),
)

ANNUAL_LEAVE_AFTER_FIVE_YEARS_MIN = Rule(
    rule_id="annual-leave-5y-min",
    article_id="labor-law:109",
    article_heading="المادة التاسعة بعد المائة",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="الإجازة السنوية بعد خمس سنوات خدمة",
    source_phrase="تُزاد إلى مدة لا تقل عن ثلاثين يومًا إذا أمضى العامل في خدمة صاحب العمل "
    "خمس سنوات متصلة",
    cues=(_ANNUAL_LEAVE,),
    comparator=Comparator.MINIMUM,
    limit=Quantity(30, Unit.DAY),
    units=_DAYS_EXACT,
    anchor=("خمس سنوات", "5 سنوات", "خمسة أعوام", "خمس سنين"),
    excludes=_NOT_ENTITLEMENT,
    skip_after=("قبل", "إكمال", "إتمام", "ترحيل", "تأجيل", "طلب", "تقديم", "استخدام"),
)

DAILY_HOURS_MAX = Rule(
    rule_id="daily-hours-max",
    article_id="labor-law:98",
    article_heading="المادة الثامنة والتسعون",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="ساعات العمل اليومية",
    source_phrase="لا يجوز تشغيل العامل تشغيلًا فعليًّا أكثر من ثماني ساعات في اليوم الواحد",
    cues=(_WORK,),
    comparator=Comparator.MAXIMUM,
    limit=Quantity(8, Unit.HOUR),
    units=_HOURS,
    per=_PER_DAY,
    excludes=("رمضان",),
    skip_after=_NOT_REGULAR_HOURS,
    blocks_violation=_HOURS_EXCEPTIONS,
    # Art. 99 lets the minister raise the day to nine hours for some categories.
    exception_margin=1,
)

WEEKLY_HOURS_MAX = Rule(
    rule_id="weekly-hours-max",
    article_id="labor-law:98",
    article_heading="المادة الثامنة والتسعون",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="ساعات العمل الأسبوعية",
    source_phrase="أو أكثر من ثمان وأربعين ساعة في الأسبوع، إذا اعتمد المعيار الأسبوعي",
    cues=(_WORK,),
    comparator=Comparator.MAXIMUM,
    limit=Quantity(48, Unit.HOUR),
    units=_HOURS,
    per=_PER_WEEK,
    excludes=("رمضان",),
    skip_after=_NOT_REGULAR_HOURS,
    blocks_violation=_HOURS_EXCEPTIONS,
)

RAMADAN_DAILY_HOURS_MAX = Rule(
    rule_id="ramadan-daily-hours-max",
    article_id="labor-law:98",
    article_heading="المادة الثامنة والتسعون",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="ساعات العمل اليومية في رمضان",
    source_phrase="وتخفض ساعات العمل الفعلية خلال شهر رمضان للمسلمين، بحيث لا تزيد على ست "
    "ساعات في اليوم",
    cues=(("رمضان",), _WORK),
    comparator=Comparator.MAXIMUM,
    limit=Quantity(6, Unit.HOUR),
    units=_HOURS,
    per=_PER_DAY,
    # The reduction is for Muslim workers only.
    blocks_violation=("غير المسلمين", *_HOURS_EXCEPTIONS),
)

RAMADAN_WEEKLY_HOURS_MAX = Rule(
    rule_id="ramadan-weekly-hours-max",
    article_id="labor-law:98",
    article_heading="المادة الثامنة والتسعون",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="ساعات العمل الأسبوعية في رمضان",
    source_phrase="أو ست وثلاثين ساعة في الأسبوع",
    cues=(("رمضان",), _WORK),
    comparator=Comparator.MAXIMUM,
    limit=Quantity(36, Unit.HOUR),
    units=_HOURS,
    per=_PER_WEEK,
    blocks_violation=("غير المسلمين", *_HOURS_EXCEPTIONS),
)

OVERTIME_RATE_MIN = Rule(
    rule_id="overtime-rate-min",
    article_id="labor-law:107",
    # Partially amended by Royal Decree M/44 (1446) and not applied
    # automatically (ADR-0005), so this rule can only ever say "review needed".
    article_heading="المادة السابعة بعد المائة",
    article_status=ArticleStatus.REVIEW_NEEDED,
    law_title=LABOR_LAW,
    topic="علاوة أجر ساعات العمل الإضافية",
    source_phrase="يوازي أجر الساعة مضافًا إليه 50% من أجره الأساسي",
    cues=(_OVERTIME,),
    comparator=Comparator.MINIMUM,
    limit=Quantity(50, Unit.PERCENT),
    units=_PERCENT,
)

MATERNITY_LEAVE_MIN = Rule(
    rule_id="maternity-leave-min",
    article_id="labor-law:151",
    article_heading="المادة الحادية والخمسون بعد المائة",
    article_status=ArticleStatus.AMENDED,
    law_title=LABOR_LAW,
    topic="إجازة الوضع بأجر كامل",
    source_phrase="للمرأة العاملة الحق في إجازة وضع بأجر كامل لمدة (اثني عشر) أسبوعاً",
    cues=(("إجازة وضع", "إجازة الوضع", "إجازة أمومة", "إجازة الأمومة"),),
    comparator=Comparator.MINIMUM,
    limit=Quantity(12, Unit.WEEK),
    units=_DAYS,
    # A father's leave on the birth of a child is Art. 113, not this article.
    excludes=("مولود له", "زوجته", "للأب"),
    # "From four weeks before the due date" and "extend by a month unpaid" are
    # not the length of the paid leave.
    skip_after=("قبل", "بعد", "خلال", "تمديد", "تمديدها", "يمدد", "تمدد", "دون أجر"),
)

SICK_LEAVE_FULL_PAY_MIN = Rule(
    rule_id="sick-leave-full-pay-min",
    article_id="labor-law:117",
    article_heading="المادة السابعة عشرة بعد المائة",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="الإجازة المرضية بأجر كامل",
    source_phrase="الحق في إجازة مرضية بأجر عن الثلاثين يومًا الأولى",
    cues=(
        ("إجازة مرضية", "إجازة مرضيه"),
        (
            "أجر كامل",
            "الأجر كاملاً",
            "كامل الأجر",
            "راتب كامل",
            "الراتب كاملاً",
            "كامل الراتب",
            "مدفوعة الأجر بالكامل",
            "مدفوعة الأجر كاملاً",
            "أجره كاملاً",
            "راتبه كاملاً",
            "كامل أجره",
            "كامل راتبه",
        ),
    ),
    comparator=Comparator.MINIMUM,
    limit=Quantity(30, Unit.DAY),
    units=_DAYS_EXACT,
    # The later tiers (three quarters, unpaid) are not the full-pay period.
    skip_after=("نصف", "أرباع", "ربع", "دون أجر", "بدون أجر", "بعد", "مرور", "انقضاء", "خلال"),
)

NON_COMPETE_MAX = Rule(
    rule_id="non-compete-max",
    article_id="labor-law:83",
    article_heading="المادة الثالثة والثمانون",
    article_status=ArticleStatus.AMENDED,
    law_title=LABOR_LAW,
    topic="مدة شرط عدم المنافسة",
    source_phrase="ويجب ألا تزيد مدته على سنتين من تاريخ انتهاء العلاقة بين الطرفين",
    cues=(("منافسة", "منافس", "منافسين", "ينافس", "منافستها", "منافسته"),),
    comparator=Comparator.MAXIMUM,
    limit=Quantity(2, Unit.YEAR),
    units=frozenset({Unit.YEAR, Unit.MONTH}),
)

LOAN_DEDUCTION_MAX = Rule(
    rule_id="loan-deduction-max",
    article_id="labor-law:92",
    article_heading="المادة الثانية والتسعون",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="نسبة الحسم من الأجر لاسترداد قروض صاحب العمل",
    source_phrase="استرداد قروض صاحب العمل، بشرط ألا يزيد ما يحسم من العامل في هذه الحالة "
    "على 10% من أجره",
    cues=(
        ("قرض", "القرض", "قروض", "سلفة", "سلف"),
        (
            "حسم",
            "يحسم",
            "تحسم",
            "خصم",
            "يخصم",
            "تخصم",
            "استقطاع",
            "يستقطع",
            "تستقطع",
            "اقتطاع",
            "يقتطع",
            "تقتطع",
            "يسترد",
            "تسترد",
            "استرداد",
        ),
    ),
    comparator=Comparator.MAXIMUM,
    limit=Quantity(10, Unit.PERCENT),
    units=_PERCENT,
    # The 10% cap applies to deductions made without the worker's written consent.
    blocks_violation=("موافقة خطية", "موافقة كتابية", "موافقته الخطية", "موافقته الكتابية"),
)

HAJJ_LEAVE_MIN = Rule(
    rule_id="hajj-leave-min",
    article_id="labor-law:114",
    article_heading="المادة الرابعة عشرة بعد المائة",
    article_status=ArticleStatus.IN_FORCE,
    law_title=LABOR_LAW,
    topic="إجازة الحج",
    source_phrase="إجازة بأجر لا تقل مدتها عن عشرة أيام ولا تزيد على خمسة عشر يومًا",
    cues=(("الحج", "حج", "فريضة الحج"), _LEAVE),
    comparator=Comparator.MINIMUM,
    limit=Quantity(10, Unit.DAY),
    units=frozenset({Unit.DAY}),
    skip_after=_CONDITION_WORDS,
)

MARRIAGE_LEAVE_MIN = Rule(
    rule_id="marriage-leave-min",
    article_id="labor-law:113",
    article_heading="المادة الثالثة عشرة بعد المائة",
    article_status=ArticleStatus.AMENDED,
    law_title=LABOR_LAW,
    topic="إجازة الزواج",
    source_phrase="للعامل الحق في إجازة بأجر كامل لمدة (خمسة) أيام عند زواجه",
    cues=(("زواج", "زواجه", "زواجها"), _LEAVE),
    comparator=Comparator.MINIMUM,
    limit=Quantity(5, Unit.DAY),
    units=frozenset({Unit.DAY}),
    # Art. 113 lists several leaves in one sentence; judge the one nearest the word.
    anchor=("زواج", "زواجه", "زواجها"),
)

PATERNITY_LEAVE_MIN = Rule(
    rule_id="paternity-leave-min",
    article_id="labor-law:113",
    article_heading="المادة الثالثة عشرة بعد المائة",
    article_status=ArticleStatus.AMENDED,
    law_title=LABOR_LAW,
    topic="إجازة ولادة مولود للعامل",
    source_phrase="و(ثلاثة) أيام في حالة ولادة مولود له",
    cues=(
        (
            "مولود له",
            "مولود للموظف",
            "مولود للعامل",
            "مولود جديد",
            "ولادة مولود",
            "ولادة طفل",
            "الأبوة",
            "أبوة",
        ),
        _LEAVE,
    ),
    comparator=Comparator.MINIMUM,
    limit=Quantity(3, Unit.DAY),
    units=frozenset({Unit.DAY}),
    anchor=("مولود", "طفل", "الأبوة", "أبوة"),
    skip_after=("خلال",),
)

LABOR_RULES: tuple[Rule, ...] = (
    PROBATION_MAX,
    NOTICE_EMPLOYER_MIN,
    ANNUAL_LEAVE_MIN,
    ANNUAL_LEAVE_AFTER_FIVE_YEARS_MIN,
    DAILY_HOURS_MAX,
    WEEKLY_HOURS_MAX,
    RAMADAN_DAILY_HOURS_MAX,
    RAMADAN_WEEKLY_HOURS_MAX,
    OVERTIME_RATE_MIN,
    MATERNITY_LEAVE_MIN,
    SICK_LEAVE_FULL_PAY_MIN,
    NON_COMPETE_MAX,
    LOAN_DEDUCTION_MAX,
    HAJJ_LEAVE_MIN,
    MARRIAGE_LEAVE_MIN,
    PATERNITY_LEAVE_MIN,
)
"""Every v1 rule, in the order findings are reported."""
