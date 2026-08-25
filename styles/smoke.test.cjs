const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const appSource = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const prismSource = fs.readFileSync(path.join(root, "web", "prism.js"), "utf8");
const appCssSource = fs.readFileSync(path.join(root, "styles", "app.src.css"), "utf8");
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
      planCount: 145,
      items: [
        { kind: "page", label: "Setup", route: "/guide/setup", planCount: 7 },
        { kind: "page", label: "Slow", route: "/guide/slow", planCount: 120 },
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
      '<div class="tab-pane" data-pane="1"><div class="codeblock"><pre><code class="language-javascript">const tabbed = true;</code></pre></div></div>',
      "</div>",
      "<div class=\"codeblock\"><pre><code class=\"language-javascript\">const safe = true;</code></pre></div>",
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

const reviewRecords = [
  {
    id: "rc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    route: "/guide/setup",
    anchor: "install",
    quote: "Install the package.",
    body: '<img id="review-xss" src=x onerror=alert(1)> Could this be clearer?',
    status: "answered",
    reply: "The setup explanation was expanded by the documentation skill.",
    createdAt: "2026-08-24T01:00:00.000Z",
    updatedAt: "2026-08-24T01:05:00.000Z",
  },
];
let lastReviewPost = null;
let lastReviewPatch = null;
let failReviewGet = false;
let rejectNextReviewPatch = true;
let reviewPostCount = 0;
let reviewPostDelay = 25;
let reviewPostResponses = 0;

const dom = new JSDOM(shellSource, {
  url: "https://docs.example.test/docs/guide/setup",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;
window.scrollTo = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};
let selectionRect = { left: 200, top: 190, right: 320, bottom: 212, width: 120, height: 22 };
let coarsePointer = false;
let visualOffsetLeft = 0;
let visualOffsetTop = 0;
let visualWidth = null;
let visualHeight = null;
const visualViewport = new window.EventTarget();
Object.defineProperties(visualViewport, {
  width: { get: () => visualWidth ?? window.innerWidth },
  height: { get: () => visualHeight ?? window.innerHeight },
  offsetLeft: { get: () => visualOffsetLeft },
  offsetTop: { get: () => visualOffsetTop },
});
Object.defineProperty(window, "visualViewport", { configurable: true, value: visualViewport });
window.Range.prototype.getBoundingClientRect = () => ({ ...selectionRect });
window.Range.prototype.getClientRects = () => [{ ...selectionRect }];
window.matchMedia = (query) => ({
  matches: query.includes("pointer") ? coarsePointer : query.includes("max-width") ? window.innerWidth <= 640 : false,
  media: query,
  addEventListener() {},
  removeEventListener() {},
});
window.fetch = async (input, options = {}) => {
  const url = new URL(String(input), window.location.href);
  const pathname = url.pathname;
  const method = String(options.method || "GET").toUpperCase();
  if (pathname === "/docs/__agent-docs/review/comments" && method === "GET") {
    if (failReviewGet) { return { ok: false, status: 500, json: async () => ({ error: "test failure" }) }; }
    const route = url.searchParams.get("route");
    return {
      ok: true,
      status: 200,
      json: async () => ({
        schemaVersion: 1,
        comments: reviewRecords.filter((comment) => !route || comment.route === route).map((comment) => structuredClone(comment)),
      }),
    };
  }
  if (pathname === "/docs/__agent-docs/review/comments" && method === "POST") {
    lastReviewPost = JSON.parse(options.body);
    reviewPostCount += 1;
    const comment = {
      id: `rc_${(reviewPostCount === 1 ? "b" : "c").repeat(32)}`,
      ...lastReviewPost,
      status: "open",
      createdAt: "2026-08-24T02:00:00.000Z",
      updatedAt: "2026-08-24T02:00:00.000Z",
    };
    reviewRecords.unshift(comment);
    await new Promise((resolve) => setTimeout(resolve, reviewPostDelay));
    reviewPostResponses += 1;
    return { ok: true, status: 201, json: async () => ({ schemaVersion: 1, comment: structuredClone(comment) }) };
  }
  const reviewPatch = pathname.match(/^\/docs\/__agent-docs\/review\/comments\/(rc_[a-f0-9]{32})$/);
  if (reviewPatch && method === "PATCH") {
    lastReviewPatch = JSON.parse(options.body);
    const comment = reviewRecords.find((candidate) => candidate.id === reviewPatch[1]);
    if (rejectNextReviewPatch || (lastReviewPatch.status === "resolved" && !comment.reply)) {
      rejectNextReviewPatch = false;
      return { ok: false, status: 409, json: async () => ({ error: "invalid review status transition" }) };
    }
    Object.assign(comment, lastReviewPatch, { updatedAt: "2026-08-24T03:00:00.000Z" });
    return { ok: true, status: 200, json: async () => ({ schemaVersion: 1, comment: structuredClone(comment) }) };
  }
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
  window.Prism = { manual: true };
  window.eval(prismSource);
  window.eval(appSource);
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Setup", "initial route did not render");
  assert.equal(window.document.querySelector("#article .token.keyword").textContent, "const");
  await waitFor(() => !window.document.querySelector("#review-button").hidden, "review endpoint did not enable comments");

  assert.equal(window.document.querySelector("#review-count").textContent, "1");
  assert.equal(window.document.querySelector("#review-panel").hidden, true);
  assert.equal(window.document.querySelector("#review-xss"), null);
  assert.match(window.document.querySelector(".review-comment-body").textContent, /<img id="review-xss"/);
  assert.equal(window.document.querySelector(".review-status").textContent, "Answered");
  assert.equal(window.document.querySelector(".review-reply strong").textContent, "Skill reply");
  assert.match(window.document.querySelector(".review-reply p").textContent, /documentation skill/);

  const reviewSelectionNode = window.document.querySelector('[data-pane="0"] p').firstChild;
  const reviewRange = window.document.createRange();
  reviewRange.selectNodeContents(reviewSelectionNode);
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(reviewRange);
  window.document.dispatchEvent(new window.Event("selectionchange"));
  const selectionAction = window.document.querySelector("#review-selection-action");
  await waitFor(() => !selectionAction.hidden, "selection action did not appear");
  assert.equal(selectionAction.textContent, "Add comment");
  assert.equal(selectionAction.getAttribute("aria-label"), "Add a comment about selected text");
  assert.ok(parseFloat(selectionAction.style.left) > selectionRect.right);
  const preserveSelection = new window.Event("pointerdown", { bubbles: true, cancelable: true });
  selectionAction.dispatchEvent(preserveSelection);
  assert.equal(preserveSelection.defaultPrevented, true);

  selectionAction.click();
  const reviewCompose = window.document.querySelector("#review-compose");
  await waitFor(() => !reviewCompose.hidden, "contextual comment editor did not open");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#review-body"), "review form did not receive focus");
  assert.equal(window.document.querySelector("#review-panel").hidden, true);
  assert.equal(reviewCompose.getAttribute("role"), "dialog");
  assert.equal(reviewCompose.hasAttribute("aria-modal"), false);
  assert.equal(window.document.querySelector("#review-body").getAttribute("aria-describedby"), "review-selection review-form-status");
  assert.equal(reviewCompose.dataset.placement, "right");
  assert.ok(parseFloat(reviewCompose.style.left) > parseFloat(selectionAction.style.left));
  assert.equal(selectionAction.getAttribute("aria-expanded"), "true");
  assert.equal(window.document.querySelector("#review-selection-text").textContent, "First pane");
  assert.equal(window.document.querySelector("#review-selection-anchor").textContent, "#install");
  assert.equal(window.document.querySelector(".topbar").hasAttribute("inert"), false);
  assert.equal(window.document.querySelector(".shell").hasAttribute("inert"), false);
  window.document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
  assert.equal(window.document.querySelector("#search-dialog").hasAttribute("open"), false);

  reviewCompose.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  await waitFor(() => reviewCompose.hidden, "Escape did not close the contextual editor");
  await waitFor(() => window.document.activeElement === selectionAction, "Escape did not restore selection-action focus");
  assert.equal(selectionAction.getAttribute("aria-expanded"), "false");
  assert.equal(selectionAction.hidden, false);

  selectionAction.click();
  await waitFor(() => !reviewCompose.hidden, "dirty contextual editor did not reopen");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#review-body"), "dirty editor did not receive focus");
  window.document.querySelector("#review-body").value = "Keep this draft";
  window.document.querySelector("#review-body").dispatchEvent(new window.Event("input", { bubbles: true }));
  window.document.querySelector("#article").focus();
  window.document.querySelector("#article").dispatchEvent(new window.Event("pointerdown", { bubbles: true }));
  assert.equal(reviewCompose.hidden, false);
  assert.equal(window.document.querySelector("#review-body").value, "Keep this draft");
  assert.equal(window.document.activeElement, window.document.querySelector("#article"));

  selectionRect = { left: 200, top: -180, right: 320, bottom: -158, width: 120, height: 22 };
  window.dispatchEvent(new window.Event("scroll"));
  await waitFor(() => reviewCompose.dataset.placement === "sheet", "dirty scrolled draft was not docked safely");
  assert.equal(reviewCompose.hidden, false);
  assert.equal(window.document.querySelector("#review-body").value, "Keep this draft");

  selectionRect = { left: 200, top: 190, right: 320, bottom: 212, width: 120, height: 22 };
  window.dispatchEvent(new window.Event("scroll"));
  await waitFor(() => reviewCompose.dataset.placement === "right", "docked draft did not return to its selection");
  reviewCompose.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  assert.equal(reviewCompose.hidden, false);
  assert.equal(window.document.querySelector("#review-form-status").textContent, "Draft kept open. Use Cancel to discard it.");
  window.document.querySelector("#review-compose-cancel").click();
  await waitFor(() => reviewCompose.hidden, "Cancel did not discard the contextual draft");
  assert.equal(window.document.querySelector("#review-body").value, "");
  await waitFor(() => window.document.activeElement === selectionAction, "Cancel did not restore selection-action focus");

  selectionAction.click();
  await waitFor(() => !reviewCompose.hidden, "empty contextual editor did not reopen");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#review-body"), "empty editor did not receive focus");
  window.document.querySelector("#article").focus();
  window.document.querySelector("#article").dispatchEvent(new window.Event("pointerdown", { bubbles: true }));
  assert.equal(reviewCompose.hidden, true);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(window.document.activeElement, window.document.querySelector("#article"));

  window.getSelection().removeAllRanges();
  window.getSelection().addRange(reviewRange);
  window.document.dispatchEvent(new window.Event("selectionchange"));
  await waitFor(() => !selectionAction.hidden, "selection action did not return after reselecting text");
  selectionAction.click();
  await waitFor(() => !reviewCompose.hidden, "contextual editor did not reopen from its cached selection");

  window.document.querySelector("#review-body").value = "Please add one more example.";
  window.document.querySelector("#review-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  window.document.querySelector("#review-refresh").click();
  await waitFor(() => window.document.querySelectorAll(".review-comment").length === 2, "review comment was not saved");
  await waitFor(() => window.document.querySelector("#review-live-status").textContent === "Comment saved.", "review save did not finish");
  assert.equal(reviewCompose.hidden, true);
  assert.equal(selectionAction.hidden, true);
  await waitFor(() => window.document.activeElement === window.document.querySelector("#article"), "saved comment did not return focus to the article");
  assert.equal(window.document.querySelectorAll(".review-comment").length, 2);
  assert.deepEqual(
    Array.from(window.document.querySelectorAll(".review-comment"), (comment) => comment.dataset.reviewId),
    ["rc_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "rc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
  );
  assert.deepEqual(lastReviewPost, {
    route: "/guide/setup",
    body: "Please add one more example.",
    anchor: "install",
    quote: "First pane",
  });

  const openComment = window.document.querySelector('[data-review-id="rc_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]');
  assert.equal(openComment.querySelector(".review-status").textContent, "Open");
  assert.equal(openComment.querySelector(".review-status-button"), null);
  assert.equal(openComment.querySelector(".review-awaiting").textContent, "Awaiting skill reply");
  assert.equal(lastReviewPatch, null);

  window.document.querySelector("#review-button").focus();
  window.document.querySelector("#review-button").click();
  await waitFor(() => !window.document.querySelector("#review-panel").hidden, "global comment drawer did not open");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#review-close"), "comment drawer did not receive focus");
  assert.match(window.document.querySelector(".review-skill-hint").textContent, /\$docs-authoring/);
  assert.equal(window.document.querySelector(".topbar").hasAttribute("inert"), true);
  assert.equal(window.document.querySelector(".shell").hasAttribute("inert"), true);

  const pageCommentButton = window.document.querySelector("#review-page-comment");
  pageCommentButton.click();
  await waitFor(() => !reviewCompose.hidden, "page-level comment editor did not open from the drawer");
  assert.equal(reviewCompose.dataset.placement, "drawer");
  assert.equal(reviewCompose.getAttribute("role"), "region");
  assert.equal(window.document.querySelector("#review-selection").hidden, true);
  assert.equal(pageCommentButton.getAttribute("aria-expanded"), "true");
  window.document.querySelector("#review-compose-close").click();
  await waitFor(() => reviewCompose.hidden, "page-level comment editor did not close");
  await waitFor(() => window.document.activeElement === pageCommentButton, "page-level editor did not restore focus");
  assert.equal(pageCommentButton.getAttribute("aria-expanded"), "false");
  assert.equal(reviewCompose.parentElement, window.document.body);
  assert.equal(window.document.querySelector("#review-panel").hidden, false);

  const answeredComment = window.document.querySelector('[data-review-id="rc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]');
  answeredComment.querySelector(".review-status-button").click();
  await waitFor(
    () => window.document.querySelector("#review-panel-status").textContent === "Comment could not be updated. Try again.",
    "rejected review transition was not reported",
  );
  assert.equal(answeredComment.querySelector(".review-status").textContent, "Answered");
  assert.equal(answeredComment.querySelector(".review-status-button").disabled, false);
  answeredComment.querySelector(".review-status-button").click();
  await waitFor(
    () => window.document.querySelector('[data-review-id="rc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] .review-status')?.textContent === "Resolved",
    "review status was not updated",
  );
  const resolvedAction = window.document.querySelector('[data-review-id="rc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] .review-status-button');
  assert.equal(resolvedAction.textContent, "Reopen");
  assert.equal(resolvedAction.dataset.reviewStatus, "open");
  assert.deepEqual(lastReviewPatch, { status: "resolved" });
  assert.equal(window.document.querySelector("#review-count").textContent, "1");
  assert.equal(window.document.querySelector("#review-button").getAttribute("aria-label"), "Page comments, 1 unresolved");
  window.document.querySelector("#review-close").click();
  assert.equal(window.document.querySelector("#review-panel").hidden, true);
  assert.equal(window.document.querySelector("#review-button").getAttribute("aria-expanded"), "false");
  assert.equal(window.document.activeElement, window.document.querySelector("#review-button"));
  assert.equal(window.document.querySelector(".topbar").hasAttribute("inert"), false);
  assert.equal(window.document.querySelector(".shell").hasAttribute("inert"), false);

  window.getSelection().removeAllRanges();
  window.document.querySelector("#review-button").click();
  window.document.querySelector('[data-review-id="rc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] .review-anchor').click();
  await waitFor(() => window.document.activeElement?.id === "install", "review anchor did not restore focus to its heading");
  assert.equal(window.document.querySelector("#review-panel").hidden, true);

  const crossBoundaryRange = window.document.createRange();
  crossBoundaryRange.setStart(reviewSelectionNode, 0);
  crossBoundaryRange.setEnd(
    window.document.querySelector("#review-title").firstChild,
    window.document.querySelector("#review-title").firstChild.length,
  );
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(crossBoundaryRange);
  assert.ok(window.getSelection().toString().length > "First pane".length);
  window.document.dispatchEvent(new window.Event("selectionchange"));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(selectionAction.hidden, true);

  selectionRect = { left: 900, top: 180, right: 980, bottom: 202, width: 80, height: 22 };
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(reviewRange);
  window.document.dispatchEvent(new window.Event("selectionchange"));
  await waitFor(() => !selectionAction.hidden, "edge selection action did not appear");
  selectionAction.click();
  await waitFor(() => !reviewCompose.hidden, "edge contextual editor did not open");
  assert.equal(reviewCompose.dataset.placement, "sheet");
  assert.equal(reviewCompose.style.right, "auto");
  visualOffsetTop = 40;
  visualViewport.dispatchEvent(new window.Event("resize"));
  await waitFor(() => parseFloat(reviewCompose.style.top) >= 104, "visual viewport offset was not respected");
  visualOffsetTop = 0;
  visualViewport.dispatchEvent(new window.Event("resize"));

  visualWidth = 280;
  visualHeight = 240;
  selectionRect = { left: 48, top: 92, right: 104, bottom: 114, width: 56, height: 22 };
  visualViewport.dispatchEvent(new window.Event("resize"));
  await waitFor(() => parseFloat(reviewCompose.style.width) <= 280, "sub-320 visual viewport width was clamped upward");
  const compactSheetTop = parseFloat(reviewCompose.style.top);
  const compactSheetHeight = parseFloat(reviewCompose.style.maxHeight);
  assert.ok(compactSheetTop >= 0);
  assert.ok(compactSheetTop + compactSheetHeight <= 240);
  assert.ok(parseFloat(reviewCompose.style.left) >= 0);
  visualWidth = null;
  visualHeight = null;
  selectionRect = { left: 900, top: 180, right: 980, bottom: 202, width: 80, height: 22 };
  visualViewport.dispatchEvent(new window.Event("resize"));
  window.document.querySelector("#review-compose-cancel").click();
  await waitFor(() => reviewCompose.hidden, "contextual cancel did not close the editor");

  coarsePointer = true;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 480 });
  selectionRect = { left: 120, top: 220, right: 240, bottom: 242, width: 120, height: 22 };
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(reviewRange);
  window.document.dispatchEvent(new window.Event("selectionchange"));
  await waitFor(() => !selectionAction.hidden, "mobile selection action did not appear");
  selectionAction.click();
  await waitFor(() => !reviewCompose.hidden, "drawer fallback editor did not open");
  assert.equal(reviewCompose.dataset.placement, "drawer");
  assert.equal(reviewCompose.getAttribute("role"), "region");
  assert.equal(reviewCompose.parentElement, window.document.querySelector("#review-panel .review-panel-body"));
  assert.equal(window.document.querySelector("#review-panel").hidden, false);
  window.document.querySelector("#review-compose-cancel").click();
  await waitFor(() => reviewCompose.hidden, "drawer fallback cancel did not close the editor");
  assert.equal(reviewCompose.parentElement, window.document.body);
  assert.equal(window.document.querySelector("#review-panel").hidden, false);
  window.document.querySelector("#review-close").click();
  coarsePointer = false;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
  window.getSelection().removeAllRanges();
  window.document.querySelector("#article").dispatchEvent(new window.Event("pointerup", { bubbles: true }));
  window.document.dispatchEvent(new window.Event("selectionchange"));
  await waitFor(() => selectionAction.hidden, "cleared selection action remained visible");

  const restoredSelectionNode = window.document.querySelector('[data-pane="0"] p').firstChild;
  const restoredSelectionRange = window.document.createRange();
  restoredSelectionRange.selectNodeContents(restoredSelectionNode);
  selectionRect = { left: 200, top: 190, right: 320, bottom: 212, width: 120, height: 22 };
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(restoredSelectionRange);
  window.document.dispatchEvent(new window.Event("selectionchange"));
  await waitFor(() => !selectionAction.hidden, "route draft selection action did not appear");
  selectionAction.click();
  await waitFor(() => !reviewCompose.hidden, "route draft editor did not open");
  window.document.querySelector("#review-body").value = "Keep this draft across navigation.";
  window.document.querySelector("#review-body").dispatchEvent(new window.Event("input", { bubbles: true }));
  window.document.querySelector(".page-link.next").click();
  await waitFor(() => Boolean(window.document.querySelector(".code-page")), "route-away draft test did not navigate");
  window.history.back();
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Setup", "route-away draft test did not return");
  await waitFor(() => !window.document.querySelector("#review-button").hidden, "review feature did not recover after Back");
  assert.equal(selectionAction.hidden, true);
  window.document.querySelector("#review-button").click();
  await waitFor(() => !window.document.querySelector("#review-panel").hidden, "restored draft drawer did not open");
  window.document.querySelector("#review-page-comment").click();
  await waitFor(() => !reviewCompose.hidden, "restored route draft did not open");
  assert.equal(reviewCompose.dataset.placement, "drawer");
  assert.equal(window.document.querySelector("#review-body").value, "Keep this draft across navigation.");
  assert.equal(window.document.querySelector("#review-selection-text").textContent, "First pane");
  assert.equal(window.document.querySelector("#review-selection-anchor").textContent, "#install");
  window.document.querySelector("#review-compose-cancel").click();
  await waitFor(() => reviewCompose.hidden, "restored draft Cancel did not close the editor");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#review-page-comment"), "restored draft Cancel did not restore focus");
  window.document.querySelector("#review-close").click();
  await waitFor(() => window.document.querySelector("#review-panel").hidden, "restored draft drawer did not close");

  window.document.querySelector(".page-link.next").click();
  await waitFor(() => Boolean(window.document.querySelector(".code-page")), "cancelled draft verification did not navigate away");
  window.history.back();
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Setup", "cancelled draft verification did not return");
  await waitFor(() => !window.document.querySelector("#review-button").hidden, "review feature did not return after cancelled draft");
  window.document.querySelector("#review-button").click();
  window.document.querySelector("#review-page-comment").click();
  await waitFor(() => !reviewCompose.hidden, "empty page composer did not open after cancelled draft");
  assert.equal(window.document.querySelector("#review-body").value, "");
  assert.equal(window.document.querySelector("#review-selection").hidden, true);

  reviewPostDelay = 400;
  window.document.querySelector("#review-body").value = "Saved while navigating away.";
  window.document.querySelector("#review-body").dispatchEvent(new window.Event("input", { bubbles: true }));
  window.document.querySelector("#review-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  window.document.querySelector("#review-close").click();
  await waitFor(() => window.document.querySelector("#review-panel").hidden, "pending-save drawer did not close");
  window.document.querySelector(".page-link.next").click();
  await waitFor(() => Boolean(window.document.querySelector(".code-page")), "pending-save test did not navigate away");
  window.history.back();
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Setup", "pending-save edit test did not return");
  await waitFor(() => !window.document.querySelector("#review-button").hidden, "review feature did not return while save was pending");
  window.document.querySelector("#review-button").click();
  window.document.querySelector("#review-page-comment").click();
  await waitFor(() => !reviewCompose.hidden, "pending submitted draft did not reopen");
  assert.equal(window.document.querySelector("#review-body").value, "Saved while navigating away.");
  window.document.querySelector("#review-body").value = "A newer draft created before the first save completed.";
  window.document.querySelector("#review-body").dispatchEvent(new window.Event("input", { bubbles: true }));
  window.document.querySelector("#review-close").click();
  await waitFor(() => window.document.querySelector("#review-panel").hidden, "newer-draft drawer did not close");
  window.document.querySelector(".page-link.next").click();
  await waitFor(() => Boolean(window.document.querySelector(".code-page")), "newer-draft test did not navigate away");
  await waitFor(() => reviewPostResponses === 2, "delayed review POST did not complete after newer draft snapshot");
  window.history.back();
  await waitFor(() => window.document.querySelector("#article h1")?.textContent === "Setup", "newer-draft test did not return");
  await waitFor(() => !window.document.querySelector("#review-button").hidden, "review feature did not return after delayed save");
  window.document.querySelector("#review-button").click();
  window.document.querySelector("#review-page-comment").click();
  await waitFor(() => !reviewCompose.hidden, "newer route draft did not reopen");
  assert.equal(window.document.querySelector("#review-body").value, "A newer draft created before the first save completed.");
  window.document.querySelector("#review-compose-cancel").click();
  await waitFor(() => reviewCompose.hidden, "post-race newer composer did not close");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#review-page-comment"), "post-race newer composer did not restore focus");
  window.document.querySelector("#review-close").click();
  await waitFor(() => window.document.querySelector("#review-panel").hidden, "post-race drawer did not close");
  reviewPostDelay = 25;

  failReviewGet = true;
  window.document.querySelector("#review-button").click();
  window.document.querySelector("#review-refresh").click();
  await waitFor(() => window.document.querySelector("#review-button").hidden, "failed review refresh did not hide the feature");
  await waitFor(() => window.document.activeElement === window.document.querySelector("#article"), "failed review refresh stranded focus");
  assert.equal(window.document.querySelector("#review-panel").hidden, true);
  failReviewGet = false;

  assert.match(appCssSource, /\.review-panel\s*\{[^}]*position:\s*fixed;[^}]*right:\s*0;[^}]*width:\s*min\(29rem,\s*100vw\);/s);
  assert.match(appCssSource, /\.review-compose\s*\{[^}]*position:\s*fixed;[^}]*width:\s*min\(22rem,/s);
  assert.match(appCssSource, /\.review-compose\[data-placement="drawer"\]\s*\{[^}]*position:\s*static;/s);
  assert.match(appCssSource, /\.review-scrim\s*\{[^}]*inset:\s*0;/s);
  assert.match(appCssSource, /@media\s*\(max-width:\s*39\.99rem\)[\s\S]*?\.review-panel\s*\{\s*width:\s*100vw;/);
  assert.match(appCssSource, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?animation-duration:\s*0\.01ms\s*!important;/);

  assert.equal(window.document.querySelector("#brand").textContent, "Atlas Docs");
  assert.equal(window.document.querySelector("#brand").getAttribute("href"), "/docs/");
  assert.equal(window.document.querySelectorAll("#space-links .space-link").length, 2);
  const activeNavLink = window.document.querySelector("#page-nav .nav-link.is-active");
  assert.equal(activeNavLink.querySelector(".nav-label-text").textContent, "Setup");
  assert.equal(activeNavLink.querySelector(".nav-chevron-slot").getAttribute("aria-hidden"), "true");
  assert.equal(activeNavLink.querySelector(".nav-chevron-slot").childElementCount, 0);
  const groupChevronSlot = window.document.querySelector("#page-nav .nav-group > summary > .nav-chevron-slot");
  assert.equal(groupChevronSlot.getAttribute("aria-hidden"), "true");
  assert.ok(groupChevronSlot.querySelector(".nav-chevron"));
  const groupPlanCount = window.document.querySelector("#page-nav .nav-group > summary > .nav-plan-count");
  assert.equal(groupPlanCount.textContent, "99+");
  assert.equal(groupPlanCount.title, "145 plans");
  assert.equal(groupPlanCount.getAttribute("aria-hidden"), "true");
  assert.equal(window.document.querySelector("#page-nav .nav-group-label .sr-only").textContent, "145 plans");
  const activePlanCount = activeNavLink.querySelector(".nav-plan-count");
  assert.equal(activePlanCount.textContent, "7");
  assert.equal(activePlanCount.title, "7 plans");
  assert.equal(activePlanCount.getAttribute("aria-hidden"), "true");
  assert.equal(activeNavLink.querySelector(".sr-only").textContent, "7 plans");
  const cappedLeafCount = Array.from(window.document.querySelectorAll("#page-nav .nav-link"))
    .find((link) => link.querySelector(".nav-label-text")?.textContent === "Slow")
    .querySelector(".nav-plan-count");
  assert.equal(cappedLeafCount.textContent, "99+");
  assert.equal(cappedLeafCount.title, "120 plans");
  assert.equal(cappedLeafCount.getAttribute("aria-hidden"), "true");
  assert.equal(cappedLeafCount.closest(".nav-link").querySelector(".sr-only").textContent, "120 plans");
  const tocUrl = new URL(window.document.querySelector("#tocbar .toc-link").href);
  assert.equal(tocUrl.pathname + tocUrl.hash, "/docs/guide/setup#install");

  assert.equal(window.__unsafe, undefined);
  assert.equal(window.document.querySelector("#article script"), null);
  assert.equal(window.document.querySelector("#unsafe-image").hasAttribute("onerror"), false);
  assert.equal(window.document.querySelector("#unsafe-link").hasAttribute("href"), false);
  assert.equal(window.document.querySelector("#unsafe-style"), null);
  assert.equal(window.document.querySelector("#safe-figure style"), null);
  assert.equal(window.document.querySelector("#safe-figure").hasAttribute("style"), false);

  const tabPanes = window.document.querySelectorAll(".tab-pane");
  assert.equal(tabPanes[0].classList.contains("code-only"), false);
  assert.equal(tabPanes[1].classList.contains("code-only"), true);
  assert.match(appCssSource, /\.tab-pane\.code-only\s*\{\s*padding:\s*0;/);
  assert.match(appCssSource, /\.tab-pane\.code-only\s*>\s*\.codeblock\s*\{[^}]*margin:\s*0;[^}]*border:\s*0;/s);

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
  navLinks.find((link) => link.querySelector(".nav-label-text")?.textContent === "Slow").click();
  navLinks.find((link) => link.querySelector(".nav-label-text")?.textContent === "Setup").click();
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
  assert.equal(alternateWindow.document.querySelector("#review-button").hidden, true);
  assert.equal(alternateWindow.document.querySelector("#review-panel").hidden, true);
  alternateDom.window.close();

  console.log("docs SPA smoke test passed");
  dom.window.close();
})().catch((error) => {
  console.error(error);
  dom.window.close();
  process.exitCode = 1;
});
