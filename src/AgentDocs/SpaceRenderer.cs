namespace AgentDocs;

internal sealed class SpaceRenderer
{
    private readonly ResolvedConfiguration _configuration;
    private readonly ResolvedSpace _space;
    private readonly string _output;
    private readonly IReadOnlySet<string> _siteRouteRoots;

    internal SpaceRenderer(ResolvedConfiguration configuration, ResolvedSpace space,
                           string output, IReadOnlySet<string> siteRouteRoots)
    {
        _configuration = configuration;
        _space = space;
        _output = output;
        _siteRouteRoots = siteRouteRoots;
    }

    internal SpaceBuildResult Render()
    {
        RenderDiagnostics diagnostics = new();
        RouteResolver routes = new(_space);
        IReadOnlyList<string> documentSources = DocumentFiles.Walk(_space);
        NavigationBuilder navigationBuilder = new(_space, routes, diagnostics);
        NavigationResult navigation = navigationBuilder.Build();
        List<Dictionary<string, object?>> navigationJson = [.. navigation.Tree];
        MarkdownPageRenderer markdown = new(_space, diagnostics, _siteRouteRoots);

        List<PageWork> pages = [];
        foreach (string source in documentSources)
        {
            (FrontMatter metadata, string body) = FrontMatterParser.Split(TextUtilities.ReadText(source));
            string route = routes.Route(source);
            string title = navigationBuilder.TitleFor(source);
            MarkdownRenderResult rendered = markdown.Render(body, source, route);
            string relative = TextUtilities.RelativePosix(source, _space.DocsDirAbsolute);
            pages.Add(new(source, relative, routes.ContentRelative(source), route, title,
                metadata.Scalar("crumb") ?? _space.Label, rendered));
        }

        int documentCount = pages.Count;
        if (_configuration.AgentWorkflows is { } workflow && workflow.SpaceId == _space.Id)
        {
            AgentWorkflowProjectionResult projection = AgentWorkflowProjection.LoadAndRender(
                _configuration, _space, markdown);
            List<Dictionary<string, object?>> workflowNodes = [];
            foreach (ProjectedWorkflowPage page in projection.Pages)
            {
                string contentRelative = RouteContentRelative(page.Route);
                pages.Add(new(page.Source,
                    TextUtilities.RelativePosix(page.Source, _configuration.RepoRoot),
                    contentRelative, page.Route, page.Title, projection.Label, page.Rendered));
                workflowNodes.Add(new()
                {
                    ["kind"] = "page",
                    ["label"] = page.Title,
                    ["route"] = page.Route,
                    ["planCount"] = Plans.Count(TextUtilities.ReadText(page.Source)),
                });
            }
            navigationJson.Add(new()
            {
                ["kind"] = "group",
                ["label"] = projection.Label,
                ["index"] = projection.Pages[0].Route,
                ["planCount"] = workflowNodes.Sum(node => Convert.ToInt32(node["planCount"])),
                ["items"] = workflowNodes,
                ["sub"] = false,
            });
        }

        Dictionary<string, PageWork> byRoute = new(StringComparer.Ordinal);
        foreach (PageWork page in pages)
            if (!byRoute.TryAdd(page.Route, page))
                throw new InvalidDataException($"two generated pages use the same route: {page.Route}");
        List<string> readingRoutes = navigation.ReadingOrder.Select(routes.Route).ToList();
        readingRoutes.AddRange(pages.Where(page => !readingRoutes.Contains(page.Route, StringComparer.Ordinal))
                                    .Select(page => page.Route));
        for (int index = 0; index < readingRoutes.Count; index++)
        {
            PageWork page = byRoute[readingRoutes[index]];
            NavLink? previous = index == 0 ? null : Link(readingRoutes[index - 1]);
            NavLink? next = index + 1 == readingRoutes.Count ? null : Link(readingRoutes[index + 1]);
            PageFragment fragment = new(page.Title, page.Crumb, page.Rendered.Html,
                page.Rendered.Toc, previous, next);
            CodeBrowser.WriteJson(Path.Combine(_output, "content",
                page.ContentRelative.Replace('/', Path.DirectorySeparatorChar)), fragment);
        }

        CodeBuildResult code = CodeBrowser.Build(_space, _output);
        CodeBrowser.WriteJson(Path.Combine(_output, "nav", _space.NavKey + ".json"), navigationJson);
        if (_space.PublishCode)
            CodeBrowser.WriteJson(Path.Combine(_output, "nav", _space.NavKey + ".code.json"),
                                  code.Navigation);

        HashSet<string> allRoutes = pages.Select(page => page.Route).ToHashSet(StringComparer.Ordinal);
        allRoutes.UnionWith(code.Routes);
        Dictionary<string, RouteAnchors> anchors = pages.ToDictionary(
            page => page.Route,
            page => RouteAnchors.ForPage(page.Rendered.Anchors.Ids),
            StringComparer.Ordinal);
        foreach ((string route, RouteAnchors value) in code.Anchors)
            anchors.Add(route, value);

        List<RenderedPage> renderedPages = pages.Select(page =>
        {
            List<string> internalRoutes = [];
            List<string> anchorLinks = [];
            foreach (string link in page.Rendered.Anchors.Links)
            {
                if (!link.StartsWith("/", StringComparison.Ordinal) && !link.StartsWith('#'))
                    continue;
                int marker = link.IndexOf('#');
                if (marker >= 0)
                    anchorLinks.Add(link);
                else
                    internalRoutes.Add(StripQuery(link));
            }
            int index = readingRoutes.IndexOf(page.Route);
            return new RenderedPage(page.Route,
                index > 0 ? readingRoutes[index - 1] : null,
                index >= 0 && index + 1 < readingRoutes.Count ? readingRoutes[index + 1] : null,
                internalRoutes, anchorLinks);
        }).ToList();
        List<SearchEntry> search = pages.Select(page => new SearchEntry(
            page.Route, page.Title, page.Rendered.Text, _space.Id, _space.Label, page.Relative))
            .Concat(code.Search).ToList();
        return new(_space, documentCount, pages.Count, code.Count, allRoutes, anchors,
                   renderedPages, search, diagnostics);

        NavLink Link(string route)
        {
            PageWork target = byRoute[route];
            return new(route, target.Title);
        }
    }

    private string RouteContentRelative(string route)
    {
        string relative = route.TrimStart('/');
        if (relative.Length == 0)
            relative = "index";
        return relative + ".json";
    }

    private static string StripQuery(string route)
    {
        int query = route.IndexOf('?');
        return query < 0 ? route : route[..query];
    }

    private sealed record PageWork(
        string Source,
        string Relative,
        string ContentRelative,
        string Route,
        string Title,
        string Crumb,
        MarkdownRenderResult Rendered);
}
