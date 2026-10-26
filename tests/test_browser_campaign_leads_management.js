/**
 * Headless Chrome CDP Verification: Campaign Lead Removal & Bulk Management UI
 */

import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-camp-leads-'));

const token = process.argv[2];
if (!token) {
  console.error('Error: Token required.');
  process.exit(1);
}

const screenshotDir = 'C:\\Users\\classic\\.gemini\\antigravity\\brain\\274c18ea-32b0-4386-96b6-ca530da6709d';
const screenshotPath = path.join(screenshotDir, 'campaign_leads_bulk_management.png');

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
  throw new Error('Chrome remote debugging did not respond');
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
      if (msg.method === 'Console.messageAdded' && msg.params.message.level === 'error') {
        errors.push({
          type: 'CONSOLE_ERROR',
          text: msg.params.message.text
        });
      }
    };

    function send(method, params = {}) {
      return new Promise((resolve) => {
        const id = msgId++;
        pending.set(id, resolve);
        ws.send(JSON.stringify({ id, method, params }));
      });
    }

    async function evaluate(expression) {
      const res = await send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true
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

    console.log('[1/7] Navigating to Campaign 1 with #leads...');
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/campaigns/1#leads' });
    await sleep(3500);

    const pageDiagnostics = await evaluate(`(() => {
      return {
        url: window.location.href,
        title: document.title,
        bodySnippet: document.body.innerText.slice(0, 300),
        buttonTexts: Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean)
      };
    })()`);
    console.log('Page Diagnostics:', JSON.stringify(pageDiagnostics, null, 2));

    console.log('[2/7] Checking Leads tab in Campaign...');
    // Ensure leads tab is active
    const switchTabResult = await evaluate(`(() => {
      const buttons = Array.from(document.querySelectorAll('button, [role="tab"]'));
      const leadsBtn = buttons.find(b => b.innerText && b.innerText.includes('Leads'));
      if (leadsBtn) {
        leadsBtn.click();
        return { clicked: true, text: leadsBtn.innerText };
      }
      return { clicked: false };
    })()`);
    console.log('Tab switch result:', switchTabResult);
    await sleep(2000);

    console.log('[3/7] Verifying table rendering and that Add Leads area is removed...');
    const tableInfo = await evaluate(`(() => {
      const table = document.querySelector('table');
      const headerCheckbox = document.querySelector('thead input[type="checkbox"]');
      const rowCheckboxes = Array.from(document.querySelectorAll('tbody input[type="checkbox"]'));
      const statusSelect = document.querySelector('select');
      const options = statusSelect ? Array.from(statusSelect.options).map(o => o.value) : [];

      const bodyText = document.body.innerText;
      const hasAddLeadsTitle = Array.from(document.querySelectorAll('h3')).some(h => h.innerText.includes('Add leads'));
      const hasSingleBtn = Array.from(document.querySelectorAll('button')).some(b => b.innerText.trim() === 'Single');
      const hasBulkPasteBtn = Array.from(document.querySelectorAll('button')).some(b => b.innerText.trim() === 'Bulk paste');

      return {
        hasTable: !!table,
        hasHeaderCheckbox: !!headerCheckbox,
        rowCount: rowCheckboxes.length,
        statusOptions: options,
        hasAddLeadsArea: hasAddLeadsTitle || hasSingleBtn || hasBulkPasteBtn,
      };
    })()`);
    console.log('Table Information:', JSON.stringify(tableInfo, null, 2));

    if (tableInfo.hasAddLeadsArea) {
      throw new Error('Add leads area is still present on the page!');
    }

    if (!tableInfo.hasHeaderCheckbox || tableInfo.rowCount === 0) {
      throw new Error(`Table checkboxes not found! hasHeaderCheckbox=${tableInfo.hasHeaderCheckbox}, rowCount=${tableInfo.rowCount}`);
    }

    console.log('[4/7] Selecting leads to test bulk action toolbar...');
    // Select first 2 rows
    const selectionInfo = await evaluate(`(() => {
      const checkboxes = Array.from(document.querySelectorAll('tbody input[type="checkbox"]'));
      if (checkboxes.length >= 2) {
        checkboxes[0].click();
        checkboxes[1].click();
        return { clicked: 2 };
      }
      return { clicked: 0 };
    })()`);
    console.log('Selection action:', selectionInfo);
    await sleep(1000);

    const toolbarInfo = await evaluate(`(() => {
      // Find bulk toolbar
      const allText = document.body.innerText;
      const removeBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Remove From Campaign'));
      const stopBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Stop Sequence'));
      const resumeBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Resume Sequence'));
      const retryBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Retry Temporary Bounces'));
      
      return {
        selectedTextFound: allText.includes('selected') || allText.includes('2 selected'),
        hasRemoveBtn: !!removeBtn,
        hasStopBtn: !!stopBtn,
        hasResumeBtn: !!resumeBtn,
        hasRetryBtn: !!retryBtn,
      };
    })()`);
    console.log('Bulk Toolbar Info:', JSON.stringify(toolbarInfo, null, 2));

    if (!toolbarInfo.hasRemoveBtn || !toolbarInfo.hasStopBtn) {
      throw new Error('Bulk toolbar actions not properly displayed!');
    }

    console.log('[5/7] Testing Bulk Remove confirmation modal...');
    // Capture screenshot of bulk toolbar before opening modal
    const toolbarScreenshot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(screenshotPath, Buffer.from(toolbarScreenshot.data, 'base64'));
    console.log(`Toolbar screenshot saved to: ${screenshotPath}`);

    // Click Remove From Campaign to open confirmation modal
    await evaluate(`(() => {
      const removeBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Remove From Campaign'));
      if (removeBtn) removeBtn.click();
    })()`);
    await sleep(1000);

    const modalScreenshotPath = path.join(screenshotDir, 'campaign_leads_bulk_remove_modal.png');
    const modalScreenshot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(modalScreenshotPath, Buffer.from(modalScreenshot.data, 'base64'));
    console.log(`Modal screenshot saved to: ${modalScreenshotPath}`);

    const modalInfo = await evaluate(`(() => {
      const bodyText = document.body.innerText;
      const hasConfirmModal = bodyText.includes('Remove Leads from Campaign') || bodyText.includes('Remove Prospects From Campaign');
      const hasSafeNotice = bodyText.includes('Central Prospect Database is safe') || bodyText.includes('central Prospects database');
      const cancelBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.trim() === 'Cancel');
      
      return {
        hasConfirmModal,
        hasSafeNotice,
        hasCancelBtn: !!cancelBtn,
      };
    })()`);
    console.log('Confirmation Modal Info:', JSON.stringify(modalInfo, null, 2));

    if (!modalInfo.hasConfirmModal || !modalInfo.hasSafeNotice) {
      throw new Error('Safety confirmation modal missing or does not state central DB preservation!');
    }

    // Dismiss modal safely by clicking Cancel
    await evaluate(`(() => {
      const cancelBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.trim() === 'Cancel');
      if (cancelBtn) cancelBtn.click();
    })()`);
    await sleep(500);

    console.log('[6/7] Capturing screenshot of Campaign Leads bulk management UI...');
    const screenshotData = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(screenshotPath, Buffer.from(screenshotData.data, 'base64'));
    console.log(`Screenshot successfully saved to: ${screenshotPath}`);

    console.log('[7/7] Checking for runtime console errors...');
    const uncaughtErrors = errors.filter(e => !e.text?.includes('React Router') && !e.text?.includes('unique "key"'));
    console.log(`Uncaught Errors Recorded: ${uncaughtErrors.length}`);
    if (uncaughtErrors.length > 0) {
      console.warn('Browser warnings/errors:', uncaughtErrors);
    }

    console.log('\nCAMPAIGN LEAD MANAGEMENT BROWSER VERIFICATION SUCCESSFUL!');
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
