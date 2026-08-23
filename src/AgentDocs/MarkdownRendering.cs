using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Markdig;
using Markdig.Extensions.CustomContainers;
using Markdig.Renderers;
using Markdig.Renderers.Html;
using Markdig.Syntax;
using Markdig.Syntax.Inlines;

namespace AgentDocs;

public sealed record MarkdownRenderResult(
    string Html,
    IReadOnlyList<object[]> Toc,
    PageAnchors Anchors,
    string Text);

/// <summary>Renders the deliberately small, portable Agent Docs Markdown dialect.</summary>
public sealed partial class MarkdownPageRenderer
{
    private readonly ResolvedSpace _space;
    private readonly RouteResolver _routes;
    private readonly SourcePolicy _sources;
    private readonly RenderDiagnostics _diagnostics;
    private readonly IReadOnlySet<string> _siteRouteRoots;
    private readonly MarkdownPipeline _pipeline;

    public MarkdownPageRenderer(ResolvedSpace space, RenderDiagnostics diagnostics,
                                IReadOnlySet<string>? siteRouteRoots = null)
    {
        _space = space;
        _routes = new RouteResolver(space);
        _sources = new SourcePolicy(space);
        _diagnostics = diagnostics;
        _siteRouteRoots = siteRouteRoots ?? new HashSet<string>(StringComparer.Ordinal);
        MarkdownPipelineBuilder builder = new MarkdownPipelineBuilder()
            .DisableHtml()
            .UsePipeTables()
            .UseEmphasisExtras(Markdig.Extensions.EmphasisExtras.EmphasisExtraOptions.Strikethrough)
            .UseTaskLists()
            .UseAutoLinks();
        Plans.AddParser(builder);
        _pipeline = builder.Build();
    }

    public MarkdownRenderResult Render(string body, string sourceFile, string currentRoute)
        => RenderCore(body, sourceFile, currentRoute, _space.DocsDirAbsolute);

    internal MarkdownRenderResult RenderWorkflow(string body, string sourceFile, string currentRoute,
                                                 string repositoryRoot)
        => RenderCore(body, sourceFile, currentRoute, repositoryRoot);

    private MarkdownRenderResult RenderCore(string body, string sourceFile, string currentRoute,
                                            string trustedRoot)
    {
        string source = Path.GetFullPath(sourceFile);
        string sourceDirectory = Path.GetDirectoryName(source)
            ?? throw new InvalidDataException("document has no containing directory");
        PathSafety.EnsureNoReparse(trustedRoot, source, "documentation page");
        PageAnchors anchors = new();
        List<object[]> toc = [];
        RenderContext context = new(this, sourceDirectory, currentRoute, anchors, toc);
        string rewritten = RewriteFigureImages(body);
        (rewritten, List<string> tabs) = ExpandTabs(rewritten, context);
        string html = RenderMarkdown(rewritten, context);
        for (int index = 0; index < tabs.Count; index++)
            html = html.Replace($"<p>{TabPlaceholder(index)}</p>", tabs[index], StringComparison.Ordinal);
        foreach (Match match in IdAttributeRegex().Matches(html))
            anchors.Ids.Add(match.Groups[1].Value);
        string searchable = HeadingAnchorRegex().Replace(html, " ");
        searchable = CopyButtonRegex().Replace(searchable, " ");
        searchable = PlanKickerRegex().Replace(searchable, " ");
        searchable = SnippetBadgeRegex().Replace(searchable, " ");
        searchable = SnippetSourceRegex().Replace(searchable, " ");
        searchable = SnippetToggleRegex().Replace(searchable, " ");
        searchable = HtmlTagRegex().Replace(searchable, " ");
        string plain = WebUtility.HtmlDecode(searchable);
        plain = WhitespaceRegex().Replace(plain, " ").Trim();
        return new(html, toc, anchors, plain);
    }

    private string RenderMarkdown(string markdown, RenderContext context)
    {
        MarkdownDocument document = Markdown.Parse(markdown, _pipeline);
        StringWriter writer = new();
        HtmlRenderer renderer = new(writer);
        _pipeline.Setup(renderer);
        renderer.ObjectRenderers.Insert(0, new HeadingRenderer(context));
        renderer.ObjectRenderers.Insert(0, new PlanRenderer(context));
        renderer.ObjectRenderers.Insert(0, new CodeRenderer(context));
        renderer.ObjectRenderers.Insert(0, new LinkRenderer(context));
        renderer.Render(document);
        writer.Flush();
        return writer.ToString();
    }

    private (string Text, List<string> Blocks) ExpandTabs(string text, RenderContext context)
    {
        List<string> blocks = [];
        string replaced = TabsRegex().Replace(text, match =>
        {
            string? block = BuildTabs(match.Groups[1].Value, context);
            if (block is null)
                return match.Value;
            blocks.Add(block);
            return $"\n\n{TabPlaceholder(blocks.Count - 1)}\n\n";
        });
        return (replaced, blocks);
    }

    private string? BuildTabs(string inner, RenderContext parent)
    {
        List<(string Label, string Body)> panes = [];
        string? label = null;
        List<string> lines = [];
        foreach (string line in inner.Split('\n'))
        {
            Match separator = TabSeparatorRegex().Match(line);
            if (separator.Success)
            {
                if (label is not null)
                    panes.Add((label, string.Join('\n', lines)));
                label = separator.Groups[1].Value.Trim();
                lines = [];
            }
            else if (label is not null)
            {
                lines.Add(line);
            }
        }
        if (label is not null)
            panes.Add((label, string.Join('\n', lines)));
        if (panes.Count == 0)
            return null;

        StringBuilder buttons = new();
        StringBuilder bodies = new();
        for (int index = 0; index < panes.Count; index++)
        {
            string active = index == 0 ? " active" : "";
            RenderContext nested = parent.ForFragment();
            string pane = RenderMarkdown(RewriteFigureImages(panes[index].Body), nested);
            buttons.Append("<button class=\"tab-btn").Append(active)
                .Append("\" type=\"button\" data-tab=\"").Append(index).Append("\">")
                .Append(TextUtilities.HtmlEscape(panes[index].Label)).Append("</button>");
            bodies.Append("<div class=\"tab-pane").Append(active)
                .Append("\" data-pane=\"").Append(index).Append("\">")
                .Append(pane).Append("</div>");
        }
        return $"<div class=\"tabs\"><div class=\"tab-bar\">{buttons}</div>{bodies}</div>";
    }

    private string RenderSnippet(string arguments, string options, RenderContext context)
    {
        if (!_space.EnableSnippets)
        {
            _diagnostics.SnippetErrors.Add($"{context.CurrentRoute}: snippet publication is disabled");
            return Error("snippet publication is disabled");
        }
        Match selector = SnippetSelectorRegex().Match(arguments);
        if (!selector.Success)
        {
            _diagnostics.SnippetErrors.Add($"{context.CurrentRoute}: invalid snippet selector '{arguments}'");
            return Error("invalid snippet selector");
        }

        Dictionary<string, string> settings = ParseFenceOptions(
            options, new HashSet<string>(["title", "lang", "fold"], StringComparer.Ordinal),
            out string? optionError);
        if (optionError is not null)
        {
            _diagnostics.SnippetErrors.Add($"{context.CurrentRoute}: {optionError}");
            return Error(optionError);
        }

        string relative = selector.Groups[1].Value;
        string name = selector.Groups[2].Value;
        try
        {
            string absolute = _sources.ResolveAllowed(relative);
            if (new FileInfo(absolute).Length > 1024 * 1024)
                throw new InvalidDataException("snippet source exceeds the 1 MiB limit");
            SnippetResolution snippet = Snippets.Resolve(TextUtilities.ReadText(absolute), name);
            if (snippet.Error is not null)
                throw new InvalidDataException(snippet.IsMissing
                    ? $"snippet marker not found: {relative}#{name}" : snippet.Error);
            string language = settings.GetValueOrDefault("lang") ?? SourcePolicy.Lexer(relative);
            if (!LanguageRegex().IsMatch(language))
                throw new InvalidDataException("snippet lang must contain only letters, digits, '_' or '-'");
            string title = settings.GetValueOrDefault("title") ?? $"{relative} - {name}";
            bool fold = false;
            if (settings.TryGetValue("fold", out string? foldValue)
                && !bool.TryParse(foldValue, out fold))
                throw new InvalidDataException("snippet fold must be exactly true or false");
            string? href = _space.PublishCode
                ? CodeBrowser.RouteFor(_space, relative) + "#L-" + snippet.FirstLine
                : _sources.SourceUrl(relative, snippet.FirstLine);
            string sourceLink = href is null ? ""
                : $"<a class=\"snip-src\" href=\"{TextUtilities.HtmlEscape(href)}\">source:{snippet.FirstLine}</a>";
            if (href is not null && href.StartsWith("/", StringComparison.Ordinal))
                context.Anchors.Links.Add(href);
            string header = "<figcaption class=\"snip-head\"><span class=\"snip-badge\">source</span>"
                + "<span class=\"snip-title\">" + TextUtilities.HtmlEscape(title) + "</span>"
                + sourceLink + "</figcaption>";
            string codeBlock = "<div class=\"codeblock\"><button class=\"copy\" type=\"button\">copy</button>"
                + "<pre><code class=\"language-" + language + "\">"
                + TextUtilities.HtmlEscape(snippet.Code!) + "</code></pre></div>";
            if (!fold)
                return "<figure class=\"snippet not-prose\">" + header + codeBlock + "</figure>";
            int lineCount = snippet.Code!.Length == 0 ? 0
                : snippet.Code.Count(character => character == '\n') + 1;
            string summary = "<summary class=\"snip-toggle\"><span class=\"snip-toggle-show\">Show code</span>"
                + "<span class=\"snip-toggle-hide\">Hide code</span><span class=\"snip-toggle-lines\">"
                + lineCount + (lineCount == 1 ? " line" : " lines") + "</span></summary>";
            return "<figure class=\"snippet not-prose\">" + header + "<details>" + summary
                + codeBlock + "</details></figure>";
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException
                                          or InvalidDataException)
        {
            _diagnostics.SnippetErrors.Add($"{context.CurrentRoute}: {exception.Message}");
            return Error(exception.Message);
        }
    }

    private string RenderFigure(string name, string caption, RenderContext context)
    {
        if (!FigureNameRegex().IsMatch(name))
        {
            _diagnostics.FigureErrors.Add($"{context.CurrentRoute}: invalid figure name '{name}'");
            return Error("invalid figure name");
        }
        string path = Path.Combine(_space.DocsDirAbsolute, "_assets", "figures", name, "figure.svg");
        try
        {
            PathSafety.EnsureNoReparse(_space.DocsDirAbsolute, path, "figure bundle");
            if (!File.Exists(path))
                throw new FileNotFoundException($"figure bundle not found: {name}");
            string svg = SafeSvg.Load(path);
            string body = string.IsNullOrWhiteSpace(caption)
                ? "" : "<figcaption>" + TextUtilities.HtmlEscape(caption.Trim()) + "</figcaption>";
            return $"<figure class=\"doc-figure not-prose\">{svg}{body}</figure>";
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException
                                          or InvalidDataException or XmlException)
        {
            _diagnostics.FigureErrors.Add($"{context.CurrentRoute}: {exception.Message}");
            return Error(exception.Message);
        }
    }

    private string? RewriteHref(string url, RenderContext context, bool image)
    {
        string value = url.Trim();
        if (value.Length == 0 || value.StartsWith("//", StringComparison.Ordinal)
            || value.Contains('\\') || value.Contains('\0'))
            return Broken(value, context, "unsafe or empty link");
        if (image)
            return Broken(value, context, "only validated local SVG figure bundles can publish images");
        if (value.StartsWith('#'))
        {
            context.Anchors.Links.Add(value);
            return value;
        }
        if (Uri.TryCreate(value, UriKind.Absolute, out Uri? absolute))
        {
            if (absolute.Scheme is "http" or "https" or "mailto")
                return value;
            return Broken(value, context, "unsupported link scheme");
        }
        if (value.StartsWith('/'))
        {
            context.Anchors.Links.Add(value);
            return value;
        }

        int marker = value.IndexOfAny(['#', '?']);
        string pathPart = marker < 0 ? value : value[..marker];
        string suffix = marker < 0 ? "" : value[marker..];
        string local;
        try
        {
            local = Path.GetFullPath(Path.Combine(context.SourceDirectory,
                Uri.UnescapeDataString(pathPart).Replace('/', Path.DirectorySeparatorChar)));
        }
        catch (Exception exception) when (exception is ArgumentException or UriFormatException)
        {
            return Broken(value, context, "invalid relative link");
        }

        if (PathSafety.IsSameOrUnder(local, _space.DocsDirAbsolute))
        {
            try
            {
                PathSafety.EnsureNoReparse(_space.DocsDirAbsolute, local, "documentation link");
            }
            catch (InvalidDataException)
            {
                return Broken(value, context, "documentation link crosses a reparse point");
            }
            if (Directory.Exists(local))
                local = Path.Combine(local, "_index.md");
            if (File.Exists(local) && local.EndsWith(".md", StringComparison.Ordinal))
            {
                string route = _routes.Route(local) + suffix;
                context.Anchors.Links.Add(route);
                return route;
            }
            if (image)
                return Broken(value, context, "only validated figure bundles can publish images");
            return Broken(value, context, "documentation target does not exist");
        }

        if (!image && File.Exists(local) && _space.PublishCode && _sources.IsAllowed(local))
        {
            string relative = TextUtilities.RelativePosix(local, _space.SourceRootAbsolute);
            string route = CodeBrowser.RouteFor(_space, relative) + suffix;
            context.Anchors.Links.Add(route);
            return route;
        }
        return Broken(value, context, "target is outside the published documentation boundary");
    }

    private string? Broken(string value, RenderContext context, string reason)
    {
        _diagnostics.BrokenLinks.Add($"{context.CurrentRoute}: {value} ({reason})");
        return null;
    }

    private static Dictionary<string, string> ParseFenceOptions(
        string text, IReadOnlySet<string> allowed, out string? error)
    {
        Dictionary<string, string> result = new(StringComparer.Ordinal);
        error = null;
        foreach (string line in text.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n'))
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;
            int colon = line.IndexOf(':');
            if (colon <= 0)
            {
                error = "snippet options must use 'name: value'";
                return result;
            }
            string key = line[..colon].Trim();
            string value = line[(colon + 1)..].Trim();
            if (!allowed.Contains(key) || value.Length == 0 || !result.TryAdd(key, value))
            {
                error = $"invalid or duplicate snippet option '{key}'";
                return result;
            }
        }
        return result;
    }

    private static string Error(string message) =>
        $"<div class=\"render-error\">{TextUtilities.HtmlEscape(message)}</div>";

    private static string RewriteFigureImages(string body) => FigureImageRegex().Replace(body,
        match => "```figure " + match.Groups["name"].Value + "\n"
                 + match.Groups["caption"].Value + "\n```");

    private static string TabPlaceholder(int index) => $"xAGENTDOCSTABx{index}x";

    [GeneratedRegex(@"^!\[(?<caption>[^\]]*)\]\([^()]*_assets/figures/(?<name>[a-z0-9-]+)/figure\.svg\)\s*$",
                    RegexOptions.Multiline)]
    private static partial Regex FigureImageRegex();
    [GeneratedRegex(@"^:::tabs[ \t]*\n(.*?)\n:::[ \t]*$", RegexOptions.Singleline | RegexOptions.Multiline)]
    private static partial Regex TabsRegex();
    [GeneratedRegex(@"^==[ \t]+(.*\S)[ \t]*$")]
    private static partial Regex TabSeparatorRegex();
    [GeneratedRegex(@"(?<![-\w:])id=""([^""]+)""")]
    private static partial Regex IdAttributeRegex();
    [GeneratedRegex(@"\s+")]
    private static partial Regex WhitespaceRegex();
    [GeneratedRegex(@"<a\s+class=""h-anchor""[^>]*>.*?</a>", RegexOptions.Singleline)]
    private static partial Regex HeadingAnchorRegex();
    [GeneratedRegex(@"<button\s+class=""copy""[^>]*>.*?</button>", RegexOptions.Singleline)]
    private static partial Regex CopyButtonRegex();
    [GeneratedRegex(@"<span\s+class=""plan-kicker""[^>]*>.*?</span>", RegexOptions.Singleline)]
    private static partial Regex PlanKickerRegex();
    [GeneratedRegex(@"<span\s+class=""snip-badge""[^>]*>.*?</span>", RegexOptions.Singleline)]
    private static partial Regex SnippetBadgeRegex();
    [GeneratedRegex(@"<a\s+class=""snip-src""[^>]*>.*?</a>", RegexOptions.Singleline)]
    private static partial Regex SnippetSourceRegex();
    [GeneratedRegex(@"<summary\s+class=""snip-toggle""[^>]*>.*?</summary>", RegexOptions.Singleline)]
    private static partial Regex SnippetToggleRegex();
    [GeneratedRegex(@"<[^>]+>")]
    private static partial Regex HtmlTagRegex();
    [GeneratedRegex(@"^([A-Za-z0-9._/-]+)#([A-Za-z0-9][A-Za-z0-9_-]*)$")]
    private static partial Regex SnippetSelectorRegex();
    [GeneratedRegex(@"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
    private static partial Regex LanguageRegex();
    [GeneratedRegex(@"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")]
    private static partial Regex FigureNameRegex();

    private sealed class RenderContext
    {
        internal RenderContext(MarkdownPageRenderer owner, string sourceDirectory, string currentRoute,
                               PageAnchors anchors, List<object[]> toc)
        {
            Owner = owner;
            SourceDirectory = sourceDirectory;
            CurrentRoute = currentRoute;
            Anchors = anchors;
            Toc = toc;
        }

        internal MarkdownPageRenderer Owner { get; }
        internal string SourceDirectory { get; }
        internal string CurrentRoute { get; }
        internal PageAnchors Anchors { get; }
        internal List<object[]> Toc { get; }
        internal Dictionary<string, int> Slugs { get; } = new(StringComparer.Ordinal);
        internal int PlanCount { get; set; }
        internal RenderContext ForFragment() => new(Owner, SourceDirectory, CurrentRoute, Anchors, []);
    }

    private sealed partial class HeadingRenderer : HtmlObjectRenderer<HeadingBlock>
    {
        private readonly RenderContext _context;
        internal HeadingRenderer(RenderContext context) => _context = context;

        protected override void Write(HtmlRenderer renderer, HeadingBlock heading)
        {
            string html = CaptureInline(renderer, heading);
            string plain = WebUtility.HtmlDecode(TextUtilities.StripTags(html));
            Match explicitId = ExplicitHeadingIdRegex().Match(plain);
            string slug;
            if (explicitId.Success)
            {
                slug = explicitId.Groups[1].Value;
                plain = plain[..explicitId.Index].TrimEnd();
                html = ExplicitHeadingIdRegex().Replace(html, "").TrimEnd();
            }
            else
            {
                string basis = TextUtilities.Slugify(plain);
                int occurrence = _context.Slugs.GetValueOrDefault(basis);
                slug = occurrence == 0 ? basis : $"{basis}-{occurrence}";
                _context.Slugs[basis] = occurrence + 1;
            }
            if (!_context.Anchors.Ids.Add(slug))
                _context.Owner._diagnostics.BrokenAnchors.Add(
                    $"{_context.CurrentRoute}: duplicate anchor #{slug}");
            if (heading.Level is 2 or 3)
                _context.Toc.Add([heading.Level, slug, plain]);
            renderer.EnsureLine();
            renderer.Write("<h").Write(heading.Level.ToString()).Write(" id=\"")
                .Write(slug).Write("\">").Write(html)
                .Write("<a class=\"h-anchor\" href=\"#").Write(slug)
                .Write("\" aria-label=\"link to section\">#</a></h")
                .Write(heading.Level.ToString()).WriteLine(">");
        }

        [GeneratedRegex(@"\s*\{#([A-Za-z0-9][A-Za-z0-9_-]*)\}\s*$")]
        private static partial Regex ExplicitHeadingIdRegex();
    }

    private sealed class PlanRenderer : HtmlObjectRenderer<CustomContainer>
    {
        private readonly RenderContext _context;
        internal PlanRenderer(RenderContext context) => _context = context;

        protected override void Write(HtmlRenderer renderer, CustomContainer container)
        {
            if (!Plans.IsPlan(container))
            {
                renderer.WriteChildren(container);
                return;
            }
            string title = Plans.Title(container);
            if (title.Length == 0)
            {
                _context.Owner._diagnostics.NavigationErrors.Add(
                    $"{_context.CurrentRoute}: :::plan requires a title");
                title = "Untitled plan";
            }
            int number = ++_context.PlanCount;
            string id = number == 1 ? "plan" : $"plan-{number}";
            string titleId = id + "-title";
            _context.Anchors.Ids.Add(id);
            _context.Anchors.Ids.Add(titleId);
            renderer.EnsureLine();
            renderer.Write("<section class=\"plan-section\" id=\"").Write(id)
                .Write("\" aria-labelledby=\"").Write(titleId).WriteLine("\">");
            renderer.Write("<header class=\"plan-header not-prose\"><span class=\"plan-kicker\">Plan</span>")
                .Write("<div class=\"plan-title\" id=\"").Write(titleId).Write("\">")
                .Write(WebUtility.HtmlEncode(title)).WriteLine("</div></header>");
            renderer.WriteLine("<div class=\"plan-body\">");
            renderer.WriteChildren(container);
            renderer.WriteLine("</div></section>");
        }
    }

    private sealed class CodeRenderer : HtmlObjectRenderer<CodeBlock>
    {
        private readonly RenderContext _context;
        internal CodeRenderer(RenderContext context) => _context = context;

        protected override void Write(HtmlRenderer renderer, CodeBlock block)
        {
            string body = Body(block);
            if (block is FencedCodeBlock fenced)
            {
                string kind = fenced.Info ?? "";
                string arguments = (fenced.Arguments ?? "").Trim();
                if (arguments.Length == 0 && kind.Contains(' '))
                {
                    int separator = kind.IndexOf(' ');
                    arguments = kind[(separator + 1)..].Trim();
                    kind = kind[..separator];
                }
                if (kind == "snippet")
                {
                    renderer.Write(_context.Owner.RenderSnippet(arguments, body, _context));
                    return;
                }
                if (kind == "figure")
                {
                    renderer.Write(_context.Owner.RenderFigure(arguments, body, _context));
                    return;
                }
                WritePlain(renderer, body, kind);
                return;
            }
            WritePlain(renderer, body, "");
        }

        private static void WritePlain(HtmlRenderer renderer, string text, string language)
        {
            string safeLanguage = LanguageRegex().IsMatch(language) ? language : "text";
            renderer.EnsureLine();
            renderer.Write("<div class=\"codeblock not-prose\"><button class=\"copy\" type=\"button\">copy</button>")
                .Write("<pre><code class=\"language-").Write(safeLanguage).Write("\">")
                .Write(TextUtilities.HtmlEscape(text)).WriteLine("</code></pre></div>");
        }

        private static string Body(LeafBlock block)
        {
            StringBuilder result = new();
            for (int index = 0; index < block.Lines.Count; index++)
                result.Append(block.Lines.Lines[index].Slice.ToString()).Append('\n');
            return result.ToString();
        }
    }

    private sealed class LinkRenderer : HtmlObjectRenderer<LinkInline>
    {
        private readonly RenderContext _context;
        internal LinkRenderer(RenderContext context) => _context = context;

        protected override void Write(HtmlRenderer renderer, LinkInline link)
        {
            string? url = _context.Owner.RewriteHref(link.Url ?? "", _context, link.IsImage);
            if (url is null)
            {
                foreach (Inline child in Children(link))
                    renderer.Render(child);
                return;
            }
            string title = string.IsNullOrEmpty(link.Title) ? ""
                : $" title=\"{TextUtilities.HtmlEscape(link.Title!)}\"";
            if (link.IsImage)
            {
                string alt = TextUtilities.StripTags(CaptureChildren(renderer, link));
                renderer.Write("<img src=\"").Write(TextUtilities.HtmlEscape(url))
                    .Write("\" alt=\"").Write(TextUtilities.HtmlEscape(alt)).Write("\"")
                    .Write(title).Write(" loading=\"lazy\">");
                return;
            }
            string external = url.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                || url.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
                ? " target=\"_blank\" rel=\"noopener\"" : "";
            renderer.Write("<a href=\"").Write(TextUtilities.HtmlEscape(url)).Write("\"")
                .Write(title).Write(external).Write(">");
            foreach (Inline child in Children(link))
                renderer.Render(child);
            renderer.Write("</a>");
        }

        private static IEnumerable<Inline> Children(LinkInline link)
        {
            for (Inline? child = link.FirstChild; child is not null; child = child.NextSibling)
                yield return child;
        }
    }

    private static string CaptureInline(HtmlRenderer renderer, LeafBlock block)
    {
        TextWriter original = renderer.Writer;
        StringWriter buffer = new();
        renderer.Writer = buffer;
        if (block.Inline is not null)
            for (Inline? child = block.Inline.FirstChild; child is not null; child = child.NextSibling)
                renderer.Render(child);
        renderer.Writer = original;
        return buffer.ToString();
    }

    private static string CaptureChildren(HtmlRenderer renderer, LinkInline link)
    {
        TextWriter original = renderer.Writer;
        StringWriter buffer = new();
        renderer.Writer = buffer;
        for (Inline? child = link.FirstChild; child is not null; child = child.NextSibling)
            renderer.Render(child);
        renderer.Writer = original;
        return buffer.ToString();
    }
}

internal static class SafeSvg
{
    private const long MaximumBytes = 512 * 1024;
    private static readonly HashSet<string> AllowedElements = new(StringComparer.Ordinal)
    {
        "svg", "title", "desc", "g", "defs", "path", "rect", "circle", "ellipse", "line",
        "polyline", "polygon", "text", "tspan", "linearGradient", "radialGradient", "stop",
        "clipPath", "mask", "symbol", "use"
    };
    private static readonly HashSet<string> AllowedAttributes = new(StringComparer.Ordinal)
    {
        "id", "role", "aria-label", "aria-labelledby", "aria-describedby", "focusable",
        "viewBox", "width", "height", "preserveAspectRatio", "version",
        "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
        "d", "points", "pathLength", "transform", "vector-effect",
        "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap",
        "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity",
        "opacity", "clip-path", "mask", "clip-rule",
        "font-family", "font-size", "font-weight", "font-style", "text-anchor",
        "dominant-baseline", "letter-spacing", "word-spacing",
        "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
        "spreadMethod", "fx", "fy", "href"
    };

    internal static string Load(string path)
    {
        FileInfo info = new(path);
        if (info.Length > MaximumBytes)
            throw new InvalidDataException("figure SVG exceeds the 512 KiB limit");
        XmlReaderSettings settings = new()
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            MaxCharactersInDocument = MaximumBytes,
            IgnoreComments = true,
        };
        using XmlReader reader = XmlReader.Create(path, settings);
        XDocument document = XDocument.Load(reader, LoadOptions.None);
        if (document.DescendantNodes().Any(node => node is XProcessingInstruction or XDocumentType))
            throw new InvalidDataException("figure cannot contain processing instructions or a document type");
        XElement root = document.Root ?? throw new InvalidDataException("figure SVG is empty");
        if (root.Name.LocalName != "svg" || root.Name.NamespaceName != "http://www.w3.org/2000/svg")
            throw new InvalidDataException("figure root must be an SVG element");
        Dictionary<string, string> rewrittenIds = new(StringComparer.Ordinal);
        string prefix = "figure-" + Convert.ToHexString(
            SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(root.ToString(SaveOptions.DisableFormatting))))
            [..12].ToLowerInvariant() + "-";
        foreach (XElement element in root.DescendantsAndSelf())
        {
            if (element.Name.NamespaceName != "http://www.w3.org/2000/svg"
                || !AllowedElements.Contains(element.Name.LocalName))
                throw new InvalidDataException($"figure contains a forbidden element: {element.Name.LocalName}");
            foreach (XAttribute attribute in element.Attributes())
            {
                if (attribute.IsNamespaceDeclaration)
                {
                    if (attribute.Name.LocalName != "xmlns"
                        || attribute.Value != "http://www.w3.org/2000/svg")
                        throw new InvalidDataException("figure contains an unsupported namespace declaration");
                    continue;
                }
                string name = attribute.Name.LocalName;
                string value = attribute.Value.Trim();
                if (attribute.Name.NamespaceName.Length != 0 || !AllowedAttributes.Contains(name))
                    throw new InvalidDataException($"figure contains an unsupported attribute: {name}");
                if (name == "id")
                {
                    if (!SvgIdRegex.IsMatch(value) || !rewrittenIds.TryAdd(value, prefix + value))
                        throw new InvalidDataException($"figure contains an invalid or duplicate id: {value}");
                }
                if (value.Contains("url(", StringComparison.OrdinalIgnoreCase)
                    && !LocalUrlRegex.IsMatch(value))
                    throw new InvalidDataException("figure URL references must be one local fragment");
                if (value.Contains("://", StringComparison.OrdinalIgnoreCase)
                    || value.StartsWith("//", StringComparison.Ordinal)
                    || value.Contains("javascript:", StringComparison.OrdinalIgnoreCase)
                    || value.Contains("data:", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("figure attributes cannot contain URL-like values");
                if (name == "href" && !LocalFragmentRegex.IsMatch(value))
                    throw new InvalidDataException("figure href must be a local fragment identifier");
            }
        }
        foreach (XElement element in root.DescendantsAndSelf())
        {
            foreach (XAttribute attribute in element.Attributes().Where(value => !value.IsNamespaceDeclaration))
            {
                string name = attribute.Name.LocalName;
                string value = attribute.Value.Trim();
                if (name == "id")
                {
                    attribute.Value = rewrittenIds[value];
                }
                else if (name is "aria-labelledby" or "aria-describedby")
                {
                    string[] ids = value.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                    if (ids.Length == 0 || ids.Any(id => !rewrittenIds.ContainsKey(id)))
                        throw new InvalidDataException($"figure {name} references an unknown id");
                    attribute.Value = string.Join(' ', ids.Select(id => rewrittenIds[id]));
                }
                else if (name == "href")
                {
                    string id = value[1..];
                    if (!rewrittenIds.TryGetValue(id, out string? replacement))
                        throw new InvalidDataException("figure href references an unknown id");
                    attribute.Value = "#" + replacement;
                }
                else
                {
                    Match url = LocalUrlRegex.Match(value);
                    if (url.Success)
                    {
                        string id = url.Groups[1].Value;
                        if (!rewrittenIds.TryGetValue(id, out string? replacement))
                            throw new InvalidDataException("figure URL references an unknown id");
                        attribute.Value = "url(#" + replacement + ")";
                    }
                }
            }
        }
        return root.ToString(SaveOptions.DisableFormatting);
    }

    private static readonly Regex SvgIdRegex = new(@"^[A-Za-z][A-Za-z0-9_.-]*$",
                                                    RegexOptions.CultureInvariant);
    private static readonly Regex LocalFragmentRegex = new(@"^#[A-Za-z][A-Za-z0-9_.-]*$",
                                                            RegexOptions.CultureInvariant);
    private static readonly Regex LocalUrlRegex = new(@"^url\(#([A-Za-z][A-Za-z0-9_.-]*)\)$",
                                                       RegexOptions.CultureInvariant);
}
