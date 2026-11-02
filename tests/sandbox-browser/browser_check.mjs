// Node half of the runpod/browser checks; see check.sh. ESM on purpose: a
// bare `import 'playwright'` ignores NODE_PATH, so this is what proves the
// global install resolves from any directory.
//
//   node browser_check.mjs <url> <out.png>
import { chromium } from 'playwright';

const [url, out] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(url);
await page.screenshot({ path: out });
await browser.close();
console.log(out);
