(() => {
  const sidebar = document.getElementById("school-sidebar");
  const toggle = document.querySelector(".school-sidebar-toggle");
  if (!sidebar || !toggle) return;

  const mobile = window.matchMedia("(max-width: 767px)");
  const setExpanded = (expanded) => {
    sidebar.hidden = !expanded;
    toggle.setAttribute("aria-expanded", String(expanded));
  };
  const syncViewport = () => {
    if (sidebar.contains(document.activeElement) && mobile.matches) toggle.focus();
    if (document.activeElement === toggle && !mobile.matches) {
      sidebar.querySelector("a")?.focus();
    }
    toggle.hidden = !mobile.matches;
    setExpanded(!mobile.matches);
  };

  toggle.addEventListener("click", () => {
    setExpanded(toggle.getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mobile.matches && !sidebar.hidden) {
      setExpanded(false);
      toggle.focus();
    }
  });
  sidebar.addEventListener("click", (event) => {
    if (mobile.matches && event.target.closest("a")) {
      setExpanded(false);
      toggle.focus();
    }
  });
  mobile.addEventListener("change", syncViewport);
  syncViewport();
})();

// Confirm existing POST actions without replacing their native submission flow.
(() => {
  const dialog = document.getElementById("school-confirmation");
  if (!dialog) return;
  const approved = new WeakSet();
  let pending = null;
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.schoolConfirm) return;
    if (approved.has(form)) { approved.delete(form); return; }
    if (!dialog.showModal) {
      if (!window.confirm(form.dataset.schoolConfirm)) event.preventDefault();
      return;
    }
    event.preventDefault();
    if (dialog.open) return;
    pending = { form, submitter: event.submitter, focus: document.activeElement };
    dialog.querySelector("#school-confirmation-message").textContent = form.dataset.schoolConfirm;
    dialog.returnValue = "cancel";
    dialog.showModal();
  });
  dialog.addEventListener("close", () => {
    const action = pending;
    pending = null;
    if (!action) return;
    action.focus?.focus();
    if (dialog.returnValue !== "confirm" || !action.form.isConnected) return;
    approved.add(action.form);
    action.form.requestSubmit(action.submitter || undefined);
    approved.delete(action.form);
  });
})();

// Shared feedback only: controls retain their names, values and enabled state.
(() => {
  const indicator = document.getElementById("school-loading");
  const workspace = document.querySelector(".school-layout");
  if (!indicator || !workspace) return;
  const requests = new Set();
  let navigationPending = false;
  let resetTimer;
  const update = () => { indicator.hidden = !navigationPending && requests.size === 0; };
  const clearNavigation = () => {
    navigationPending = false;
    workspace.querySelectorAll("[data-school-loading]").forEach((element) => {
      element.removeAttribute("data-school-loading");
    });
    update();
  };
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!workspace.contains(form) || form.method === "dialog") return;
    // Wait for confirmation/HTMX handlers to prevent or accept the submission.
    queueMicrotask(() => {
      if (event.defaultPrevented) return;
      navigationPending = true;
      if (event.submitter) event.submitter.setAttribute("data-school-loading", "true");
      update();
      clearTimeout(resetTimer);
      resetTimer = setTimeout(clearNavigation, 30000);
    });
  });
  document.body.addEventListener("htmx:beforeRequest", (event) => {
    if (!workspace.contains(event.detail.elt)) return;
    requests.add(event.detail.xhr);
    update();
  });
  const finish = (event) => {
    requests.delete(event.detail.xhr);
    update();
  };
  ["htmx:afterRequest", "htmx:sendError", "htmx:timeout", "htmx:sendAbort"].forEach((name) => {
    document.body.addEventListener(name, finish);
  });
  window.addEventListener("pageshow", () => {
    requests.clear();
    clearTimeout(resetTimer);
    clearNavigation();
  });
})();

// Show safe request feedback; never display a server response body or traceback.
(() => {
  const error = document.getElementById("school-request-error");
  const workspace = document.querySelector(".school-layout");
  if (!error || !workspace) return;
  const failure = (event) => {
    if (!workspace.contains(event.detail.elt)) return;
    error.textContent = "The request could not be completed. Please check the page before trying again.";
    error.hidden = false;
  };
  ["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach((name) => {
    document.body.addEventListener(name, failure);
  });
  document.body.addEventListener("htmx:beforeRequest", (event) => {
    if (workspace.contains(event.detail.elt)) error.hidden = true;
  });
})();
