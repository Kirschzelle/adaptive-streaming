const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const NAV_TIMEOUT_MS = 120000;
const ATTACH_INTERVAL_MS = 250;
const SAMPLE_INTERVAL_MS = 1000;

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

  const header = lines[0].split(",").map(s => s.trim());
  const col = (name) => header.indexOf(name);

  const timeStamp = col("timestamp_s");
  const download = col("download_kbps");
  const upload = col("upload_kbps");
  const latency = col("latency_ms");

  if ([timeStamp, download, upload, latency].some(i => i === -1)) {
    throw new Error("CSV header must include: timestamp_s,download_kbps,upload_kbps,latency_ms");
  }

  return lines.slice(1).map(line => {
    const p = line.split(",").map(s => s.trim());
    return {
      timestamp_s: Number(p[timeStamp]),
      download_kbps: Number(p[download]),
      upload_kbps: Number(p[upload]),
      latency_ms: Number(p[latency]),
    };
  }).sort((a, b) => a.timestamp_s - b.timestamp_s);
}

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

(async () => {
  const url = mustGetArg("url")
  const tracePath = getArg("trace", "traces/lte.csv");
  const out = mustGetArg("out")
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

  await page.evaluateOnNewDocument(() => {
    window.__qoe = {
      t0: performance.now(),
      events: [],
      samples: [],
      lastWaitingAt: null,
      startupAt: null,
      startedPlaying: false,
    };

    function nowS() { return (performance.now() - window.__qoe.t0) / 1000.0; }

    function attachVideo(video) {
      if (!video || video.__qoeAttached) return;
      video.__qoeAttached = true;

      const pushEvent = (type, extra = {}) => {
        window.__qoe.events.push({ t: nowS(), type, ...extra });
      };

      video.addEventListener("playing", () => {
        if (!window.__qoe.startedPlaying) {
          window.__qoe.startedPlaying = true;
          window.__qoe.startupAt = nowS();
          pushEvent("startup_playing");
        }
        pushEvent("playing");
        if (window.__qoe.lastWaitingAt !== null) {
          const stallDur = nowS() - window.__qoe.lastWaitingAt;
          pushEvent("stall_end", { stallDur });
          window.__qoe.lastWaitingAt = null;
        }
      });

      video.addEventListener("waiting", () => {
        pushEvent("waiting");
        if (window.__qoe.startedPlaying && window.__qoe.lastWaitingAt === null) {
          window.__qoe.lastWaitingAt = nowS();
          pushEvent("stall_start");
        }
      });

      video.addEventListener("stalled", () => pushEvent("stalled"));
      video.addEventListener("timeupdate", () => {
      });
    }

    setInterval(() => {
      const v = document.querySelector("video");
      if (v) attachVideo(v);
    }, ATTACH_INTERVAL_MS);

    setInterval(() => {
      const v = document.querySelector("video");
      if (!v) return;

      let bufEnd = null;
      try {
        if (v.buffered && v.buffered.length > 0) bufEnd = v.buffered.end(v.buffered.length - 1);
      } catch (_) {}

      const droppedFrames = (typeof v.getVideoPlaybackQuality === "function")
        ? v.getVideoPlaybackQuality().droppedVideoFrames
        : null;

      window.__qoe.samples.push({
        t: (performance.now() - window.__qoe.t0) / 1000.0,
        currentTime: v.currentTime,
        readyState: v.readyState,
        paused: v.paused,
        playbackRate: v.playbackRate,
        bufferEnd: bufEnd,
        bufferLevel: (bufEnd !== null) ? Math.max(0, bufEnd - v.currentTime) : null,
        droppedFrames,
      });
    }, SAMPLE_INTERVAL_MS);
  });

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
      console.log(`Applied t=${cur.timestamp_s}s down=${cur.download_kbps}kbps rtt=${cur.latency_ms}ms`);
    }
  })();

  await sleep(duration * 1000);

  const qoe = await page.evaluate(() => window.__qoe || null);

  const shakaStats = await page.evaluate(() => {
    try {
      if (window.player && typeof window.player.getStats === "function") {
        return window.player.getStats();
      }
    } catch (_) {}
    return null;
  });

  await traceTask.catch(() => {});

  const result = {
    url,
    tracePath,
    startedAt,
    finishedAt: Date.now(),
    appliedNetworkProfile: applied,
    qoeProbe: qoe,
    shakaStatsSnapshot: shakaStats,
  };

  fs.writeFileSync(out, JSON.stringify(result, null, 2));
  console.log("OK, wrote", out);

  await browser.close();
})();