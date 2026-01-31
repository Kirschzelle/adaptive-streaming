const redis = require("redis");
const { spawn } = require("child_process");

const REDIS_URL = process.env.REDIS_URL || "redis://redis:6379/0";
const client = redis.createClient({ url: REDIS_URL });

async function main() {
  await client.connect();
  console.log("Runner connected to Redis");

  while (true) {
    const res = await client.brPop("emulation_jobs", 0);
    const job = JSON.parse(res.element);

    const traceName = job.trace.replace(".csv", "");
    const url = `http://web:8000/detailed_view/${job.video_id}/?autoplay=1`;
    const out = `results/video_${job.video_id}_${traceName}.json`;

    console.log("Running emulation job", job.job_id);

    const proc = spawn(
      "node",
      [
        "run_trace_experiment.js",
        "--url", url,
        "--trace", `traces/${job.trace}`,
        "--out", out,
        "--duration", String(job.duration),
      ],
      { stdio: "inherit" }
    );

    await new Promise((resolve, reject) => {
      proc.on("exit", code => {
        if (code === 0) resolve();
        else reject(new Error(`Runner failed with code ${code}`));
      });
    });

    console.log("Finished job", job.job_id);
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});