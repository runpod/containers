// CommonJS twin of browser_check.mjs: require() resolves differently from
// import, and agents write both.
//
//   node browser_check.cjs <url> <out.png>
const { chromium } = require('playwright');

(async () => {
  const [url, out] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(url);
  await page.screenshot({ path: out });
  await browser.close();
  console.log(out);
})();
