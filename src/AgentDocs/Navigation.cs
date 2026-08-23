namespace AgentDocs;

internal abstract record NavigationItem;
internal sealed record NavigationPage(string Source, string? Label = null) : NavigationItem;
internal sealed record NavigationGroup(string Directory, string? Index, IReadOnlyList<NavigationItem> Items)
    : NavigationItem;

internal sealed record NavigationResult(
    IReadOnlyList<Dictionary<string, object?>> Tree,
    IReadOnlyList<string> ReadingOrder);

internal sealed class NavigationBuilder
{
    private readonly ResolvedSpace _space;
    private readonly RouteResolver _routes;
    private readonly RenderDiagnostics _diagnostics;

    internal NavigationBuilder(ResolvedSpace space, RouteResolver routes,
                               RenderDiagnostics diagnostics)
    {
        _space = space;
        _routes = routes;
        _diagnostics = diagnostics;
    }

    internal NavigationResult Build()
    {
        IReadOnlyList<NavigationItem> children = ItemsFor(_space.DocsDirAbsolute);
        string? rootIndex = IndexOf(_space.DocsDirAbsolute);
        List<NavigationItem> items = [];
        if (rootIndex is not null)
            items.Add(new NavigationPage(rootIndex, "Overview"));
        items.AddRange(children);

        List<string> reading = [];
        void Flatten(IEnumerable<NavigationItem> nodes)
        {
            foreach (NavigationItem node in nodes)
            {
                if (node is NavigationPage page)
                    reading.Add(page.Source);
                else if (node is NavigationGroup group)
                {
                    if (group.Index is not null)
                        reading.Add(group.Index);
                    Flatten(group.Items);
                }
            }
        }
        Flatten(items);
        return new(items.Select((item, index) => Serialize(item, index > 0 ? 0 : 0).Json).ToList(),
                   reading);
    }

    internal string TitleFor(string source)
    {
        (_, string body) = FrontMatterParser.Split(TextUtilities.ReadText(source));
        string? heading = body.Split('\n').FirstOrDefault(line => line.StartsWith("# ", StringComparison.Ordinal));
        if (heading is null)
            return Path.GetFileNameWithoutExtension(source);
        string title = System.Text.RegularExpressions.Regex.Replace(
            heading[2..].Trim(), @"\s*\{#[A-Za-z0-9_-]+\}\s*$", "");
        return title.Replace("`", "", StringComparison.Ordinal);
    }

    private IReadOnlyList<NavigationItem> ItemsFor(string directory)
    {
        PathSafety.EnsureNoReparse(_space.DocsDirAbsolute, directory, "documentation navigation");
        NavigationIntent intent = Intent(directory);
        List<Child> children = Children(directory);
        if (_space.Curated && children.Count > 0)
        {
            _diagnostics.CuratedSections++;
            if (intent.Kind == NavigationKind.Undeclared)
                _diagnostics.UndeclaredSections.Add(RelativeIndex(directory)
                    + ": declare nav: or nav: unordered");
        }

        if (intent.Kind == NavigationKind.Flat)
            return FlatPages(directory, intent).Cast<NavigationItem>().ToList();

        Dictionary<string, Child> byName = children.ToDictionary(child => child.Name, StringComparer.Ordinal);
        HashSet<string> excluded = ValidateExclusions(directory, intent, byName);
        List<Child> ordered = [];
        HashSet<string> seen = new(StringComparer.Ordinal);
        if (intent.Kind == NavigationKind.Ordered)
        {
            foreach (string configured in intent.Order)
            {
                string name = configured.TrimEnd('/');
                if (!byName.TryGetValue(name, out Child? child))
                    _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: nav -> {configured}");
                else if (!seen.Add(name))
                    _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: duplicate nav -> {configured}");
                else if (excluded.Contains(name))
                    _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: {name} is both listed and excluded");
                else
                    ordered.Add(child);
            }
            foreach (Child child in children)
                if (!seen.Contains(child.Name) && !excluded.Contains(child.Name))
                    _diagnostics.UnlistedDocuments.Add($"{RelativeIndex(directory)}: {child.Name}");
        }
        else
        {
            ordered.AddRange(children.Where(child => !excluded.Contains(child.Name)));
        }

        return ordered.Select(child => child.Directory
            ? (NavigationItem)new NavigationGroup(child.Path, IndexOf(child.Path), ItemsFor(child.Path))
            : new NavigationPage(child.Path)).ToList();
    }

    private IReadOnlyList<NavigationPage> FlatPages(string directory, NavigationIntent intent)
    {
        string root = Path.GetFullPath(directory);
        HashSet<string> exclusions = new(PathComparer);
        foreach (string configured in intent.Excluded)
        {
            string normalized = configured.TrimEnd('/');
            if (!PathSafety.IsPortableRelative(normalized))
            {
                _diagnostics.NavigationErrors.Add(
                    $"{RelativeIndex(directory)}: invalid nav_exclude -> {configured}");
                continue;
            }
            string absolute = Path.GetFullPath(Path.Combine(root,
                normalized.Replace('/', Path.DirectorySeparatorChar)));
            PathSafety.EnsureNoReparse(root, absolute, "flat navigation exclusion");
            if (!File.Exists(absolute) && !Directory.Exists(absolute))
                _diagnostics.NavigationErrors.Add(
                    $"{RelativeIndex(directory)}: nav_exclude -> {configured}");
            else
                exclusions.Add(absolute);
        }
        List<string> pages = DocumentFiles.Walk(_space)
            .Where(path => PathSafety.IsSameOrUnder(path, root))
            .Where(path => path != IndexOf(root))
            .Where(path => Path.GetFileName(path) != "_index.md")
            .Where(path => !exclusions.Any(excluded => PathSafety.IsSameOrUnder(path, excluded)))
            .ToList();

        List<string> pinned = [];
        foreach (string configured in intent.Order)
        {
            if (!PathSafety.IsPortableRelative(configured))
            {
                _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: invalid flat nav -> {configured}");
                continue;
            }
            string absolute = Path.GetFullPath(Path.Combine(root,
                configured.Replace('/', Path.DirectorySeparatorChar)));
            PathSafety.EnsureNoReparse(root, absolute, "flat navigation entry");
            if (!pages.Contains(absolute, PathComparer))
                _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: flat nav -> {configured}");
            else if (!pinned.Contains(absolute, PathComparer))
                pinned.Add(absolute);
        }
        HashSet<string> seen = pinned.ToHashSet(PathComparer);
        pinned.AddRange(pages.Where(page => !seen.Contains(page))
            .OrderBy(TitleFor, StringComparer.OrdinalIgnoreCase)
            .ThenBy(page => TextUtilities.RelativePosix(page, root), StringComparer.Ordinal));
        return pinned.Select(page => new NavigationPage(page)).ToList();
    }

    private HashSet<string> ValidateExclusions(string directory, NavigationIntent intent,
                                                IReadOnlyDictionary<string, Child> children)
    {
        HashSet<string> excluded = new(StringComparer.Ordinal);
        foreach (string configured in intent.Excluded)
        {
            string name = configured.TrimEnd('/');
            if (!PathSafety.IsPortableRelative(name) || name.Contains('/'))
                _diagnostics.NavigationErrors.Add(
                    $"{RelativeIndex(directory)}: invalid nav_exclude -> {configured}");
            else if (!children.ContainsKey(name))
                _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: nav_exclude -> {configured}");
            else if (!excluded.Add(name))
                _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: duplicate nav_exclude -> {configured}");
        }
        return excluded;
    }

    private List<Child> Children(string directory)
    {
        List<Child> children = [];
        PathSafety.EnsureNoReparse(_space.DocsDirAbsolute, directory, "documentation navigation");
        foreach (string entry in Directory.GetFileSystemEntries(directory).Order(StringComparer.Ordinal))
        {
            if (PathSafety.IsReparsePoint(entry))
                throw new InvalidDataException(
                    $"documentation navigation contains a symbolic link or reparse point: {entry}");
            string name = Path.GetFileName(entry);
            if (File.Exists(entry) && name.EndsWith(".md", StringComparison.Ordinal) && name != "_index.md")
                children.Add(new(name, entry, false));
            else if (Directory.Exists(entry) && !DocumentFiles.IsExcludedDirectory(name)
                     && DocumentFiles.DirectoryHasDocuments(_space, entry))
                children.Add(new(name, entry, true));
        }
        return children;
    }

    private NavigationIntent Intent(string directory)
    {
        string? index = IndexOf(directory);
        if (index is null)
            return new(NavigationKind.Undeclared, [], []);
        (FrontMatter meta, _) = FrontMatterParser.Split(TextUtilities.ReadText(index));
        IReadOnlyList<string> excluded = meta.List("nav_exclude") ?? [];
        IReadOnlyList<string>? order = meta.List("nav");
        string? mode = meta.Scalar("nav_mode");
        if (mode is not null and not "flat")
            _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: unsupported nav_mode '{mode}'");
        if (mode == "flat")
            return new(NavigationKind.Flat, order ?? [], excluded);
        if (order is not null)
            return new(NavigationKind.Ordered, order, excluded);
        string? scalar = meta.Scalar("nav");
        if (scalar == "unordered")
            return new(NavigationKind.Unordered, [], excluded);
        if (scalar is not null)
            _diagnostics.NavigationErrors.Add($"{RelativeIndex(directory)}: nav must be a list or 'unordered'");
        return new(NavigationKind.Undeclared, [], excluded);
    }

    private (Dictionary<string, object?> Json, int Plans) Serialize(NavigationItem item, int depth)
    {
        if (item is NavigationPage page)
        {
            (_, string body) = FrontMatterParser.Split(TextUtilities.ReadText(page.Source));
            int count = AgentDocs.Plans.Count(body);
            return (new()
            {
                ["kind"] = "page",
                ["label"] = page.Label ?? TitleFor(page.Source),
                ["route"] = _routes.Route(page.Source),
                ["planCount"] = count,
            }, count);
        }
        NavigationGroup group = (NavigationGroup)item;
        List<(Dictionary<string, object?> Json, int Plans)> children = group.Items
            .Select(child => Serialize(child, depth + 1)).ToList();
        int own = group.Index is null ? 0 : AgentDocs.Plans.Count(
            FrontMatterParser.Split(TextUtilities.ReadText(group.Index)).Body);
        int total = own + children.Sum(child => child.Plans);
        return (new()
        {
            ["kind"] = "group",
            ["label"] = group.Index is null ? TextUtilities.Prettify(Path.GetFileName(group.Directory))
                                             : TitleFor(group.Index),
            ["index"] = group.Index is null ? null : _routes.Route(group.Index),
            ["planCount"] = total,
            ["items"] = children.Select(child => child.Json).ToList(),
            ["sub"] = depth > 0,
        }, total);
    }

    private string RelativeIndex(string directory)
    {
        string relative = TextUtilities.RelativePosix(directory, _space.DocsDirAbsolute);
        return relative == "." ? "_index.md" : relative + "/_index.md";
    }

    private string? IndexOf(string directory)
    {
        string path = Path.Combine(directory, "_index.md");
        PathSafety.EnsureNoReparse(_space.DocsDirAbsolute, path, "navigation index");
        return File.Exists(path) ? Path.GetFullPath(path) : null;
    }

    private static StringComparer PathComparer => OperatingSystem.IsWindows()
        ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    private sealed record Child(string Name, string Path, bool Directory);
    private sealed record NavigationIntent(
        NavigationKind Kind, IReadOnlyList<string> Order, IReadOnlyList<string> Excluded);
    private enum NavigationKind { Undeclared, Unordered, Ordered, Flat }
}
