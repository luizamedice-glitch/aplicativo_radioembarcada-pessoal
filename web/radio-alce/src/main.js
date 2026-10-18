import './style.css';
import { waveform } from './waveform.js';
// Parallel HLS test stream. Keep the original Icecast relay available for rollback.
const HLS_URL = 'https://pub-5f56eb102f284301a06abb9ec674001d.r2.dev/alce-test/live.m3u8';
const audio = document.querySelector('audio');
const radio = document.querySelector('.radio');
const button = document.querySelector('.play-pause');
const badge = document.querySelector('.live-badge');
const status = document.querySelector('#status');
const wave = waveform(document.querySelector('canvas'));
let requested = false, playing = false, attempt = 0, generation = 0, retryTimer, watchdog, loadingTimer;
let hls;
const loading = document.querySelector('.loading-program');
const loadingSeconds = document.querySelector('.loading-seconds');
function render() {
  radio.classList.toggle('is-requested', requested); radio.classList.toggle('is-playing', playing); radio.classList.toggle('is-loading', requested && !playing);
  button.setAttribute('aria-label', requested ? 'Pausar rádio' : 'Reproduzir rádio');
  button.setAttribute('aria-pressed', String(requested));
  button.setAttribute('aria-busy', String(requested && !playing));
  const label = playing ? 'Rádio em reprodução' : requested ? 'Conectando à rádio' : 'Rádio em espera';
  badge.setAttribute('aria-label', label); status.textContent = label; wave.setActive(playing);
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
}
function stopLoadingTimer() { clearInterval(loadingTimer); loadingTimer = undefined; loadingSeconds.textContent = '0'; }
function startLoadingTimer() {
  stopLoadingTimer();
  let seconds = 0; loadingSeconds.textContent = String(seconds);
  loadingTimer = setInterval(() => { loadingSeconds.textContent = String(++seconds); }, 1000);
}
function pause() {
  requested = false; playing = false; generation++; attempt = 0; stopLoadingTimer();
  clearTimeout(retryTimer); retryTimer = undefined; clearTimeout(watchdog);
  if (hls) { hls.destroy(); hls = undefined; }
  audio.pause(); audio.removeAttribute('src'); audio.load(); render();
}
function retry() {
  if (!requested || retryTimer) return;
  playing = false; render(); clearTimeout(watchdog);
  retryTimer = setTimeout(() => { retryTimer = undefined; connect(); }, Math.min(1000 * 2 ** attempt++, 30000));
}
function armWatchdog() { clearTimeout(watchdog); if (requested) watchdog = setTimeout(retry, 20000); }
function connect() {
  if (!requested) return;
  const current = ++generation;
  if (hls) { hls.destroy(); hls = undefined; }
  audio.pause();
  audio.removeAttribute('src');
  audio.load();
  armWatchdog();
  function playWhenReady() {
    if (current !== generation || !requested) return;
    audio.play().catch(error => {
      if (current !== generation || !requested) return;
      if (error.name === 'NotAllowedError') pause();
      else if (error.name !== 'AbortError') retry();
    });
  }
  // On Chrome/Android, hls.js supplies MediaSource playback for the HLS playlist.
  // Safari and other browsers with native HLS support remain compatible.
  if (window.Hls?.isSupported()) {
    const player = new window.Hls({
      enableWorker: false,
      lowLatencyMode: false,
      liveSyncDurationCount: 3,
      backBufferLength: 30,
      maxBufferLength: 30,
    });
    hls = player;
    player.on(window.Hls.Events.MANIFEST_PARSED, playWhenReady);
    player.on(window.Hls.Events.ERROR, (_, data) => {
      if (!requested || current !== generation || !data.fatal) return;
      if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR) {
        try { player.recoverMediaError(); armWatchdog(); } catch { retry(); }
      } else retry();
    });
    player.loadSource(HLS_URL);
    player.attachMedia(audio);
  } else if (audio.canPlayType('application/vnd.apple.mpegurl')) {
    audio.src = HLS_URL;
    audio.load();
    playWhenReady();
  } else retry();
}
function play() { if (requested) return; requested = true; startLoadingTimer(); render(); connect(); }
button.addEventListener('click', () => requested ? pause() : play());
audio.addEventListener('playing', () => { if (!requested) return; playing = true; attempt = 0; stopLoadingTimer(); clearTimeout(retryTimer); retryTimer = undefined; clearTimeout(watchdog); render(); });
audio.addEventListener('waiting', () => { playing = false; render(); armWatchdog(); });
audio.addEventListener('stalled', armWatchdog);
audio.addEventListener('error', retry); audio.addEventListener('ended', retry);
audio.addEventListener('pause', () => { playing = false; render(); });
window.addEventListener('online', () => { if (requested && !playing) { clearTimeout(retryTimer); retryTimer = undefined; connect(); } });
function recoverIfRequested() {
  if (!requested || playing) return;
  clearTimeout(retryTimer); retryTimer = undefined;
  connect();
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) recoverIfRequested();
});
window.addEventListener('pageshow', recoverIfRequested);
window.addEventListener('focus', recoverIfRequested);
for (const [id, change] of [['volume-down', -.1], ['volume-up', .1]]) document.getElementById(id).addEventListener('click', () => {
  // iOS may reserve output volume for the hardware buttons; do not route audio through WebAudio.
  audio.volume = Math.min(1, Math.max(0, Math.round((audio.volume + change) * 10) / 10));
});
if ('mediaSession' in navigator) {
  navigator.mediaSession.metadata = new MediaMetadata({ title: 'Rádio Alce', artist: 'AO VIVO', album: 'Sua Rádio em Movimento', artwork: [{ src: '/radio-alce-media.png', type: 'image/png' }] });
  for (const [action, handler] of Object.entries({ play, pause, stop: pause, nexttrack: null, previoustrack: null, seekto: null, seekforward: null, seekbackward: null })) {
    try { navigator.mediaSession.setActionHandler(action, handler); } catch { /* Unsupported browser action. */ }
  }
}
render();
