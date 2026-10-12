### Runpod Sandbox — Browser

**A headless Chromium with Playwright, ready in a Runpod Sandbox.**

Use it to review a UI change, screenshot a deployed page, or run end-to-end tests. Nothing has to be downloaded first, so it works even when the sandbox has no outbound access beyond the site under test.

### What's included
- **Playwright 1.63.0** for both **Python** (`from playwright.sync_api import sync_playwright`) and **Node** (`require('playwright')` or `import { chromium } from 'playwright'`), sharing one pinned **Chromium** in `/ms-playwright`.
- **Fonts for real pages**: CJK (IPA Gothic, WenQuanYi Zen Hei), Noto Color Emoji, Liberation and FreeFont, so screenshots render without tofu boxes.
- **`playwright screenshot <url> <out.png>`**, Playwright's own CLI, for the common case without writing a script. See `playwright screenshot --help` for `--full-page`, `--device`, `--color-scheme`, `--wait-for-selector` and more.
- Everything from the Ubuntu sandbox image: Python 3.14, `uv`, Node.js 24, `git`, `tmux` and the usual build tooling.
- **Unprivileged by default**: commands run as `user`.

### Quick start

```bash
playwright screenshot https://example.com example.png
playwright screenshot --full-page --device "Pixel 7" https://example.com mobile.png
```

`playwright screenshot` captures whatever the server returns, including a 404 or 500 page, and still exits 0. Look at the image, or use a script and check `response.status`, when that matters.

Use Android devices for mobile emulation. iPhone and iPad descriptors always launch WebKit, even with `-b chromium`, and only Chromium is baked in.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")
    page.screenshot(path="example.png")
    browser.close()
```

```js
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('https://example.com');
  await page.screenshot({ path: 'example.png' });
  await browser.close();
})();
```

### Notes
- **No launch flags needed.** Playwright already starts Chromium with `--no-sandbox` (the sandbox itself is the isolation boundary) and `--disable-dev-shm-usage`, so the size of `/dev/shm` does not matter. Do not pass `chromiumSandbox: true`.
- **Keep to a few pages at once.** A single page fits comfortably in the default 2 vCPU / 4 GB sandbox, and each extra page or context adds a few hundred MB. Running out of memory restarts the whole sandbox and loses its state, so close browsers you are done with.
- **Only Chromium is baked in.** `playwright install firefox` works if the sandbox can reach Playwright's CDN.
- **Your own Playwright version:** a project's `node_modules` takes precedence over the global one, but a different Playwright version expects a different browser build, and that one is not baked in.
