// Same 41 bars, envelope and 20 Hz cadence as Android WaveformVisualizer.kt.
export function waveform(canvas) {
  const context = canvas.getContext('2d');
  let active = false, phase = 0, timer;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function draw() {
    const { width, height } = canvas.getBoundingClientRect();
    const ratio = Math.min(devicePixelRatio || 1, 3);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.strokeStyle = active ? 'rgba(224,183,95,.85)' : 'rgba(224,183,95,.35)';
    context.lineCap = 'round';
    const step = width / 41; context.lineWidth = Math.min(step * .38, 4);
    for (let i = 0; i < 41; i++) {
      const envelope = Math.sin(Math.PI * (i + .5) / 41);
      const movement = active ? .18 + .70 * Math.abs(Math.sin(i * .73 + phase) * Math.sin(i * .21 - phase)) : .055;
      const h = Math.max(height * envelope * movement, 3), x = step * (i + .5);
      context.beginPath(); context.moveTo(x, (height - h) / 2); context.lineTo(x, (height + h) / 2); context.stroke();
    }
  }
  function update() {
    clearInterval(timer); draw();
    if (active && !document.hidden && !reduced.matches) timer = setInterval(() => { phase = (phase + .12) % (Math.PI * 2); draw(); }, 50);
  }
  new ResizeObserver(draw).observe(canvas);
  document.addEventListener('visibilitychange', update); reduced.addEventListener('change', update);
  return { setActive(value) { active = value; canvas.setAttribute('aria-label', value ? 'Onda sonora ativa' : 'Onda sonora pausada'); update(); } };
}
