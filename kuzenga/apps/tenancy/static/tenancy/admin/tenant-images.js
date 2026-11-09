(() => {
  document.querySelectorAll(".tenant-image-preview img").forEach((preview) => {
    const inputId = preview.id.replace(/_preview$/, "");
    const input = document.getElementById(inputId);
    const clear = document.getElementById(`${inputId}-clear_id`);
    const originalSource = preview.dataset.originalSrc || "";
    let previewUrl = "";

    if (!input) return;

    input.addEventListener("change", () => {
      const file = input.files?.[0];
      if (!file) return;
      if (clear) clear.checked = false;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
      preview.hidden = false;
    });

    clear?.addEventListener("change", () => {
      if (clear.checked) {
        input.value = "";
        preview.hidden = true;
      } else if (input.files?.[0]) {
        input.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (originalSource) {
        preview.src = originalSource;
        preview.hidden = false;
      }
    });
  });
})();
