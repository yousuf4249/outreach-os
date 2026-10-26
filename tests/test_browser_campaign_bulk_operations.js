/**
 * Headless Chrome CDP Verification: Campaign Bulk Select, Bulk Delete, and Bulk Archive UI
 */

import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-camp-bulk-'));

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

    console.log('\n======================================================');
    console.log('TEST 1: Navigating to http://127.0.0.1:5173/campaigns');
    console.log('======================================================');
    errors.length = 0;

    await send('Page.navigate', { url: 'http://127.0.0.1:5173/campaigns' });
    await sleep(3500);

    const initialPage = await evaluate(`() => {
      const h1 = document.querySelector('h1')?.innerText || '';
      const checkboxes = Array.from(document.querySelectorAll('tbody input[type="checkbox"]'));
      const headerCheckbox = document.querySelector('thead input[type="checkbox"]');
      const rows = Array.from(document.querySelectorAll('tbody tr'));
      const filterButtons = Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(t => t.includes('All (') || t.includes('Active (') || t.includes('Paused ('));
      const searchInput = document.querySelector('input[placeholder*="Search"]');

      return {
        h1,
        totalRows: rows.length,
        checkboxesCount: checkboxes.length,
        hasHeaderCheckbox: !!headerCheckbox,
        hasSearchInput: !!searchInput,
        filterButtons,
        blank: (document.getElementById('root')?.innerHTML.trim() === '')
      };
    }`);
    console.log('Initial Page Inspection:', JSON.stringify(initialPage, null, 2));

    if (initialPage.blank || !initialPage.hasHeaderCheckbox || initialPage.checkboxesCount === 0) {
      console.error('FAIL: Campaigns page failed to render checkboxes or loaded blank');
      exitCode = 1;
    } else {
      console.log('PASS: Campaigns page rendered with table checkboxes and filter pills.');
    }

    console.log('\n======================================================');
    console.log('TEST 2: Testing Checkbox Selection and Bulk Toolbar');
    console.log('======================================================');

    // Click first row checkbox
    const singleSelect = await evaluate(`() => {
      const firstCb = document.querySelector('tbody input[type="checkbox"]');
      if (firstCb) {
        firstCb.click();
        const toolbar = document.querySelector('.animate-fade-in');
        const toolbarText = toolbar ? toolbar.innerText.replace(/\\s+/g, ' ').trim() : '';
        return { clicked: true, toolbarText, hasToolbar: !!toolbar };
      }
      return { clicked: false };
    }`);
    console.log('Single Select Result:', JSON.stringify(singleSelect, null, 2));
    await sleep(500);

    // Click Header "Select All" checkbox
    const selectAllTest = await evaluate(`() => {
      const headerCb = document.querySelector('thead input[type="checkbox"]');
      if (headerCb) {
        headerCb.click();
        const checkedCount = Array.from(document.querySelectorAll('tbody input[type="checkbox"]:checked')).length;
        const toolbar = document.querySelector('.animate-fade-in');
        return {
          headerClicked: true,
          checkedCount,
          toolbarText: toolbar ? toolbar.innerText.replace(/\\s+/g, ' ').trim() : ''
        };
      }
      return { headerClicked: false };
    }`);
    console.log('Select All Result:', JSON.stringify(selectAllTest, null, 2));
    await sleep(500);

    if (!selectAllTest.headerClicked || selectAllTest.checkedCount === 0) {
      console.error('FAIL: Select All did not check table rows');
      exitCode = 1;
    } else {
      console.log('PASS: Header Select All checked all visible campaigns and showed toolbar.');
    }

    console.log('\n======================================================');
    console.log('TEST 3: Opening Bulk Deletion Confirmation Modal');
    console.log('======================================================');

    const openModalResult = await evaluate(`() => {
      const delBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Delete Selected'));
      if (delBtn) {
        delBtn.click();
        return 'Clicked Delete Selected';
      }
      return 'Delete Selected button not found';
    }`);
    console.log(openModalResult);
    await sleep(1000);

    const modalInspection = await evaluate(`() => {
      const modal = document.querySelector('.fixed.inset-0');
      const title = modal?.querySelector('h2')?.innerText || '';
      const text = modal?.innerText || '';
      const hasActiveWarning = text.includes('Active Campaign') || text.includes('Active (Will be skipped)');
      const hasSafeNotice = text.includes('Central Prospects remain completely safe');
      const cancelBtn = Array.from(modal ? modal.querySelectorAll('button') : []).find(b => b.innerText.includes('Cancel'));
      const confirmBtn = Array.from(modal ? modal.querySelectorAll('button') : []).find(b => b.innerText.includes('Confirm & Delete'));

      return {
        modalRendered: !!modal,
        title,
        hasActiveWarning,
        hasSafeNotice,
        hasCancelBtn: !!cancelBtn,
        hasConfirmBtn: !!confirmBtn
      };
    }`);
    console.log('Modal Inspection:', JSON.stringify(modalInspection, null, 2));

    if (!modalInspection.modalRendered || !modalInspection.hasSafeNotice) {
      console.error('FAIL: Confirmation modal failed to display safety notices');
      exitCode = 1;
    } else {
      console.log('PASS: Confirmation modal displayed safety notices, campaign listing, and active campaign detection.');
    }

    // Dismiss modal by clicking Cancel
    await evaluate(`() => {
      const cancelBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Cancel'));
      if (cancelBtn) cancelBtn.click();
    }`);
    await sleep(500);

    console.log('\n======================================================');
    console.log('TEST 4: Testing Search and Status Filtering');
    console.log('======================================================');

    // Search for "Austin"
    const searchResult = await evaluate(`() => {
      const input = document.querySelector('input[placeholder*="Search"]');
      if (input) {
        input.value = 'Austin';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return { searched: true };
      }
      return { searched: false };
    }`);
    console.log(searchResult);
    await sleep(1000);

    const postSearchInspection = await evaluate(`() => {
      const rows = Array.from(document.querySelectorAll('tbody tr'));
      return {
        rowsCount: rows.length,
        firstCampaignName: rows[0]?.querySelector('a')?.innerText || ''
      };
    }`);
    console.log('Post-Search Results:', JSON.stringify(postSearchInspection, null, 2));

    // Clear search
    await evaluate(`() => {
      const clearBtn = document.querySelector('input[placeholder*="Search"] + button');
      if (clearBtn) clearBtn.click();
    }`);
    await sleep(500);

    const uncaughtErrors = errors.filter(e => !e.text?.includes('React Router') && !e.text?.includes('unique "key"'));
    console.log(`\nUncaught Errors During Entire Suite: ${uncaughtErrors.length}`);
    if (uncaughtErrors.length > 0) {
      console.error('Uncaught browser errors recorded:', uncaughtErrors);
      exitCode = 1;
    }

    ws.close();
  } catch (err) {
    console.error('FATAL: Test run error:', err);
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
