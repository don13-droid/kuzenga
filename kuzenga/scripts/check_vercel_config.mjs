// Validate against Vercel's current public schema; never links or deploys a project.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const Ajv = require(path.join(project, "../.deployment-tools/schema/node_modules/ajv-draft-04"));
const addFormats = require(path.join(project, "../.deployment-tools/node/node_modules/ajv-formats"));
const configuration = JSON.parse(readFileSync(path.join(project, "vercel.json"), "utf8"));
const response = await fetch("https://openapi.vercel.sh/vercel.json", { signal: AbortSignal.timeout(20000) });
assert.ok(response.ok, "Could not fetch official Vercel configuration schema");
const schema = await response.json();
// The published schema declares draft 4 but currently contains modern numeric
// exclusive bounds in experimental triggers. Translate those bounds to their
// equivalent draft-4 representation; do not disable schema validation.
let translated = 0;
function draft4Bounds(value) {
  if (!value || typeof value !== "object") return;
  for (const [exclusive, inclusive] of [["exclusiveMinimum", "minimum"], ["exclusiveMaximum", "maximum"]]) {
    if (typeof value[exclusive] === "number") {
      assert.equal(value[inclusive], undefined, "Review combined numeric bounds in the upstream schema");
      value[inclusive] = value[exclusive];
      value[exclusive] = true;
      translated++;
    }
  }
  for (const child of Object.values(value)) draft4Bounds(child);
}
draft4Bounds(schema);
const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);
const validate = ajv.compile(schema);
assert.ok(validate(configuration), JSON.stringify(validate.errors));
assert.equal(configuration.git.deploymentEnabled, false, "Automatic deployment must remain disabled");
assert.ok(readFileSync(path.join(project, "pyproject.toml"), "utf8").includes('entrypoint = "config.wsgi:application"'));
assert.equal(readFileSync(path.join(project, ".python-version"), "utf8").trim(), "3.12");
console.log(`Vercel schema compatibility validation passed (${translated} equivalent numeric-bound translations); WSGI/Python selection and Git deployment disabled. No project linked or deployed.`);
