using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace AgentDocs;

public sealed class AgentDocsConfiguration
{
    public int SchemaVersion { get; init; }
    public string Title { get; init; } = "";
    public string? SiteUrl { get; init; }
    public List<SpaceConfiguration> Spaces { get; init; } = [];
    public AgentWorkflowConfiguration? AgentWorkflows { get; init; }
}

public sealed class SpaceConfiguration
{
    public string? Id { get; init; }
    public string Label { get; init; } = "";
    public string DocsDir { get; init; } = "";
    public bool Curated { get; init; }
    public bool ShowInMenu { get; init; } = true;
    public string SourceRoot { get; init; } = ".";
    public string? SourceUrlBase { get; init; }
    public bool EnableSnippets { get; init; }
    public bool PublishCode { get; init; }
    public List<string> SourceTrees { get; init; } = [];
    public List<string> SourceExtensions { get; init; } = [];
    public List<string> ExcludedSourcePaths { get; init; } = [];
    public List<string> BrowsableRootFiles { get; init; } = [];
}

public sealed class AgentWorkflowConfiguration
{
    public bool? Enabled { get; init; }
    public string? SpaceId { get; init; }
    public string? Manifest { get; init; }
    public string? RoutePrefix { get; init; }
}

public sealed record ResolvedConfiguration(
    string Title,
    string? SiteUrl,
    string RepoRoot,
    IReadOnlyList<ResolvedSpace> Spaces,
    ResolvedAgentWorkflowConfiguration? AgentWorkflows);

public sealed record ResolvedSpace(
    string Id,
    string Label,
    string DocsDir,
    string DocsDirAbsolute,
    bool Curated,
    bool ShowInMenu,
    string SourceRoot,
    string SourceRootAbsolute,
    Uri? SourceUrlBase,
    bool EnableSnippets,
    bool PublishCode,
    IReadOnlyList<string> SourceTrees,
    IReadOnlySet<string> SourceExtensions,
    IReadOnlyList<string> ExcludedSourcePaths,
    IReadOnlyList<string> BrowsableRootFiles)
{
    public string NavKey => Id.Length == 0 ? "overview" : Id;
    public string RouteRoot => Id.Length == 0 ? "/" : "/" + Id;
}

public sealed record ResolvedAgentWorkflowConfiguration(
    string SpaceId,
    string ManifestAbsolute,
    string RoutePrefix);

public static partial class ConfigurationLoader
{
    private static readonly JsonSerializerOptions InputOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        RespectNullableAnnotations = true,
        AllowTrailingCommas = false,
        ReadCommentHandling = JsonCommentHandling.Disallow,
    };

    public static ResolvedConfiguration Load(string repoRoot, string configPath)
    {
        string repo = Path.GetFullPath(repoRoot);
        if (!Directory.Exists(repo))
            throw new DirectoryNotFoundException($"repository root does not exist: {repo}");
        PathSafety.EnsureNoReparse(repo, repo, "repository root");

        string config = Path.GetFullPath(configPath);
        if (!PathSafety.IsSameOrUnder(config, repo))
            throw new InvalidDataException("configuration must live inside the repository root");
        PathSafety.EnsureNoReparse(repo, config, "configuration");
        if (new FileInfo(config).Length > 1024 * 1024)
            throw new InvalidDataException("configuration exceeds the 1 MiB limit");
        AgentDocsConfiguration value = JsonSerializer.Deserialize<AgentDocsConfiguration>(
            File.ReadAllText(config), InputOptions)
            ?? throw new InvalidDataException("configuration is empty");
        return Resolve(value, repo);
    }

    private static ResolvedConfiguration Resolve(AgentDocsConfiguration value, string repo)
    {
        if (value.SchemaVersion != 1)
            throw new InvalidDataException("schemaVersion must be exactly 1");
        if (string.IsNullOrWhiteSpace(value.Title) || value.Title.Length > 160
            || value.Title != value.Title.Trim())
            throw new InvalidDataException("title must be a trimmed nonempty string");
        if (value.Spaces.Count is 0 or > 64)
            throw new InvalidDataException("between 1 and 64 documentation spaces are required");

        string? siteUrl = NormalizeSiteUrl(value.SiteUrl);
        List<ResolvedSpace> spaces = [];
        HashSet<string> ids = new(StringComparer.Ordinal);
        List<string> docsRoots = [];
        foreach (SpaceConfiguration? space in value.Spaces)
        {
            if (space is null)
                throw new InvalidDataException("spaces cannot contain null entries");
            if (space.Id is null)
                throw new InvalidDataException(
                    "every space requires an explicit id; use an empty space id for root");
            string id = space.Id;
            if (id.Length > 80 || !SpaceIdRegex().IsMatch(id) || !ids.Add(id))
                throw new InvalidDataException($"space id is invalid or duplicated: '{space.Id}'");
            if (string.IsNullOrWhiteSpace(space.Label) || space.Label.Length > 160
                || space.Label != space.Label.Trim())
                throw new InvalidDataException($"space '{id}' requires a trimmed label");

            string docs = PathSafety.ResolveRepoRelative(repo, space.DocsDir,
                $"space '{id}' docsDir");
            string source = PathSafety.ResolveRepoRelative(repo, space.SourceRoot,
                $"space '{id}' sourceRoot", allowDot: true);
            if (PathSafety.ContainsAgentDocsDirectory(docs, repo))
                throw new InvalidDataException(
                    $"space '{id}' docsDir cannot publish the reserved .agent-docs directory");
            if (!Directory.Exists(docs))
                throw new DirectoryNotFoundException($"docsDir does not exist: {space.DocsDir}");
            if (!Directory.Exists(source))
                throw new DirectoryNotFoundException($"sourceRoot does not exist: {space.SourceRoot}");
            if (docsRoots.Any(existing => PathSafety.Overlaps(existing, docs)))
                throw new InvalidDataException("documentation spaces cannot use overlapping docsDir paths");
            docsRoots.Add(docs);

            List<string> trees = ValidateRelativeList(space.SourceTrees, "sourceTrees", allowDot: false);
            if (trees.Any(SourcePolicy.ContainsGeneratedDirectory))
                throw new InvalidDataException(
                    $"space '{id}' sourceTrees cannot publish .agent-docs or generated directories");
            HashSet<string> extensions = ValidateExtensions(space.SourceExtensions);
            List<string> excluded = ValidateRelativeList(
                space.ExcludedSourcePaths, "excludedSourcePaths", allowDot: false);
            List<string> rootFiles = ValidateRootFiles(space.BrowsableRootFiles);
            foreach (string tree in trees)
            {
                string published = PathSafety.ResolveRepoRelative(
                    source, tree, $"space '{id}' source tree");
                if (PathSafety.ContainsAgentDocsDirectory(published, repo))
                    throw new InvalidDataException(
                        $"space '{id}' sourceTrees cannot publish the reserved .agent-docs directory");
            }
            foreach (string rootFile in rootFiles)
            {
                string published = PathSafety.ResolveRepoRelative(
                    source, rootFile, $"space '{id}' browsable root file");
                if (PathSafety.ContainsAgentDocsDirectory(published, repo))
                    throw new InvalidDataException(
                        $"space '{id}' browsableRootFiles cannot publish the reserved .agent-docs directory");
            }
            if ((space.EnableSnippets || space.PublishCode) && (trees.Count == 0 || extensions.Count == 0))
                throw new InvalidDataException(
                    $"space '{id}' source publication requires sourceTrees and sourceExtensions");
            if (!space.PublishCode && rootFiles.Count > 0)
                throw new InvalidDataException("browsableRootFiles requires publishCode");

            Uri? sourceUrl = NormalizeSourceUrl(space.SourceUrlBase, id);
            spaces.Add(new ResolvedSpace(
                id, space.Label, space.DocsDir, docs, space.Curated, space.ShowInMenu,
                space.SourceRoot, source, sourceUrl, space.EnableSnippets, space.PublishCode,
                trees, extensions, excluded, rootFiles));
        }

        ResolvedAgentWorkflowConfiguration? workflows = null;
        if (value.AgentWorkflows is { Enabled: null })
            throw new InvalidDataException("agentWorkflows.enabled is required when agentWorkflows is present");
        if (value.AgentWorkflows is { Enabled: true } workflow)
        {
            if (workflow.SpaceId is null || !ids.Contains(workflow.SpaceId))
                throw new InvalidDataException("agentWorkflows.spaceId names no configured space");
            if (workflow.RoutePrefix is null || !RoutePathRegex().IsMatch(workflow.RoutePrefix))
                throw new InvalidDataException("agentWorkflows.routePrefix is invalid");
            if (workflow.RoutePrefix.Length > 160)
                throw new InvalidDataException("agentWorkflows.routePrefix exceeds 160 characters");
            if (workflow.Manifest is null)
                throw new InvalidDataException("agentWorkflows.manifest is required when enabled");
            string manifest = PathSafety.ResolveRepoRelative(repo, workflow.Manifest,
                "agentWorkflows.manifest");
            if (PathSafety.ContainsAgentDocsDirectory(manifest, repo))
                throw new InvalidDataException(
                    "agentWorkflows.manifest cannot publish the reserved .agent-docs directory");
            if (!File.Exists(manifest))
                throw new FileNotFoundException("agent workflow manifest not found", manifest);
            workflows = new(workflow.SpaceId, manifest, workflow.RoutePrefix);
        }
        else if (value.AgentWorkflows is { Enabled: false } disabled
                 && (disabled.Manifest is not null || disabled.SpaceId is not null
                     || disabled.RoutePrefix is not null))
        {
            throw new InvalidDataException("disabled agentWorkflows must not carry publication settings");
        }

        return new(value.Title, siteUrl, repo, spaces, workflows);
    }

    private static List<string> ValidateRelativeList(IEnumerable<string> values, string label,
                                                      bool allowDot)
    {
        List<string> result = [];
        HashSet<string> unique = new(PathComparer);
        foreach (string value in values)
        {
            if (!PathSafety.IsPortableRelative(value, allowDot) || !unique.Add(value))
                throw new InvalidDataException($"{label} contains an invalid or duplicate path: {value}");
            result.Add(value);
        }
        if (result.Count > 256)
            throw new InvalidDataException($"{label} cannot contain more than 256 paths");
        return result;
    }

    private static HashSet<string> ValidateExtensions(IEnumerable<string> values)
    {
        HashSet<string> result = new(StringComparer.OrdinalIgnoreCase);
        foreach (string value in values)
            if (value.Length > 17 || !ExtensionRegex().IsMatch(value) || !result.Add(value))
                throw new InvalidDataException($"invalid or duplicate source extension: {value}");
        if (result.Count > 64)
            throw new InvalidDataException("sourceExtensions cannot contain more than 64 values");
        return result;
    }

    private static List<string> ValidateRootFiles(IEnumerable<string> values)
    {
        List<string> result = [];
        HashSet<string> unique = new(PathComparer);
        foreach (string value in values)
        {
            if (!PathSafety.IsPortableRelative(value) || value.Contains('/') || !char.IsAsciiLetterOrDigit(value[0])
                || !unique.Add(value))
                throw new InvalidDataException($"invalid or duplicate browsable root file: {value}");
            result.Add(value);
        }
        if (result.Count > 64)
            throw new InvalidDataException("browsableRootFiles cannot contain more than 64 values");
        return result;
    }

    private static string? NormalizeSiteUrl(string? configured)
    {
        if (configured is null)
            return null;
        if (configured.Length > 2048)
            throw new InvalidDataException("siteUrl exceeds 2048 characters");
        if (!Uri.TryCreate(configured, UriKind.Absolute, out Uri? uri)
            || uri.Scheme is not ("http" or "https") || configured.EndsWith('/')
            || uri.UserInfo.Length > 0 || uri.Query.Length > 0 || uri.Fragment.Length > 0)
            throw new InvalidDataException("siteUrl must be an absolute HTTP(S) URL without a trailing slash");
        return configured;
    }

    private static Uri? NormalizeSourceUrl(string? configured, string id)
    {
        if (configured is null)
            return null;
        if (configured.Length > 2048)
            throw new InvalidDataException($"space '{id}' sourceUrlBase exceeds 2048 characters");
        if (!Uri.TryCreate(configured, UriKind.Absolute, out Uri? uri)
            || uri.Scheme is not ("http" or "https") || !configured.EndsWith('/'))
            throw new InvalidDataException(
                $"space '{id}' sourceUrlBase must be HTTP(S) and end with '/'");
        return uri;
    }

    private static StringComparer PathComparer => OperatingSystem.IsWindows()
        ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    [GeneratedRegex(@"^(?:[a-z0-9]+(?:-[a-z0-9]+)*)?$")]
    private static partial Regex SpaceIdRegex();

    [GeneratedRegex(@"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")]
    private static partial Regex RoutePathRegex();

    [GeneratedRegex(@"^\.[a-z0-9][a-z0-9.]*$")]
    private static partial Regex ExtensionRegex();
}
