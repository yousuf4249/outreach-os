/**
 * Headless Chrome CDP Verification: Prospects Database Scrolling & Responsive Layout
 */

import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-leads-scroll-'));

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
  const screenshots = {};

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

    async function capture(name) {
      const res = await send('Page.captureScreenshot', { format: 'png' });
      if (res?.data) {
        const filePath = path.join(artifactDir, `${name}.png`);
        fs.writeFileSync(filePath, Buffer.from(res.data, 'base64'));
        screenshots[name] = filePath;
        console.log(`[SCREENSHOT] Saved: ${name}.png (${Math.round(res.data.length / 1024)} KB)`);
      }
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

    console.log('\n======================================================');
    console.log('TEST 1: Navigating to http://127.0.0.1:5173/leads');
    console.log('======================================================');
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/leads' });
    await sleep(3500);

    // VIEWPORT 1: 1920x1080 Desktop
    console.log('\n======================================================');
    console.log('TEST 2: Desktop 1920x1080 Viewport');
    console.log('======================================================');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1920,
      height: 1080,
      deviceScaleFactor: 1,
      mobile: false
    });
    await sleep(1200);

    const desktopStats = await evaluate(`() => {
      const container = document.querySelector('[role="region"][aria-label="Prospects Database Table"]');
      const rows = document.querySelectorAll('tbody tr');
      const ths = Array.from(document.querySelectorAll('thead th')).map(t => t.innerText.trim());
      const totalBadge = document.querySelector('h1 + span');
      const h1 = document.querySelector('h1')?.innerText;
      return {
        h1,
        totalBadge: totalBadge ? totalBadge.innerText : null,
        renderedRows: rows.length,
        columnsCount: ths.length,
        columns: ths,
        containerWidth: container?.offsetWidth,
        containerHeight: container?.offsetHeight,
        scrollWidth: container?.scrollWidth,
        scrollHeight: container?.scrollHeight
      };
    }`);
    console.log('Desktop 1920x1080 Result:', JSON.stringify(desktopStats, null, 2));
    await capture('leads_viewport_1920_desktop');

    // VIEWPORT 2: 1366x768 Laptop
    console.log('\n======================================================');
    console.log('TEST 3: Laptop 1366x768 Viewport');
    console.log('======================================================');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1366,
      height: 768,
      deviceScaleFactor: 1,
      mobile: false
    });
    await sleep(1000);

    const laptopStats = await evaluate(`() => {
      const container = document.querySelector('[role="region"][aria-label="Prospects Database Table"]');
      return {
        containerWidth: container?.offsetWidth,
        containerHeight: container?.offsetHeight,
        scrollWidth: container?.scrollWidth,
        hasHorizontalScroll: container ? container.scrollWidth > container.offsetWidth : false,
        hasVerticalScroll: container ? container.scrollHeight > container.offsetHeight : false
      };
    }`);
    console.log('Laptop 1366x768 Result:', JSON.stringify(laptopStats, null, 2));
    await capture('leads_viewport_1366_laptop');

    // VIEWPORT 3: 1024x768 Tablet & Horizontal Scroll
    console.log('\n======================================================');
    console.log('TEST 4: Tablet 1024x768 & Horizontal Scrolling');
    console.log('======================================================');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1024,
      height: 768,
      deviceScaleFactor: 1,
      mobile: false
    });
    await sleep(1000);

    // Initial unscrolled tablet view
    await capture('leads_viewport_1024_tablet_start');

    // Scroll right by 450px
    await evaluate(`() => {
      const container = document.querySelector('[role="region"][aria-label="Prospects Database Table"]');
      if (container) container.scrollLeft = 450;
    }`);
    await sleep(800);

    const tabletScrolledStats = await evaluate(`() => {
      const container = document.querySelector('[role="region"][aria-label="Prospects Database Table"]');
      const stickyCheckHeader = document.querySelector('thead th.sticky.left-0');
      const stickyActionsHeader = document.querySelector('thead th.sticky.right-0');
      const firstRowStickyCheck = document.querySelector('tbody tr td.sticky.left-0');
      const firstRowStickyActions = document.querySelector('tbody tr td.sticky.right-0');
      const containerRect = container.getBoundingClientRect();
      const checkRect = firstRowStickyCheck.getBoundingClientRect();
      const actionRect = firstRowStickyActions.getBoundingClientRect();
      return {
        scrollLeft: container?.scrollLeft,
        checkboxLeftPushed: checkRect.left - containerRect.left,
        actionsRightPushed: containerRect.right - actionRect.right,
        isCheckboxSticky: Math.abs(checkRect.left - containerRect.left) < 5,
        isActionsSticky: Math.abs(containerRect.right - actionRect.right) < 5
      };
    }`);
    console.log('Tablet 1024 Scrolled Result:', JSON.stringify(tabletScrolledStats, null, 2));
    await capture('leads_viewport_1024_tablet_scrolled_right');

    // VIEWPORT 4: 768x1024 Narrow Screen
    console.log('\n======================================================');
    console.log('TEST 5: Narrow 768x1024 Screen');
    console.log('======================================================');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 768,
      height: 1024,
      deviceScaleFactor: 1,
      mobile: false
    });
    await sleep(1000);
    await capture('leads_viewport_768_narrow');

    // VIEWPORT 5: 390x844 Mobile
    console.log('\n======================================================');
    console.log('TEST 6: Mobile 390x844 Screen');
    console.log('======================================================');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true
    });
    await sleep(1000);
    await capture('leads_viewport_390_mobile');

    // TEST 7: Vertical Scrolling with Sticky Header & 100+ Rows
    console.log('\n======================================================');
    console.log('TEST 7: Vertical Scroll with Sticky Header on 1366x768');
    console.log('======================================================');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1366,
      height: 768,
      deviceScaleFactor: 1,
      mobile: false
    });
    await sleep(800);

    // Scroll vertical inside table container
    await evaluate(`() => {
      const container = document.querySelector('[role="region"][aria-label="Prospects Database Table"]');
      if (container) {
        container.scrollLeft = 0;
        container.scrollTop = 500;
      }
    }`);
    await sleep(800);

    const verticalStats = await evaluate(`() => {
      const container = document.querySelector('[role="region"][aria-label="Prospects Database Table"]');
      const thead = document.querySelector('thead');
      const containerRect = container.getBoundingClientRect();
      const theadRect = thead.getBoundingClientRect();
      return {
        scrollTop: container?.scrollTop,
        theadTopRelativeToContainer: theadRect.top - containerRect.top,
        isHeaderStickyAtTop: Math.abs(theadRect.top - containerRect.top) <= 2
      };
    }`);
    console.log('Vertical Scroll Sticky Header Result:', JSON.stringify(verticalStats, null, 2));
    await capture('leads_vertical_scroll_sticky_header');

    // TEST 8: Pagination Interaction (Page 2 & Rows per page)
    console.log('\n======================================================');
    console.log('TEST 8: Pagination Navigation & Row Size');
    console.log('======================================================');
    const paginationTest = await evaluate(`() => {
      const nextBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Next');
      if (nextBtn) nextBtn.click();
      const pageSpan = document.querySelector('span.px-2.font-medium');
      const rows = document.querySelectorAll('tbody tr');
      const paginationInfo = document.querySelector('.bg-slate-50.dark\\:bg-slate-800\\/60')?.innerText;
      return {
        clickedNext: !!nextBtn,
        pageLabel: pageSpan?.innerText,
        rowsCountOnPage: rows.length,
        paginationInfo
      };
    }`);
    console.log('Pagination Result:', JSON.stringify(paginationTest, null, 2));
    await capture('leads_pagination_page_2');

    console.log('\n======================================================');
    console.log(`ALL TESTS COMPLETED! Total errors: ${errors.length}`);
    console.log('Captured Screenshots:');
    for (const [k, v] of Object.entries(screenshots)) {
      console.log(` - ${k}: ${v}`);
    }
    console.log('======================================================\n');

    ws.close();
  } catch (err) {
    console.error('Fatal error during test run:', err);
    exitCode = 1;
  } finally {
    try { chrome.kill(); } catch {}
    try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
    process.exit(exitCode);
  }
}

run();
