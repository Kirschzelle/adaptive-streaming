async function init() {
    const video = document.getElementById('video');
    const ui = video['ui'];
    const controls = ui.getControls();
    const player = controls.getPlayer();
    const manifestUri = video.dataset.mpd;

    window.player = player;
    window.ui = ui;

    player.addEventListener('error', onPlayerErrorEvent);
    controls.addEventListener('error', onUIErrorEvent);

    try {
        await player.load(manifestUri);

        const params = new URLSearchParams(window.location.search);
        const shouldAutoplay = params.get("autoplay") === "1";

        if (shouldAutoplay) {
            video.muted = true;
            video.playsInline = true;

            try {
                await video.play();
                console.log("Autoplay started via ?autoplay=1");
            } catch (e) {
                console.log("Autoplay blocked:", e);
            }
        }
    } catch (error) {
        onPlayerError(error);
    }
}

function onPlayerErrorEvent(errorEvent) {
    onPlayerError(errorEvent.detail);
}

function onPlayerError(error) {
    console.error('Error code', error.code, 'object', error);
}

function onUIErrorEvent(errorEvent) {
    onPlayerError(errorEvent.detail);
}

function initFailed(errorEvent) {
    console.error('Unable to load the UI library!');
}

document.addEventListener('shaka-ui-loaded', init);
document.addEventListener('shaka-ui-load-failed', initFailed);