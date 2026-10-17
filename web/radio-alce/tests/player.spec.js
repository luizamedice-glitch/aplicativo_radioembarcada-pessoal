import { test, expect } from '@playwright/test';
// A generated PCM tone tests actual browser decoding/playback, without external dependencies.
function tone() {
  const sampleRate = 8000, frames = sampleRate * 25;
  const b = Buffer.alloc(44 + frames * 2);
  b.write('RIFF'); b.writeUInt32LE(b.length - 8, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(sampleRate, 24); b.writeUInt32LE(sampleRate * 2, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(frames * 2, 40);
  for (let i = 0; i < frames; i++) b.writeInt16LE(Math.round(2000 * Math.sin(i * 2 * Math.PI * 440 / sampleRate)), 44 + i * 2);
  return b;
}
test.beforeEach(async ({ page }) => { await page.route('**/radio/stream', route => route.fulfill({ contentType: 'audio/wav', body: tone() })); });
for (const [width,height] of [[320,568],[360,640],[390,664],[393,852],[430,932],[768,1024],[844,390]]) {
  test(`fits ${width}x${height} without scroll or cropped controls`, async ({ page }) => {
    await page.setViewportSize({ width,height }); await page.goto('/');
    await expect(page.getByAltText('Logo Alce — Rádio Alce')).toBeVisible();
    await expect(page.getByText('AO VIVO', { exact:true })).toBeVisible();
    await expect(page.getByText('Sua Rádio em Movimento')).toBeVisible();
    for (const locator of [page.locator('.logo'),page.locator('.controls'),page.locator('.waveform')]) {
      const box = await locator.boundingBox(); expect(box.y).toBeGreaterThanOrEqual(0); expect(box.y+box.height).toBeLessThanOrEqual(height); expect(box.x+box.width).toBeLessThanOrEqual(width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight && document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: `test-results/player-${width}x${height}.png` });
  });
}
test('play/pause follows actual playback, badge and waveform; resume reconnects', async ({ page }) => {
  let connections=0;page.on('request',r=>{if(r.url().includes('/radio/stream'))connections++;});
  await page.goto('/'); await expect(page.locator('.radio')).not.toHaveClass(/is-playing/);
  await page.getByRole('button',{name:'Reproduzir rádio'}).click();
  await expect(page.locator('.radio')).toHaveClass(/is-playing/);
  await expect(page.locator('canvas')).toHaveAttribute('aria-label','Onda sonora ativa');
  await expect.poll(()=>page.locator('audio').evaluate(a=>a.currentTime)).toBeGreaterThan(.1);
  await page.getByRole('button',{name:'Pausar rádio'}).click();
  await expect(page.locator('audio')).not.toHaveAttribute('src');
  await expect(page.locator('.radio')).not.toHaveClass(/is-playing/);
  await expect(page.locator('canvas')).toHaveAttribute('aria-label','Onda sonora pausada');
  await page.getByRole('button',{name:'Reproduzir rádio'}).click();
  await expect(page.locator('.radio')).toHaveClass(/is-playing/); expect(connections).toBeGreaterThanOrEqual(2);
});
test('volume responds and only three buttons exist', async ({page})=>{
  await page.goto('/'); await expect(page.getByRole('button')).toHaveCount(3);
  await page.getByRole('button',{name:'Diminuir volume'}).click(); expect(await page.locator('audio').evaluate(a=>a.volume)).toBe(.9);
  await page.getByRole('button',{name:'Aumentar volume'}).click(); expect(await page.locator('audio').evaluate(a=>a.volume)).toBe(1);
});
test('failed stream retries and pause cancels it without raw errors',async({page})=>{
  let requests=0;await page.route('**/radio/stream',route=>{requests++;return route.fulfill({status:503,body:''});});
  await page.goto('/');await page.getByRole('button',{name:'Reproduzir rádio'}).click();
  await expect.poll(()=>requests).toBeGreaterThan(1);
  await expect(page.locator('.radio')).not.toHaveClass(/is-playing/);
  await page.getByRole('button',{name:'Pausar rádio'}).click();const stopped=requests;
  await page.waitForTimeout(2500);expect(requests).toBe(stopped);
  await page.getByRole('button', { name: 'Reproduzir rádio' }).click();
  await expect.poll(() => requests).toBeGreaterThan(stopped + 1);
  await page.getByRole('button', { name: 'Pausar rádio' }).click();
  await expect(page.locator('body')).not.toContainText(/503|IOException|https?:\/\//);
});
test('copied logo is byte-identical to the main Android logo',async()=>{
  const fs=await import('node:fs');expect(fs.readFileSync('public/alce-logo.png').equals(fs.readFileSync('../../app/src/main/res/drawable-nodpi/radio_alce_logo.png'))).toBeTruthy();
});

test('background lifecycle never pauses requested playback and recovers on return', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button',{name:'Reproduzir rádio'}).click();
  await expect(page.locator('.radio')).toHaveClass(/is-playing/);
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })));
  await expect(page.locator('audio')).toHaveAttribute('src', /\/radio\/stream/);
  await page.evaluate(() => {
    const audio = document.querySelector('audio');
    audio.dispatchEvent(new Event('waiting'));
    window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
  });
  await expect.poll(() => page.locator('audio').evaluate(a => a.getAttribute('src'))).toContain('/radio/stream');
});
