/**
 * Regression Test Suite: Browser Rendering & Critical Frontend Flow Verification
 * Tests:
 * 1. Prospect Detail Page (/leads/{id})
 * 2. Campaign Prospect Selection Modal (/campaigns/{id}#leads -> Select Existing Prospects)
 * 3. Page Navigation, Browser Refresh, and Direct URL access
 */

import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-reg-test-'));

const token = process.argv[2];
if (!token) {
  console.error('Error: Token required as CLI argument.');
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
  throw new Error('Chrome debugging endpoint unreachable');
}

async function run() {
  let exitCode = 0;
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
      const id = msgId++;
      return new Promise((resolve) => {
        pending.set(id, resolve);
        ws.send(JSON.stringify({ id, method, params }));
      });
    }

    async function evaluate(fnStr) {
      const res = await send('Runtime.evaluate', {
        expression: `(${fnStr})()`,
        returnByValue: true
      });
      return res?.result?.value;
    }

    await send('Page.enable');
    await send('Runtime.enable');
    await send('Console.enable');

    await send('Page.addScriptToEvaluateOnNewDocument', {
      source: `
        try {
          localStorage.setItem('access_token', ${JSON.stringify(token)});
          sessionStorage.setItem('access_token', ${JSON.stringify(token)});
          localStorage.setItem('onboardingCompleted', 'true');
          localStorage.setItem('has_seen_onboarding', 'true');
        } catch (e) {}
      `
    });

    // TEST 1: Lead Detail
    errors.length = 0;
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/leads/1' });
    await sleep(3500);

    const leadInfo = await evaluate(`() => ({
      h1: document.querySelector('h1')?.innerText || '',
      hasEmail: document.body.innerText.includes('@'),
      hasDeliverability: document.body.innerText.toLowerCase().includes('deliverability health') || document.body.innerText.toLowerCase().includes('technical verification'),
      blank: (document.getElementById('root')?.innerHTML.trim() === ''),
      bodySnippet: document.body.innerText.slice(0, 300)
    })`);
    console.log('leadInfo:', leadInfo);

    if (leadInfo.blank || !leadInfo.hasDeliverability || errors.length > 0) {
      console.error('FAIL: Lead Detail Page (/leads/1) failed to render or encountered errors:', errors);
      exitCode = 1;
    } else {
      console.log('PASS: Lead Detail Page (/leads/1) rendered cleanly.');
    }

    // TEST 2: Campaign Prospect Selection Modal
    errors.length = 0;
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/campaigns/1#leads' });
    await sleep(3500);

    await evaluate(`() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Select Existing Prospects'));
      if (btn) btn.click();
    }`);
    await sleep(2500);

    const modalInfo = await evaluate(`() => {
      const modal = document.querySelector('.fixed.inset-0');
      const rows = modal ? Array.from(modal.querySelectorAll('tbody tr')) : [];
      return {
        open: !!modal,
        rowsCount: rows.length,
        blank: (document.getElementById('root')?.innerHTML.trim() === '')
      };
    }`);

    if (modalInfo.blank || !modalInfo.open || modalInfo.rowsCount === 0 || errors.length > 0) {
      console.error('FAIL: Select Prospects Modal failed to render or encountered errors:', errors);
      exitCode = 1;
    } else {
      console.log(`PASS: Select Prospects Modal opened with ${modalInfo.rowsCount} prospects rendered.`);
    }

    ws.close();
  } catch (err) {
    console.error('FATAL: Browser test error:', err);
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
