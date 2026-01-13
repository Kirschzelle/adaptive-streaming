const MAX_DURATION = 600;

document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("run-emulation");

  button.addEventListener("click", async () => {
    const videoId = button.dataset.videoId;
    const csrfToken = button.dataset.csrfToken;
    const duration = Math.ceil(button.dataset.duration);
    const durationToRun = Math.min(duration, MAX_DURATION);

    try {
      const response = await fetch("/experiments/start/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({
          video_id: Number(videoId),
          trace: "lte.csv",
          duration: durationToRun,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
    } catch (err) {
      console.error("Failed to start emulation:", err);
    }
  });
});