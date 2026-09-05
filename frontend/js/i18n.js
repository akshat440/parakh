const SUPPORTED_LANGS = {
  en: "English",
  hi: "हिन्दी (Hindi)",
  mr: "मराठी (Marathi)",
  ta: "தமிழ் (Tamil)",
  te: "తెలుగు (Telugu)",
  kn: "ಕನ್ನಡ (Kannada)",
};

let currentTranslations = {};

async function loadLocale(lang) {
  const res = await fetch(`locales/${lang}.json`);
  currentTranslations = await res.json();
  localStorage.setItem("lm_lang", lang);
  applyTranslations();
}

function t(key) {
  return currentTranslations[key] || key;
}

function applyTranslations() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    el.textContent = t(key);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });
  document.title = t("app_title");
  // Let the app re-render any dynamic content that embeds translated strings
  if (typeof onTranslationsApplied === "function") {
    onTranslationsApplied();
  }
}

function initLangSwitchers() {
  document.querySelectorAll(".lang-select").forEach((sel) => {
    sel.innerHTML = Object.entries(SUPPORTED_LANGS)
      .map(([code, label]) => `<option value="${code}">${label}</option>`)
      .join("");
    sel.value = localStorage.getItem("lm_lang") || "en";
    sel.addEventListener("change", (e) => {
      document.querySelectorAll(".lang-select").forEach((s) => (s.value = e.target.value));
      loadLocale(e.target.value);
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initLangSwitchers();
  loadLocale(localStorage.getItem("lm_lang") || "en");
});
