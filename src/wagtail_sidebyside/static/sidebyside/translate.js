(() => {
  const form = document.querySelector("[data-sbs-form]");
  if (!form) return;

  // Filter rows by status.
  const filters = form.querySelectorAll("[data-sbs-filter]");
  filters.forEach((button) => {
    button.addEventListener("click", () => {
      const status = button.dataset.sbsFilter;
      filters.forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      form.querySelectorAll(".sbs-row").forEach((row) => {
        row.classList.toggle("sbs-hidden", Boolean(status) && row.dataset.status !== status);
      });
    });
  });

  // Fill the slug from the translated title until the editor types a slug.
  const slugify = (text) =>
    text
      .normalize("NFKD")
      .replace(/\p{Diacritic}/gu, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  const title = form.querySelector("[data-sbs-title] input");
  const slug = form.querySelector("[data-sbs-slug] input");
  if (title && slug) {
    let auto = !slug.value || slug.value === slugify(title.value);
    slug.addEventListener("input", () => {
      auto = !slug.value;
    });
    title.addEventListener("input", () => {
      if (auto) slug.value = slugify(title.value);
    });
  }

  // "Same in both languages": the page uses the source text. The field is
  // read-only (still submitted, so its text is kept for when it is unticked);
  // CSS dims it and blocks the rich text editor too.
  const applySame = (checkbox) => {
    const target = checkbox.closest(".sbs-row").querySelector(".sbs-target");
    target.classList.toggle("sbs-target--same", checkbox.checked);
    target.querySelectorAll("input:not([type=hidden]), textarea").forEach((field) => {
      field.readOnly = checkbox.checked;
    });
  };

  // Image/document: the chooser is only used when "different in this
  // language" is ticked; otherwise the source's one is.
  const applyOverride = (checkbox) => {
    checkbox
      .closest("[data-sbs-override-target]")
      .querySelector(".sbs-override__chooser")
      .classList.toggle("sbs-hidden", !checkbox.checked);
  };

  const applyCheckboxes = (root) => {
    root.querySelectorAll("input[name=same]").forEach(applySame);
    root.querySelectorAll("input[name=override]").forEach(applyOverride);
  };
  applyCheckboxes(form);
  // Delegated, so it also works for rows replaced below.
  form.addEventListener("change", (event) => {
    if (event.target.name === "same") applySame(event.target);
    if (event.target.name === "override") applyOverride(event.target);
  });

  // Copy source / AI for one field: post the form in the background and swap
  // in that row's new content, instead of reloading the page. The rich text
  // editor cannot be filled from JS, but a new one starts by itself: Wagtail
  // initialises Draftail when its input appears in the page. Capture phase,
  // so this runs before the handlers below and Wagtail's w-unsaved.
  form.addEventListener(
    "submit",
    async (event) => {
      const button = event.submitter;
      if (!button || !["copy", "ai"].includes(button.name) || button.value === "all") return;
      event.preventDefault();
      event.stopImmediatePropagation();

      const body = new FormData(form, button);
      const label = button.innerHTML;
      if (button.dataset.sbsBusy) button.textContent = button.dataset.sbsBusy;
      button.disabled = true;
      try {
        const response = await fetch(window.location.href, { method: "POST", body });
        const page = new DOMParser().parseFromString(await response.text(), "text/html");
        const selector = `.sbs-row[data-path="${CSS.escape(button.value)}"]`;
        const row = form.querySelector(selector);
        const fresh = page.querySelector(selector);
        if (row && fresh) {
          // Content and header controls only: the panel itself (collapse
          // toggle, minimap anchor) stays as it is.
          for (const part of [".w-panel__content", ".w-panel__controls"]) {
            const current = row.querySelector(part);
            const update = fresh.querySelector(part);
            if (current && update) current.replaceWith(document.importNode(update, true));
          }
          applyCheckboxes(row);
          // Tell Wagtail's w-unsaved: unsaved changes, and a live preview update.
          row.querySelector(".sbs-target input, .sbs-target textarea")?.dispatchEvent(
            new Event("change", { bubbles: true }),
          );
        }
        const messages = document.querySelector(".messages");
        const freshMessages = page.querySelector(".messages");
        if (messages && freshMessages) messages.innerHTML = freshMessages.innerHTML;
      } finally {
        if (button.isConnected) {
          button.innerHTML = label;
          button.disabled = false;
        }
      }
    },
    { capture: true },
  );

  // Other submits (AI for all empty fields, save, publish) reload the page.
  // AI takes a while: show it, and prevent double submits. Disable after the
  // submit, so the clicked button's value is still sent.
  form.addEventListener("submit", (event) => {
    const busy = event.submitter?.dataset.sbsBusy;
    if (busy) event.submitter.textContent = busy;
    setTimeout(() => {
      form.querySelectorAll("button[type=submit]").forEach((b) => (b.disabled = true));
    });
  });

  // After translating one field with AI without JS, scroll back to it.
  const focus = form.dataset.sbsFocus;
  if (focus) {
    const row = [...form.querySelectorAll(".sbs-row")].find((r) => r.dataset.path === focus);
    row?.scrollIntoView({ block: "center" });
  }

  // Enter in a text field must not submit: the first submit button in the
  // form is an action button. Saving is Wagtail's footer (also Ctrl/Cmd+S).
  form.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches("input[type=text]")) {
      event.preventDefault();
    }
  });
})();
