const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const output = path.join(root, "build");
const indexPath = path.join(output, "index.json");

if (!fs.existsSync(indexPath)) {
  console.log("generated docs smoke test skipped (build/index.json is absent)");
  process.exit(0);
}

const index = readJson(indexPath);
assert.ok(index && Array.isArray(index.spaces) && index.spaces.length, "generated index must contain spaces");
for (const asset of ["index.html", "app.js", "app.css", "prism.js", "search.json"]) {
  assert.ok(fs.existsSync(path.join(output, asset)), `generated asset is missing: ${asset}`);
}

const mount = "/manual";
const shell = fs.readFileSync(path.join(output, "index.html"), "utf8");
assert.match(shell, /data-base="[^"]*"/, "generated shell must expose the base marker");
const mountedShell = shell
  .replace(/<script>[\s\S]*?<\/script>/, "")
  .replace(/data-base="[^"]*"/, `data-base="${mount}"`);
const appSource = fs.readFileSync(path.join(output, "app.js"), "utf8");
const prismSource = fs.readFileSync(path.join(output, "prism.js"), "utf8");
const generatedCss = fs.readFileSync(path.join(output, "app.css"), "utf8");
assert.equal(appSource, fs.readFileSync(path.join(root, "web", "app.js"), "utf8"), "generated app.js is stale");
assert.equal(prismSource, fs.readFileSync(path.join(root, "web", "prism.js"), "utf8"), "generated prism.js is stale");
assert.equal(generatedCss, fs.readFileSync(path.join(root, "web", "app.css"), "utf8"), "generated app.css is stale");
assert.match(generatedCss, /\.source-lines/, "generated stylesheet does not cover source-line output");

const dom = new JSDOM(mountedShell, {
  url: `https://docs.example.test${mount}/`,
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;
window.scrollTo = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};

const requestedPaths = [];
window.fetch = async (input) => {
  const pathname = new URL(String(input), window.location.href).pathname;
  requestedPaths.push(pathname);
  const file = outputFileForRequest(pathname);
  if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    return { ok: false, status: 404, json: async () => ({}) };
  }
  return { ok: true, status: 200, json: async () => readJson(file) };
};

let copied = "";
Object.defineProperty(window.navigator, "clipboard", {
  configurable: true,
  value: { writeText: async (value) => { copied = value; } },
});
Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function outputFileForRequest(pathname) {
  if (pathname !== mount && !pathname.startsWith(mount + "/")) { return null; }
  const relative = pathname.slice(mount.length).replace(/^\/+/, "");
  const segments = relative.split("/").filter(Boolean).map((segment) => decodeURIComponent(segment));
  if (segments.some((segment) => segment === "." || segment === ".." || segment.includes("\\"))) { return null; }
  const candidate = path.resolve(output, ...segments);
  return candidate === output || candidate.startsWith(output + path.sep) ? candidate : null;
}

function routeFiles(route) {
  const segments = String(route).split("/").filter(Boolean);
  if (!segments.length) { return [path.join(output, "content", "index.json")]; }
  return [
    path.join(output, "content", ...segments.slice(0, -1), segments.at(-1) + ".json"),
    path.join(output, "content", ...segments, "index.json"),
  ];
}

function contentForRoute(route) {
  const file = routeFiles(route).find((candidate) => fs.existsSync(candidate));
  assert.ok(file, `generated content is missing for route ${route}`);
  return readJson(file);
}

function flattenNodes(nodes) {
  const result = [];
  for (const node of Array.isArray(nodes) ? nodes : []) {
    result.push(node);
    result.push(...flattenNodes(node && node.items));
  }
  return result;
}

function waitFor(test, message) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const poll = () => {
      if (test()) { resolve(); return; }
      attempts += 1;
      if (attempts > 150) { reject(new Error(message)); return; }
      setTimeout(poll, 10);
    };
    poll();
  });
}

function mountedPath(route) {
  return mount + (route === "/" ? "/" : route);
}

function routeLink(route, selector = "a[data-route]") {
  return Array.from(window.document.querySelectorAll(selector)).find((link) => {
    return new URL(link.href).pathname === mountedPath(route);
  });
}

(async () => {
  window.Prism = { manual: true };
  window.eval(prismSource);
  window.eval(appSource);

  const rootSpace = index.spaces.find((space) => space.route === "/");
  const homeSpace = rootSpace || index.spaces.find((space) => space.showInMenu !== false) || index.spaces[0];
  const homeRoute = homeSpace.route;
  const homeContent = contentForRoute(homeRoute);
  await waitFor(
    () => window.document.title === `${homeContent.title} — ${index.title}`,
    "generated home route did not render",
  );
  assert.equal(window.location.pathname, mountedPath(homeRoute));

  const nav = readJson(path.join(output, "nav", homeSpace.navKey + ".json"));
  const directoryIndex = flattenNodes(nav).find((node) => {
    if (!node || typeof node.index !== "string") { return false; }
    const candidates = routeFiles(node.index);
    return !fs.existsSync(candidates[0]) && fs.existsSync(candidates[1]);
  });
  assert.ok(directoryIndex, "generated navigation must cover the directory-index fallback");
  const directoryLink = routeLink(directoryIndex.index);
  assert.ok(directoryLink, "directory index route is not discoverable in generated navigation");
  directoryLink.click();
  const directoryContent = contentForRoute(directoryIndex.index);
  await waitFor(
    () => window.document.title === `${directoryContent.title} — ${index.title}`,
    "generated directory index did not render",
  );

  const codeSpace = index.spaces.find((space) => space.hasCode === true);
  assert.ok(codeSpace, "generated index must expose a source-enabled space");
  if (codeSpace.navKey !== homeSpace.navKey) {
    const spaceLink = routeLink(codeSpace.route, ".space-link");
    assert.ok(spaceLink, "source-enabled space is not discoverable");
    spaceLink.click();
    await waitFor(() => window.location.pathname === mountedPath(codeSpace.route), "source-enabled space did not render");
  }

  const codeNavPath = path.join(output, "nav", codeSpace.navKey + ".code.json");
  const codeNav = readJson(codeNavPath);
  assert.ok(Array.isArray(codeNav) && codeNav.length, "generated source navigation must be a non-empty flat array");
  const codeEntry = codeNav.find((entry) => entry && typeof entry.route === "string");
  assert.ok(codeEntry, "generated source navigation has no route");
  const sourceLink = routeLink(codeEntry.route, ".source-file");
  assert.ok(sourceLink, "generated source route is not discoverable in the Source group");
  sourceLink.click();
  const codeContent = contentForRoute(codeEntry.route);
  await waitFor(() => Boolean(window.document.querySelector(".code-page")), "generated source page did not render");
  assert.equal(window.location.pathname, mountedPath(codeEntry.route));
  assert.equal(window.document.querySelectorAll(".source-lines tr").length, codeContent.lines.length);
  assert.equal(codeContent.language, "csharp");
  assert.ok(window.document.querySelector(".source-lines code.language-csharp"));
  assert.ok(window.document.querySelector(".source-lines .token.keyword"));
  assert.equal(window.document.querySelector(".code-page-body .copy"), null);
  window.document.querySelector(".code-page-copy").click();
  await waitFor(() => copied === codeContent.lines.join("\n"), "generated source copy did not match fragment lines");

  window.document.querySelector("#search-button").click();
  await waitFor(() => window.document.querySelector("#search-dialog").hasAttribute("open"), "generated search did not open");
  const searchInput = window.document.querySelector("#search-input");
  searchInput.value = codeContent.title;
  searchInput.dispatchEvent(new window.Event("input", { bubbles: true }));
  await waitFor(
    () => Boolean(routeLink(codeEntry.route, ".search-result")),
    "generated search did not return the source page",
  );

  assert.ok(requestedPaths.length > 4);
  assert.ok(requestedPaths.every((pathname) => pathname === mount || pathname.startsWith(mount + "/")), "a generated request escaped the mount path");
  console.log("generated docs smoke test passed");
  dom.window.close();
})().catch((error) => {
  console.error(error);
  dom.window.close();
  process.exitCode = 1;
});
