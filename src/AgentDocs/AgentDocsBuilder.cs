namespace AgentDocs;

public static class AgentDocsBuilder
{
    public static BuildReport Build(string repoRoot, string configPath, string outputPath)
    {
        string repository = Path.GetFullPath(repoRoot);
        string configurationPath = Path.IsPathFullyQualified(configPath)
            ? Path.GetFullPath(configPath)
            : Path.GetFullPath(Path.Combine(repository, configPath));
        string requestedOutput = Path.IsPathFullyQualified(outputPath)
            ? Path.GetFullPath(outputPath)
            : Path.GetFullPath(Path.Combine(repository, outputPath));
        ResolvedConfiguration configuration = ConfigurationLoader.Load(repository, configurationPath);

        string webRoot = Path.Combine(repository, "web");
        IReadOnlyList<string> webAssets = WebAssets.Validate(webRoot);
        IReadOnlyList<NoticeAsset> noticeAssets = NoticeAssets.Validate(repository);
        List<string> protectedInputs = [configurationPath, webRoot,
            Path.Combine(repository, "THIRD-PARTY-NOTICES.md"),
            Path.Combine(repository, "third_party_licenses")];
        foreach (ResolvedSpace space in configuration.Spaces)
        {
            protectedInputs.Add(space.DocsDirAbsolute);
            if (!PathSafety.IsSameOrUnder(space.SourceRootAbsolute, repository)
                || !PathSafety.IsSameOrUnder(repository, space.SourceRootAbsolute))
                protectedInputs.Add(space.SourceRootAbsolute);
            protectedInputs.AddRange(space.SourceTrees.Select(tree => PathSafety.ResolveRepoRelative(
                space.SourceRootAbsolute, tree, "published source tree")));
            protectedInputs.AddRange(space.BrowsableRootFiles.Select(file => PathSafety.ResolveRepoRelative(
                space.SourceRootAbsolute, file, "published root file")));
        }
        protectedInputs.AddRange(AgentWorkflowProjection.InputPaths(configuration));
        string output = OutputDirectory.Prepare(repository, requestedOutput, protectedInputs);
        WebAssets.Copy(webAssets, output, StaticBasePath(configuration.SiteUrl));
        NoticeAssets.Copy(noticeAssets, output);

        HashSet<string> siteRoots = configuration.Spaces
            .Where(space => space.Id.Length > 0)
            .Select(space => "/" + space.Id)
            .ToHashSet(StringComparer.Ordinal);
        List<SpaceBuildResult> spaces = configuration.Spaces.Select(space =>
            new SpaceRenderer(configuration, space, output, siteRoots).Render()).ToList();
        ValidateRoutesAndAnchors(spaces);

        List<SpaceSummary> summaries = spaces.Select(space => new SpaceSummary(
            space.Space.Id,
            space.Space.NavKey,
            space.Space.Label,
            space.Space.RouteRoot,
            space.Documents,
            space.Fragments,
            space.CodeFiles,
            space.CodeFiles > 0,
            space.Space.ShowInMenu)).ToList();
        CodeBrowser.WriteJson(Path.Combine(output, "index.json"), new
        {
            title = configuration.Title,
            siteUrl = configuration.SiteUrl,
            spaces = summaries,
        });
        List<SearchEntry> search = spaces.SelectMany(space => space.Search)
            .OrderBy(entry => entry.Route, StringComparer.Ordinal)
            .ThenBy(entry => entry.Title, StringComparer.Ordinal)
            .ToList();
        CodeBrowser.WriteJson(Path.Combine(output, "search.json"), search);
        CodeBrowser.WriteJson(Path.Combine(output, "build-report.json"), new
        {
            documents = spaces.Sum(space => space.Documents),
            fragments = spaces.Sum(space => space.Fragments),
            codeFiles = spaces.Sum(space => space.CodeFiles),
            broken = spaces.Sum(space => space.Diagnostics.Broken),
        });
        return new(spaces.Sum(space => space.Documents),
                   spaces.Sum(space => space.Fragments),
                   spaces.Sum(space => space.CodeFiles), spaces);
    }

    private static void ValidateRoutesAndAnchors(IReadOnlyList<SpaceBuildResult> spaces)
    {
        Dictionary<string, (RouteAnchors Anchors, SpaceBuildResult Space)> routes =
            new(StringComparer.Ordinal);
        foreach (SpaceBuildResult space in spaces)
        {
            foreach (string route in space.Routes)
                if (!routes.TryAdd(route, (space.Anchors[route], space)))
                    throw new InvalidDataException($"two generated pages use the same route: {route}");
        }

        foreach (SpaceBuildResult space in spaces)
        {
            foreach (RenderedPage page in space.RenderedPages)
            {
                foreach (string route in page.InternalRoutes)
                    if (!routes.ContainsKey(route))
                        space.Diagnostics.BrokenLinks.Add($"{page.Route}: {route} (route not generated)");
                foreach (string link in page.AnchorLinks)
                {
                    int marker = link.IndexOf('#');
                    string route = marker == 0 ? page.Route : StripQuery(link[..marker]);
                    string fragment = marker < 0 ? "" : link[(marker + 1)..];
                    space.Diagnostics.CheckedAnchors++;
                    if (!routes.TryGetValue(route, out var target))
                    {
                        space.Diagnostics.BrokenLinks.Add($"{page.Route}: {link} (route not generated)");
                        continue;
                    }
                    if (fragment.Length == 0 || !target.Anchors.Contains(Uri.UnescapeDataString(fragment)))
                        space.Diagnostics.BrokenAnchors.Add($"{page.Route}: {link} (anchor not generated)");
                }
            }
        }
    }

    private static string StripQuery(string route)
    {
        int query = route.IndexOf('?');
        return query < 0 ? route : route[..query];
    }

    private static string StaticBasePath(string? siteUrl)
    {
        if (siteUrl is null)
            return "/";
        string path = new Uri(siteUrl, UriKind.Absolute).AbsolutePath.TrimEnd('/');
        return path.Length == 0 ? "/" : path;
    }
}

internal sealed record NoticeAsset(string Source, string DestinationRelative);

internal static class NoticeAssets
{
    private const long MaximumNoticeBytes = 256 * 1024;
    private static readonly string[] LicenseFiles =
    [
        "Markdig-BSD-2-Clause.txt",
        "Tailwind-CSS-MIT.txt",
        "Tailwind-Preflight-MIT.txt",
    ];

    internal static IReadOnlyList<NoticeAsset> Validate(string repository)
    {
        List<NoticeAsset> assets = [];
        Add(Path.Combine(repository, "THIRD-PARTY-NOTICES.md"), "THIRD-PARTY-NOTICES.md");
        string licenseRoot = Path.Combine(repository, "third_party_licenses");
        PathSafety.EnsureNoReparse(repository, licenseRoot, "third-party license root");
        foreach (string name in LicenseFiles)
            Add(Path.Combine(licenseRoot, name), "third_party_licenses/" + name);
        return assets;

        void Add(string source, string destination)
        {
            PathSafety.EnsureNoReparse(repository, source, "third-party notice");
            if (!File.Exists(source))
                throw new InvalidDataException($"required third-party notice not found: {destination}");
            if (new FileInfo(source).Length > MaximumNoticeBytes)
                throw new InvalidDataException($"third-party notice exceeds 256 KiB: {destination}");
            assets.Add(new(source, destination));
        }
    }

    internal static void Copy(IEnumerable<NoticeAsset> assets, string output)
    {
        foreach (NoticeAsset asset in assets)
        {
            string destination = Path.Combine(output,
                asset.DestinationRelative.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            File.Copy(asset.Source, destination, overwrite: false);
        }
    }
}

internal static class WebAssets
{
    private static readonly string[] RequiredFiles = ["index.html", "app.js", "app.css"];
    private const long MaximumAssetBytes = 2 * 1024 * 1024;

    internal static IReadOnlyList<string> Validate(string webRoot)
    {
        if (!Directory.Exists(webRoot))
            throw new DirectoryNotFoundException($"web asset root does not exist: {webRoot}");
        string repository = Path.GetDirectoryName(Path.GetFullPath(webRoot))!;
        PathSafety.EnsureNoReparse(repository, webRoot, "web assets");
        List<string> files = [];
        foreach (string name in RequiredFiles)
        {
            string path = Path.Combine(webRoot, name);
            PathSafety.EnsureNoReparse(webRoot, path, "web asset");
            if (!File.Exists(path))
                throw new InvalidDataException($"required web asset not found: {name}");
            if (new FileInfo(path).Length > MaximumAssetBytes)
                throw new InvalidDataException($"web asset exceeds the 2 MiB limit: {name}");
            files.Add(path);
        }
        return files;
    }

    internal static void Copy(IEnumerable<string> files, string output, string basePath)
    {
        foreach (string source in files)
        {
            string destination = Path.Combine(output, Path.GetFileName(source));
            if (Path.GetFileName(source) != "index.html")
            {
                File.Copy(source, destination, overwrite: false);
                continue;
            }
            string html = TextUtilities.ReadText(source);
            const string marker = "data-base=\"/\"";
            if (html.Split(marker, StringSplitOptions.None).Length != 2)
                throw new InvalidDataException("web index must contain exactly one root data-base marker");
            File.WriteAllText(destination,
                html.Replace(marker, $"data-base=\"{basePath}\"", StringComparison.Ordinal),
                new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        }
    }
}
