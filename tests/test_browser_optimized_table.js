/**
 * Headless Chrome CDP Test: Optimized 7-Column Prospects Table, Show/Hide Columns, Copy & Filters
 */

import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-leads-7col-'));

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

    // 1. Inject localStorage token
    console.log('[1/5] Injecting auth token and navigating to http://127.0.0.1:5173/leads...');
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/' });
    await sleep(1000);

    await send('Runtime.evaluate', {
      expression: `
        localStorage.setItem('access_token', '${token}');
        sessionStorage.setItem('access_token', '${token}');
        localStorage.setItem('user', JSON.stringify({ id: 1, role: 'admin' }));
        // Ensure default columns
        localStorage.removeItem('weblinx_prospect_columns');
      `
    });

    await send('Page.navigate', { url: 'http://127.0.0.1:5173/leads' });
    await sleep(2500);

    // 2. Evaluate rendered table structure
    console.log('[2/5] Inspecting visible columns in DOM...');
    const colEval = await send('Runtime.evaluate', {
      expression: `
        (() => {
          const headers = Array.from(document.querySelectorAll('table thead th'))
            .map(th => th.innerText.trim())
            .filter(Boolean);
          const rowCount = document.querySelectorAll('table tbody tr').length;
          const firstRowCells = Array.from(document.querySelectorAll('table tbody tr:first-child td'))
            .map(td => td.innerText.trim());
          const hasWebsiteLink = !!document.querySelector('table tbody tr:first-child a[title*="Visit"]');
          const copyButtons = document.querySelectorAll('button[title*="Copy"]').length;
          const actionButtons = document.querySelectorAll('table tbody tr:first-child td:last-child button, table tbody tr:first-child td:last-child a').length;
          const searchInput = !!document.querySelector('input[placeholder*="Search company"]');
          const columnsButtonText = document.querySelector('button[title*="Customize"]')?.innerText?.trim();
          
          return {
            headers,
            rowCount,
            firstRowCells,
            hasWebsiteLink,
            copyButtons,
            actionButtons,
            searchInput,
            columnsButtonText
          };
        })()
      `,
      returnByValue: true
    });

    const colResult = colEval.result.value;
    console.log('Table Headers Detected:', colResult.headers);
    console.log('Row Count in Table:', colResult.rowCount);
    console.log('Columns Button Label:', colResult.columnsButtonText);
    console.log('Website Link present in Row 1:', colResult.hasWebsiteLink);
    console.log('Total Copy Buttons detected:', colResult.copyButtons);
    console.log('Action Buttons in Row 1 (View/Email/Add):', colResult.actionButtons);

    // Assert only the 7 columns (+ checkbox) are displayed by default
    const expectedCols = [
      'COMPANY NAME',
      'CONTACT / FOUNDER',
      'EMAIL ADDRESS',
      'PHONE NUMBER',
      'VERIFICATION STATUS',
      'PIPELINE STAGE',
      'ACTIONS'
    ];
    for (const exp of expectedCols) {
      const match = colResult.headers.some(h => h.toUpperCase().includes(exp));
      if (!match) {
        throw new Error(`Missing expected column: ${exp} in ${JSON.stringify(colResult.headers)}`);
      }
    }
    console.log('  [PASS] All 7 core columns are visible by default.');

    // Assert optional columns are hidden by default
    const forbiddenByDefault = ['LOCATION', 'INDUSTRY', 'TAGS', 'CAMPAIGNS'];
    for (const forb of forbiddenByDefault) {
      const match = colResult.headers.some(h => h.toUpperCase() === forb);
      if (match) {
        throw new Error(`Optional column ${forb} should be hidden by default!`);
      }
    }
    console.log('  [PASS] Optional columns (Location, Industry, Tags, Campaigns) are hidden by default.');

    // 3. Test Show/Hide Columns Dropdown Menu
    console.log('[3/5] Testing Show/Hide Columns Menu...');
    await send('Runtime.evaluate', {
      expression: `
        (() => {
          const colBtn = document.querySelector('button[title*="Customize"]');
          if (colBtn) colBtn.click();
        })()
      `
    });
    await sleep(400);

    // Toggle Location checkbox
    await send('Runtime.evaluate', {
      expression: `
        (() => {
          const labels = Array.from(document.querySelectorAll('label'));
          const locLabel = labels.find(l => l.innerText.includes('Location'));
          if (locLabel) {
            const cb = locLabel.querySelector('input[type="checkbox"]');
            if (cb) cb.click();
          }
        })()
      `
    });
    await sleep(500);

    const afterToggle = await send('Runtime.evaluate', {
      expression: `
        (() => {
          const headers = Array.from(document.querySelectorAll('table thead th'))
            .map(th => th.innerText.trim());
          return headers;
        })()
      `,
      returnByValue: true
    });
    console.log('Headers after enabling Location:', afterToggle.result.value);
    const hasLocation = afterToggle.result.value.some(h => h.toUpperCase().includes('LOCATION'));
    if (!hasLocation) {
      throw new Error('Location column was not dynamically added to table when toggled!');
    }
    console.log('  [PASS] Show/Hide Columns menu dynamically toggled Location column!');

    // 4. Test Search by Phone or Name
    console.log('[4/5] Testing Search filter for phone/name...');
    await send('Runtime.evaluate', {
      expression: `
        (() => {
          // Close menu first
          document.body.click();
          const searchInput = document.querySelector('input[placeholder*="Search company"]');
          if (searchInput) {
            // Native setter for React controlled input
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(searchInput, 'Marcus');
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
          }
        })()
      `
    });
    await sleep(800);

    const searchRowsEval = await send('Runtime.evaluate', {
      expression: `
        (() => {
          const rows = Array.from(document.querySelectorAll('table tbody tr')).map(tr => tr.innerText);
          return { count: rows.length, rowText: rows[0] || '' };
        })()
      `,
      returnByValue: true
    });
    console.log(`Search result rows count: ${searchRowsEval.result.value.count}`);
    if (searchRowsEval.result.value.count !== 1 || !searchRowsEval.result.value.rowText.includes('Marcus Vance')) {
      throw new Error(`Search failed to filter to Marcus Vance: ${JSON.stringify(searchRowsEval.result.value)}`);
    }
    console.log('  [PASS] Live search filtered table to matching prospect.');

    // Reset search
    await send('Runtime.evaluate', {
      expression: `
        (() => {
          const searchInput = document.querySelector('input[placeholder*="Search company"]');
          if (searchInput) {
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(searchInput, '');
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
          }
        })()
      `
    });
    await sleep(600);

    // 5. Take Verification Screenshot
    console.log('[5/5] Capturing browser verification screenshot...');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false
    });
    await sleep(300);

    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const shotPath = path.join(artifactDir, 'optimized_prospects_table_7columns.png');
    fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'));
    console.log(`Saved screenshot to: ${shotPath}`);

    if (errors.length > 0) {
      console.error('Browser runtime errors:', errors);
      exitCode = 1;
    } else {
      console.log('\n=== BROWSER VERIFICATION SUCCESSFUL: 0 RUNTIME ERRORS ===');
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
