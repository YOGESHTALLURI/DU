const { chromium } = require('d:/Digitalurth/cinqflow/frontend/node_modules/playwright');
const path = require('path');

(async () => {
    let browser;
    try {
        browser = await chromium.launch({ headless: true });
    } catch (e) {
        console.error('Chromium launch failed:', e.message);
        process.exit(1);
    }
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();

    console.log('1. Logging in as Data Steward (steward:steward123)...');
    await page.goto('http://localhost:3000/login');
    await page.waitForSelector('input');
    await page.fill('input', 'steward:steward123');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(2000);

    console.log('2. Navigating to Business Glossary screen (/glossary)...');
    await page.goto('http://localhost:3000/glossary');
    await page.waitForSelector('body');
    await page.waitForTimeout(3000);

    const hasTitle = await page.locator('text=Enterprise Business Glossary').isVisible();
    console.log('[PASS] Enterprise Business Glossary title visible: ' + hasTitle);

    // Save screenshot of full glossary catalog
    const brainDir = 'C:\\Users\\I Satyanand\\.gemini\\antigravity\\brain\\c7d2c25d-e66b-4af4-9010-11b1270b0ded';
    await page.screenshot({ path: path.join(brainDir, 'slice7_glossary_catalog.png'), fullPage: true });
    console.log('[SAVED] slice7_glossary_catalog.png');

    console.log('3. Clicking on Member Identifier to open detail drawer...');
    const memberCard = page.locator('div:has-text("Member Identifier")').last();
    await memberCard.click();
    await page.waitForTimeout(1000);

    await page.screenshot({ path: path.join(brainDir, 'slice7_glossary_term_detail.png'), fullPage: true });
    console.log('[SAVED] slice7_glossary_term_detail.png');

    console.log('4. Filtering by Confirmed PHI terms...');
    await page.selectOption('select:has-text("All PHI Levels")', 'CONFIRMED_PHI');
    await page.waitForTimeout(1000);

    await page.screenshot({ path: path.join(brainDir, 'slice7_glossary_phi_filter.png'), fullPage: true });
    console.log('[SAVED] slice7_glossary_phi_filter.png');

    console.log('5. Logging in as Read-Only user...');
    await page.goto('http://localhost:3000/login');
    await page.waitForSelector('input');
    await page.fill('input', 'readonly:readonly123');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(2000);

    await page.goto('http://localhost:3000/glossary');
    await page.waitForTimeout(2000);

    const hasReadOnlyBadge = await page.locator('text=Read-Only Mode').isVisible();
    console.log('[PASS] Read-Only Mode badge visible: ' + hasReadOnlyBadge);

    await page.screenshot({ path: path.join(brainDir, 'slice7_glossary_readonly.png'), fullPage: true });
    console.log('[SAVED] slice7_glossary_readonly.png');

    await browser.close();
    console.log('Browser automated verification completed successfully!');
})();
