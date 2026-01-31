import { mkdirSync, readFileSync, writeFileSync } from "fs";
import { dirname, basename, join } from "path";
import { launch } from "puppeteer";

const P1203_INPUT_DIR = "P1203_Inputs";
const NAV_TIMEOUT_MS = 120000;
const PLAYER_WAIT_MS = 15000;
const SLEEP_DURATION = 250;
const THRESHOLD_CONSECUTIVE_SWITCHES = 0.05;
const BITS_TO_KBITS = 1 / 1000;
const KBITS_TO_BITS = 1000;
const S_TO_MS = 1000;

function getArg(name, def = null) {
  const idx = process.argv.indexOf(`--${name}`);
  if (idx !== -1 && idx + 1 < process.argv.length) return process.argv[idx + 1];
  return def;
}

function mustGetArg(name) {
  const video = getArg(name, null);
  if (!video) throw new Error(`Missing required --${name} argument`);
  return video;
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
      const play = line.split(",").map((s) => s.trim());
      return {
        timestamp_s: Number(play[timeStamp]),
        download_kbps: Number(play[download]),
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
    await sleep(SLEEP_DURATION);
  }
  return false;
}

function buildSegmentsFromSwitchHistory(shakaStats, shakaTrackInfo, durationSeconds) {
  const tracks = shakaTrackInfo?.tracks || [];
  const byId = new Map(tracks.map((t) => [t.id, t]));

  const history = shakaStats?.switchHistory || [];
  const variantSwitches = history.filter((x) => x.type === "variant" && x.id != null);
  if (variantSwitches.length === 0) return [];

  const timestamp0 = Number(variantSwitches[0].timestamp);
  const relativeToStart = (timestamp) => Math.max(0, Number(timestamp) - timestamp0);

  const rawSwitches = variantSwitches
      .map((switchEvent) => ({ 
          timestamp: relativeToStart(switchEvent.timestamp), 
          variantId: switchEvent.id 
      }))
      .sort((a, b) => a.timestamp - b.timestamp);

  const filteredSwitches = [];
  for (const currentSwitch of rawSwitches) {
      const previousSwitch = filteredSwitches[filteredSwitches.length - 1];
      if (previousSwitch && 
          previousSwitch.variantId === currentSwitch.variantId && 
          Math.abs(previousSwitch.timestamp - currentSwitch.timestamp) < THRESHOLD_CONSECUTIVE_SWITCHES) {
          continue;
      }
      filteredSwitches.push(currentSwitch);
  }

  const segments = [];
  for (let i = 0; i < filteredSwitches.length; i++) {
    const currentSwitch = filteredSwitches[i];
    const nextTimestamp = i + 1 < filteredSwitches.length ? filteredSwitches[i + 1].timestamp : durationSeconds;

    const start = Math.max(0, currentSwitch.timestamp);
    const end = Math.min(durationSeconds, Math.max(start, nextTimestamp));
    const duration = end - start;
    if (duration < 0.05) continue;

    const track = byId.get(currentSwitch.variantId);
    if (!track) continue;

    segments.push({
      start,
      duration: duration,
      bitrate_kbps: (Number(track.bandwidth) || 0) * BITS_TO_KBITS,
      width: Number(track.width) || 0,
      height: Number(track.height) || 0,
      fps: Number(track.frameRate) || 25,
      vcodec: "vp9",
      acodec: "aaclc",
      representation: track.id,
    });
  }

  return segments;
}

function buildP1203InputFromSegments(segments, startupBufferingSeconds, displaySize = "1920x1080", device = "pc") {
  const stalling = [];
  if (startupBufferingSeconds && startupBufferingSeconds > THRESHOLD_CONSECUTIVE_SWITCHES) stalling.push([0, startupBufferingSeconds]);

  return {
    IGen: {
      device,
      displaySize,
      viewingDistance: "150cm",
    },
    I11: {
      streamId: 42,
      segments: segments.map((s) => ({
        codec: s.acodec,
        start: s.start,
        duration: s.duration,
        bitrate: 128, // Note: We do currently not support varying audio streams, so we just use a default bitrate here.
      })),
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

  mkdirSync(dirname(out), { recursive: true });
  mkdirSync(P1203_INPUT_DIR, { recursive: true });

  const traceText = readFileSync(tracePath, "utf-8");
  const trace = parseCsvTrace(traceText);
  if (!trace.length) throw new Error("Trace CSV has no rows");

  const browser = await launch({
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
    downloadThroughput: (first.download_kbps * KBITS_TO_BITS) / 8,
    uploadThroughput: 0,
    latency: 0,
  });
  applied.push({ wall_ms: Date.now() - startedAt, ...first });

  await page.setCacheEnabled(false);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT_MS });

  await page.waitForSelector("video", { timeout: NAV_TIMEOUT_MS });

  await page.evaluate(() => {
    const video = document.querySelector("video");
    if (video) {
      video.muted = true;
      video.autoplay = true;
      const play = video.play();
      if (play && typeof play.catch === "function") play.catch(() => {});
    }
  });

  const bufferSamples = [];
  const sampleIntervalMs = Number(getArg("sample-interval", "1000"));

  const samplingTask = (async () => {
    while (Date.now() - startedAt < duration * S_TO_MS) {
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
    for (let trace_index = 1; trace_index < trace.length; trace_index++) {
      if (Date.now() - startedAt >= duration * KBITS_TO_BITS) break;
      const previous = trace[trace_index - 1];
      const current = trace[trace_index];
      const waitMs = Math.max(0, (current.timestamp_s - previous.timestamp_s) * KBITS_TO_BITS);
      await sleep(waitMs);

      await cdp.send("Network.emulateNetworkConditions", {
        offline: false,
        downloadThroughput: (current.download_kbps * KBITS_TO_BITS) / 8,
        uploadThroughput: 0,
        latency: 0,
      });

      applied.push({ wall_ms: Date.now() - startedAt, ...current });
      console.log(`Applied t=${current.timestamp_s}s download=${current.download_kbps}`);
    }
  })();

  await sleep(duration * S_TO_MS);
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
          ? window.player.getVariantTracks().map((track) => ({
              id: track.id,
              bandwidth: track.bandwidth,
              width: track.width,
              height: track.height,
              frameRate: track.frameRate || null,
              codecs: track.codecs || null,
              active: track.active || false,
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
    const totalBufferingSeconds = buffering.reduce((acc, x) => acc + (x.duration || 0), 0);

    const startupBufferingSeconds = buffering.length > 0 ? buffering[0].duration : null;
    const stallCount = Math.max(0, buffering.length - 1);
    const stallTimeSeconds = buffering.slice(1).reduce((acc, x) => acc + (x.duration || 0), 0);

    const switchCount = Array.isArray(shakaStats.switchHistory)
      ? Math.max(0, shakaStats.switchHistory.length - 1)
      : null;

    derivedFromShaka = {
      startupBufferingSeconds,
      stallCount,
      stallTimeSeconds,
      totalBufferingSeconds,
      switchCount,
    };
  }

  await traceTask.catch(() => {});
  await samplingTask.catch(() => {});

  const startupBufferingSeconds = derivedFromShaka?.startupBufferingSeconds || 0;
  const segments = buildSegmentsFromSwitchHistory(shakaStats, shakaTrackInfo, duration);

  const displaySize = `${shakaStats?.width || 1920}x${shakaStats?.height || 1080}`;
  const p1203Input = buildP1203InputFromSegments(segments, startupBufferingSeconds, displaySize, "pc");

  const baseName = basename(out).replace(/\.json$/i, "");
  const p1203InputPath = join(P1203_INPUT_DIR,`${baseName}_p1203_input.json`);
  writeFileSync(p1203InputPath, JSON.stringify(p1203Input, null, 2));

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

  writeFileSync(out, JSON.stringify(result, null, 2));
  console.log("OK, wrote", out);
  console.log("OK, wrote", p1203InputPath);

  await browser.close();
})().catch((err) => {
  console.error("run_trace_experiment failed:", err);
  process.exit(1);
});