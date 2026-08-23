const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const appSource = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const shellSource = fs.readFileSync(path.join(root, "web", "index.html"), "utf8")
  .replace(/<script>[\s\S]*?<\/script>/, "")
  .replace('data-base="/"', 'data-base="/docs"');

const fixtures = {
  "/docs/index.json": {
    title: "Atlas Docs",
    spaces: [
      { id: "", navKey: "home", label: "Home", route: "/", showInMenu: true },
      { id: "guide", navKey: "guide", label: "Guide", route: "/guide", hasCode: true, showInMenu: true },
    ],
  },
  "/docs/nav/guide.json": [
    {
      kind: "group",
      label: "Guide",
      index: "/guide",
      items: [
        { kind: "page", label: "Setup", route: "/guide/setup" },
        { kind: "page", label: "Slow", route: "/guide/slow" },
        { kind: "page", label: "Source", route: "/guide/code/sample.cs" },
      ],
    },
  ],
  "/docs/nav/guide.code.json": [
    { kind: "code", label: "sample.cs", route: "/guide/code/sample.cs" },
  ],
  "/docs/nav/home.json": [
    { kind: "page", label: "Welcome", route: "/" },
  ],
  "/docs/content/index.json": {
    title: "Welcome",
    crumb: "docs/_index.md",
    html: "<h1>Welcome</h1><p>Neutral documentation.</p>",
    toc: [],
    prev: null,
    next: { route: "/guide", title: "Guide" },
  },
  "/docs/content/guide/index.json": {
    title: "Guide",
    crumb: "docs/guide/_index.md",
    html: '<h1>Guide</h1><h2 id="start">Start</h2><p>Choose a page.</p>',
    toc: [[2, "start", "Start"]],
    prev: { route: "/", title: "Welcome" },
    next: { route: "/guide/setup", title: "Setup" },
  },
  "/docs/content/guide/setup.json": {
    title: "Setup",
    crumb: "docs/guide/setup.md",
    html: [
      "<h1>Setup</h1>",
      '<script>window.__unsafe = true</script>',
      '<img id="unsafe-image" src="missing" onerror="window.__unsafe = true">',
      '<a id="unsafe-link" href="javascript:alert(1)">Unsafe link</a>',
      '<style id="unsafe-style">body{display:none}</style>',
      '<svg id="safe-figure" style="position:fixed"><style>body{display:none}</style><title>Safe figure</title></svg>',
      '<h2 id="install">Install</h2>',
      '<div class="tabs"><div class="tab-bar">',
      '<button class="tab-btn active" data-tab="0">One</button>',
      '<button class="tab-btn" data-tab="1">Two</button>',
      "</div>",
      '<div class="tab-pane active" data-pane="0"><p>First pane</p></div>',
      '<div class="tab-pane" data-pane="1"><p>Second pane</p></div>',
      "</div>",
      "<div class=\"codeblock\"><pre><code>const safe = true;</code></pre></div>",
    ].join(""),
    toc: [[2, "install", "Install"]],
    prev: { route: "/guide", title: "Guide" },
    next: { route: "/guide/code/sample.cs", title: "Source" },
  },
  "/docs/content/guide/slow.json": {
    title: "Slow",
    crumb: "docs/guide/slow.md",
    html: "<h1>Slow</h1>",
    toc: [],
    prev: null,
    next: null,
  },
  "/docs/content/guide/code/sample.cs.json": {
    kind: "code",
    title: "sample.cs",
    path: "sample.cs",
    lines: ["one", "two"],
    sourceUrl: "https://example.com/source",
    html: '<div class="source-lines not-prose"><table><tbody><tr id="L-1"><th><a href="#L-1" aria-label="line 1">1</a></th><td><pre><code>one</code></pre></td></tr><tr id="L-2"><th><a href="#L-2" aria-label="line 2">2</a></th><td><pre><code>two</code></pre></td></tr></tbody></table></div>',
  },
  "/docs/search.json": [
    { route: "/guide/setup", title: "Setup", text: "Install the package.", spaceId: "guide", space: "Guide", path: "setup" },
  ],
};

const dom = new JSDOM(shellSource, {
  url: "https://docs.example.test/docs/guide/setup",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;
window.scrollTo = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};
window.fetch = async (input) => {
  const pathname = new URL(String(input), window.location.href).pathname;
  if (pathname === "/docs/content/guide/slow.json") {
    await new Promise((resolve) => setTimeout(resolve, 60));
  }
  if (!Object.prototype.hasOwnProperty.call(fixtures, pathname)) {
    return { ok: false, status: 404, json: async () => ({}) };
  }
  return { ok: true, status: 200, json: async () => structuredClone(fixtures[pathname]) };
};

let copied = "";
Object.defineProperty(window.navigator, "clipboard", {
  configurable: true,
  value: { writeText: async (value) => { copied = value; } },
});
Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });

function waitFor(test, message) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const poll = () => {
      if (test()) { resolve(); return; }
      attempts += 1;
      if (attempts > 100) { reject(new Error(message)); return; }
      setTimeout(poll, 10);
    };
    poll();
  });
}

(async () => {
  window.eval(appSource);
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Setup", "initial route did not render");

  assert.equal(window.document.querySelector("#brand").textContent, "Atlas Docs");
  assert.equal(window.document.querySelector("#brand").getAttribute("href"), "/docs/");
  assert.equal(window.document.querySelectorAll("#space-links .space-link").length, 2);
  assert.equal(window.document.querySelector("#page-nav .nav-link.is-active").textContent, "Setup");
  const tocUrl = new URL(window.document.querySelector("#tocbar .toc-link").href);
  assert.equal(tocUrl.pathname + tocUrl.hash, "/docs/guide/setup#install");

  assert.equal(window.__unsafe, undefined);
  assert.equal(window.document.querySelector("#article script"), null);
  assert.equal(window.document.querySelector("#unsafe-image").hasAttribute("onerror"), false);
  assert.equal(window.document.querySelector("#unsafe-link").hasAttribute("href"), false);
  assert.equal(window.document.querySelector("#unsafe-style"), null);
  assert.equal(window.document.querySelector("#safe-figure style"), null);
  assert.equal(window.document.querySelector("#safe-figure").hasAttribute("style"), false);

  const secondTab = window.document.querySelectorAll(".tab-btn")[1];
  secondTab.click();
  assert.equal(secondTab.getAttribute("aria-selected"), "true");
  assert.equal(window.document.querySelector('[data-pane="0"]').hidden, true);
  assert.equal(window.document.querySelector('[data-pane="1"]').hidden, false);

  window.document.querySelector("#theme-button").click();
  assert.equal(window.document.documentElement.getAttribute("data-theme"), "dark");

  window.document.querySelector("#search-button").click();
  await waitFor(() => window.document.querySelector("#search-dialog").hasAttribute("open"), "search did not open");
  const searchInput = window.document.querySelector("#search-input");
  searchInput.value = "install";
  searchInput.dispatchEvent(new window.Event("input", { bubbles: true }));
  await waitFor(() => Boolean(window.document.querySelector(".search-result")), "search result did not render");
  assert.equal(window.document.querySelector(".search-result strong").textContent, "Setup");

  window.document.querySelector(".page-link.next").click();
  await waitFor(() => Boolean(window.document.querySelector(".code-page")), "code route did not render");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#article"), "route change did not move focus to content");
  assert.equal(window.location.pathname, "/docs/guide/code/sample.cs");
  assert.deepEqual(Array.from(window.document.querySelectorAll(".code-page-body code"), (code) => code.textContent), ["one", "two"]);
  assert.equal(window.document.querySelector(".code-page-body .copy"), null);
  assert.equal(window.document.querySelector(".source-nav .nav-group-label").textContent, "Source");
  assert.equal(window.document.querySelector(".source-file.is-active").textContent, "sample.cs");
  window.document.querySelector(".code-page-copy").click();
  await waitFor(() => copied === "one\ntwo", "copy did not use only the rendered source text");

  const guideSpace = Array.from(window.document.querySelectorAll("#space-links .space-link"))
    .find((link) => link.textContent === "Guide");
  guideSpace.click();
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Guide", "directory index fallback did not render");
  assert.equal(window.location.pathname, "/docs/guide");

  const navLinks = Array.from(window.document.querySelectorAll("#page-nav .nav-link"));
  navLinks.find((link) => link.textContent === "Slow").click();
  navLinks.find((link) => link.textContent === "Setup").click();
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Setup", "newer route did not win");
  await new Promise((resolve) => setTimeout(resolve, 90));
  assert.equal(window.document.querySelector("#article h1").textContent, "Setup");

  window.document.querySelector("#brand").click();
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Welcome", "root index did not render");
  assert.equal(window.location.pathname, "/docs/");

  const alternateDom = new JSDOM(shellSource, {
    url: "https://docs.example.test/docs/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const alternateWindow = alternateDom.window;
  alternateWindow.scrollTo = () => {};
  alternateWindow.HTMLElement.prototype.scrollIntoView = () => {};
  const alternateFiles = {
    "/docs/index.json": {
      title: "Space Docs",
      spaces: [
        { id: "alpha", navKey: "alpha", label: "Alpha", route: "/alpha", showInMenu: true },
        { id: "beta", navKey: "beta", label: "Beta", route: "/beta", showInMenu: true },
      ],
    },
    "/docs/nav/alpha.json": [{ kind: "page", label: "Alpha home", route: "/alpha" }],
    "/docs/content/alpha/index.json": {
      title: "Alpha home",
      crumb: "docs/alpha/_index.md",
      html: "<h1>Alpha home</h1>",
      toc: [],
      prev: null,
      next: null,
    },
  };
  alternateWindow.fetch = async (input) => {
    const pathname = new URL(String(input), alternateWindow.location.href).pathname;
    if (!Object.prototype.hasOwnProperty.call(alternateFiles, pathname)) {
      return { ok: false, status: 404, json: async () => ({}) };
    }
    return { ok: true, status: 200, json: async () => structuredClone(alternateFiles[pathname]) };
  };
  alternateWindow.eval(appSource);
  await waitFor(
    () => alternateWindow.document.querySelector("#article h1")?.textContent === "Alpha home",
    "a valid non-root-only configuration did not select a home route",
  );
  assert.equal(alternateWindow.location.pathname, "/docs/alpha");
  assert.equal(new URL(alternateWindow.document.querySelector("#brand").href).pathname, "/docs/alpha");
  alternateDom.window.close();

  console.log("docs SPA smoke test passed");
  dom.window.close();
})().catch((error) => {
  console.error(error);
  dom.window.close();
  process.exitCode = 1;
});
