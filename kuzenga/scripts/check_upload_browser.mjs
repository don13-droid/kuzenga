// Local, synthetic browser test. No application DB, cloud account or real data.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const browserPath = process.env.KUZENGA_BROWSER_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
assert.ok(existsSync(browserPath), "Set KUZENGA_BROWSER_PATH to an installed Chromium browser");
const profile = mkdtempSync(path.join(project, "../.deployment-tools/browser-"));
const javascript = readFileSync(path.join(project, "static/js/direct-uploads.js"), "utf8");
let origin, objectOrigin, failure = false, grant, savedResolve, savedBody, uploadedBytes = 0;
const collect = async (request) => {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks);
};
const listen = (server) => new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const app = http.createServer(async (request, response) => {
  if (request.url === "/uploads/grant/") {
    assert.equal(request.headers["x-csrftoken"], "test-csrf");
    grant = JSON.parse((await collect(request)).toString());
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ url: objectOrigin + "/object", ticket: "test-ticket", content_type: "application/pdf" }));
  } else if (request.url === "/save" && request.method === "POST") {
    savedBody = await collect(request);
    response.end("Saved synthetic form");
    savedResolve?.();
  } else {
    response.setHeader("Content-Type", "text/html");
    response.setHeader("Set-Cookie", "synthetic-session=browser-test; SameSite=Lax; Path=/");
    response.end(`<form action="/save" method="post" enctype="multipart/form-data">
      <input type="hidden" name="csrfmiddlewaretoken" value="test-csrf">
      <input type="file" name="file"><button name="action" value="document">Save</button></form>
      <script data-upload-grant="/uploads/grant/">${javascript}</script>`);
  }
});
const objects = http.createServer(async (request, response) => {
  response.setHeader("Access-Control-Allow-Origin", origin);
  response.setHeader("Access-Control-Allow-Methods", "PUT");
  response.setHeader("Access-Control-Allow-Headers", "content-type");
  if (request.method === "OPTIONS") return response.end();
  assert.equal(request.method, "PUT");
  assert.equal(request.headers.cookie, undefined, "App cookies must not reach object storage");
  assert.equal(request.headers.referer, undefined, "Object PUT must not disclose a referrer");
  const bytes = await collect(request);
  uploadedBytes = bytes.length;
  assert.equal(bytes.length, 5 * 1024 * 1024);
  assert.equal(createHash("sha256").update(bytes).digest("hex"), grant.sha256);
  response.statusCode = failure ? 403 : 200;
  response.end();
});
let browser, socket;
const pending = new Map();
let sequence = 0;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const until = async (fn, description) => {
  for (let attempt = 0; attempt < 100; attempt++) {
    const value = await fn();
    if (value) return value;
    await pause(100);
  }
  throw new Error("Timed out: " + description);
};
try {
  await listen(app);
  origin = `http://127.0.0.1:${app.address().port}`;
  await listen(objects);
  objectOrigin = `http://127.0.0.1:${objects.address().port}`;
  browser = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--remote-debugging-port=0", "--user-data-dir=" + profile, "about:blank"], { windowsHide: true, stdio: "ignore" });
  const debuggingPort = await until(() => {
    try { return readFileSync(path.join(profile, "DevToolsActivePort"), "utf8").split("\n")[0]; } catch { return null; }
  }, "headless browser startup");
  const tabs = await (await fetch(`http://127.0.0.1:${debuggingPort}/json/list`)).json();
  socket = new WebSocket(tabs.find((tab) => tab.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve); socket.addEventListener("error", reject); });
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      message.error ? reject(new Error(message.error.message)) : resolve(message.result);
    }
  });
  const command = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const openForm = async () => {
    await command("Page.navigate", { url: origin + "/form" });
    await until(() => evaluate("document.readyState === 'complete' && !!document.querySelector('input[type=file]')"), "form load");
  };
  const submitFile = () => evaluate(`(() => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array(5 * 1024 * 1024)], 'record.pdf', {type: 'application/pdf'}));
    const input = document.querySelector('input[type=file]');
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles: true}));
    input.form.requestSubmit(input.form.querySelector('button'));
    return true;
  })()`);
  await openForm();
  const saved = new Promise((resolve) => { savedResolve = resolve; });
  await submitFile();
  await Promise.race([saved, pause(20000).then(() => { throw new Error("Form was not saved"); })]);
  assert.equal(uploadedBytes, 5 * 1024 * 1024);
  assert.ok(savedBody.length < 10000, "Final app request must contain only small fields/tickets");
  assert.ok(savedBody.toString().includes("_direct_upload_file"));
  assert.ok(savedBody.toString().includes("document"), "Clicked submitter action must survive");
  failure = true;
  savedBody = null;
  await openForm();
  await submitFile();
  await until(() => evaluate("document.querySelector('[role=alert]')?.textContent.includes('upload failed')"), "failed PUT feedback");
  assert.equal(savedBody, null, "Failed object PUT must not submit the app form");
  assert.equal(await evaluate("document.querySelector('input[type=file]').disabled"), false);
  assert.equal(await evaluate(`(() => {
    const input = document.querySelector('input[type=file]');
    input.form.insertAdjacentHTML('beforeend', '<input type=hidden name=_direct_upload_file value=old>');
    input.dispatchEvent(new Event('change', {bubbles: true}));
    return !input.form.querySelector('[name=_direct_upload_file]');
  })()`), true, "Changing the file must remove stale upload tickets");
  console.log("Browser passed: 5 MB cross-origin PUT, small form, CSRF header, no storage cookies/referrer, failure/retry and stale-ticket handling.");
  await command("Browser.close");
} finally {
  socket?.close();
  browser?.kill();
  app.closeAllConnections(); app.close();
  objects.closeAllConnections(); objects.close();
}
