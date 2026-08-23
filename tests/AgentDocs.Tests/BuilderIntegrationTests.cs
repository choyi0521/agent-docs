using System.Text.Json;

namespace AgentDocs.Tests;

public sealed class BuilderIntegrationTests
{
    [Fact]
    public void Build_writes_navigation_content_search_and_reading_order()
    {
        using TempRepository repo = new();
        repo.Write("docs/_index.md",
            "---\nnav:\n  - guide.md\n  - reference\n---\n"
            + "# Home\n\nStart here.\n");
        repo.Write("docs/guide.md",
            "# Guide\n\nSee [setup](reference/setup.md#install).\n\n"
            + "## Orientation\n\nA uniquely searchable phrase.\n");
        repo.Write("docs/reference/_index.md",
            "---\nnav:\n  - setup.md\n---\n# Reference\n\nReference overview.\n");
        repo.Write("docs/reference/setup.md",
            "# Setup\n\n## Install {#install}\n\nInstallation details.\n");
        repo.WriteConfiguration(curated: true);

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        Assert.Equal(4, report.Documents);
        Assert.Equal(4, report.Fragments);
        Assert.Equal(0, report.CodeFiles);
        Assert.Equal(0, report.Broken);
        SpaceBuildResult space = Assert.Single(report.Spaces);
        Assert.Equal(2, space.Diagnostics.CuratedSections);

        JsonElement guide = ReadJson(repo.Output, "content", "guide.json");
        Assert.Equal("Guide", guide.GetProperty("title").GetString());
        Assert.Equal("/", guide.GetProperty("prev").GetProperty("route").GetString());
        Assert.Equal("/reference",
            guide.GetProperty("next").GetProperty("route").GetString());
        string html = guide.GetProperty("html").GetString()!;
        Assert.Contains("href=\"/reference/setup#install\"", html,
            StringComparison.Ordinal);
        Assert.Contains("id=\"orientation\"", html, StringComparison.Ordinal);
        JsonElement toc = guide.GetProperty("toc");
        Assert.Single(toc.EnumerateArray());

        JsonElement nav = ReadJson(repo.Output, "nav", "overview.json");
        JsonElement[] navItems = [.. nav.EnumerateArray()];
        string[] labels = navItems.Select(item =>
            item.GetProperty("label").GetString()!).ToArray();
        Assert.Equal(new[] { "Overview", "Guide", "Reference" }, labels);
        Assert.Equal("/guide", navItems[1].GetProperty("route").GetString());
        Assert.Equal("group", navItems[2].GetProperty("kind").GetString());

        JsonElement search = ReadJson(repo.Output, "search.json");
        JsonElement guideSearch = search.EnumerateArray().Single(entry =>
            entry.GetProperty("route").GetString() == "/guide");
        Assert.Contains("uniquely searchable phrase",
            guideSearch.GetProperty("text").GetString()!,
            StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("<h", guideSearch.GetProperty("text").GetString()!,
            StringComparison.Ordinal);

        JsonElement site = ReadJson(repo.Output, "index.json");
        Assert.Equal("Fixture Docs", site.GetProperty("title").GetString());
        Assert.Equal(4, site.GetProperty("spaces")[0].GetProperty("docs").GetInt32());
    }

    [Fact]
    public void Curated_navigation_reports_unlisted_documents_as_a_broken_gate()
    {
        using TempRepository repo = new();
        repo.Write("docs/_index.md",
            "---\nnav:\n  - listed.md\n---\n# Home\n");
        repo.Write("docs/listed.md", "# Listed\n");
        repo.Write("docs/unlisted.md", "# Unlisted\n");
        repo.WriteConfiguration(curated: true);

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        SpaceBuildResult space = Assert.Single(report.Spaces);
        Assert.Equal(1, report.Broken);
        Assert.Single(space.Diagnostics.UnlistedDocuments);
        Assert.Contains("unlisted.md", space.Diagnostics.UnlistedDocuments[0],
            StringComparison.Ordinal);
    }

    [Fact]
    public void Curated_navigation_accepts_an_explicit_unordered_section()
    {
        using TempRepository repo = new();
        repo.Write("docs/_index.md", "---\nnav: unordered\n---\n# Home\n");
        repo.Write("docs/second.md", "# Second\n");
        repo.Write("docs/first.md", "# First\n");
        repo.WriteConfiguration(curated: true);

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        SpaceBuildResult space = Assert.Single(report.Spaces);
        Assert.Equal(0, report.Broken);
        Assert.Equal(1, space.Diagnostics.CuratedSections);
        Assert.Empty(space.Diagnostics.UndeclaredSections);
        Assert.Empty(space.Diagnostics.UnlistedDocuments);
    }

    [Fact]
    public void Two_documents_that_canonicalize_to_one_route_fail_with_a_data_error()
    {
        using TempRepository repo = new();
        repo.Write("docs/topic.md", "# Topic page\n");
        repo.Write("docs/topic/_index.md", "# Topic section\n");
        repo.WriteConfiguration();

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("route", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Broken_heading_fragments_are_reported_after_rendering()
    {
        using TempRepository repo = new();
        repo.Write("docs/_index.md",
            "---\nnav:\n  - first.md\n  - second.md\n---\n# Home\n");
        repo.Write("docs/first.md", "# First\n\n[Read it](second.md#missing).\n");
        repo.Write("docs/second.md", "# Second\n\n## Present\n");
        repo.WriteConfiguration(curated: true);

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        SpaceBuildResult space = Assert.Single(report.Spaces);
        Assert.Equal(1, report.Broken);
        Assert.Equal(1, space.Diagnostics.CheckedAnchors);
        Assert.Single(space.Diagnostics.BrokenAnchors);
        Assert.Contains("#missing", space.Diagnostics.BrokenAnchors[0],
            StringComparison.Ordinal);
    }

    [Fact]
    public void Build_publishes_only_allowlisted_code_and_includes_it_in_search()
    {
        using TempRepository repo = new();
        repo.Write("examples/Sample.cs",
            "internal static class Sample<T> { public const int Value = 7; }\n");
        repo.Write("examples/obj/Generated.cs", "internal static class Generated;\n");
        repo.Write("examples/node_modules/Dependency.cs", "internal static class Dependency;\n");
        repo.Write("private/Hidden.cs", "internal static class Hidden;\n");
        repo.WriteConfiguration(
            publishCode: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        Assert.Equal(1, report.CodeFiles);
        JsonElement code = ReadJson(
            repo.Output, "content", "code", "examples", "Sample.cs.json");
        Assert.Equal("examples/Sample.cs", code.GetProperty("path").GetString());
        Assert.Equal("csharp", code.GetProperty("language").GetString());
        Assert.Contains("class=\"language-csharp\"", code.GetProperty("html").GetString()!,
            StringComparison.Ordinal);
        Assert.Contains("Sample&lt;T&gt;", code.GetProperty("html").GetString()!,
            StringComparison.Ordinal);
        Assert.False(File.Exists(Path.Combine(
            repo.Output, "content", "code", "private", "Hidden.cs.json")));
        Assert.False(Directory.Exists(Path.Combine(
            repo.Output, "content", "code", "examples", "obj")));
        Assert.False(Directory.Exists(Path.Combine(
            repo.Output, "content", "code", "examples", "node_modules")));

        JsonElement search = ReadJson(repo.Output, "search.json");
        Assert.Contains(search.EnumerateArray(), entry =>
            entry.GetProperty("route").GetString() == "/code/examples/Sample.cs");
        JsonElement codeNavigation = ReadJson(repo.Output, "nav", "overview.code.json");
        Assert.Equal(JsonValueKind.Array, codeNavigation.ValueKind);
        JsonElement codeItem = Assert.Single(codeNavigation.EnumerateArray());
        Assert.Equal("code", codeItem.GetProperty("kind").GetString());
        Assert.Equal("examples/Sample.cs", codeItem.GetProperty("label").GetString());
        Assert.Equal("/code/examples/Sample.cs", codeItem.GetProperty("route").GetString());
    }

    [Fact]
    public void Builder_returns_snippet_marker_errors_in_the_report()
    {
        using TempRepository repo = new();
        repo.Write("examples/Sample.cs", "no snippet markers\n");
        repo.Write("docs/_index.md",
            "# Home\n\n```snippet examples/Sample.cs#sample\n```\n");
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        SpaceBuildResult space = Assert.Single(report.Spaces);
        Assert.Equal(1, report.Broken);
        Assert.Single(space.Diagnostics.SnippetErrors);
        JsonElement page = ReadJson(repo.Output, "content", "index.json");
        Assert.Contains("render-error", page.GetProperty("html").GetString()!,
            StringComparison.Ordinal);
    }

    private static JsonElement ReadJson(string root, params string[] relative)
    {
        string path = relative.Aggregate(root, Path.Combine);
        using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
        return document.RootElement.Clone();
    }
}
