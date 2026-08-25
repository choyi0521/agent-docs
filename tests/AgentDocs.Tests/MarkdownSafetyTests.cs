namespace AgentDocs.Tests;

public sealed class MarkdownSafetyTests
{
    public static TheoryData<string> UnsafeFigurePayloads => new()
    {
        "<script>run()</script>",
        "<rect width=\"1\" height=\"1\" onload=\"run()\"/>",
        "<image href=\"https://example.test/pixel.png\"/>",
        "<foreignObject><div xmlns=\"http://www.w3.org/1999/xhtml\">x</div></foreignObject>",
        "<g xml:base=\"https://example.test/assets/\"><use href=\"#shape\"/></g>",
        "<g xmlns:alt=\"urn:foreign\"><alt:path d=\"M0 0\"/></g>",
        "<rect width=\"1\" height=\"1\" fill=\"https://example.test/paint.svg#p\"/>",
        "<use href=\"java%73cript:run()\"/>",
        "<use href=\"javascript:javascript:run()\"/>",
        "<?figure href=\"https://example.test/\"?><rect width=\"1\" height=\"1\"/>",
        "<filter id=\"f\"><feImage href=\"#local\"/></filter>",
        "<handler type=\"application/ecmascript\">run()</handler>",
        "<listener event=\"click\" handler=\"#action\"/>",
    };

    [Fact]
    public void Raw_html_is_rendered_as_text_instead_of_active_markup()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        const string markdown = "# Safe page\n\n"
            + "<script>globalThis.changed = true</script>\n\n"
            + "<img src=x onerror=globalThis.changed=true>\n";
        string source = repo.Write("docs/raw-html.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/raw-html");

        Assert.DoesNotContain("<script>", rendered.Html, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("<img ", rendered.Html, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("&lt;script&gt;", rendered.Html, StringComparison.Ordinal);
        Assert.Contains("&lt;img", rendered.Html, StringComparison.Ordinal);
        Assert.Empty(diagnostics.BrokenLinks);
    }

    [Fact]
    public void Code_fences_escape_html_sensitive_characters()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        const string markdown = "```html\n<button data-value=\"a&b\">run</button>\n```\n";
        string source = repo.Write("docs/code.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/code");

        Assert.Contains("&lt;button data-value=&quot;a&amp;b&quot;&gt;run&lt;/button&gt;",
            rendered.Html, StringComparison.Ordinal);
        Assert.DoesNotContain("<button data-value", rendered.Html, StringComparison.Ordinal);
    }

    [Fact]
    public void Search_text_keeps_authored_token_boundaries_and_excludes_renderer_chrome()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        const string markdown = "# Search page\n\nParagraph before.\n\n"
            + "```text\nalpha token\n```\n\n"
            + ":::tabs\n== First\nfirst pane text\n== Second\nsecond pane text\n:::\n";
        string source = repo.Write("docs/search.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/search");

        Assert.Contains("Search page Paragraph before.", rendered.Text,
            StringComparison.Ordinal);
        Assert.Contains("alpha token", rendered.Text, StringComparison.Ordinal);
        Assert.Contains("first pane text", rendered.Text, StringComparison.Ordinal);
        Assert.Contains("second pane text", rendered.Text, StringComparison.Ordinal);
        Assert.DoesNotContain("Search page#", rendered.Text, StringComparison.Ordinal);
        Assert.DoesNotContain("copyalpha", rendered.Text, StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("//example.test/resource")]
    [InlineData("javascript:run()")]
    [InlineData("data:text/plain,hello")]
    [InlineData("%2e%2e/private/Hidden.md")]
    public void Unsafe_or_out_of_boundary_links_are_not_emitted(string target)
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        repo.Write("private/Hidden.md", "DO_NOT_DISCLOSE_THIS_PAGE\n");
        string markdown = $"[unsafe target]({target})\n";
        string source = repo.Write("docs/links.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/links");

        Assert.Single(diagnostics.BrokenLinks);
        Assert.DoesNotContain("href=", rendered.Html, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("DO_NOT_DISCLOSE_THIS_PAGE", rendered.Html,
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("/guides/getting-started")]
    [InlineData("/authoring/navigation#durable-links")]
    [InlineData("/code/examples/source/GreetingFormatter.cs")]
    public void Site_root_links_are_preserved_as_internal_routes_on_every_platform(string target)
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        string markdown = $"[site route]({target})\n";
        string source = repo.Write("docs/links.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/links");

        Assert.Empty(diagnostics.BrokenLinks);
        Assert.Contains($"href=\"{target}\"", rendered.Html, StringComparison.Ordinal);
        Assert.Contains(target, rendered.Anchors.Links);
    }

    [Fact]
    public void Renderer_rejects_a_source_file_outside_the_documentation_root()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        const string markdown = "# Outside\n";
        string source = repo.Write("outside.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => renderer.Render(markdown, source, "/outside"));

        Assert.Contains("trusted root", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Snippets_are_disabled_unless_the_space_explicitly_opts_in()
    {
        using TempRepository repo = new();
        repo.Write("examples/Sample.cs",
            "// docs:begin sample\nreturn 42;\n// docs:end sample\n");
        repo.WriteConfiguration();
        const string markdown = "```snippet examples/Sample.cs#sample\n```\n";
        string source = repo.Write("docs/snippet.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/snippet");

        Assert.Contains("snippet publication is disabled", rendered.Html,
            StringComparison.Ordinal);
        Assert.Contains(diagnostics.SnippetErrors,
            error => error.Contains("snippet publication is disabled", StringComparison.Ordinal));
        Assert.DoesNotContain("return 42", rendered.Html, StringComparison.Ordinal);
    }

    [Fact]
    public void Enabled_snippets_publish_only_a_named_allowed_region_and_escape_it()
    {
        using TempRepository repo = new();
        repo.Write("examples/Sample.cs",
            "string hidden = \"outside\";\n"
            + "// docs:begin sample\n"
            + "if (left < right) return left & right;\n"
            + "// docs:end sample\n");
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);
        const string markdown = "```snippet examples/Sample.cs#sample\n"
            + "title: Comparison\nlang: csharp\n```\n";
        string source = repo.Write("docs/snippet.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/snippet");

        Assert.Empty(diagnostics.SnippetErrors);
        Assert.Contains("<figure class=\"snippet not-prose\">", rendered.Html,
            StringComparison.Ordinal);
        Assert.Contains("if (left &lt; right) return left &amp; right;", rendered.Html,
            StringComparison.Ordinal);
        Assert.DoesNotContain("outside", rendered.Html, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("// docs:begin sample", "// docs:end sample")]
    [InlineData("# docs:begin sample", "# docs:end sample")]
    [InlineData("-- docs:begin sample", "-- docs:end sample")]
    [InlineData("; docs:begin sample", "; docs:end sample")]
    [InlineData("/* docs:begin sample */", "/* docs:end sample */")]
    [InlineData("<!-- docs:begin sample -->", "<!-- docs:end sample -->")]
    public void Enabled_snippets_accept_each_strict_whole_line_marker_form(
        string begin, string end)
    {
        using TempRepository repo = new();
        repo.Write("examples/Sample.txt",
            $"outside before\n{begin}\nVISIBLE_SNIPPET_TOKEN\n{end}\noutside after\n");
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".txt"]);
        const string markdown = "```snippet examples/Sample.txt#sample\n```\n";
        string source = repo.Write("docs/snippet.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/snippet");

        Assert.Empty(diagnostics.SnippetErrors);
        Assert.Contains("VISIBLE_SNIPPET_TOKEN", rendered.Html,
            StringComparison.Ordinal);
        Assert.DoesNotContain("outside before", rendered.Html, StringComparison.Ordinal);
        Assert.DoesNotContain("outside after", rendered.Html, StringComparison.Ordinal);
    }

    [Fact]
    public void Snippet_marker_text_inside_a_string_literal_is_not_a_marker()
    {
        using TempRepository repo = new();
        repo.Write("examples/Sample.cs",
            "string begin = \"// docs:begin sample\";\n"
            + "string end = \"// docs:end sample\";\n"
            + "SHOULD_NOT_BE_PUBLISHED\n");
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);
        const string markdown = "```snippet examples/Sample.cs#sample\n```\n";
        string source = repo.Write("docs/snippet.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/snippet");

        Assert.Single(diagnostics.SnippetErrors);
        Assert.Contains("render-error", rendered.Html, StringComparison.Ordinal);
        Assert.DoesNotContain("SHOULD_NOT_BE_PUBLISHED", rendered.Html,
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("no markers here\n")]
    [InlineData("// docs:begin sample\nfirst\n// docs:begin sample\nsecond\n// docs:end sample\n")]
    [InlineData("// docs:end sample\ncontent\n// docs:begin sample\n")]
    public void Missing_duplicate_or_reversed_snippet_markers_are_gate_errors(string sourceText)
    {
        using TempRepository repo = new();
        repo.Write("examples/Sample.cs", sourceText);
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);
        const string markdown = "```snippet examples/Sample.cs#sample\n```\n";
        string source = repo.Write("docs/snippet.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/snippet");

        Assert.Single(diagnostics.SnippetErrors);
        Assert.Contains("render-error", rendered.Html, StringComparison.Ordinal);
        Assert.DoesNotContain("first", rendered.Html, StringComparison.Ordinal);
        Assert.DoesNotContain("second", rendered.Html, StringComparison.Ordinal);
    }

    [Fact]
    public void A_snippet_outside_the_source_allowlist_is_not_disclosed()
    {
        using TempRepository repo = new();
        repo.Write("private/Hidden.cs",
            "// docs:begin sample\nDO_NOT_PUBLISH_THIS_TEXT\n// docs:end sample\n");
        repo.Write("examples/Allowed.cs", "internal static class Allowed;\n");
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);
        const string markdown = "```snippet private/Hidden.cs#sample\n```\n";
        string source = repo.Write("docs/snippet.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/snippet");

        Assert.Single(diagnostics.SnippetErrors);
        Assert.Contains("render-error", rendered.Html, StringComparison.Ordinal);
        Assert.DoesNotContain("DO_NOT_PUBLISH_THIS_TEXT", rendered.Html,
            StringComparison.Ordinal);
    }

    [Fact]
    public void A_safe_self_contained_figure_is_inlined_and_its_caption_is_escaped()
    {
        using TempRepository repo = new();
        repo.Write("docs/_assets/figures/flow/figure.svg",
            "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 20 20\">"
            + "<rect width=\"20\" height=\"20\" fill=\"#fff\"/>"
            + "<text x=\"2\" y=\"12\">A &amp; B</text></svg>\n");
        repo.WriteConfiguration();
        const string markdown = "```figure flow\nA < B & C\n```\n";
        string source = repo.Write("docs/figure.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/figure");

        Assert.Empty(diagnostics.FigureErrors);
        Assert.Contains("<figure class=\"doc-figure not-prose\"><svg", rendered.Html,
            StringComparison.Ordinal);
        Assert.Contains("<figcaption>A &lt; B &amp; C</figcaption>", rendered.Html,
            StringComparison.Ordinal);
    }

    [Theory]
    [MemberData(nameof(UnsafeFigurePayloads))]
    public void Active_or_external_figure_content_fails_closed(string payload)
    {
        using TempRepository repo = new();
        repo.Write("docs/_assets/figures/unsafe/figure.svg",
            "<svg xmlns=\"http://www.w3.org/2000/svg\">" + payload + "</svg>\n");
        repo.WriteConfiguration();
        const string markdown = "```figure unsafe\nUnsafe figure\n```\n";
        string source = repo.Write("docs/figure.md", markdown);
        RenderDiagnostics diagnostics = new();
        MarkdownPageRenderer renderer = new(LoadSpace(repo), diagnostics);

        MarkdownRenderResult rendered = renderer.Render(markdown, source, "/figure");

        Assert.Single(diagnostics.FigureErrors);
        Assert.Contains("render-error", rendered.Html, StringComparison.Ordinal);
        Assert.DoesNotContain(payload, rendered.Html, StringComparison.Ordinal);
    }

    private static ResolvedSpace LoadSpace(TempRepository repo) =>
        Assert.Single(ConfigurationLoader.Load(repo.Root, repo.ConfigPath).Spaces);
}
