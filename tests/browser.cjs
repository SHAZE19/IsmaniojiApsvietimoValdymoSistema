const { chromium } = require("playwright");
const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const assert = require("assert/strict");
const root = path.resolve(__dirname, "..");
const data = fs.mkdtempSync(path.join(require("os").tmpdir(), "sviesa-ui-"));
const key = "ui-test-device-key-" + "b".repeat(32);
async function run() {
  const port = await new Promise((resolve) => {
    const listener = require("net").createServer();
    listener.listen(0, "127.0.0.1", () => {
      const p = listener.address().port;
      listener.close(() => resolve(p));
    });
  });
  const child = spawn(
    path.join(root, ".venv/Scripts/python.exe"),
    ["-m", "uvicorn", "backend.main:app", "--port", String(port)],
    {
      cwd: root,
      env: {
        ...process.env,
        LIGHTING_DATA_DIR: data,
        LIGHTING_ADMIN_PASSWORD: "Browser-test-password-2026",
        LIGHTING_DEVICE_KEY: key,
      },
      stdio: "ignore",
    },
  );
  let browser;
  try {
    for (let i = 0; i < 100; i++) {
      try {
        const r = await fetch(`http://127.0.0.1:${port}/`);
        if (r.ok) break;
      } catch {}
      await new Promise((r) => setTimeout(r, 100));
    }
    browser = await chromium.launch({
      executablePath:
        process.env.BROWSER_PATH ||
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
      headless: true,
    });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${port}/`);
    await page.locator("[name=username]").first().fill("admin");
    await page
      .locator("[name=password]")
      .first()
      .fill("Browser-test-password-2026");
    await page.locator("#login-form button").click();
    await page.locator("#app-view").waitFor({ state: "visible" });
    await page.locator("[data-mode=on]").click();
    await page.locator("#brightness").fill("65");
    await page.locator("#apply-lighting").click();
    await page.waitForFunction(
      () => document.querySelector("#desired-brightness").textContent === "65",
    );
    await page.locator(".sidebar [data-view=users]").click();
    await page.locator("#user-form [name=username]").fill("testuser");
    await page
      .locator("#user-form [name=display_name]")
      .fill("Testinis vartotojas");
    await page
      .locator("#user-form [name=password]")
      .fill("User-browser-password-2026");
    await page.locator("#user-form button").click();
    await page
      .locator("#users-body")
      .getByText("testuser", { exact: true })
      .waitFor();
    await page.locator(".sidebar [data-view=cards]").click();
    await page.locator("#card-form [name=card_id]").fill("A1B2C3D4");
    await page
      .locator("#card-form [name=label]")
      .fill("<img src=x onerror=alert(1)>");
    await page
      .locator("#card-owner")
      .selectOption({ label: "Testinis vartotojas" });
    await page.locator("#card-form button").click();
    await page.locator("#cards-body code").waitFor();
    assert.equal(await page.locator("#cards-body img").count(), 0);
    const grant = await page.request.post(
      `http://127.0.0.1:${port}/api/nfc/authorize`,
      { headers: { "X-Device-Key": key }, data: { card_id: "A1B2C3D4" } },
    );
    assert.equal((await grant.json()).authorized, true);
    await page.locator("[data-card-toggle]").click();
    await page
      .locator("#cards-body")
      .getByText("Užblokuota", { exact: true })
      .waitFor();
    const deny = await page.request.post(
      `http://127.0.0.1:${port}/api/nfc/authorize`,
      { headers: { "X-Device-Key": key }, data: { card_id: "A1B2C3D4" } },
    );
    assert.equal((await deny.json()).authorized, false);
    await page.locator(".sidebar [data-view=events]").click();
    assert.equal(
      await page.locator("#event-filter option[value=nfc_granted]").count(),
      1,
    );
    await page.locator("#event-filter").selectOption("nfc_denied");
    await page
      .locator("#events-body")
      .getByText("Prieiga atmesta", { exact: true })
      .waitFor();
    await page.locator(".sidebar [data-view=settings]").click();
    await page.locator("[name=dim_after_seconds]").fill("15");
    await page.locator("[name=off_after_seconds]").fill("45");
    await page.locator("#settings-form button").click();
    await page.locator("#logout").click();
    await page.locator("#login-form [name=username]").fill("testuser");
    await page
      .locator("#login-form [name=password]")
      .fill("User-browser-password-2026");
    await page.locator("#login-form button").click();
    await page.locator("#app-view").waitFor({ state: "visible" });
    assert.equal(await page.locator(".sidebar .admin-only:visible").count(), 0);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.locator("#mobile-logout").click();
    await page.locator("#login-view").waitFor({ state: "visible" });
    assert.deepEqual(errors, []);
    console.log(
      "Browser checks passed: login, controls, users, cards, XSS escaping, NFC/blocking, events, settings, roles, mobile, logout.",
    );
  } finally {
    if (browser) await browser.close();
    try {
      execFileSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
    } catch {}
  }
}
run().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
