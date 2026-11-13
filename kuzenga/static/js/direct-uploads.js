/* Move file bodies directly to private object storage; retain existing forms. */
(() => {
  const script = document.currentScript;
  const endpoint = script.dataset.uploadGrant;
  const permittedSubmission = new WeakSet();
  const busy = new WeakSet();
  class UploadError extends Error {}

  // A changed/cleared selection must never submit a previously uploaded file.
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.type !== "file" || !input.form) return;
    for (const hidden of input.form.querySelectorAll('input[type="hidden"]')) {
      if (hidden.name === "_direct_upload_" + input.name) hidden.remove();
    }
  }, true);

  document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || permittedSubmission.has(form)) return;
    const inputs = [...form.querySelectorAll('input[type="file"]')]
      .filter((input) => !input.disabled && input.name && input.files.length);
    if (!inputs.length) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (busy.has(form)) return;
    busy.add(form);
    const button = event.submitter;
    const status = form.querySelector("[data-direct-upload-status]") || document.createElement("p");
    status.dataset.directUploadStatus = "";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    form.append(status);
    status.textContent = "Uploading files…";
    form.setAttribute("aria-busy", "true");
    const csrf = form.querySelector('[name="csrfmiddlewaretoken"]')?.value;
    try {
      const target = new URL(form.action || window.location.href, window.location.href);
      if (target.origin !== window.location.origin) throw new UploadError("Invalid form destination.");
      for (const input of inputs) {
        if (input.files.length !== 1) throw new UploadError("Select one file per field.");
        const file = input.files[0];
        if (!file.size || file.size > 10 * 1024 * 1024) throw new UploadError("Files must be non-empty and no larger than 10 MB.");
        const hash = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
        const sha256 = [...new Uint8Array(hash)].map((value) => value.toString(16).padStart(2, "0")).join("");
        const response = await fetch(endpoint, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({ target: target.pathname, field: input.name, name: file.name, size: file.size, sha256 }),
        });
        if (!response.ok || response.redirected) throw new UploadError("Upload could not be authorized. Refresh and try again.");
        const grant = await response.json();
        const uploaded = await fetch(grant.url, {
          method: "PUT", credentials: "omit", referrerPolicy: "no-referrer",
          headers: { "Content-Type": grant.content_type }, body: file,
        });
        if (!uploaded.ok) throw new UploadError("File upload failed. Please try again.");
        const ticketName = "_direct_upload_" + input.name;
        const hidden = [...form.querySelectorAll('input[type="hidden"]')].find((item) => item.name === ticketName)
          || document.createElement("input");
        hidden.type = "hidden";
        hidden.name = ticketName;
        hidden.value = grant.ticket;
        form.append(hidden);
      }
      inputs.forEach((input) => { input.disabled = true; });
      status.textContent = "Files uploaded. Saving…";
      permittedSubmission.add(form);
      form.requestSubmit(button || undefined);
    } catch (error) {
      status.textContent = error instanceof UploadError ? error.message : "Upload failed. Refresh and try again.";
      status.setAttribute("role", "alert");
      inputs.forEach((input) => { input.disabled = false; });
      form.removeAttribute("aria-busy");
    } finally {
      busy.delete(form);
    }
  }, true);
})();
