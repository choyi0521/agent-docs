using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentDocs.Tests;

internal sealed class TempRepository : IDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
    };

    internal TempRepository()
    {
        Workspace = Path.Combine(
            Path.GetTempPath(),
            "agent-docs-tests-" + Guid.NewGuid().ToString("N"));
        Root = Path.Combine(Workspace, "repo");
        Output = Path.Combine(Workspace, "site");
        Directory.CreateDirectory(Path.Combine(Root, "docs"));
        Write("docs/_index.md", "# Home\n\nWelcome.\n");
        Write("web/index.html",
            "<!doctype html><html data-base=\"/\"><body>preview shell</body></html>\n");
        Write("web/app.js", "globalThis.agentDocsPreview = true;\n");
        Write("web/app.css", "body { margin: 0; }\n");
        Write("web/prism.js", "globalThis.Prism = { manual: true };\n");
        Write("THIRD-PARTY-NOTICES.md", "# Third-party notices\n\nFixture notice.\n");
        Write("third_party_licenses/Markdig-BSD-2-Clause.txt",
            "Fixture BSD-2-Clause license text.\n");
        Write("third_party_licenses/PrismJS-MIT.txt",
            "Fixture PrismJS MIT license text.\n");
        Write("third_party_licenses/Tailwind-CSS-MIT.txt",
            "Fixture Tailwind CSS MIT license text.\n");
        Write("third_party_licenses/Tailwind-Preflight-MIT.txt",
            "Fixture Preflight MIT license text.\n");
    }

    internal string Workspace { get; }
    internal string Root { get; }
    internal string Output { get; }
    internal string ConfigPath => Path.Combine(Root, "agent-docs.json");

    internal string Write(string relative, string text)
    {
        string path = Path.Combine(
            Root,
            relative.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, text);
        return path;
    }

    internal string WriteOutside(string name, string text)
    {
        string path = Path.Combine(Workspace, name);
        File.WriteAllText(path, text);
        return path;
    }

    internal string WriteConfiguration(
        Action<JsonObject>? mutate = null,
        bool curated = false,
        bool enableSnippets = false,
        bool publishCode = false,
        string sourceRoot = ".",
        IReadOnlyList<string>? sourceTrees = null,
        IReadOnlyList<string>? sourceExtensions = null)
    {
        JsonObject space = new()
        {
            ["id"] = "",
            ["label"] = "Guide",
            ["docsDir"] = "docs",
            ["curated"] = curated,
            ["showInMenu"] = true,
            ["sourceRoot"] = sourceRoot,
            ["enableSnippets"] = enableSnippets,
            ["publishCode"] = publishCode,
            ["sourceTrees"] = ToArray(sourceTrees),
            ["sourceExtensions"] = ToArray(sourceExtensions),
            ["excludedSourcePaths"] = new JsonArray(),
            ["browsableRootFiles"] = new JsonArray(),
        };
        JsonObject config = new()
        {
            ["schemaVersion"] = 1,
            ["title"] = "Fixture Docs",
            ["spaces"] = new JsonArray(space),
        };
        mutate?.Invoke(config);
        Write("agent-docs.json", config.ToJsonString(JsonOptions) + "\n");
        return ConfigPath;
    }

    internal static JsonObject OnlySpace(JsonObject config) =>
        config["spaces"]!.AsArray()[0]!.AsObject();

    public void Dispose()
    {
        if (Directory.Exists(Workspace))
            Directory.Delete(Workspace, recursive: true);
    }

    private static JsonArray ToArray(IReadOnlyList<string>? values)
    {
        JsonArray result = [];
        foreach (string value in values ?? [])
            result.Add(value);
        return result;
    }
}
