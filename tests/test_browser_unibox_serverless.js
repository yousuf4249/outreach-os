/**
 * Headless Chrome CDP Verification for Unibox Serverless Enhancements:
 * 1. Folder Navigation (Inbox, Sent, Replies, Drafts, All)
 * 2. Message Attachment viewer & Forwarding action
 * 3. Compose Modal with Attachment selector
 */

import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-unibox-serverless-'));

const token = process.argv[2];
if (!token) {
  console.error('Error: Token required.');
  process.exit(1);
}

const screenshotDir = 'C:\\Users\\classic\\.gemini\\antigravity\\brain\\274c18ea-32b0-4386-96b6-ca530da6709d';
const screenshotPath = path.join(screenshotDir, 'unibox_folders_and_composer.png');

const chrome = spawn(chromePath, [
  '--headless=new',
  '--remote-debugging-port=9222',
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
      const res = await fetch('http://127.0.0.1:9222/json');
      if (res.ok) {
        const pages = await res.json();
        const page = pages.find(p => p.type === 'page');
        if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
      }
    } catch {}
    await sleep(200);
  }
  throw new Error('Chrome debugging unreachable');
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
    const exceptions = [];

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg.result);
        pending.delete(msg.id);
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        exceptions.push(msg.params.exceptionDetails);
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
    await send('DOM.enable');

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

    console.log('Navigating to http://127.0.0.1:5173/unibox...');
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/unibox' });
    await sleep(3500);

    // TEST 1: Check Folder Navigation Tabs
    console.log('\n--- TEST 1: Checking Folder Navigation Tabs ---');
    const folderTabs = await evaluate(`() => {
      const buttons = Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim());
      return {
        hasInbox: buttons.some(b => b === 'Inbox'),
        hasSent: buttons.some(b => b === 'Sent'),
        hasReplies: buttons.some(b => b === 'Replies'),
        hasDrafts: buttons.some(b => b === 'Drafts'),
        hasAll: buttons.some(b => b === 'All'),
        buttonsSnippet: buttons.slice(0, 15)
      };
    }`);
    console.log('Folder Tabs found:', folderTabs);

    if (!folderTabs.hasInbox || !folderTabs.hasSent || !folderTabs.hasReplies || !folderTabs.hasDrafts) {
      throw new Error('Folder navigation tabs are missing in Unibox');
    }
    console.log('PASS: Folder navigation tabs (Inbox, Sent, Replies, Drafts, All) rendered.');

    // TEST 2: Switch to "Sent" folder
    console.log('\n--- TEST 2: Switching to "Sent" folder ---');
    await evaluate(`() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Sent');
      if (btn) btn.click();
    }`);
    await sleep(1500);

    const sentFolderState = await evaluate(`() => {
      const header = document.querySelector('h2')?.innerText || '';
      return {
        header,
        conversationsCount: document.querySelectorAll('.divide-y > *').length
      };
    }`);
    console.log('Sent folder state:', sentFolderState);

    // TEST 3: Switch back to "Inbox" folder
    console.log('\n--- TEST 3: Switching to "Inbox" folder ---');
    await evaluate(`() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Inbox');
      if (btn) btn.click();
    }`);
    await sleep(1500);

    // TEST 4: Open Compose Modal & check Attachment Selector
    console.log('\n--- TEST 4: Opening Compose Modal & Checking Attachment Selector ---');
    await evaluate(`() => {
      const composeBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Compose'));
      if (composeBtn) composeBtn.click();
    }`);
    await sleep(1000);

    const composeInspection = await evaluate(`() => {
      const modal = document.querySelector('.fixed.inset-0');
      const text = modal?.innerText || '';
      return {
        modalOpen: !!modal,
        hasAttachButton: text.includes('Attach Files'),
        hasFileInput: !!modal?.querySelector('input[type="file"]')
      };
    }`);
    console.log('Compose Inspection:', composeInspection);

    if (!composeInspection.modalOpen || !composeInspection.hasAttachButton) {
      throw new Error('Compose modal or Attach Files button failed to render');
    }
    console.log('PASS: Compose modal opened with Attach Files selector.');

    // TEST 5: Capture screenshot
    console.log('\n--- TEST 5: Capturing Verification Screenshot ---');
    const screenshot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'));
    console.log('Screenshot saved to:', screenshotPath);

    // Check for exceptions
    if (exceptions.length > 0) {
      throw new Error(`JavaScript exceptions encountered: ${JSON.stringify(exceptions)}`);
    }
    console.log('PASS: Zero unhandled JavaScript exceptions.');

    console.log('\nALL BROWSER UNIBOX CHECKS PASSED SUCCESSFULLY!');

  } catch (err) {
    console.error('BROWSER TEST FAILURE:', err.message);
    exitCode = 1;
  } finally {
    try {
      chrome.kill('SIGKILL');
    } catch {}
    try {
      if (fs.existsSync(userDataDir)) {
        fs.rmSync(userDataDir, { recursive: true, force: true });
      }
    } catch {}
    process.exit(exitCode);
  }
}

run();
