(() => {
  const supported = new Set(["en", "fa"]);
  const persianDigits = "۰۱۲۳۴۵۶۷۸۹";
  const arabicDigits = "٠١٢٣٤٥٦٧٨٩";

  function requestedLanguage() {
    const query = new URLSearchParams(location.search).get("lang");
    if (supported.has(query)) return query;
    try {
      const saved = localStorage.getItem("audit-lab-language");
      if (supported.has(saved)) return saved;
    } catch (_) {}
    return document.documentElement.lang === "fa" ? "fa" : "en";
  }

  function toPersian(value) {
    return value.replace(/[0-9]/g, digit => persianDigits[Number(digit)]);
  }

  function toLatin(value) {
    return value
      .replace(/[۰-۹]/g, digit => String(persianDigits.indexOf(digit)))
      .replace(/[٠-٩]/g, digit => String(arabicDigits.indexOf(digit)));
  }

  function localizeVisibleDigits(language) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      const parent = node.parentElement;
      if (!parent || parent.closest("code, pre, script, style, [data-preserve-digits]")) return;
      node.nodeValue = language === "fa" ? toPersian(node.nodeValue) : toLatin(node.nodeValue);
    });
  }

  function applyLanguage(language, updateHistory = true) {
    const next = supported.has(language) ? language : "en";
    document.documentElement.lang = next;
    document.documentElement.dir = next === "fa" ? "rtl" : "ltr";

    document.querySelectorAll("[data-en][data-fa]").forEach(element => {
      element.textContent = next === "fa" ? element.dataset.fa : element.dataset.en;
    });
    document.querySelectorAll("[data-en-aria][data-fa-aria]").forEach(element => {
      element.setAttribute("aria-label", next === "fa" ? element.dataset.faAria : element.dataset.enAria);
    });
    document.querySelectorAll("[data-language]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.language === next));
    });

    localizeVisibleDigits(next);
    try { localStorage.setItem("audit-lab-language", next); } catch (_) {}
    if (updateHistory) {
      const url = new URL(location.href);
      if (next === "fa") url.searchParams.set("lang", "fa");
      else url.searchParams.delete("lang");
      history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }
    document.dispatchEvent(new CustomEvent("auditlab:languagechange", { detail: { language: next } }));
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("[data-language]");
    if (button) applyLanguage(button.dataset.language);
  });

  applyLanguage(requestedLanguage(), false);
})();
