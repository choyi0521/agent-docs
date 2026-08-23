namespace AgentDocs.Tests;

public sealed class BuilderSafetyTests
{
    private const string SentinelName = ".agent-docs-output";

    [Fact]
    public void Build_creates_an_ownership_sentinel_and_cleans_stale_owned_output()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();

        BuildReport first = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        Assert.Equal(1, first.Documents);
        Assert.True(File.Exists(Path.Combine(repo.Output, SentinelName)));
        string stale = Path.Combine(repo.Output, "stale.txt");
        File.WriteAllText(stale, "old output\n");

        BuildReport second = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        Assert.Equal(1, second.Documents);
        Assert.False(File.Exists(stale));
        Assert.True(File.Exists(Path.Combine(repo.Output, SentinelName)));
        Assert.True(File.Exists(Path.Combine(repo.Output, "index.json")));
        Assert.True(File.Exists(Path.Combine(repo.Output, "index.html")));
        Assert.True(File.Exists(Path.Combine(repo.Output, "app.js")));
        Assert.True(File.Exists(Path.Combine(repo.Output, "app.css")));
        Assert.Equal(
            File.ReadAllText(Path.Combine(repo.Root, "THIRD-PARTY-NOTICES.md")),
            File.ReadAllText(Path.Combine(repo.Output, "THIRD-PARTY-NOTICES.md")));
        foreach (string license in new[]
                 {
                     "Markdig-BSD-2-Clause.txt",
                     "Tailwind-CSS-MIT.txt",
                     "Tailwind-Preflight-MIT.txt",
                 })
        {
            Assert.Equal(
                File.ReadAllText(Path.Combine(repo.Root, "third_party_licenses", license)),
                File.ReadAllText(Path.Combine(repo.Output, "third_party_licenses", license)));
        }
    }

    [Fact]
    public void Build_refuses_to_clean_nonempty_output_without_its_sentinel()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        Directory.CreateDirectory(repo.Output);
        string witness = Path.Combine(repo.Output, "keep.txt");
        File.WriteAllText(witness, "must remain\n");

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("without .agent-docs-output", error.Message,
            StringComparison.Ordinal);
        Assert.Equal("must remain\n", File.ReadAllText(witness));
    }

    [Fact]
    public void Build_refuses_a_tampered_sentinel_without_cleaning_the_directory()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);
        string sentinel = Path.Combine(repo.Output, SentinelName);
        File.WriteAllText(sentinel, "not an ownership marker\n");
        string witness = Path.Combine(repo.Output, "keep.txt");
        File.WriteAllText(witness, "must remain\n");

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("invalid output ownership sentinel", error.Message,
            StringComparison.Ordinal);
        Assert.Equal("must remain\n", File.ReadAllText(witness));
    }

    [Fact]
    public void Build_rejects_the_repository_its_ancestor_and_documentation_inputs_as_output()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        string homePage = Path.Combine(repo.Root, "docs", "_index.md");
        string original = File.ReadAllText(homePage);
        string[] dangerous =
        [
            repo.Root,
            repo.Workspace,
            Path.Combine(repo.Root, "docs"),
            repo.ConfigPath,
        ];

        foreach (string output in dangerous)
        {
            InvalidDataException error = Assert.Throws<InvalidDataException>(
                () => AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, output));
            Assert.True(
                error.Message.Contains("output", StringComparison.OrdinalIgnoreCase),
                error.Message);
        }

        Assert.Equal(original, File.ReadAllText(homePage));
    }

    [Fact]
    public void Build_rejects_a_published_source_tree_as_output()
    {
        using TempRepository repo = new();
        string source = repo.Write("examples/Sample.cs", "internal static class Sample;\n");
        repo.WriteConfiguration(
            publishCode: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            AgentDocsBuilder.Build(repo.Root, repo.ConfigPath,
                Path.Combine(repo.Root, "examples")));

        Assert.Contains("overlaps a protected input path", error.Message,
            StringComparison.Ordinal);
        Assert.Equal("internal static class Sample;\n", File.ReadAllText(source));
    }

    [Fact]
    public void Relative_configuration_and_output_paths_are_resolved_from_the_repository()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();

        BuildReport report = AgentDocsBuilder.Build(
            repo.Root, "agent-docs.json", "generated-site");

        Assert.Equal(1, report.Documents);
        Assert.True(File.Exists(Path.Combine(
            repo.Root, "generated-site", SentinelName)));
    }

    [Fact]
    public void Build_rejects_an_incomplete_web_shell_before_claiming_output()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        File.Delete(Path.Combine(repo.Root, "web", "app.js"));

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("web", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.False(Directory.Exists(repo.Output));
    }

    [Fact]
    public void Build_rejects_incomplete_third_party_notices_before_claiming_output()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        File.Delete(Path.Combine(
            repo.Root, "third_party_licenses", "Tailwind-Preflight-MIT.txt"));

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output));

        Assert.Contains("third-party notice", error.Message,
            StringComparison.OrdinalIgnoreCase);
        Assert.False(Directory.Exists(repo.Output));
    }
}
