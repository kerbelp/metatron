---
type: Metatron Decision
scope: metatron/webui/app
confidence: high
source_refs:
  - metatron/webui/app/index.html
  - metatron/webui/app/boot_state.js
  - package.json
---

## Pattern
The front-end has no build step: `.jsx` files are transpiled in the browser by
Babel standalone, loaded via `<script type="text/babel">` in `index.html`
(script order matters). Use plain ASCII quotes in JSX — a single typographic
("curly") quote breaks Babel at load time and blanks the whole app. Extract any
testable logic into plain `.js` modules with `node:test` suites (`npm test`);
`.jsx` files stay presentational.

## Rationale
No build step means no node toolchain to install for a self-hosted, on-prem
tool — `metatron ui` just serves static files. The cost is that syntax errors
surface only at load time, hence the ASCII-quote rule and the logic/presentation
split that keeps everything testable outside a browser.
