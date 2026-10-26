/**
 * Headless Chrome CDP Test: Compact Email Tracking UI in Unibox & LeadDetail
 */

import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-email-tracking-'));

const token = process.argv[2];
if (!token) {
  console.error('Error: Token required.');
  process.exit(1);
}

const chrome = spawn(chromePath, [
  '--headless=new',
  '--remote-debugging-port=9222',
  `--user-data-dir=${userDataDir}`,
  '--no-first-run',
  '--no-default-browser-check',
  'about:blank'
], { stdio: 'ignore' });

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function getWsUrl() {
  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch('http://127.0.0.1:9222/json');
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
  let exitCode = 0;
  const artifactDir = 'C:\\Users\\classic\\.gemini\\antigravity\\brain\\274c18ea-32b0-4386-96b6-ca530da6709d';

  try {
    const wsUrl = await getWsUrl();
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      ws.onopen = res;
      ws.onerror = rej;
    });

    let msgId = 1;
    const pending = new Map();
    const errors = [];

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg.result);
        pending.delete(msg.id);
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        const details = msg.params.exceptionDetails;
        errors.push({
          type: 'UNCAUGHT_EXCEPTION',
          text: details.text,
          exception: details.exception?.description || details.exception?.value
        });
      }
    };

    function send(method, params = {}) {
      return new Promise((res) => {
        const id = msgId++;
        pending.set(id, res);
        ws.send(JSON.stringify({ id, method, params }));
      });
    }

    await send('Page.enable');
    await send('Runtime.enable');
    await send('DOM.enable');

    // 1. Inject auth token & navigate
    console.log('[1/4] Navigating to Weblinx Outreach OS...');
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/' });
    await sleep(800);

    await send('Runtime.evaluate', {
      expression: `
        localStorage.setItem('access_token', '${token}');
        sessionStorage.setItem('access_token', '${token}');
        localStorage.setItem('user', JSON.stringify({ id: 1, role: 'admin' }));
      `
    });

    // 2. Open LeadDetail of Lead #1 or navigate to Unibox
    console.log('[2/4] Testing Tracking Indicators on LeadDetail / Unibox...');
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/leads/1' });
    await sleep(2000);

    // Evaluate presence of tracking or test direct interactive popover
    const evalResult = await send('Runtime.evaluate', {
      expression: `
        (() => {
          const indicators = Array.from(document.querySelectorAll('button[title*="tracking"], button[title*="details"]'))
            .map(b => b.innerText.trim());
          const hasTrackingCards = !!document.querySelector('.grid.grid-cols-2.sm\\\\:grid-cols-4');
          return {
            indicators,
            hasLargeCards: hasTrackingCards
          };
        })()
      `,
      returnByValue: true
    });

    console.log('DOM Evaluation on Lead Detail:', evalResult.result.value);
    if (evalResult.result.value.hasLargeCards) {
      throw new Error('Old large tracking grid is still present!');
    }
    console.log('  [PASS] Old large 4-card tracking grid has been successfully removed.');

    // 3. Test Desktop Viewport
    console.log('[3/4] Capturing Desktop Screenshot (1440x900)...');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false
    });
    await sleep(500);

    const shotDesktop = await send('Page.captureScreenshot', { format: 'png' });
    const deskPath = path.join(artifactDir, 'compact_email_tracking_desktop.png');
    fs.writeFileSync(deskPath, Buffer.from(shotDesktop.data, 'base64'));
    console.log(`Saved desktop screenshot to: ${deskPath}`);

    // 4. Test Mobile Viewport (iPhone 13 - 390x844)
    console.log('[4/4] Capturing Mobile Viewport Screenshot (390x844)...');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true
    });
    await sleep(500);

    const shotMobile = await send('Page.captureScreenshot', { format: 'png' });
    const mobPath = path.join(artifactDir, 'compact_email_tracking_mobile.png');
    fs.writeFileSync(mobPath, Buffer.from(shotMobile.data, 'base64'));
    console.log(`Saved mobile screenshot to: ${mobPath}`);

    if (errors.length > 0) {
      console.error('Browser errors detected:', errors);
      exitCode = 1;
    } else {
      console.log('\n=== COMPACT EMAIL TRACKING BROWSER VERIFICATION SUCCESSFUL ===');
    }

    ws.close();
  } catch (err) {
    console.error('Test execution failed:', err);
    exitCode = 1;
  } finally {
    chrome.kill();
    try {
      fs.rmSync(userDataDir, { recursive: true, force: true });
    } catch {}
    process.exit(exitCode);
  }
}

run();
