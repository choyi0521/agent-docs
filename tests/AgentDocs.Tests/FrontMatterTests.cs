using System.Text.Json;

namespace AgentDocs.Tests;

public sealed class FrontMatterTests
{
    [Fact]
    public void Research_json_exposes_top_level_simple_values_without_flattening_evidence()
    {
        const string header = """
            {
              "schema": "research/v2",
              "id": "rr-2026-09-07-publication-01234567",
              "title": "Publication boundaries",
              "status": "draft",
              "facets": { "domains": ["software-design"] },
              "sources": [
                { "id": "sample", "revision": { "kind": "git-commit", "value": "0123456789012345678901234567890123456789" } }
              ],
              "claims": [
                { "id": "scope", "statement": "METADATA_ONLY_CANARY", "evidence": ["sample:contract"] }
              ],
              "relations": { "related": [], "title": "Not the page title", "nav": ["hidden.md"] },
              "consumers": ["docs/guide.md"],
              "count": 3,
              "enabled": false,
              "optional": null
            }
            """;
        const string body = "\n# A body heading\n\n<!-- research:provenance -->\nVisible evidence.\n";

        (FrontMatter meta, string actualBody) = FrontMatterParser.Split(Wrap(header, body));

        Assert.Equal("research/v2", meta.Scalar("schema"));
        Assert.Equal("Publication boundaries", meta.Scalar("title"));
        Assert.Equal("3", meta.Scalar("count"));
        Assert.Equal("false", meta.Scalar("enabled"));
        Assert.Equal(new[] { "docs/guide.md" }, meta.List("consumers"));
        Assert.Null(meta.Scalar("facets"));
        Assert.Null(meta.Scalar("optional"));
        Assert.Null(meta.List("sources"));
        Assert.Null(meta.List("claims"));
        Assert.Null(meta.List("nav"));
        Assert.Equal(body, actualBody);
    }

    [Fact]
    public void Json_navigation_preserves_string_arrays_and_scalar_values()
    {
        (FrontMatter meta, _) = FrontMatterParser.Split(Wrap(
            """{"title":"Guide","nav":["first.md","second/"],"nav_exclude":[],"nav_mode":"flat","crumb":"Research"}"""));

        Assert.Equal("Guide", meta.Scalar("title"));
        Assert.Equal(new[] { "first.md", "second/" }, meta.List("nav"));
        Assert.Empty(meta.List("nav_exclude")!);
        Assert.Equal("flat", meta.Scalar("nav_mode"));
        Assert.Equal("Research", meta.Scalar("crumb"));

        (FrontMatter unordered, _) = FrontMatterParser.Split(Wrap("""{"nav":"unordered"}"""));
        Assert.Equal("unordered", unordered.Scalar("nav"));
    }

    [Fact]
    public void Json_unicode_and_crlf_preserve_the_complete_body()
    {
        const string body = "\r\n\r\n  Indented introduction\r\n# 자료 연구\r\n\r\n본문\r\n";
        const string header = "--- \t\r\n{\r\n  \"title\": \"자료 연구\",\r\n  \"nav\": [\"안내.md\"]\r\n}\r\n--- \t\r\n";

        (FrontMatter meta, string actualBody) = FrontMatterParser.Split(header + body);

        Assert.Equal("자료 연구", meta.Scalar("title"));
        Assert.Equal(new[] { "안내.md" }, meta.List("nav"));
        Assert.Equal(body, actualBody);
    }

    [Theory]
    [InlineData("{\"title\":}")]
    [InlineData("{\"title\":\"Guide\",}")]
    [InlineData("{/* comment */\"title\":\"Guide\"}")]
    [InlineData("/* comment */{}")]
    [InlineData("// comment\n{}")]
    [InlineData("{\"title\":\"Guide\"} trailing")]
    [InlineData("[\"not an object\"]")]
    [InlineData("{\"Bad-Key\":\"value\"}")]
    [InlineData("{\"title\\n\":\"value\"}")]
    public void Malformed_or_unsupported_json_is_a_data_error(string header)
    {
        Assert.Throws<InvalidDataException>(() => FrontMatterParser.Split(Wrap(header)));
    }

    [Theory]
    [InlineData("{\"title\":\"One\",\"title\":\"Two\"}")]
    [InlineData("{\"title\":\"One\",\"ti\\u0074le\":\"Two\"}")]
    [InlineData("{\"relations\":{\"related\":[],\"related\":[]}}")]
    [InlineData("{\"claims\":[{\"id\":\"first\",\"id\":\"second\"}]}")]
    public void Duplicate_json_keys_are_rejected_at_every_depth(string header)
    {
        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            FrontMatterParser.Split(Wrap(header)));

        Assert.Contains("duplicate", error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("{\"title\":[]}")]
    [InlineData("{\"title\":null}")]
    [InlineData("{\"title\":42}")]
    [InlineData("{\"crumb\":{\"name\":\"Research\"}}")]
    [InlineData("{\"nav\":{\"items\":[\"guide.md\"]}}")]
    [InlineData("{\"nav\":[\"guide.md\",false]}")]
    [InlineData("{\"nav\":null}")]
    [InlineData("{\"nav_exclude\":\"guide.md\"}")]
    [InlineData("{\"nav_mode\":true}")]
    public void Renderer_metadata_requires_its_declared_json_shape(string header)
    {
        Assert.Throws<InvalidDataException>(() => FrontMatterParser.Split(Wrap(header)));
    }

    [Fact]
    public void Yaml_subset_retains_scalar_block_list_and_empty_list_behavior()
    {
        const string header = "title: Guide\nnav:\n  - first.md\n  - second/\nnav_exclude: []\ncrumb: Research";
        const string body = "\n# Guide\n\nBody remains unchanged.\n";

        (FrontMatter meta, string actualBody) = FrontMatterParser.Split(Wrap(header, body));

        Assert.Equal("Guide", meta.Scalar("title"));
        Assert.Equal("Research", meta.Scalar("crumb"));
        Assert.Equal(new[] { "first.md", "second/" }, meta.List("nav"));
        Assert.Empty(meta.List("nav_exclude")!);
        Assert.Equal(body, actualBody);

        (FrontMatter unordered, _) = FrontMatterParser.Split(Wrap("nav: unordered"));
        Assert.Equal("unordered", unordered.Scalar("nav"));
    }

    [Fact]
    public void Ordinary_markdown_is_unchanged()
    {
        const string text = "\n# Guide\n\n---\n\nA thematic break is not metadata.\n";

        (FrontMatter meta, string body) = FrontMatterParser.Split(text);

        Assert.Empty(meta.Scalars);
        Assert.Empty(meta.Lists);
        Assert.Equal(text, body);
    }

    [Fact]
    public void Curated_site_renders_and_searches_a_json_research_record_without_metadata()
    {
        using TempRepository repo = new();
        repo.Write("docs/_index.md", Wrap("""{"nav":["record.md"]}""", "# Research\n"));
        repo.Write("docs/record.md", Wrap(
            """
            {
              "schema": "research/v2",
              "id": "rr-2026-09-07-publication-01234567",
              "title": "Metadata title stays separate",
              "status": "draft",
              "facets": { "domains": ["software-design"] },
              "claims": [{ "statement": "METADATA_ONLY_CANARY", "evidence": [] }],
              "sources": [],
              "relations": { "nav": ["missing.md"] }
            }
            """,
            "# Publication boundaries\n\n<!-- research:provenance -->\n"
            + "Evidence verified in a named revision.\n<!-- /research:provenance -->\n\n"
            + "A uniquely searchable research finding.\n"));
        repo.WriteConfiguration(curated: true);

        BuildReport report = AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        Assert.Equal(2, report.Documents);
        Assert.Equal(0, report.Broken);
        using JsonDocument page = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(repo.Output, "content", "record.json")));
        Assert.Equal("Publication boundaries", page.RootElement.GetProperty("title").GetString());
        string html = page.RootElement.GetProperty("html").GetString()!;
        Assert.Contains("Evidence verified in a named revision.", html, StringComparison.Ordinal);
        Assert.Contains("uniquely searchable research finding", html, StringComparison.Ordinal);
        Assert.DoesNotContain("METADATA_ONLY_CANARY", html, StringComparison.Ordinal);
        Assert.DoesNotContain("research/v2", html, StringComparison.Ordinal);

        using JsonDocument index = JsonDocument.Parse(File.ReadAllText(Path.Combine(repo.Output, "search.json")));
        JsonElement result = index.RootElement.EnumerateArray().Single(item =>
            item.GetProperty("route").GetString() == "/record");
        Assert.Contains("uniquely searchable research finding", result.GetProperty("text").GetString()!,
            StringComparison.Ordinal);
        Assert.DoesNotContain("METADATA_ONLY_CANARY", result.GetProperty("text").GetString()!,
            StringComparison.Ordinal);
    }

    private static string Wrap(string header, string body = "# Body\n") =>
        "---\n" + header + "\n---\n" + body;
}
