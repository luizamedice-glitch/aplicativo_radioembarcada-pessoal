import './style.css';
import { waveform } from './waveform.js';
const audio = document.querySelector('audio');
const radio = document.querySelector('.radio');
const button = document.querySelector('.play-pause');
const badge = document.querySelector('.live-badge');
const status = document.querySelector('#status');
const wave = waveform(document.querySelector('canvas'));
let requested = false, playing = false, attempt = 0, generation = 0, retryTimer, watchdog;
function render() {
  radio.classList.toggle('is-requested', requested); radio.classList.toggle('is-playing', playing);
  button.setAttribute('aria-label', requested ? 'Pausar rádio' : 'Reproduzir rádio');
  button.setAttribute('aria-pressed', String(requested));
  button.setAttribute('aria-busy', String(requested && !playing));
  const label = playing ? 'Rádio em reprodução' : requested ? 'Conectando à rádio' : 'Rádio em espera';
  badge.setAttribute('aria-label', label); status.textContent = label; wave.setActive(playing);
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
}
function pause() {
  requested = false; playing = false; generation++; attempt = 0;
  clearTimeout(retryTimer); retryTimer = undefined; clearTimeout(watchdog);
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
  audio.src = '/radio/stream'; audio.load(); armWatchdog();
  audio.play().catch(error => {
    if (current !== generation || !requested) return;
    if (error.name === 'NotAllowedError') pause(); else if (error.name !== 'AbortError') retry();
  });
}
function play() { if (requested) return; requested = true; render(); connect(); }
button.addEventListener('click', () => requested ? pause() : play());
audio.addEventListener('playing', () => { if (!requested) return; playing = true; attempt = 0; clearTimeout(retryTimer); retryTimer = undefined; clearTimeout(watchdog); render(); });
audio.addEventListener('waiting', () => { playing = false; render(); armWatchdog(); });
audio.addEventListener('stalled', armWatchdog);
audio.addEventListener('error', retry); audio.addEventListener('ended', retry);
audio.addEventListener('pause', () => { playing = false; render(); });
window.addEventListener('online', () => { if (requested && !playing) { clearTimeout(retryTimer); retryTimer = undefined; connect(); } });
window.addEventListener('pagehide', pause);
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
