(function () {
  "use strict";

  // Mobile menu toggle
  var burger = document.getElementById("set-burger");
  var menu = document.getElementById("set-mobile-menu");
  if (burger && menu) {
    burger.addEventListener("click", function () {
      var isOpen = menu.classList.toggle("is-open");
      burger.classList.toggle("is-active", isOpen);
      burger.setAttribute("aria-expanded", isOpen ? "true" : "false");
      document.body.classList.toggle("set-menu-open", isOpen);
    });
    menu.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        menu.classList.remove("is-open");
        burger.classList.remove("is-active");
        burger.setAttribute("aria-expanded", "false");
        document.body.classList.remove("set-menu-open");
      });
    });
  }

  // FAQ accordion
  document.querySelectorAll(".set-faq__item").forEach(function (item) {
    var btn = item.querySelector(".set-faq__q");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var wasOpen = item.classList.contains("is-open");
      item.closest(".set-faq").querySelectorAll(".set-faq__item").forEach(function (i) {
        i.classList.remove("is-open");
        i.querySelector(".set-faq__q").setAttribute("aria-expanded", "false");
      });
      if (!wasOpen) {
        item.classList.add("is-open");
        btn.setAttribute("aria-expanded", "true");
      }
    });
  });

  // Smooth scroll for in-page anchors
  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    var targetId = link.getAttribute("href");
    if (!targetId || targetId === "#" || targetId.length < 2) return;
    link.addEventListener("click", function (e) {
      var target = document.querySelector(targetId);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  // Footer year
  var yearEl = document.getElementById("set-year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();
})();
