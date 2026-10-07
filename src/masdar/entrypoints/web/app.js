// Masdar web UI. No framework and no build step: one small script talking to /api.
// Every piece of law text is inserted as a text node, never as HTML, so the
// page stays safe under its strict Content-Security-Policy.
"use strict";

(() => {
  const RESULTS_PER_QUERY = 5;

  const form = document.getElementById("search-form");
  const input = document.getElementById("q");
  const filters = document.getElementById("law-filters");
  const sourcesList = document.getElementById("law-sources");
  const statusEl = document.getElementById("status");
  const progress = document.getElementById("progress");
  const list = document.getElementById("results");
  const answerBox = document.getElementById("answer");
  const template = document.getElementById("result-template");

  let lawTitles = new Map();
  let inFlight = null;
  // Set from /api/health: deployments without the reranker serve search only.
  let answersEnabled = false;

  // ---------------------------------------------------------------- Arabic matching
  // Mirrors the server's normalizer closely enough for highlighting: drop
  // diacritics and tatweel, fold alef / alef maqsura / taa marbuta, and map
  // Arabic-Indic digits, so "إجازة" in a question marks "اجازه" in the law.
  const DIACRITICS = /[ؐ-ًؚ-ٰٟۖ-ۭـ]/g;
  const STOP_WORDS = new Set([
    "ما", "ماذا", "هل", "كم", "كيف", "متى", "اين", "لماذا", "من", "في", "على", "علي",
    "عن", "الي", "او", "ان", "لا", "هي", "هو", "مع", "ذلك", "التي", "الذي", "يجوز",
    "النظام", "نظام", "ماده", "الماده",
  ]);
  const PREFIXES = ["وال", "بال", "فال", "كال", "لل", "ال", "و", "ب", "ف", "ل", "ك"];
  const MIN_STEM = 3;
  const MIN_PREFIX_MATCH = 4;

  function normalize(word) {
    return word
      .normalize("NFKC")
      .replace(DIACRITICS, "")
      .replace(/[أإآٱ]/g, "ا")
      .replace(/ى/g, "ي")
      .replace(/ة/g, "ه")
      .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
      .replace(/[^\p{L}\p{N}]/gu, "");
  }

  function stem(word) {
    const prefix = PREFIXES.find((p) => word.startsWith(p) && word.length - p.length >= MIN_STEM);
    return prefix ? word.slice(prefix.length) : word;
  }

  function queryStems(query) {
    return query
      .split(/\s+/)
      .map(normalize)
      .filter((word) => word.length >= 2 && !STOP_WORDS.has(word))
      .map(stem);
  }

  function matches(token, stems) {
    const candidate = stem(normalize(token));
    if (candidate.length < 2) return false;
    return stems.some((s) => {
      if (s === candidate) return true;
      const [short, long] = s.length <= candidate.length ? [s, candidate] : [candidate, s];
      return short.length >= MIN_PREFIX_MATCH && long.startsWith(short);
    });
  }

  // Splits on whitespace (kept), and wraps matching words in <mark>.
  function highlighted(text, stems) {
    const fragment = document.createDocumentFragment();
    for (const part of text.split(/(\s+)/)) {
      if (part && !/^\s+$/.test(part) && stems.length && matches(part, stems)) {
        const mark = document.createElement("mark");
        mark.textContent = part;
        fragment.append(mark);
      } else if (part) {
        fragment.append(document.createTextNode(part));
      }
    }
    return fragment;
  }

  // Long articles (definitions, penalty tables) would bury the answer, so the
  // card shows a window around the first matching word; the full article is
  // one click away.
  const EXCERPT_WORDS = 70;
  const EXCERPT_LEAD = 15;

  function excerpt(text, stems) {
    const words = text.split(/(\s+)/);
    const wordCount = words.filter((w) => w.trim()).length;
    if (wordCount <= EXCERPT_WORDS * 1.3) return text;
    const first = Math.max(0, words.findIndex((w) => w.trim() && matches(w, stems)));
    const start = Math.max(0, first - EXCERPT_LEAD * 2);
    const end = start + EXCERPT_WORDS * 2;
    const slice = words.slice(start, end).join("").trim();
    return `${start > 0 ? "… " : ""}${slice}${end < words.length ? " …" : ""}`;
  }

  // ------------------------------------------------------------------- rendering
  const AMENDMENT_VERBS = {
    replace: "عُدّل نصّ هذه المادة",
    add: "أُضيفت هذه المادة",
    consolidate: "أُعيدت صياغة هذه المادة",
    renumber: "أُعيد ترقيم هذه المادة",
    partial: "عُدّل جزء من هذه المادة",
  };

  function provenance(amendment) {
    const parts = [AMENDMENT_VERBS[amendment.kind] || "عُدّلت هذه المادة"];
    if (amendment.decree) parts.push(`بالمرسوم الملكي رقم (${amendment.decree})`);
    if (amendment.issued) parts.push(`وتاريخ ${amendment.issued} هـ`);
    let sentence = parts.join(" ") + ".";
    // Say plainly that the shown text may predate a partial edit.
    if (amendment.kind === "partial") sentence += " لم يُدمج التعديل في النص المعروض؛ راجع المصدر الرسمي.";
    return sentence;
  }

  function citationText(hit) {
    return hit.source_url ? `${hit.citation}\n${hit.source_url}` : hit.citation;
  }

  function renderHit(hit, stems) {
    const node = template.content.firstElementChild.cloneNode(true);
    const card = node.querySelector(".card");
    card.dataset.status = hit.status;
    node.querySelector(".card__heading").textContent = hit.heading;
    node.querySelector(".card__law").textContent = hit.article_title
      ? `${hit.law_title}، ${hit.article_title}`
      : hit.law_title;

    const badge = node.querySelector(".badge");
    badge.textContent = hit.status_label;
    badge.title = "حالة المادة";

    const trail = [hit.part, hit.chapter].filter(Boolean);
    const trailEl = node.querySelector(".card__trail");
    if (trail.length) trailEl.textContent = trail.join(" ‹ ");
    else trailEl.remove();

    const shown = excerpt(hit.matched_text, stems);
    node.querySelector(".card__text").append(highlighted(shown, stems));
    if (shown !== hit.matched_text || hit.text.trim() !== hit.matched_text.trim()) {
      const details = node.querySelector(".card__full");
      details.hidden = false;
      details.querySelector(".card__text--full").append(highlighted(hit.text, stems));
    }

    if (hit.latest_amendment) {
      const line = node.querySelector(".card__provenance");
      line.textContent = provenance(hit.latest_amendment);
      line.hidden = false;
    }

    const source = node.querySelector(".card__source");
    if (hit.source_url) {
      source.href = hit.source_url;
      source.setAttribute("aria-label", `${hit.citation} في المصدر الرسمي (يفتح في نافذة جديدة)`);
    } else {
      source.remove();
    }

    const copy = node.querySelector(".card__copy");
    copy.setAttribute("aria-label", `نسخ استشهاد ${hit.citation}`);
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(citationText(hit));
        copy.textContent = "نُسخ الاستشهاد";
      } catch {
        copy.textContent = "تعذّر النسخ";
      }
      setTimeout(() => { copy.textContent = "نسخ الاستشهاد"; }, 2000);
    });
    return node;
  }

  // The answer is the law's own sentence, copied verbatim by the server; the
  // page only lays it out. A refusal is shown as plainly as an answer.
  function renderAnswer(body) {
    answerBox.replaceChildren();
    answerBox.dataset.state = body.status;
    const title = document.createElement("h3");
    title.className = "answer__title";
    if (body.status !== "answered") {
      title.textContent = "لا توجد جملة في هذه الأنظمة تجيب سؤالك بثقة";
      const note = document.createElement("p");
      note.className = "answer__note";
      note.textContent = "لم نخمّن جواباً. هذه أقرب المواد إلى سؤالك، اقرأها للتحقق.";
      answerBox.append(title, note);
      answerBox.hidden = false;
      return;
    }
    title.textContent = "الجواب من نص النظام";
    answerBox.append(title);
    for (const quote of body.quotes) {
      const block = document.createElement("blockquote");
      block.className = "answer__quote";
      block.textContent = quote.sentence;
      answerBox.append(block);
    }
    const first = body.quotes[0];
    const cite = document.createElement("p");
    cite.className = "answer__cite";
    if (first.source_url) {
      const link = document.createElement("a");
      link.href = first.source_url;
      link.rel = "noopener noreferrer";
      link.target = "_blank";
      link.textContent = first.citation;
      cite.append(link);
    } else {
      cite.textContent = first.citation;
    }
    const note = document.createElement("p");
    note.className = "answer__note";
    note.textContent = "مقتبس حرفياً من نص المادة السارية، دون صياغة أو توليد.";
    answerBox.append(cite, note);
    answerBox.hidden = false;
  }

  function setStatus(message, tone = "") {
    statusEl.textContent = message;
    statusEl.dataset.tone = tone;
  }

  function setBusy(busy) {
    progress.hidden = !busy;
    list.setAttribute("aria-busy", String(busy));
    form.querySelector(".search__submit").disabled = busy;
  }

  // ---------------------------------------------------------------- data access
  function selectedLaws() {
    return [...filters.querySelectorAll("input:checked")].map((box) => box.value);
  }

  // Arabic counted nouns: 1 and 2 have their own forms, 3-10 take the plural.
  function articleCount(n) {
    if (n === 1) return "مادة واحدة";
    if (n === 2) return "مادتان";
    return n <= 10 ? `${n} مواد` : `${n} مادة`;
  }

  function scopeLabel(laws) {
    if (!laws.length) return "الأنظمة الثلاثة";
    return laws.map((id) => lawTitles.get(id) || id).join(" و");
  }

  async function search(question) {
    const laws = selectedLaws();
    const params = new URLSearchParams({ q: question, k: String(RESULTS_PER_QUERY) });
    laws.forEach((law) => params.append("law", law));
    history.replaceState(null, "", `?${params}`);

    if (inFlight) inFlight.abort();
    const controller = new AbortController();
    inFlight = controller;
    setBusy(true);
    setStatus("جارٍ البحث…");
    list.replaceChildren();
    answerBox.hidden = true;
    try {
      const endpoint = answersEnabled ? "/api/answer" : "/api/search";
      const response = await fetch(`${endpoint}?${params}`, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      const body = await response.json();
      if (!response.ok) {
        setStatus(body?.error?.message_ar || "تعذّر تنفيذ البحث. حاول مرة أخرى.", "error");
        return;
      }
      if (!body.results.length) {
        setStatus(`لا توجد مادة تطابق سؤالك في ${scopeLabel(laws)}. جرّب صياغة أخرى أو وسّع النطاق.`, "empty");
        return;
      }
      if (body.status) renderAnswer(body);
      const stems = queryStems(body.query);
      list.replaceChildren(...body.results.map((hit) => renderHit(hit, stems)));
      setStatus(`${articleCount(body.results.length)} من ${scopeLabel(laws)}، مرتبة بحسب الصلة بسؤالك.`);
    } catch (error) {
      if (error.name === "AbortError") return;
      setStatus("تعذّر الاتصال بالخادم. تحقّق من اتصالك ثم أعد المحاولة.", "error");
    } finally {
      // An aborted older search must not end the busy state of the newer one.
      if (inFlight === controller) {
        inFlight = null;
        setBusy(false);
      }
    }
  }

  // An ISO date inside RTL text renders reversed ("07-10-2026"); a written
  // Arabic date reads correctly. Latin digits match the rest of the page.
  const DATE_FORMAT = new Intl.DateTimeFormat("ar-u-nu-latn", {
    day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });

  function snapshotDate(iso) {
    const date = new Date(`${iso}T00:00:00Z`);
    return Number.isNaN(date.getTime()) ? iso : DATE_FORMAT.format(date);
  }

  function renderLaws(laws, preselected) {
    lawTitles = new Map(laws.map((law) => [law.law_id, law.title]));
    filters.replaceChildren(...laws.map((law) => {
      const label = document.createElement("label");
      label.className = "pill";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.name = "law";
      box.value = law.law_id;
      box.checked = preselected.includes(law.law_id);
      const text = document.createElement("span");
      text.textContent = law.title;
      label.append(box, text);
      return label;
    }));
    sourcesList.replaceChildren(...laws.map((law) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = law.source_url;
      link.rel = "noopener noreferrer";
      link.target = "_blank";
      link.textContent = law.title;
      const meta = document.createElement("span");
      meta.className = "sources__meta";
      meta.textContent = `${law.current} مادة سارية، نسخة ${snapshotDate(law.retrieved_on)}`;
      item.append(link, meta);
      return item;
    }));
  }

  // --------------------------------------------------------------------- wiring
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) {
      setStatus("اكتب سؤالاً أولاً، أو اختر أحد الأسئلة المقترحة.", "error");
      input.focus();
      return;
    }
    search(question);
  });

  document.querySelectorAll(".chip[data-question]").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.question;
      search(input.value);
    });
  });

  filters.addEventListener("change", () => {
    if (input.value.trim()) search(input.value.trim());
  });

  const initial = new URLSearchParams(location.search);
  const getJson = (url) => fetch(url, { headers: { Accept: "application/json" } })
    .then((response) => (response.ok ? response.json() : null));
  Promise.allSettled([
    getJson("/api/laws").then((laws) => renderLaws(laws || [], initial.getAll("law"))),
    getJson("/api/health").then((health) => { answersEnabled = Boolean(health?.answers); }),
  ])
    // Filters and answers are optional; search still covers every law.
    .finally(() => {
      const question = initial.get("q");
      if (question) {
        input.value = question;
        search(question);
      }
    });

  // ------------------------------------------------------------ contract checker
  const checkForm = document.getElementById("check-form");
  const contract = document.getElementById("contract");
  const checkStatus = document.getElementById("check-status");
  const checkList = document.getElementById("check-results");
  const quiet = document.getElementById("check-quiet");
  const SAMPLE_CONTRACT = [
    "المادة الأولى: يخضع الموظف لفترة تجربة مدتها مائتا يوم من تاريخ مباشرته العمل.",
    "المادة الثانية: ساعات العمل عشر ساعات يومياً من الأحد إلى الخميس.",
    "المادة الثالثة: يستحق الموظف إجازة سنوية مدتها واحد وعشرون يوماً بأجر كامل.",
    "المادة الرابعة: يحق لصاحب العمل إنهاء العقد غير محدد المدة بإشعار كتابي قبل ثلاثين يوماً.",
    "المادة الخامسة: يلتزم الموظف بعدم منافسة صاحب العمل لمدة ثلاث سنوات بعد انتهاء العقد.",
    "المادة السادسة: يلتزم الموظف بالمحافظة على سرية المعلومات وعدم إفشائها.",
  ].join("\n");

  function renderFinding(finding) {
    const box = document.createElement("div");
    box.className = "finding";
    box.dataset.kind = finding.kind;
    const head = document.createElement("p");
    head.className = "finding__head";
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = finding.kind_label;
    head.append(badge);
    if (finding.source_url) {
      const link = document.createElement("a");
      link.className = "finding__source";
      link.href = finding.source_url;
      link.rel = "noopener noreferrer";
      link.target = "_blank";
      link.textContent = finding.citation;
      head.append(link);
    } else {
      head.append(document.createTextNode(finding.citation));
    }
    const message = document.createElement("p");
    message.className = "finding__message";
    message.textContent = finding.message;
    box.append(head, message);
    return box;
  }

  function renderClause(clause) {
    const item = document.createElement("li");
    item.className = "clause";
    const text = document.createElement("p");
    text.className = "clause__text";
    text.textContent = clause.text;
    item.append(text, ...clause.findings.map(renderFinding));
    return item;
  }

  function renderCheck(body) {
    const judged = body.clauses.filter((clause) => clause.findings.length);
    const others = body.clauses.filter((clause) => !clause.findings.length);
    checkList.replaceChildren(...judged.map(renderClause));
    const { violation = 0, compliant = 0, review_needed: review = 0 } = body.counts;
    checkStatus.dataset.tone = "";
    checkStatus.textContent = judged.length
      ? `${body.clauses.length} بنداً: ${violation} مخالفة، ${compliant} متوافق، ${review} يحتاج مراجعة.`
      : "لم نجد في النص مدداً أو ساعات أو نسباً يحدّها نظام العمل. راجع المواد المتعلقة أدناه.";
    const quietList = quiet.querySelector("ol");
    quietList.replaceChildren(...others.map((clause) => {
      const line = document.createElement("li");
      const related = clause.related[0];
      line.textContent = related ? `${clause.text}  ←  ${related.citation}` : clause.text;
      return line;
    }));
    quiet.querySelector("summary").textContent = `بنود بلا حكم رقمي (${others.length}) وأقرب مادة لكل منها`;
    quiet.hidden = !others.length;
  }

  async function check(text) {
    checkStatus.dataset.tone = "";
    checkStatus.textContent = "جارٍ الفحص…";
    checkList.replaceChildren();
    quiet.hidden = true;
    const buttons = [checkForm.querySelector("[type=submit]"), document.getElementById("check-sample")];
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const response = await fetch("/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ text }),
      });
      // A proxy error page is not JSON; it is still a server answer, not a lost connection.
      const body = await response.json().catch(() => null);
      if (!response.ok || !body) {
        checkStatus.dataset.tone = "error";
        checkStatus.textContent = body?.error?.message_ar || "تعذّر فحص النص. حاول مرة أخرى.";
        return;
      }
      renderCheck(body);
    } catch {
      checkStatus.dataset.tone = "error";
      checkStatus.textContent = "تعذّر الاتصال بالخادم. تحقّق من اتصالك ثم أعد المحاولة.";
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  checkForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = contract.value.trim();
    if (!text) {
      checkStatus.dataset.tone = "error";
      checkStatus.textContent = "الصق نص العقد أو السياسة أولاً، أو جرّب العقد النموذجي.";
      contract.focus();
      return;
    }
    check(text);
  });

  document.getElementById("check-sample").addEventListener("click", () => {
    contract.value = SAMPLE_CONTRACT;
    check(SAMPLE_CONTRACT);
  });
})();
