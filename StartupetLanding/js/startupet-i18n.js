/* StartupET — minimal EN/Amharic toggle.
 *
 * Deliberately not tied into the template's React hydration: it runs after
 * the page has fully loaded and settled, then walks the DOM looking for
 * leaf elements (no child elements, just text) whose text exactly matches an
 * English phrase in the dictionary below and swaps it for the active
 * language. Toggling again swaps back using the same dictionary, so no
 * original text is ever lost.
 *
 * Extensible: add more phrases to DICTIONARY, or add another language by
 * adding a new top-level key to each entry (LANGS.push('om'), etc.) and a
 * matching button in the switcher markup on each page.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "startupet-lang";
  var LANGS = ["en", "am"];

  // Headings that use the template's character-by-character "reveal" load
  // animation are split into one DOM node per letter, so there is no single
  // leaf node holding the full phrase for the generic dictionary walk below
  // to match against. Those are targeted directly by selector instead, same
  // as the hero (whose words are similarly split into per-word wrappers).
  var ELEMENT_OVERRIDES = [
    {
      selector: ".mxd-hero-05__headline h1",
      html: {
        en: "Ethiopia&rsquo;s<br><small>Startup Era Has Begun</small>",
        am: "የኢትዮጵያ<br><small>የስታርትአፕ ዘመን ጀምሯል</small>"
      }
    },
    {
      selector: ".mxd-section-title__title.centered h2.reveal-type",
      text: { en: "Trust, transparency, and clear facts", am: "እምነት፣ ግልጽነት እና ግልጽ መረጃ" }
    },
    {
      selector: ".mxd-section-title.pre-grid h2.reveal-type",
      text: { en: "Key resources", am: "ዋና ዋና ግብዓቶች" }
    },
    {
      selector: "h2.reveal-type.opposite",
      text: { en: "Ready to register your startup?", am: "ስታርትአፕዎን ለመመዝገብ ዝግጁ ነዎት?" }
    }
  ];

  // { en: "exact visible text", am: "translation" } — matched against leaf
  // elements (no child elements) whose full trimmed text equals `en`/`am`.
  var DICTIONARY = [
    { en: "Official Startup Designation Platform", am: "ይፋዊ የስታርትአፕ ምዝገባ መድረክ" },
    { en: "Scroll to explore", am: "ለማየት ይሸብልሉ" },
    { en: "All Resources", am: "ሁሉንም ግብዓቶች" },
    { en: "ALL RESOURCES", am: "ሁሉንም ግብዓቶች" },
    { en: "Apply for Designation", am: "ለምዝገባ ያመልክቱ" },
    { en: "Apply Now", am: "አሁን ያመልክቱ" },
    { en: "Menu", am: "ማውጫ" },
    { en: "Platform", am: "መድረክ" },
    { en: "Eligibility", am: "ብቁነት" },
    { en: "Benefits", am: "ጥቅሞች" },
    { en: "Process", am: "ሂደት" },
    { en: "Apply", am: "ያመልክቱ" }
  ];

  function dictLookup(text, lang) {
    for (var i = 0; i < DICTIONARY.length; i++) {
      var entry = DICTIONARY[i];
      if (entry.en === text) return entry[lang];
      if (lang === "en" && entry.am === text) return entry.en;
    }
    return null;
  }

  function isLeaf(el) {
    return el.children.length === 0;
  }

  function applyDictionary(lang) {
    var all = document.body.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (!isLeaf(el)) continue;
      var text = el.textContent.trim();
      if (!text) continue;
      var translated = dictLookup(text, lang);
      if (translated && translated !== text) {
        el.textContent = translated;
      }
    }
    // aria-labels aren't covered by the textContent walk above.
    document.querySelectorAll("[aria-label]").forEach(function (el) {
      var label = el.getAttribute("aria-label");
      var translated = dictLookup(label, lang);
      if (translated && translated !== label) {
        el.setAttribute("aria-label", translated);
      }
    });
  }

  function applyElementOverrides(lang) {
    ELEMENT_OVERRIDES.forEach(function (o) {
      var el = document.querySelector(o.selector);
      if (!el) return;
      if (o.html) el.innerHTML = o.html[lang];
      else if (o.text) el.textContent = o.text[lang];
      // These headings carry a character/word-split reveal animation that
      // re-triggers on its own schedule (independent of the hydration churn
      // the MutationObserver guards against) and rebuilds its split markup
      // from a copy of the original English text it holds internally,
      // silently undoing the override. Stripping its hooks stops it from
      // touching the element again; the reveal only ever plays once on
      // initial load anyway, so there's nothing lost by disarming it here.
      el.removeAttribute("data-common-animated");
      el.classList.remove("loading-split", "reveal-type");
    });
  }

  function setSwitcherState(lang) {
    document.querySelectorAll(".lang-switcher__opt").forEach(function (btn) {
      var active = btn.getAttribute("data-lang-set") === lang;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.classList.toggle("active", active);
    });
    document.documentElement.setAttribute("lang", lang === "am" ? "am" : "en");
  }

  var currentLang = "en";
  var applying = false;

  function setLang(lang) {
    if (LANGS.indexOf(lang) === -1) lang = "en";
    currentLang = lang;
    applying = true;
    applyDictionary(lang);
    applyElementOverrides(lang);
    buildSwitcher();
    setSwitcherState(lang);
    applying = false;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {
      /* storage unavailable (private browsing, etc.) — toggle still works for this page view */
    }
  }

  // The header is a hydrated React tree: any switcher markup baked into the
  // static HTML gets stripped out the moment the client takes over, since it
  // isn't part of that tree's render output. Building the button here, after
  // hydration has already settled, is the only way it survives.
  function buildSwitcher() {
    if (document.querySelector(".mxd-lang-switcher")) return;
    var controls = document.querySelector(".mxd-header__controls");
    var colorSwitcher = document.getElementById("color-switcher");
    if (!controls) return;

    var wrap = document.createElement("div");
    wrap.className = "mxd-lang-switcher";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "Language");
    wrap.innerHTML =
      '<button type="button" class="lang-switcher__opt" data-lang-set="en" aria-pressed="true">EN</button>' +
      '<span class="lang-switcher__sep" aria-hidden="true">/</span>' +
      '<button type="button" class="lang-switcher__opt" data-lang-set="am" aria-pressed="false">አማ</button>';

    if (colorSwitcher) controls.insertBefore(wrap, colorSwitcher);
    else controls.appendChild(wrap);

    wrap.querySelectorAll(".lang-switcher__opt").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setLang(btn.getAttribute("data-lang-set"));
      });
    });
  }

  // The template's own hydration occasionally fails and falls back to a full
  // client re-render of a subtree (observed on the header controls) — which
  // silently discards the switcher button and reverts any translated text
  // inside that subtree back to English. Watching for DOM churn and
  // re-asserting the current language/switcher after it settles makes the
  // toggle resilient to that, regardless of when or why it happens.
  function observeAndHeal() {
    var pending = null;
    var observer = new MutationObserver(function () {
      if (applying) return;
      if (pending) clearTimeout(pending);
      pending = setTimeout(function () {
        pending = null;
        if (!document.querySelector(".mxd-lang-switcher")) buildSwitcher();
        if (currentLang !== "en") applyDictionary(currentLang);
        setSwitcherState(currentLang);
      }, 150);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // The hero/section headings above are different: they carry a scroll-linked
  // reveal animation that re-renders on its own continuous loop, far faster
  // than the debounced observer above can settle, so a debounce just starves
  // and never fires. Reasserting them unconditionally every animation frame
  // — a handful of cheap DOM writes — reliably wins that race instead.
  function healOverridesLoop() {
    if (currentLang !== "en") applyElementOverrides(currentLang);
    requestAnimationFrame(healOverridesLoop);
  }

  function boot() {
    buildSwitcher();
    var saved = null;
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      /* ignore */
    }
    if (saved && saved !== "en") setLang(saved);
    else setSwitcherState("en");
    observeAndHeal();
    requestAnimationFrame(healOverridesLoop);
  }

  if (document.readyState === "complete") {
    boot();
  } else {
    window.addEventListener("load", boot);
  }
})();
