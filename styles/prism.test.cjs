const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const prismSource = fs.readFileSync(path.join(root, "web", "prism.js"), "utf8");
const appSource = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const shellSource = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");

assert.ok(shellSource.indexOf('syntax.src = base + "/prism.js"') < shellSource.indexOf('app.src = base + "/app.js"'),
  "the syntax bundle must load before the reader");
assert.match(shellSource, /window\.Prism\.manual\s*=\s*true/);
assert.match(appSource, /window\.Prism\.highlightAllUnder\(elements\.article\)/);

const dom = new JSDOM([
  '<pre><code class="language-json">{"answer": 42}</code></pre>',
  '<pre><code class="language-csharp">public sealed class Sample { }</code></pre>',
  '<pre><code class="language-text">plain &amp; safe</code></pre>',
].join(""), { runScripts: "outside-only" });
const { window } = dom;
window.Prism = { manual: true };
window.eval(prismSource);

for (const language of ["bash", "cpp", "csharp", "json", "markdown", "powershell", "python", "typescript", "yaml"]) {
  assert.ok(window.Prism.languages[language], `Prism language is missing: ${language}`);
}
window.Prism.highlightAllUnder(window.document);
assert.equal(window.document.querySelector(".language-json .token.property").textContent, '"answer"');
assert.equal(window.document.querySelector(".language-json .token.number").textContent, "42");
assert.equal(window.document.querySelector(".language-csharp .token.keyword").textContent, "public");
assert.equal(window.document.querySelector(".language-text").textContent, "plain & safe");
assert.equal(window.document.querySelector(".language-text .token"), null);

console.log("syntax highlighting smoke test passed");
dom.window.close();
