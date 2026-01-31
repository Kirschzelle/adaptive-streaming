const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const P1203_INPUT_DIR = "P1203_Inputs";
const NAV_TIMEOUT_MS = 120000;
const PLAYER_WAIT_MS = 15000;

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
  const lines = csvText.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) throw new Error("Trace CSV must have header + at least 1 row");

  const header = lines[0].split(",").map((s) => s.trim());
  const col = (name) => header.indexOf(name);

  const timeStamp = col("timestamp_s");
  const download = col("download_kbps");

  if ([timeStamp, download].some((i) => i === -1)) {
    throw new Error("CSV header must include: timestamp_s,download_kbps");
  }

  return lines
    .slice(1)
    .map((line) => {
      const p = line.split(",").map((s) => s.trim());
      return {
        timestamp_s: Number(p[timeStamp]),
        download_kbps: Number(p[download]),
      };
    })
    .sort((a, b) => a.timestamp_s - b.timestamp_s);
}

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForShakaPlayer(page, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const hasPlayer = await page.evaluate(
      () => !!(window.player && typeof window.player.getStats === "function")
    );
    if (hasPlayer) return true;
    await sleep(250);
  }
  return false;
}

function buildSegmentsFromSwitchHistory(shakaStats, shakaTrackInfo, durationS) {
  const tracks = shakaTrackInfo?.tracks || [];
  const byId = new Map(tracks.map((t) => [t.id, t]));

  const hist = shakaStats?.switchHistory || [];
  const variantSwitches = hist.filter((x) => x.type === "variant" && x.id != null);
  if (variantSwitches.length === 0) return [];

  const t0 = Number(variantSwitches[0].timestamp);
  const rel = (ts) => Math.max(0, Number(ts) - t0);

  const raw = variantSwitches
    .map((s) => ({ t: rel(s.timestamp), id: s.id }))
    .sort((a, b) => a.t - b.t);

  const sw = [];
  for (const x of raw) {
    const last = sw[sw.length - 1];
    if (last && last.id === x.id && Math.abs(last.t - x.t) < 0.05) continue;
    sw.push(x);
  }

  const segments = [];
  for (let i = 0; i < sw.length; i++) {
    const cur = sw[i];
    const nextT = i + 1 < sw.length ? sw[i + 1].t : durationS;

    const start = Math.max(0, cur.t);
    const end = Math.min(durationS, Math.max(start, nextT));
    const dur = end - start;
    if (dur < 0.05) continue;

    const tr = byId.get(cur.id);
    if (!tr) continue;

    segments.push({
      start,
      duration: dur,
      bitrate_kbps: (Number(tr.bandwidth) || 0) / 1000,
      width: Number(tr.width) || 0,
      height: Number(tr.height) || 0,
      fps: Number(tr.frameRate) || 25,
      vcodec: "h264", // Changed from vp9 to h264
      acodec: "aaclc",
      representation: tr.id,
    });
  }

  return segments;
}

function buildP1203InputFromSegments(segments, startupBufferingS, displaySize = "1920x1080", device = "pc") {
  const stalling = [];
  if (startupBufferingS && startupBufferingS > 0.05) stalling.push([0, startupBufferingS]);

  return {
    IGen: {
      device,
      displaySize,
      viewingDistance: 0,
    },
    I13: {
      streamId: 42,
      segments: segments.map((s) => ({
        codec: s.vcodec,
        start: s.start,
        duration: s.duration,
        resolution: `${s.width}x${s.height}`,
        bitrate: s.bitrate_kbps,
        fps: s.fps,
        representation: s.representation,
      })),
    },
    I11: {
      streamId: 42,
      segments: segments.map((s) => ({
        codec: s.acodec,
        start: s.start,
        duration: s.duration,
        bitrate: 128,
      })),
    },
    I23: {
      streamId: 42,
      stalling,
    },
  };
}

(async () => {
  const url = mustGetArg("url");
  const tracePath = getArg("trace", "traces/lte.csv");
  const out = mustGetArg("out");
  const duration = Number(getArg("duration", "60"));

  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.mkdirSync(P1203_INPUT_DIR, { recursive: true });

  const traceText = fs.readFileSync(tracePath, "utf-8");
  const trace = parseCsvTrace(traceText);
  if (!trace.length) throw new Error("Trace CSV has no rows");

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
    uploadThroughput: 0,
    latency: 0,
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

  const bufferSamples = [];
  const sampleIntervalMs = Number(getArg("sample-interval", "1000"));

  const samplingTask = (async () => {
    while (Date.now() - startedAt < duration * 1000) {
      const sample = await page.evaluate(() => {
        try {
          const video = document.querySelector("video");
          const sample = {
            wall_ms: null,
            currentTime: video ? video.currentTime : null,
            buffered: null,
            bufferLength: null,
            paused: video ? video.paused : null,
            readyState: video ? video.readyState : null,
          };

          if (video && video.buffered && video.buffered.length > 0) {
            const ranges = [];
            for (let i = 0; i < video.buffered.length; i++) {
              ranges.push({
                start: video.buffered.start(i),
                end: video.buffered.end(i),
              });
            }
            sample.buffered = ranges;

            const ct = video.currentTime;
            let bufferAhead = 0;
            for (const range of ranges) {
              if (range.start <= ct && range.end > ct) {
                bufferAhead = range.end - ct;
                break;
              }
            }
            sample.bufferLength = bufferAhead;
          }

          if (window.player && typeof window.player.getStats === "function") {
            const stats = window.player.getStats();
            sample.estimatedBandwidth = stats.estimatedBandwidth || null;
            sample.streamBandwidth = stats.streamBandwidth || null;
          }

          return sample;
        } catch (e) {
          return { error: String(e) };
        }
      });

      sample.wall_ms = Date.now() - startedAt;
      bufferSamples.push(sample);

      await sleep(sampleIntervalMs);
    }
  })();

  const traceTask = (async () => {
    for (let i = 1; i < trace.length; i++) {
      if (Date.now() - startedAt >= duration * 1000) break;
      const prev = trace[i - 1];
      const cur = trace[i];
      const waitMs = Math.max(0, (cur.timestamp_s - prev.timestamp_s) * 1000);
      await sleep(waitMs);

      await cdp.send("Network.emulateNetworkConditions", {
        offline: false,
        downloadThroughput: (cur.download_kbps * 1000) / 8,
        uploadThroughput: 0,
        latency: 0,
      });

      applied.push({ wall_ms: Date.now() - startedAt, ...cur });
      console.log(`Applied t=${cur.timestamp_s}s download=${cur.download_kbps}`);
    }
  })();

  await sleep(duration * 1000);
  await waitForShakaPlayer(page, PLAYER_WAIT_MS);

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
  await samplingTask.catch(() => {});

  const startupBufferingS = derivedFromShaka?.startupBufferingS || 0;
  const segments = buildSegmentsFromSwitchHistory(shakaStats, shakaTrackInfo, duration);

  const displaySize = `${shakaStats?.width || 1920}x${shakaStats?.height || 1080}`;
  const p1203Input = buildP1203InputFromSegments(segments, startupBufferingS, displaySize, "pc");

  const baseName = path.basename(out).replace(/\.json$/i, "");
  const p1203InputPath = path.join(P1203_INPUT_DIR,`${baseName}_p1203_input.json`);
  fs.writeFileSync(p1203InputPath, JSON.stringify(p1203Input, null, 2));

  const result = {
    url,
    tracePath,
    startedAt,
    finishedAt: Date.now(),
    durationRequestedS: duration,
    appliedNetworkProfile: applied,

    bufferSamples,
    sampleIntervalMs,
    shakaStatsSnapshot: shakaStats,
    shakaTrackInfo,
    derivedFromShaka,

    p1203InputPath,
    p1203Input
  };

  fs.writeFileSync(out, JSON.stringify(result, null, 2));
  console.log("OK, wrote", out);
  console.log("OK, wrote", p1203InputPath);

  await browser.close();
})().catch((err) => {
  console.error("run_trace_experiment failed:", err);
  process.exit(1);
});