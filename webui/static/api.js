export const state = {
  tools: [],
  jobs: [],
  scene: null,
  shots: null,
  assets: null,
  plan: null,
  latestScript: null,
  latestDirector: null,
  build: null,
  film: null,
  previews: [],
  characterViews: [],
  character: null,
  renderOptions: null,
  reviewFrame: null,
  reviewVideo: null,
  gallery: [],
};
const waiters = new Map();
export async function request(path, options = {}) {
  const r = await fetch(path, options);
  if (!r.ok) {
    let detail;
    try {
      detail = (await r.json()).error;
    } catch {
      detail = r.statusText;
    }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}
export async function run(tool, arguments_ = {}, options = {}) {
  const { job_id } = await request("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tool,
      arguments: arguments_,
      confirm_external: options.confirmExternal === true,
    }),
  });
  return new Promise((resolve, reject) => {
    waiters.set(job_id, { resolve, reject, onUpdate: options.onUpdate });
    document.dispatchEvent(
      new CustomEvent("job-submitted", { detail: { id: job_id, tool } }),
    );
    poll();
  });
}
export function data(result) {
  return result.data;
}
let polling = false;
export async function poll() {
  if (polling) return;
  polling = true;
  try {
    const response = await request("/api/jobs");
    const previous = new Map(state.jobs.map((job) => [job.id, job.status]));
    state.jobs = response.jobs;
    for (const job of [...state.jobs].reverse()) {
      if (job.status === "completed" && job.result) remember(job);
      if (
        (previous.has(job.id) || waiters.has(job.id)) &&
        previous.get(job.id) !== job.status &&
        ["completed", "failed", "cancelled"].includes(job.status)
      ) {
        document.dispatchEvent(
          new CustomEvent("job-finished", { detail: job }),
        );
      }
    }
    document.dispatchEvent(
      new CustomEvent("jobs-updated", { detail: response }),
    );
    for (const job of state.jobs) {
      const waiter = waiters.get(job.id);
      if (!waiter) continue;
      waiter.onUpdate?.(job);
      if (["completed", "failed", "cancelled"].includes(job.status)) {
        waiters.delete(job.id);
        if (job.status === "completed") waiter.resolve(job.result);
        else waiter.reject(new Error(job.error || "Pekerjaan dibatalkan"));
      }
    }
  } catch (error) {
    document.dispatchEvent(
      new CustomEvent("connection-error", { detail: error }),
    );
  } finally {
    polling = false;
  }
}
export const startPolling = () => {
  poll();
  return setInterval(poll, 1200);
};
const remembered = new Set();
function remember(job) {
  if (remembered.has(job.id)) return;
  remembered.add(job.id);
  const value = job.result.data;
  if (["new_scene", "open_project", "open_film_scene"].includes(job.tool)) {
    state.film = null;
    state.build = null;
    state.plan = null;
    state.latestScript = null;
    state.previews = [];
    state.characterViews = [];
    state.scene = null;
    state.shots = null;
    state.character = null;
  }
  if (job.tool === "scene_info") state.scene = value;
  if (job.tool === "list_shots") state.shots = value;
  if (job.tool === "direct_scene") state.latestDirector = value;
  if (job.tool === "mpfb_assets") state.assets = value;
  if (["script_to_scene", "script_to_film"].includes(job.tool)) {
    const built = value.kind === "film" ? value.built : !!Object.keys(value.characters || {}).length;
    if (value.kind === "film" && built) state.film = value.film;
    state.latestScript = { data: value, built };
    if (built) state.build = value;
    else state.plan = value;
  }
  if (["render_frames", "render_preview"].includes(job.tool))
    state.previews = job.result.images;
  if (job.tool === "render_views") state.characterViews = job.result.images;
  if (["create_realistic_human", "create_human"].includes(job.tool))
    state.character = value;
}
export async function scene(force = false) {
  if (force || !state.scene) state.scene = data(await run("scene_info"));
  return state.scene;
}
export async function upload(file, kind) {
  return request(`/api/upload?kind=${kind}`, {
    method: "POST",
    headers: {
      "X-Filename": encodeURIComponent(file.name),
      "Content-Type": "application/octet-stream",
    },
    body: file,
  });
}
