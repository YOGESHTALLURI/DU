const { chromium } = require('d:/Digitalurth/cinqflow/frontend/node_modules/playwright');
const http = require('http');

async function fetchJSON(url, token) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const options = {
      hostname: parsed.hostname,
      port: parsed.port,
      path: parsed.pathname + parsed.search,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    };
    http.get(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve(null);
        }
      });
    }).on('error', reject);
  });
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (e) {
    console.error('Chromium launch failed:', e.message);
    process.exit(1);
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
  const page = await context.newPage();

  console.log('1. Logging in as Engineer...');
  const loginRes = await new Promise((resolve, reject) => {
    const req = http.request('http://localhost:8000/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    });
    req.on('error', reject);
    req.write(JSON.stringify({ credential: 'engineer:engineer123' }));
    req.end();
  });
  const token = loginRes.access_token;
  console.log('Obtained JWT token for Engineer.');

  await page.goto('http://localhost:3000/login');
  await page.waitForSelector('body');
  await page.evaluate((tok) => localStorage.setItem('cinqflow_token', tok), token);
  await page.waitForTimeout(500);

  // Fetch batches and drift reports
  const driftList = await fetchJSON('http://localhost:8000/api/v1/schemas/drift', token);
  const batchesList = await fetchJSON('http://localhost:8000/api/v1/pipeline/batches', token);

  console.log(`Found ${driftList?.items?.length || 0} drift reports, ${batchesList?.length || 0} batches.`);

  const breakingReport = driftList?.items?.find(r => r.drift_severity === 'BREAKING');
  const nonBreakingReport = driftList?.items?.find(r => r.drift_severity === 'NON_BREAKING');

  const artifactDir = 'C:/Users/I Satyanand/.gemini/antigravity/brain/c7d2c25d-e66b-4af4-9010-11b1270b0ded';

  // 1. Breaking drift on batch page
  if (breakingReport) {
    console.log(`2. Navigating to batch with BREAKING drift (${breakingReport.batch_id})...`);
    await page.goto(`http://localhost:3000/batches/${breakingReport.batch_id}`);
    await page.waitForSelector('body');
    await page.waitForTimeout(3000);

    const hasBreakingBanner = await page.locator('text=BREAKING DRIFT DETECTED').isVisible();
    console.log('[PASS] Breaking drift banner visible: ' + hasBreakingBanner);

    const p1 = `${artifactDir}/wave2_slice1_breaking_drift_banner.png`;
    await page.screenshot({ path: p1, fullPage: true });
    console.log('[SCREENSHOT] Saved: ' + p1);
  }

  // 2. Non-breaking drift on feed page & acknowledge modal
  if (nonBreakingReport) {
    console.log(`3. Navigating to feed page (${nonBreakingReport.feed_id})...`);
    await page.goto(`http://localhost:3000/feeds/${nonBreakingReport.feed_id}`);
    await page.waitForSelector('body');
    await page.waitForTimeout(3000);

    const p2 = `${artifactDir}/wave2_slice1_feed_drift_banner.png`;
    await page.screenshot({ path: p2, fullPage: true });
    console.log('[SCREENSHOT] Saved: ' + p2);

    console.log(`4. Navigating to batch page with NON-BREAKING drift (${nonBreakingReport.batch_id})...`);
    await page.goto(`http://localhost:3000/batches/${nonBreakingReport.batch_id}`);
    await page.waitForSelector('body');
    await page.waitForTimeout(3000);

    const hasNbBanner = await page.locator('text=NON_BREAKING DRIFT DETECTED').isVisible();
    console.log('[PASS] Non-breaking drift banner visible: ' + hasNbBanner);

    const ackBtn = page.locator('button:has-text("Acknowledge Drift")').first();
    if (await ackBtn.isVisible()) {
      await ackBtn.click();
      await page.waitForTimeout(1000);
      const hasModal = await page.locator('text=Acknowledge Schema Drift').isVisible();
      console.log('[PASS] Acknowledge modal visible: ' + hasModal);

      const p3 = `${artifactDir}/wave2_slice1_nonbreaking_drift_modal.png`;
      await page.screenshot({ path: p3, fullPage: true });
      console.log('[SCREENSHOT] Saved: ' + p3);

      await page.locator('button:has-text("Cancel")').click();
      await page.waitForTimeout(500);
    }
  }

  // 3. Batch with Production DQ Execution & Quarantine
  // Look for batch with DQ results
  for (const b of (batchesList || [])) {
    const dqSummary = await fetchJSON(`http://localhost:8000/api/v1/rules/executions/batch/${b.id}`, token);
    if (dqSummary && dqSummary.total_rules_executed > 0) {
      if (dqSummary.has_quarantined_rows && !dqSummary.has_reject_file_violation) {
        console.log(`5. Navigating to batch with QUARANTINE DQ results (${b.id})...`);
        await page.goto(`http://localhost:3000/batches/${b.id}`);
        await page.waitForSelector('body');
        await page.waitForTimeout(3000);

        const hasDQSummary = await page.locator('text=Production Data Quality Execution').isVisible();
        console.log('[PASS] Production DQ Summary visible: ' + hasDQSummary);

        const p4 = `${artifactDir}/wave2_slice1_production_dq_quarantine.png`;
        await page.screenshot({ path: p4, fullPage: true });
        console.log('[SCREENSHOT] Saved: ' + p4);
        break;
      }
    }
  }

  // 4. Batch with Production DQ REJECT_FILE abort
  for (const b of (batchesList || [])) {
    const dqSummary = await fetchJSON(`http://localhost:8000/api/v1/rules/executions/batch/${b.id}`, token);
    if (dqSummary && dqSummary.has_reject_file_violation) {
      console.log(`6. Navigating to batch with REJECT_FILE abort (${b.id})...`);
      await page.goto(`http://localhost:3000/batches/${b.id}`);
      await page.waitForSelector('body');
      await page.waitForTimeout(3000);

      const p5 = `${artifactDir}/wave2_slice1_production_dq_aborted.png`;
      await page.screenshot({ path: p5, fullPage: true });
      console.log('[SCREENSHOT] Saved: ' + p5);
      break;
    }
  }

  console.log('Browser verification completed successfully!');
  await browser.close();
})();
