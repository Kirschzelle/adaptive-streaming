const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const NAV_TIMEOUT_MS = 120000;

function getArg(name, def = null) {
  const idx = process.argv.indexOf(`--${name}`);
  if (idx !== -1 && idx + 1 < process.argv.length) return process.argv[idx + 1];
  return def;
}

function mustGetArg(name) {
  const v = getArg(name, null);
  if (!v) throw new Error(`Missing required --${name} argument`);
  return v;
}

function parseCsvTrace(csvText) {
  const lines = csvText.split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("Trace CSV must have header + at least 1 row");

  const header = lines[0].split(",").map((s) => s.trim());
  const col = (name) => header.indexOf(name);

  const timeStamp = col("timestamp_s");
  const download = col("download_kbps");
  const upload = col("upload_kbps");
  const latency = col("latency_ms");

  if ([timeStamp, download, upload, latency].some((i) => i === -1)) {
    throw new Error("CSV header must include: timestamp_s,download_kbps,upload_kbps,latency_ms");
  }

  return lines
    .slice(1)
    .map((line) => {
      const p = line.split(",").map((s) => s.trim());
      return {
        timestamp_s: Number(p[timeStamp]),
        download_kbps: Number(p[download]),
        upload_kbps: Number(p[upload]),
        latency_ms: Number(p[latency]),
      };
    })
    .sort((a, b) => a.timestamp_s - b.timestamp_s);
}

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

(async () => {
  const url = mustGetArg("url");
  const tracePath = getArg("trace", "traces/lte.csv");
  const out = mustGetArg("out");
  const duration = Number(getArg("duration", "60"));

  fs.mkdirSync(path.dirname(out), { recursive: true });

  const traceText = fs.readFileSync(tracePath, "utf-8");
  const trace = parseCsvTrace(traceText);

  const browser = await puppeteer.launch({
    headless: "new",
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--autoplay-policy=no-user-gesture-required",
    ],
  });

  const page = await browser.newPage();
  const cdp = await page.target().createCDPSession();
  await cdp.send("Network.enable");

  const startedAt = Date.now();
  const applied = [];
  const first = trace[0];

  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    downloadThroughput: (first.download_kbps * 1000) / 8,
    uploadThroughput: (first.upload_kbps * 1000) / 8,
    latency: first.latency_ms,
  });
  applied.push({ wall_ms: Date.now() - startedAt, ...first });

  await page.setCacheEnabled(false);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT_MS });

  await page.waitForSelector("video", { timeout: NAV_TIMEOUT_MS });

  await page.evaluate(() => {
    const v = document.querySelector("video");
    if (v) {
      v.muted = true;
      v.autoplay = true;
      const p = v.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    }
  });

  const traceTask = (async () => {
    for (let i = 1; i < trace.length; i++) {
      const prev = trace[i - 1];
      const cur = trace[i];
      const waitMs = Math.max(0, (cur.timestamp_s - prev.timestamp_s) * 1000);
      await sleep(waitMs);

      await cdp.send("Network.emulateNetworkConditions", {
        offline: false,
        downloadThroughput: (cur.download_kbps * 1000) / 8,
        uploadThroughput: (cur.upload_kbps * 1000) / 8,
        latency: cur.latency_ms,
      });

      applied.push({ wall_ms: Date.now() - startedAt, ...cur });
      console.log(
        `Applied t=${cur.timestamp_s}s down=${cur.download_kbps}kbps up=${cur.upload_kbps}kbps rtt=${cur.latency_ms}ms`
      );
    }
  })();

  await sleep(duration * 1000);

  const shakaStats = await page.evaluate(() => {
    try {
      if (window.player && typeof window.player.getStats === "function") {
        return window.player.getStats();
      }
    } catch (_) {}
    return null;
  });

  const shakaTrackInfo = await page.evaluate(() => {
    try {
      if (!window.player) return null;

      const tracks =
        typeof window.player.getVariantTracks === "function"
          ? window.player.getVariantTracks().map((t) => ({
              id: t.id,
              bandwidth: t.bandwidth,
              width: t.width,
              height: t.height,
              frameRate: t.frameRate || null,
              codecs: t.codecs || null,
              active: t.active || false,
            }))
          : null;

      return { tracks };
    } catch (e) {
      return { error: String(e) };
    }
  });

  let derivedFromShaka = null;
  if (shakaStats && Array.isArray(shakaStats.stateHistory)) {
    const buffering = shakaStats.stateHistory.filter((x) => x.state === "buffering");
    const totalBufferingS = buffering.reduce((acc, x) => acc + (x.duration || 0), 0);

    const startupBufferingS = buffering.length > 0 ? buffering[0].duration : null;
    const stallCount = Math.max(0, buffering.length - 1);
    const stallTimeS = buffering.slice(1).reduce((acc, x) => acc + (x.duration || 0), 0);

    const switchCount = Array.isArray(shakaStats.switchHistory)
      ? Math.max(0, shakaStats.switchHistory.length - 1)
      : null;

    derivedFromShaka = {
      startupBufferingS,
      stallCount,
      stallTimeS,
      totalBufferingS,
      switchCount,
    };
  }

  await traceTask.catch(() => {});

  const result = {
    url,
    tracePath,
    startedAt,
    finishedAt: Date.now(),
    durationRequestedS: duration,
    appliedNetworkProfile: applied,

    shakaStatsSnapshot: shakaStats,
    shakaTrackInfo,
    derivedFromShaka,
  };

  fs.writeFileSync(out, JSON.stringify(result, null, 2));
  console.log("OK, wrote", out);

  await browser.close();
})().catch((err) => {
  console.error("run_trace_experiment failed:", err);
  process.exit(1);
});