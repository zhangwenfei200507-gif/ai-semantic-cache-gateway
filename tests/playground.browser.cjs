/* Run against a local gateway. LIVE_IMAGES=1 makes two billable image requests. */
const {chromium} = require("playwright");
const {execFileSync} = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

const base = process.env.GATEWAY_URL || "http://127.0.0.1:8011";
const output = path.resolve(process.env.LIVE_IMAGES === "1" ? "test-results/playground" : "test-results/playground-regression");
fs.mkdirSync(output, {recursive: true});
const python = path.resolve(".venv/Scripts/python.exe");
// Use the project's token helper; no credentials or signed tokens are written to test logs.
const token = execFileSync(python, ["-c", [
  "from app.auth.database import get_connection",
  "from app.auth.security import create_access_token",
  "with get_connection() as c: u=c.execute('SELECT id,email,is_admin FROM users WHERE is_active=1 AND is_verified=1 ORDER BY id LIMIT 1').fetchone()",
  "assert u, 'No verified local account available for testing'",
  "print(create_access_token(u['id'],u['email'],bool(u['is_admin']),expires_seconds=1800))"
].join("\n")], {encoding: "utf8"}).trim();

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || "msedge"});
  const context = await browser.newContext({viewport: {width: 1440, height: 960},
    permissions: ["clipboard-read", "clipboard-write"]});
  await context.addInitScript(value => {
    localStorage.setItem("ascg_access_token", value);
    localStorage.setItem("ascg_theme", "light");
  }, token);
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const errors = [];
  const results = [];
  page.on("pageerror", error => errors.push(error.message));
  const check = async (name, task) => {
    const start = Date.now();
    await task();
    results.push({name, status: "passed", seconds: +((Date.now() - start) / 1000).toFixed(2)});
    console.log("PASS", name, results.at(-1).seconds + "s");
  };
  try {
    await check("Authenticated page and model list", async () => {
      await page.goto(base + "/pages/playground.html");
      await page.locator("#pg-message").waitFor({timeout: 90000});
      const me = await context.request.get(base + "/api/auth/me", {headers: {Authorization: `Bearer ${token}`}});
      assert.equal(me.status(), 200);
      assert.match(await page.locator("#pg-model").innerText(), /qwen-image-3.0/);
      await page.screenshot({path: path.join(output, "desktop-empty.png")});
    });
    await check("Settings validation and persistence", async () => {
      await page.click("#chat-settings");
      await page.fill('[name="maxTokens"]', "0");
      await page.click('#chat-settings-form button[type="submit"]');
      assert.equal(await page.locator("#chat-dialog").count(), 1);
      await page.fill('[name="maxTokens"]', "256");
      await page.fill('[name="temperature"]', "0");
      await page.click('#chat-settings-form button[type="submit"]');
      await page.click("#chat-settings");
      assert.equal(await page.inputValue('[name="temperature"]'), "0");
      assert.equal(await page.inputValue('[name="maxTokens"]'), "256");
      await page.click("#close-chat-dialog");
    });
    await check("Draft survives tabs, navigation, and reload", async () => {
      await page.fill("#pg-message", "This draft must survive navigation.");
      await page.click('[data-tab="raw"]');
      await page.click('[data-tab="chat"]');
      assert.equal(await page.inputValue("#pg-message"), "This draft must survive navigation.");
      await page.goto(base + "/pages/providers.html");
      await page.goto(base + "/pages/playground.html");
      assert.equal(await page.inputValue("#pg-message"), "This draft must survive navigation.");
      await page.reload();
      assert.equal(await page.inputValue("#pg-message"), "This draft must survive navigation.");
    });
    await check("Composer and conversation fullscreen", async () => {
      for (const [button, target] of [["#expand-request", "#chat-composer"], ["#expand-response", "#chat-thread"]]) {
        await page.click(button);
        assert.match(await page.locator(target).getAttribute("class"), /chat-fullscreen/);
        await page.keyboard.press("Escape");
        assert.doesNotMatch(await page.locator(target).getAttribute("class"), /chat-fullscreen/);
      }
    });
    await check("Image Auto routing preview", async () => {
      await page.selectOption("#pg-model", "auto");
      await page.fill("#pg-message", "帮我生成一张小猫的图片");
      await page.click("#pg-preview");
      await page.waitForFunction(() => document.querySelector("#chat-preview-result")?.textContent.includes("qwen-image-3.0"), {timeout: 60000});
      await page.click("#close-chat-dialog");
    });
    if (process.env.LIVE_IMAGES === "1") {
      for (const model of ["auto", "qwen-image-3.0"]) {
        await check(`REAL image generation via ${model}`, async () => {
          await page.selectOption("#pg-model", model);
          await page.fill("#pg-message", model === "auto" ? "帮我生成一张小猫的图片，水彩画，简洁背景" : "Generate a watercolor image of a quiet mountain lake at sunrise");
          const responsePromise = page.waitForResponse(r => r.url().endsWith("/api/playground") && r.request().method() === "POST", {timeout: 245000});
          await page.click("#pg-send");
          const response = await responsePromise;
          const body = await response.json();
          assert.equal(response.status(), 200, body.detail);
          assert.equal(body.response.llm.provider, "qwen_image");
          assert.equal(body.response.llm.model, "qwen-image-3.0");
          assert.ok(body.response.llm.images.length > 0);
          await page.waitForFunction(() => {
            const images = [...document.querySelectorAll(".chat-image img")];
            return images.length > 0 && images.every(img => img.complete && img.naturalWidth > 0);
          }, null, {timeout: 60000});
          await page.screenshot({path: path.join(output, `desktop-${model}.png`)});
        });
      }
      await check("REAL text response after image conversation", async () => {
        await page.selectOption("#pg-model", "deepseek-chat");
        await page.fill("#pg-message", "Reply with exactly: gateway text works");
        const responsePromise = page.waitForResponse(r => r.url().endsWith("/api/playground"), {timeout: 120000});
        await page.click("#pg-send");
        const response = await responsePromise;
        const body = await response.json();
        assert.equal(response.status(), 200, body.detail);
        assert.equal(body.response.llm.provider, "deepseek");
        assert.match(body.response.llm.answer, /gateway text works/i);
        await page.locator(".chat-prose").last().waitFor();
      });
      await check("Copy, download, details, and restored image conversation", async () => {
        await page.locator('[data-chat-action="copy"]').last().click();
        assert.match(await page.evaluate(() => navigator.clipboard.readText()), /gateway text works/i);
        const downloadPromise = page.waitForEvent("download");
        await page.locator('[data-chat-action="download"]').last().click();
        const download = await downloadPromise;
        assert.match(download.suggestedFilename(), /^response-/);
        await page.locator(".chat-details summary").last().click();
        assert.match(await page.locator(".chat-details").last().innerText(), /deepseek/);
        await page.reload();
        await page.locator(".chat-turn").last().waitFor();
        assert.equal(await page.locator(".chat-turn").count(), 3);
        assert.equal(await page.locator(".chat-image img").count(), 2);
      });
    }
    await check("Markdown rendering and unsafe HTML rejection", async () => {
      await page.evaluate(() => {
        chat.turns.push({id: "markdown-only", question: "Formatting test", result: {
          answer: "# Heading\n\n**Bold**\n\n```python\nprint('safe')\n```\n\n<img src=x onerror=\"window.injected=true\"><script>window.injected=true</script>",
          images: [], model: "layout-fixture", provider: "test"}});
        renderChatTurns();
      });
      assert.equal(await page.locator(".chat-prose h1").last().innerText(), "Heading");
      assert.match(await page.locator(".chat-prose pre").last().innerText(), /print/);
      assert.equal(await page.locator(".chat-prose img, .chat-prose script").count(), 0);
      assert.equal(await page.evaluate(() => window.injected), undefined);
      await page.evaluate(() => { chat.turns = chat.turns.filter(t => t.id !== "markdown-only"); renderChatTurns(); });
    });
    await check("Long conversation stays inside desktop/mobile viewport", async () => {
      // Synthetic content tests layout only; it is not counted as a live API response.
      await page.evaluate(() => {
        chat.turns.push({id: "layout-only", question: "Long question ".repeat(250),
          result: {answer: "Long answer\n".repeat(500), images: [], model: "layout-fixture", provider: "test", tokens: 0}});
        renderChatTurns();
      });
      for (const size of [{width: 1440, height: 960}, {width: 390, height: 844}]) {
        await page.setViewportSize(size);
        const bounds = await page.evaluate(() => {
          const composer = document.getElementById("chat-composer").getBoundingClientRect();
          const thread = document.getElementById("chat-thread");
          return {bottom: composer.bottom, right: composer.right, scroll: thread.scrollHeight,
            height: thread.clientHeight, docHeight: document.documentElement.scrollHeight,
            docWidth: document.documentElement.scrollWidth};
        });
        assert.ok(bounds.bottom <= size.height, JSON.stringify(bounds));
        assert.ok(bounds.right <= size.width, JSON.stringify(bounds));
        assert.ok(bounds.docWidth <= size.width, JSON.stringify(bounds));
        assert.ok(bounds.docHeight <= size.height + 1, JSON.stringify(bounds));
        assert.ok(bounds.scroll > bounds.height);
        await page.screenshot({path: path.join(output, `layout-${size.width}.png`)});
      }
      await page.evaluate(() => { chat.turns = chat.turns.filter(t => t.id !== "layout-only"); renderChatTurns(); });
      await page.setViewportSize({width: 1440, height: 960});
    });
    await check("Visible upstream error and explicit retry", async () => {
      await page.route("**/api/playground", route => route.fulfill({status: 502, contentType: "application/json",
        body: JSON.stringify({detail: "Test-only upstream rejection"})}));
      await page.fill("#pg-message", "Error state test");
      await page.click("#pg-send");
      await page.locator(".chat-failure").waitFor();
      assert.match(await page.locator(".chat-failure").last().innerText(), /upstream rejection/);
      await page.locator('[data-chat-action="retry"]').last().click();
      assert.equal(await page.inputValue("#pg-message"), "Error state test");
      await page.unroute("**/api/playground");
    });
    await check("Stop waiting cancels browser request with clear status", async () => {
      await page.route("**/api/playground", async route => {
        await new Promise(resolve => setTimeout(resolve, 2000));
        await route.abort().catch(() => {});
      });
      await page.fill("#pg-message", "Cancellation test");
      await page.click("#pg-send");
      await page.click("#pg-stop");
      await page.waitForFunction(() => document.querySelector("#chat-thread").textContent.includes("Stopped waiting"));
      await page.unroute("**/api/playground");
    });
    await check("Existing generated image restored from real request history", async () => {
      const history = await context.request.get(base + "/api/history?limit=30", {headers: {Authorization: `Bearer ${token}`}});
      assert.equal(history.status(), 200);
      const records = (await history.json()).items;
      const record = records.find(item => item.provider === "qwen_image" && item.status === "success" && item.answer?.startsWith("https://"));
      assert.ok(record, "No successful image request in real history");
      await page.evaluate(record => {
        chat.turns = [{id: record.request_id, question: record.question, requestedModel: record.model,
          result: {answer: record.answer, images: record.answer.split("\n"), model: record.model,
            provider: record.provider, tokens: record.total_tokens, latency: record.latency_ms}}];
        renderChatTurns();
      }, record);
      for (const size of [{width: 1440, height: 960}, {width: 390, height: 844}]) {
        await page.setViewportSize(size);
        await page.waitForFunction(() => {
          const img = document.querySelector(".chat-image img");
          return img?.complete && img.naturalWidth > 0;
        }, null, {timeout: 60000});
        await page.screenshot({path: path.join(output, `actual-image-${size.width}.png`)});
      }
    });
    await check("New conversation and empty-submit validation", async () => {
      await page.setViewportSize({width: 1440, height: 960});
      page.once("dialog", dialog => dialog.accept());
      await page.click("#chat-new");
      assert.equal(await page.locator(".chat-turn").count(), 0);
      await page.click("#pg-send");
      assert.equal(await page.locator(".chat-turn").count(), 0);
      await page.fill("#pg-message", "Line one");
      await page.locator("#pg-message").press("Shift+Enter");
      assert.equal(await page.inputValue("#pg-message"), "Line one\n");
    });
    assert.deepEqual(errors, []);
    console.log("No uncaught browser errors.");
  } finally {
    fs.writeFileSync(path.join(output, "results.json"), JSON.stringify({results, errors}, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
