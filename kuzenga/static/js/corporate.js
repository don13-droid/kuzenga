(() => {
  const data = JSON.parse(document.getElementById("pricing-data").textContent);
  const enrolment = document.getElementById("enrolment");
  const plan = document.getElementById("plan");
  const output = document.getElementById("quote");
  const money = (value) => `US$${value}`;
  function update() {
    const count = Number(enrolment.value);
    const chosen = plan.value;
    const inputs = [...document.querySelectorAll('input[name="addon"]')];
    data.addons.forEach((item) => {
      const included = item.included.includes(chosen);
      const input = inputs.find((control) => control.value === item.code);
      input.disabled = included;
      document.querySelector(`[data-included="${item.code}"]`).textContent =
        included ? "Included" : "";
    });
    if (enrolment.value === "" || !Number.isInteger(count) || count < 0) {
      output.textContent = "Enter a non-negative whole student enrolment.";
      return;
    }
    if (count > 2000 || chosen === "enterprise") {
      output.textContent =
        "Custom quotation required. For 2,001+ students, once-off setup starts at US$120. Contact sales for subscription and annual totals.";
      return;
    }
    const band = data.bands.find((item) => count <= item.limit);
    const subscription =
      band.prices[["starter", "standard", "professional"].indexOf(chosen)];
    const selected = inputs
      .filter((item) => item.checked && !item.disabled)
      .map((item) => item.value);
    const extras = data.addons
      .filter((item) => selected.includes(item.code))
      .reduce((total, item) => total + item.price, 0);
    const prefix = selected.includes("api") ? "From " : "";
    const rows = [
      ["Termly subscription", money(subscription)],
      ["Add-on charges / term", prefix + money(extras)],
      ["Once-off setup", money(band.setup)],
      ["First-term total", prefix + money(subscription + extras + band.setup)],
      [
        "Annual recurring · 3 terms",
        prefix + money(3 * (subscription + extras)),
      ],
    ];
    output.replaceChildren();
    const title = document.createElement("h3");
    title.textContent = "Your estimate";
    output.append(title);
    const list = document.createElement("dl");
    rows.forEach(([label, value]) => {
      const row = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = value;
      row.append(dt, dd);
      list.append(row);
    });
    output.append(list);
  }
  enrolment.addEventListener("input", update);
  plan.addEventListener("change", update);
  document
    .querySelectorAll('input[name="addon"]')
    .forEach((input) => input.addEventListener("change", update));
  update();
})();
