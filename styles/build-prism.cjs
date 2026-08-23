const fs = require("node:fs");
const path = require("node:path");

const expectedVersion = "1.30.0";
const packageRoot = path.dirname(require.resolve("prismjs/package.json"));
const packageMetadata = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8"));
if (packageMetadata.version !== expectedVersion) {
  throw new Error(`expected PrismJS ${expectedVersion}, found ${packageMetadata.version}`);
}

const componentMetadata = JSON.parse(
  fs.readFileSync(path.join(packageRoot, "components.json"), "utf8"),
).languages;
const requestedLanguages = [
  "markup",
  "css",
  "clike",
  "javascript",
  "bash",
  "cpp",
  "csharp",
  "json",
  "markdown",
  "powershell",
  "python",
  "typescript",
  "yaml",
];
const orderedLanguages = [];
const visited = new Set();

function asArray(value) {
  if (value === undefined) { return []; }
  return Array.isArray(value) ? value : [value];
}

function addLanguage(language) {
  if (visited.has(language)) { return; }
  const metadata = componentMetadata[language];
  if (!metadata || typeof metadata !== "object") {
    throw new Error(`unknown PrismJS language component: ${language}`);
  }
  for (const dependency of [...asArray(metadata.require), ...asArray(metadata.modify)]) {
    addLanguage(dependency);
  }
  visited.add(language);
  orderedLanguages.push(language);
}

for (const language of requestedLanguages) {
  addLanguage(language);
}

const sourceFiles = [
  path.join(packageRoot, "components", "prism-core.min.js"),
  ...orderedLanguages.map((language) =>
    path.join(packageRoot, "components", `prism-${language}.min.js`)),
];
for (const source of sourceFiles) {
  if (!fs.existsSync(source)) {
    throw new Error(`required PrismJS source is missing: ${path.relative(packageRoot, source)}`);
  }
}

const banner = [
  `/*! PrismJS ${expectedVersion} | MIT license: third_party_licenses/PrismJS-MIT.txt */`,
  `/* Languages: ${orderedLanguages.join(", ")} */`,
].join("\n");
const bundle = banner + "\n" + sourceFiles
  .map((source) => fs.readFileSync(source, "utf8").trim())
  .join("\n") + "\n";
fs.writeFileSync(path.resolve(__dirname, "..", "web", "prism.js"), bundle, "utf8");
