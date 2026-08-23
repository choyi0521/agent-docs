using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentDocs.Tests;

public sealed class AgentWorkflowProjectionTests
{
    [Fact]
    public void Enabled_projection_emits_a_neutral_page_navigation_and_search_entry()
    {
        using TempRepository repo = new();
        repo.Write("workflows/start.md",
            "# Authored heading\n\n"
            + "<script>globalThis.changed = true</script>\n\n"
            + "## First step\n\nProjection search phrase.\n");
        EnableProjection(repo, Manifest(
            Page("workflows/start.md", "start", "Workflow start")));

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        Assert.Equal(1, report.Documents);
        Assert.Equal(2, report.Fragments);
        Assert.Equal(0, report.Broken);
        JsonElement page = ReadJson(
            repo.Output, "content", "agent-guides", "start.json");
        Assert.Equal("Workflow start", page.GetProperty("title").GetString());
        string html = page.GetProperty("html").GetString()!;
        Assert.Contains("&lt;script&gt;", html, StringComparison.Ordinal);
        Assert.DoesNotContain("<script>", html, StringComparison.OrdinalIgnoreCase);

        JsonElement navigation = ReadJson(repo.Output, "nav", "overview.json");
        JsonElement workflowGroup = navigation.EnumerateArray().Single(item =>
            item.GetProperty("label").GetString() == "Workflow guide");
        Assert.Equal("group", workflowGroup.GetProperty("kind").GetString());
        Assert.Equal("/agent-guides/start",
            workflowGroup.GetProperty("items")[0].GetProperty("route").GetString());

        JsonElement search = ReadJson(repo.Output, "search.json");
        JsonElement entry = search.EnumerateArray().Single(item =>
            item.GetProperty("route").GetString() == "/agent-guides/start");
        Assert.Contains("Projection search phrase", entry.GetProperty("text").GetString()!,
            StringComparison.Ordinal);
        Assert.Equal("workflows/start.md", entry.GetProperty("path").GetString());
    }

    [Theory]
    [InlineData("manifest")]
    [InlineData("page")]
    public void Projection_manifest_rejects_unknown_fields(string target)
    {
        using TempRepository repo = new();
        repo.Write("workflows/start.md", "# Start\n");
        JsonObject manifest = Manifest(
            Page("workflows/start.md", "start", "Workflow start"));
        if (target == "manifest")
            manifest["unexpected"] = true;
        else
            manifest["pages"]!.AsArray()[0]!.AsObject()["unexpected"] = true;
        EnableProjection(repo, manifest);

        Assert.Throws<JsonException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));
    }

    [Theory]
    [InlineData("")]
    [InlineData("Bad")]
    [InlineData("bad--route")]
    [InlineData("../escape")]
    public void Projection_rejects_invalid_page_routes(string route)
    {
        using TempRepository repo = new();
        repo.Write("workflows/start.md", "# Start\n");
        EnableProjection(repo, Manifest(
            Page("workflows/start.md", route, "Workflow start")));

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("route", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Projection_rejects_duplicate_routes()
    {
        using TempRepository repo = new();
        repo.Write("workflows/first.md", "# First\n");
        repo.Write("workflows/second.md", "# Second\n");
        EnableProjection(repo, Manifest(
            Page("workflows/first.md", "same", "First workflow"),
            Page("workflows/second.md", "same", "Second workflow")));

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("duplicated", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Projection_rejects_sources_outside_the_repository()
    {
        using TempRepository repo = new();
        string outside = repo.WriteOutside("outside.md", "OUTSIDE_CANARY\n");
        EnableProjection(repo, Manifest(
            Page("../outside.md", "outside", "Outside workflow")));

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("portable", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Equal("OUTSIDE_CANARY\n", File.ReadAllText(outside));
    }

    [Fact]
    public void Projection_rejects_a_reparse_source_without_reading_its_target()
    {
        using TempRepository repo = new();
        string outside = repo.WriteOutside("outside.md", "REPARSE_CANARY\n");
        string linked = Path.Combine(repo.Root, "workflows", "linked.md");
        Directory.CreateDirectory(Path.GetDirectoryName(linked)!);
        try
        {
            File.CreateSymbolicLink(linked, outside);
        }
        catch (Exception exception) when (exception is IOException
                                          or UnauthorizedAccessException
                                          or PlatformNotSupportedException)
        {
            Assert.Skip($"file links unavailable: {exception.GetType().Name}");
        }
        EnableProjection(repo, Manifest(
            Page("workflows/linked.md", "linked", "Linked workflow")));

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("symbolic link or reparse point", error.Message,
            StringComparison.OrdinalIgnoreCase);
        Assert.Equal("REPARSE_CANARY\n", File.ReadAllText(outside));
    }

    [Fact]
    public void Projection_rejects_private_key_shaped_content()
    {
        using TempRepository repo = new();
        string marker = new string('-', 5) + "BEGIN PRIVATE" + " KEY" + new string('-', 5);
        repo.Write("workflows/start.md", "# Start\n\n" + marker + "\n");
        EnableProjection(repo, Manifest(
            Page("workflows/start.md", "start", "Workflow start")));

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("private key", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Projection_rejects_literal_credential_shaped_content()
    {
        using TempRepository repo = new();
        string assignment = "api_" + "key = " + new string('Z', 24);
        repo.Write("workflows/start.md", "# Start\n\n" + assignment + "\n");
        EnableProjection(repo, Manifest(
            Page("workflows/start.md", "start", "Workflow start")));

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("credential assignment", error.Message,
            StringComparison.OrdinalIgnoreCase);
    }

    private static void EnableProjection(TempRepository repo, JsonObject manifest)
    {
        repo.Write("workflow-manifest.json", manifest.ToJsonString() + "\n");
        repo.WriteConfiguration(config => config["agentWorkflows"] = new JsonObject
        {
            ["enabled"] = true,
            ["spaceId"] = "",
            ["manifest"] = "workflow-manifest.json",
            ["routePrefix"] = "agent-guides",
        });
    }

    private static JsonObject Manifest(params JsonObject[] pages)
    {
        JsonArray values = [];
        foreach (JsonObject page in pages)
            values.Add(page);
        return new JsonObject
        {
            ["version"] = 1,
            ["label"] = "Workflow guide",
            ["pages"] = values,
        };
    }

    private static JsonObject Page(string source, string route, string title) => new()
    {
        ["source"] = source,
        ["route"] = route,
        ["title"] = title,
    };

    private static JsonElement ReadJson(string root, params string[] relative)
    {
        string path = relative.Aggregate(root, Path.Combine);
        using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
        return document.RootElement.Clone();
    }
}
