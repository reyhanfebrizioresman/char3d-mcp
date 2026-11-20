/* Run against an isolated char3d Web UI, with installed MPFB, VRM and local face models.
 * CHAR3D_TEST_VRM and CHAR3D_TEST_PHOTO are an authorized VRM and a frontal image.
 * Optional CHAR3D_TEST_SSH_TARGET enables an actual, owner-controlled SSH render.
 * The paid quote workflow always uses mocked responses and never rents a GPU.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright-core");

const base = process.env.CHAR3D_UI_URL || "http://127.0.0.1:8781";
const vrm = process.env.CHAR3D_TEST_VRM;
const photo = process.env.CHAR3D_TEST_PHOTO;
const sshTarget = process.env.CHAR3D_TEST_SSH_TARGET || "local";
const out = "output/webui_production";

async function jobResult(request, id) {
  const deadline = Date.now() + 360_000;
  while (Date.now() < deadline) {
    const job = await (await request.get(`${base}/api/jobs/${id}`)).json();
    if (job.status === "completed") return job.result;
    assert(!["failed", "cancelled"].includes(job.status), job.error || job.status);
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  throw new Error(`Job ${id} timed out`);
}

async function waitForSubmit(page, tool, click, complete = true) {
  const sent = page.waitForResponse(response => response.url() === base + "/api/run"
    && response.request().method() === "POST" && response.request().postDataJSON().tool === tool);
  await click();
  const response = await sent;
  const args = response.request().postDataJSON().arguments;
  assert.equal(response.status(), 202);
  if (!complete) return args;
  return { args, ...(await jobResult(page.request, (await response.json()).job_id)) };
}

async function tool(request, name, args = {}) {
  const response = await request.post(base + "/api/run", { data: { tool: name, arguments: args } });
  assert.equal(response.status(), 202);
  return jobResult(request, (await response.json()).job_id);
}

async function navigate(page, hash, ready) {
  await page.evaluate(value => { location.hash = value; }, hash);
  await page.waitForSelector(ready);
}

async function chooseResolution(page) {
  await page.locator("input[name=resolution][value='480p']").check();
}

async function paidQuoteCheck(browser) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const fakeJobs = [];
  const attempts = [];
  await context.route("**/api/run", async route => {
    const body = route.request().postDataJSON();
    if (body.arguments?.target !== "qa-paid") return route.continue();
    const id = `paid-qa-${fakeJobs.length}`;
    let data;
    if (body.tool === "render_options") {
      data = { options: [{ resolution: "480p", size: "854x480", total_s: 20, estimated_cost_usd: .06 }],
        duration_s: 1, frames: [1, 24] };
    } else {
      assert.equal(body.tool, "render_video");
      attempts.push(body.arguments);
      data = body.arguments.confirm_cost ? { status: "done" } : {
        status: "quote_required", target: "qa-paid", gpu_type: "Test GPU", quote_id: id,
        estimated_total_usd: .08, estimated_runtime_s: 20, hourly_price_usd: .8,
        max_hours: 1, max_budget_usd: 2, billing_note: "Test estimate",
      };
    }
    fakeJobs.unshift({ id, tool: body.tool, status: "completed", result: { data, files: [], images: [] } });
    return route.fulfill({ status: 202, json: { job_id: id } });
  });
  await context.route("**/api/jobs", async route => {
    const response = await route.fetch();
    const result = await response.json();
    for (const job of result.jobs) {
      if (job.tool === "remote_targets" && job.result?.data)
        job.result.data.targets.push({ name: "qa-paid", kind: "runpod" });
    }
    result.jobs.unshift(...fakeJobs);
    return route.fulfill({ response, json: result });
  });
  try {
    await page.goto(base + "/#render");
    await page.locator("#video-target").selectOption("qa-paid");
    await chooseResolution(page);
    await page.locator("#start-render").click();
    await page.getByRole("dialog").getByText("Kirim snapshot ke qa-paid?").waitFor();
    await page.locator("#confirm-no").click();
    assert.equal(attempts.length, 0);
    const previousVideo = await page.$eval("#render-player", el => el.querySelector("video")?.getAttribute("src") ?? null);
    for (const acceptCost of [false, true]) {
      await page.locator("#start-render").click();
      await page.getByRole("dialog").getByText("Kirim snapshot ke qa-paid?").waitFor();
      await page.locator("#confirm-yes").click();
      await page.getByRole("dialog").getByText("Konfirmasi biaya render").waitFor();
      assert.match(await page.getByRole("dialog").innerText(), /\$0\.0800/);
      assert.equal(attempts.at(-1).confirm_cost, undefined);
      if (!acceptCost) {
        await page.locator("#confirm-no").click();
        assert.equal(attempts.length, 1);
        assert.equal(await page.$eval("#render-player", el => el.querySelector("video")?.getAttribute("src") ?? null),
          previousVideo);
      } else {
        const submitted = await waitForSubmit(page, "render_video", () => page.locator("#confirm-yes").click(), false);
        assert.equal(submitted.confirm_cost, true);
        assert.equal(attempts.length, 3);
        const { quote_id, confirm_cost, ...confirmed } = submitted;
        assert.ok(quote_id);
        assert.deepEqual(confirmed, attempts[1]);
        assert.equal(confirmed.consent_upload, true);
      }
    }
    console.log("PASS render GPU: consent, cancel, quote and exact confirmed payload");
  } finally {
    await context.close();
  }
}

(async () => {
  assert(vrm && fs.existsSync(vrm), "CHAR3D_TEST_VRM is required");
  assert(photo && fs.existsSync(photo), "CHAR3D_TEST_PHOTO is required");
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium", headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--enable-unsafe-swiftshader"],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 950 }, colorScheme: "dark", reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const external = [];
  await context.route("**/*", route => {
    const url = route.request().url();
    if (url.startsWith(base + "/") || /^(data|blob):/.test(url)) return route.continue();
    external.push(url);
    return route.abort();
  });
  try {
    await tool(context.request, "new_scene", { frame_end: 12 });
    await page.goto(base + "/#naskah");
    assert.equal(await page.locator("#script-camera").inputValue(), "directed");
    await page.locator("#script-text").fill(`JUDUL: Uji kamera
ANA (perempuan, 28, anime, rambut bob): Aku marah sekali! Kamu menyembunyikan kabar itu dariku. Mengapa?
BUDI (laki-laki, 30, kartun): Aku takut membuatmu kecewa. Maaf, seharusnya aku bicara sejak kemarin.
ANA: Kita harus saling percaya. Aku kesal, tetapi sekarang aku mau mendengar.
BUDI: Terima kasih sudah mendengar. Kita akan menyelesaikan ini bersama.`);
    await page.locator("#tts-engine").selectOption("none");
    await page.locator("#script-sound").uncheck();
    const plan = await waitForSubmit(page, "script_to_scene", () => page.locator("#plan").click());
    assert.equal(plan.args.camera, "directed");
    assert.equal(plan.data.plan.characters[0].style, "anime");
    const built = await waitForSubmit(page, "script_to_scene", () => page.locator("#build").click());
    const roles = built.data.shots.map(shot => shot.reason?.role);
    assert(roles.includes("OTS") && roles.includes("reaction"), roles.join(","));
    assert(built.data.reactions.length);
    await navigate(page, "adegan", "#shot-list .shot-block");
    await page.getByRole("button", { name: /Reaksi pendengar/ }).first().waitFor();
    await page.getByRole("button", { name: /Dari balik bahu/ }).first().click();
    assert(Number(await page.locator("#preview-frames").inputValue()) > 0);
    await page.getByText("Tambah shot dari balik bahu (OTS)").click();
    await page.locator("#ots-start").fill("10");
    await page.locator("#ots-end").fill("16");
    const ots = await waitForSubmit(page, "camera_shot", () => page.getByRole("button", { name: "Tambah shot", exact: true }).click());
    assert.equal(ots.args.shot, "over_shoulder");
    assert.notEqual(ots.args.subject[0], ots.args.foreground);
    await page.locator("#ots-result").getByText(ots.data.camera, { exact: false }).waitFor();
    console.log("PASS kamera: naskah bergaya, OTS, reaksi pendengar, timeline dan OTS manual");

    await page.locator("#collision-start").fill("10");
    await page.locator("#collision-end").fill("16");
    await page.locator("#collision-part").selectOption("arms");
    const scan = await waitForSubmit(page, "resolve_collisions", () => page.locator("#collision-check").click());
    assert.equal(scan.args.report_only, true);
    assert.deepEqual(scan.data.frames, [10, 16]);
    assert.equal(scan.data.frames_corrected, 0);
    await page.locator("#collision-repair").click();
    await page.getByRole("dialog").getByText("Terapkan koreksi collision?").waitFor();
    const repair = await waitForSubmit(page, "resolve_collisions", () => page.locator("#confirm-yes").click());
    assert.equal(repair.args.report_only, false);
    assert.equal(repair.args.parts, "arms");
    await page.locator("#collision-result").getByText(/frame dikoreksi/).waitFor();
    console.log("PASS collision: ukur tanpa keyframe, konfirmasi dan tampilkan hasil koreksi");

    await navigate(page, "review", "#review-form");
    const review = await waitForSubmit(page, "review_scene", () => page.getByRole("button", { name: "Jalankan Review" }).click());
    assert.equal(review.args.fix, false);
    assert(Number.isFinite(review.data.score));
    assert(await page.locator(".review-sheet img").count() || review.data.contact_sheet);
    await page.waitForFunction(() => document.querySelector(".review-sheet img")?.naturalWidth > 0);
    const href = await page.getByRole("link", { name: "Unduh laporan" }).getAttribute("href");
    const attachment = await context.request.get(base + href);
    assert(attachment.ok() && attachment.headers()["content-disposition"].startsWith("attachment;"));
    await page.screenshot({ path: out + "/review-desktop.png" });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: out + "/review-mobile.png" });
    await page.setViewportSize({ width: 1440, height: 950 });
    if (await page.locator("[data-review-frame]").count()) {
      const jump = page.locator("[data-review-frame]").first();
      const first = await jump.getAttribute("data-review-frame");
      await jump.click();
      await page.waitForSelector("#preview-frames");
      assert.equal(await page.locator("#preview-frames").inputValue(), first);
    }
    console.log("PASS Review adegan: skor, cuplikan, laporan dan layout 390 px");

    await navigate(page, "karakter", "#photo-form");
    await page.locator("#char-style").selectOption("chibi");
    await page.locator("#char-name").fill("UjiChibi");
    const chibi = await waitForSubmit(page, "create_realistic_human", () => page.getByRole("button", { name: "Buat karakter" }).click());
    assert.equal(chibi.args.style, "chibi");
    await page.waitForFunction(() => !document.querySelector('#character-form button[type=submit]').disabled, null, { timeout: 240_000 });
    const photoCharacter = await page.locator("#photo-character option").filter({ hasText: /UjiChibi/ }).first().getAttribute("value");
    await page.locator("#photo-character").selectOption(photoCharacter);
    await page.locator("#photo-file").setInputFiles(photo);
    await page.getByRole("button", { name: "Terapkan wajah" }).click();
    assert.equal(await page.locator("#photo-consent").evaluate(el => el.validity.valueMissing), true);
    await page.locator("#photo-consent").check();
    const fitted = await waitForSubmit(page, "face_from_photo", () => page.getByRole("button", { name: "Terapkan wajah" }).click());
    assert.equal(fitted.args.consent, true);
    assert(fitted.data.local_only && Number.isFinite(fitted.data.fit_error_px));
    await page.getByText("Wajah diterapkan ke", { exact: false }).waitFor();
    await page.waitForFunction(() => !document.querySelector('#photo-form button[type=submit]').disabled);
    assert.equal(await page.locator("#photo-result .error").count(), 0);
    await page.locator("#vrm-file").setInputFiles(vrm);
    const model = await waitForSubmit(page, "import_model", () => page.getByRole("button", { name: "Impor VRM" }).click());
    assert(model.args.path.endsWith(".vrm") && model.data.vrm.length === 1);
    assert(Object.keys(model.data.vrm[0].mapped_bones).length >= 15);
    await page.getByText("tulang terpetakan", { exact: false }).waitFor();
    await page.waitForFunction(() => !document.querySelector('#vrm-form button[type=submit]').disabled);
    assert.equal(await page.locator("#vrm-result .error").count(), 0);
    assert.equal(await page.locator("#character-views .filmstrip img").count(), 4);
    console.log(`PASS karakter: chibi, fit lokal ${fitted.data.fit_error_px}px, VRM ${model.data.vrm[0].version}`);

    await tool(context.request, "new_scene", { frame_end: 12 });
    await tool(context.request, "add_primitive", { kind: "cube", name: "RenderQA", location: [0, 0, .5] });
    await tool(context.request, "camera_shot", { subject: ["RenderQA"], shot: "full", start_frame: 1, end_frame: 12 });
    await navigate(page, "render", "#video-target");
    if (sshTarget !== "local") await page.locator("#video-target").selectOption(sshTarget);
    await page.locator("#video-name").fill("webui-target-qa.mp4");
    await chooseResolution(page);
    const rendered = await waitForSubmit(page, "render_video", async () => {
      await page.locator("#start-render").click();
      if (sshTarget !== "local") {
        await page.getByRole("dialog").getByText(`Kirim snapshot ke ${sshTarget}?`).waitFor();
        await page.locator("#confirm-yes").click();
      }
    });
    assert.equal(rendered.args.target, sshTarget);
    assert.equal(rendered.data.status, "done");
    if (sshTarget !== "local") assert(rendered.data.verified && rendered.args.consent_upload);
    const movie = rendered.files.find(url => url.endsWith("/webui-target-qa.mp4"));
    assert(movie && (await context.request.get(base + movie)).ok());
    await page.waitForFunction(url => document.querySelector("#render-player video")?.getAttribute("src") === url, movie);
    await page.locator("#render-review").click();
    await page.waitForFunction(() => document.querySelector("#review-video")?.value === "webui-target-qa.mp4");
    const mediaReview = await waitForSubmit(page, "review_video", () => page.getByRole("button", { name: "Jalankan Review" }).click());
    assert.equal(mediaReview.data.frames, 12);
    assert.equal(await page.locator("#review-fix").isVisible(), false);
    console.log(`PASS render ${sshTarget}: MP4 12 frame dan Review video dari layar Render`);

    const film = await tool(context.request, "script_to_film", {
      script: "JUDUL: Web UI Review QA\nANA (perempuan, 28)\nADEGAN 1: Sapa\nANA: Halo.\nADEGAN 2: Pamit\nANA: Sampai jumpa.",
      camera: "directed", voice: false, sound: false, subtitles: false,
      body_language: false, music: null,
    });
    await navigate(page, "adegan", "#preview-form");
    await navigate(page, "review", "#review-form");
    await page.locator("#review-scope").selectOption("film");
    const filmReview = await waitForSubmit(page, "review_film", () => page.getByRole("button", { name: "Jalankan Review" }).click());
    assert.equal(filmReview.args.name, film.data.film.name);
    assert.equal(filmReview.data.scenes.length, 2);
    await page.getByText("Skor per adegan").waitFor();
    await page.locator("#review-fix").click();
    assert.match(await page.getByRole("dialog").innerText(), /disimpan ke file adegan film/);
    await page.locator("#confirm-no").click();
    await page.locator("#review-sheet").uncheck();
    await page.locator("#review-fix").click();
    const corrected = await waitForSubmit(page, "review_film", () => page.locator("#confirm-yes").click());
    assert.equal(corrected.args.fix, true);
    assert.equal(corrected.data.fix_rounds, 1);
    await page.getByText("Koreksi diterapkan", { exact: false }).waitFor();
    console.log("PASS Review film: dua adegan tersimpan, konfirmasi dan satu putaran koreksi");

    await tool(context.request, "new_scene", { frame_end: 12 });
    await paidQuoteCheck(browser);
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    console.log("WEBUI PRODUCTION OK");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
