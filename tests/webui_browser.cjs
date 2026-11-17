/* Development-only browser QA. No Node dependency is used by the application.
 * PLAYWRIGHT_MODULE=/path/to/playwright-core [AXE_MODULE=/path/to/@axe-core/playwright]
 * node tests/webui_browser.cjs
 * Requires the completed tests/webui_e2e.py artifacts in the running UI.
 */
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright-core",
);
const Axe = process.env.AXE_MODULE
  ? require(process.env.AXE_MODULE).default
  : null;
const base = process.env.CHAR3D_UI_URL || "http://127.0.0.1:8781";
const output = path.resolve("output/webui_screens");

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--enable-unsafe-swiftshader",
    ],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "dark",
  });
  const page = await context.newPage();
  const errors = [],
    external = [],
    violations = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await context.route("**/*", (route) => {
    const url = route.request().url();
    if (
      !url.startsWith(base) &&
      !url.startsWith("data:") &&
      !url.startsWith("blob:")
    ) {
      external.push(url);
      return route.abort();
    }
    return route.continue();
  });
  try {
    await page.goto(base);
    await page.waitForSelector("#script-text");
    const catalog = await (
      await context.request.get(base + "/api/tools")
    ).json();
    // Exercise every generated schema without invoking the tools.
    await page.evaluate(() => (location.hash = "tools"));
    await page.waitForSelector("#tool-list button");
    for (const tool of catalog.tools) {
      await page.locator(`[data-tool="${tool.name}"]`).click();
      assert.equal(
        await page.locator('#tool-form [id^="arg-"]').count(),
        Object.keys(tool.inputSchema.properties || {}).length,
        tool.name,
      );
    }
    console.log(`PASS ${catalog.tools.length} generated tool forms`);
    await page.locator('[data-tool="render_video"]').click();
    assert.equal(await page.locator("#arg-subtitles").inputValue(), "");
    await page.locator('[data-tool="script_to_scene"]').click();
    await page.locator("#arg-script").fill("ANA (perempuan, 28): Halo!");
    assert(
      await page.locator("#arg-script").evaluate((el) => el.checkValidity()),
    );
    await page.locator('[data-tool="transform_object"]').click();
    await page.locator("#arg-location").fill("[oops");
    assert(
      !(await page
        .locator("#arg-location")
        .evaluate((el) => el.checkValidity())),
    );
    await page.locator("#arg-location").fill("[0, 0, 0]");
    assert(
      await page.locator("#arg-location").evaluate((el) => el.checkValidity()),
    );
    console.log("PASS nullable booleans + text/JSON unions + JSON validation");
    const submissions = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/api/run"))
        submissions.push(request.postDataJSON().tool);
    });
    await page.locator('[data-tool="ai_text_to_video"]').click();
    await page
      .locator("#arg-prompt")
      .fill("Studio test; cancel before submission");
    await page.locator("#tool-form button[type=submit]").click();
    await page.waitForSelector("#confirm-no");
    assert.match(
      await page.locator("#modal").innerText(),
      /pihak ketiga|fal.ai/,
    );
    await page.locator("#confirm-no").click();
    assert(!submissions.includes("ai_text_to_video"));
    await page.locator('[data-tool="create_human"]').click();
    console.log(
      "PASS explicit external AI confirmation; cancellation sends no generation request",
    );

    const screens = [
      "naskah",
      "adegan",
      "karakter",
      "render",
      "galeri",
      "tools",
    ];
    for (const size of ["desktop", "mobile"]) {
      await page.setViewportSize(
        size === "desktop"
          ? { width: 1440, height: 1000 }
          : { width: 390, height: 844 },
      );
      for (const theme of ["dark", "light"]) {
        await page.evaluate((theme) => {
          localStorage.setItem("char3d-theme", theme);
          document.documentElement.dataset.theme = theme;
        }, theme);
        for (const screen of screens) {
          await page.evaluate((screen) => (location.hash = screen), screen);
          await page.waitForTimeout(500);
          await page.waitForFunction(
            () => !document.querySelector("main .skeleton"),
          );
          if (screen === "render")
            await page.locator('input[name=resolution][value="480p"]').check();
          if (screen === "tools")
            await page.locator('[data-tool="create_human"]').click();
          await page.evaluate(async () => {
            // Full-page captures need offscreen lazy images to finish decoding.
            for (const img of document.images) img.loading = "eager";
            await Promise.all(
              [...document.images].map((img) => img.decode().catch(() => {})),
            );
          });
          assert.equal(
            await page.evaluate(
              () => document.documentElement.scrollWidth > innerWidth,
            ),
            false,
            `${size}/${theme}/${screen}: horizontal overflow`,
          );
          if (Axe) {
            const result = await new Axe({ page })
              .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
              .analyze();
            for (const item of result.violations)
              violations.push({
                size,
                theme,
                screen,
                id: item.id,
                nodes: item.nodes.map((n) => ({
                  html: n.html,
                  reason: n.failureSummary,
                })),
              });
          }
          await page.screenshot({
            path: path.join(output, `${size}-${theme}-${screen}.png`),
            fullPage: true,
          });
          console.log(`SCREEN ${size}-${theme}-${screen}.png`);
        }
      }
    }
    fs.writeFileSync(
      "output/webui_accessibility.json",
      JSON.stringify(violations, null, 2),
    );
    await page.locator("#mobile-menu").click();
    assert.equal(
      await page.locator("#mobile-menu").getAttribute("aria-expanded"),
      "true",
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("#mobile-menu").getAttribute("aria-expanded"),
      "false",
    );
    console.log("PASS mobile navigation + Escape");

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.evaluate(() => {
      document.documentElement.dataset.theme = "dark";
      location.hash = "galeri";
    });
    await page.waitForSelector(".asset-card");
    await page.locator("[data-filter=model]").click();
    await page.locator('[data-file$=".glb"]').first().click();
    await page.waitForFunction(
      () =>
        document
          .querySelector(".model-message")
          ?.textContent.includes("seret untuk memutar"),
      null,
      { timeout: 60000 },
    );
    assert(await page.locator("#model-viewport canvas").count());
    await page.screenshot({
      path: path.join(output, "desktop-dark-glb-viewer.png"),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await page.locator("[data-filter=video]").click();
    await page.locator('[data-file$=".mp4"]').first().click();
    await page.waitForFunction(
      () => document.querySelector("#modal video")?.duration > 0,
    );
    console.log("PASS offline GLB viewer + MP4 playback");
    await page.keyboard.press("Escape");

    await page.evaluate(() => (location.hash = "naskah"));
    await page.waitForSelector("#script-text");
    await page
      .locator("#script-text")
      .fill(
        "JUDUL: Uji browser\nANA (perempuan, 28): Halo!\nBUDI (laki-laki, 30): Selamat pagi.",
      );
    await page.locator("#plan").click();
    await page.evaluate(() => (location.hash = "galeri"));
    await page.waitForFunction(
      async () => {
        const { jobs } = await (await fetch("/api/jobs")).json();
        return jobs.some(
          (j) =>
            j.tool === "script_to_scene" &&
            j.status === "completed" &&
            j.result?.data?.plan?.title === "Uji browser",
        );
      },
      null,
      { polling: 1000 },
    );
    await page.evaluate(() => (location.hash = "naskah"));
    await page.waitForFunction(() =>
      document
        .querySelector("#script-result")
        ?.textContent.includes("Rencana siap"),
    );
    assert.equal(await page.locator("#script-result .cast-card").count(), 2);
    console.log(
      "PASS script plan through browser controls; results survive navigation during a job",
    );
    fs.writeFileSync(
      "output/webui_accessibility.json",
      JSON.stringify(violations, null, 2),
    );
    assert.deepEqual(errors, [], "Browser JavaScript errors");
    assert.deepEqual(external, [], "Unexpected external runtime requests");
    assert.deepEqual(
      violations,
      [],
      "WCAG A/AA violations; see output/webui_accessibility.json",
    );
    console.log(
      "WEBUI BROWSER OK — 24 screen captures, no overflow, no external requests, no JS errors" +
        (Axe ? ", WCAG A/AA checks passed" : ""),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
