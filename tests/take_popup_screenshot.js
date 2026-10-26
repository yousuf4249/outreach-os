import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-popup-shot-'));

const token = process.argv[2];
if (!token) {
  console.error('Error: Token required.');
  process.exit(1);
}

const screenshotDir = 'C:\\Users\\classic\\.gemini\\antigravity\\brain\\274c18ea-32b0-4386-96b6-ca530da6709d';
const screenshotPath = path.join(screenshotDir, 'campaign_select_prospects_improved.png');

const chrome = spawn(chromePath, [
  '--headless=new',
  '--remote-debugging-port=9223',
  `--user-data-dir=${userDataDir}`,
  '--no-first-run',
  '--no-default-browser-check',
  '--window-size=1440,900',
  'about:blank'
], { stdio: 'ignore' });

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function getWsUrl() {
  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch('http://127.0.0.1:9223/json');
      if (res.ok) {
        const pages = await res.json();
        const page = pages.find(p => p.type === 'page');
        if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
      }
    } catch {}
    await sleep(200);
  }
  throw new Error('Chrome remote debugging did not respond');
}

async function run() {
  const wsUrl = await getWsUrl();
  const ws = new globalThis.WebSocket(wsUrl);

  let msgId = 1;
  const callbacks = new Map();

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && callbacks.has(msg.id)) {
      const { resolve, reject } = callbacks.get(msg.id);
      callbacks.delete(msg.id);
      if (msg.error) reject(msg.error);
      else resolve(msg.result);
    }
  };

  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = msgId++;
      callbacks.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  await new Promise(r => ws.onopen = r);
  await send('Page.enable');
  await send('Runtime.enable');

  // Navigate to login page first
  await send('Page.navigate', { url: 'http://localhost:5173/login' });
  await sleep(1000);

  // Set auth tokens and dismiss onboarding tour in localStorage
  const setAuthScript = `
    localStorage.setItem('access_token', ${JSON.stringify(token)});
    localStorage.setItem('token', ${JSON.stringify(token)});
    localStorage.setItem('onboardingCompleted', 'true');
  `;
  await send('Runtime.evaluate', { expression: setAuthScript });

  // Navigate to campaign 1 leads tab directly
  await send('Page.navigate', { url: 'http://localhost:5173/campaigns/1#leads' });
  await sleep(3000);

  // Click the "Select Existing Prospects" button
  const openModalScript = `
    (() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const btn = btns.find(b => b.textContent && b.textContent.includes('Select Existing Prospects'));
      if (btn) {
        btn.click();
        return 'modal button clicked';
      }
      return 'button not found';
    })()
  `;
  const clickRes = await send('Runtime.evaluate', { expression: openModalScript });
  console.log('Open modal click result:', clickRes.result.value);

  await sleep(2500);

  // Capture screenshot of the modal
  const { data } = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(screenshotPath, Buffer.from(data, 'base64'));
  console.log(`Screenshot saved successfully: ${screenshotPath}`);

  ws.close();
  chrome.kill();
  process.exit(0);
}

run().catch(e => {
  console.error(e);
  chrome.kill();
  process.exit(1);
});
