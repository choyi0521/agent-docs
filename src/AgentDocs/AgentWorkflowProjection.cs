using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace AgentDocs;

public sealed class AgentWorkflowManifest
{
    public int Version { get; init; }
    public string Label { get; init; } = "";
    public List<AgentWorkflowPage> Pages { get; init; } = [];
}

public sealed class AgentWorkflowPage
{
    public string Source { get; init; } = "";
    public string Route { get; init; } = "";
    public string Title { get; init; } = "";
}

internal sealed record ProjectedWorkflowPage(
    string Source,
    string Route,
    string Title,
    MarkdownRenderResult Rendered);

internal sealed record AgentWorkflowProjectionResult(
    string Label,
    IReadOnlyList<ProjectedWorkflowPage> Pages);

internal static partial class AgentWorkflowProjection
{
    private const long MaximumManifestBytes = 128 * 1024;
    private const long MaximumPageBytes = 256 * 1024;
    private const long MaximumTotalBytes = 2 * 1024 * 1024;
    private const int MaximumPages = 256;
    private static readonly JsonSerializerOptions InputOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        RespectNullableAnnotations = true,
        AllowTrailingCommas = false,
        ReadCommentHandling = JsonCommentHandling.Disallow,
    };

    internal static AgentWorkflowProjectionResult LoadAndRender(
        ResolvedConfiguration configuration,
        ResolvedSpace space,
        MarkdownPageRenderer renderer)
    {
        ResolvedAgentWorkflowConfiguration settings = configuration.AgentWorkflows
            ?? throw new InvalidOperationException("agent workflow publication is not configured");
        FileInfo manifestInfo = new(settings.ManifestAbsolute);
        if (manifestInfo.Length > MaximumManifestBytes)
            throw new InvalidDataException("agent workflow manifest exceeds the 128 KiB limit");
        AgentWorkflowManifest manifest = JsonSerializer.Deserialize<AgentWorkflowManifest>(
            TextUtilities.ReadText(settings.ManifestAbsolute), InputOptions)
            ?? throw new InvalidDataException("agent workflow manifest is empty");
        if (manifest.Version != 1)
            throw new InvalidDataException("agent workflow manifest version must be exactly 1");
        if (string.IsNullOrWhiteSpace(manifest.Label) || manifest.Label.Length > 160
            || manifest.Label != manifest.Label.Trim())
            throw new InvalidDataException("agent workflow manifest requires a trimmed label");
        if (manifest.Pages.Count == 0 || manifest.Pages.Count > MaximumPages)
            throw new InvalidDataException($"agent workflow manifest must list 1 to {MaximumPages} pages");

        string prefix = (space.Id.Length == 0 ? "" : "/" + space.Id)
                        + "/" + settings.RoutePrefix;
        HashSet<string> routes = new(StringComparer.Ordinal);
        HashSet<string> sources = new(StringComparer.Ordinal);
        List<ProjectedWorkflowPage> result = [];
        long total = 0;
        foreach (AgentWorkflowPage? page in manifest.Pages)
        {
            if (page is null)
                throw new InvalidDataException("agent workflow pages cannot contain null entries");
            if (!PathSafety.IsPortableRelative(page.Source)
                || !page.Source.EndsWith(".md", StringComparison.Ordinal))
                throw new InvalidDataException($"agent workflow source must be a portable .md path: {page.Source}");
            if (!WorkflowRouteRegex().IsMatch(page.Route) || !routes.Add(page.Route))
                throw new InvalidDataException($"agent workflow route is invalid or duplicated: {page.Route}");
            if (!sources.Add(page.Source))
                throw new InvalidDataException($"agent workflow source is duplicated: {page.Source}");
            if (string.IsNullOrWhiteSpace(page.Title) || page.Title.Length > 160
                || page.Title != page.Title.Trim())
                throw new InvalidDataException($"agent workflow page requires a trimmed title: {page.Source}");

            string source = PathSafety.ResolveRepoRelative(
                configuration.RepoRoot, page.Source, "agent workflow source");
            RejectLocalStateSource(configuration.RepoRoot, source);
            if (!File.Exists(source))
                throw new FileNotFoundException("agent workflow source not found", source);
            FileInfo sourceInfo = new(source);
            if (sourceInfo.Length > MaximumPageBytes)
                throw new InvalidDataException($"agent workflow page exceeds the 256 KiB limit: {page.Source}");
            total += sourceInfo.Length;
            if (total > MaximumTotalBytes)
                throw new InvalidDataException("agent workflow pages exceed the 2 MiB aggregate limit");

            string markdown = TextUtilities.ReadText(source);
            RejectSecrets(markdown, page.Source);
            (_, string body) = FrontMatterParser.Split(markdown);
            string route = prefix + "/" + page.Route;
            MarkdownRenderResult rendered = renderer.RenderWorkflow(
                body, source, route, configuration.RepoRoot);
            result.Add(new(source, route, page.Title, rendered));
        }
        return new(manifest.Label, result);
    }

    internal static IReadOnlyList<string> InputPaths(ResolvedConfiguration configuration)
    {
        if (configuration.AgentWorkflows is null)
            return [];
        ResolvedAgentWorkflowConfiguration settings = configuration.AgentWorkflows;
        FileInfo info = new(settings.ManifestAbsolute);
        if (info.Length > MaximumManifestBytes)
            throw new InvalidDataException("agent workflow manifest exceeds the 128 KiB limit");
        AgentWorkflowManifest manifest = JsonSerializer.Deserialize<AgentWorkflowManifest>(
            TextUtilities.ReadText(settings.ManifestAbsolute), InputOptions)
            ?? throw new InvalidDataException("agent workflow manifest is empty");
        List<string> inputs = [settings.ManifestAbsolute];
        foreach (AgentWorkflowPage? page in manifest.Pages)
        {
            if (page is null)
                throw new InvalidDataException("agent workflow pages cannot contain null entries");
            if (!PathSafety.IsPortableRelative(page.Source))
                throw new InvalidDataException($"agent workflow source must be portable: {page.Source}");
            string source = PathSafety.ResolveRepoRelative(
                configuration.RepoRoot, page.Source, "agent workflow source");
            RejectLocalStateSource(configuration.RepoRoot, source);
            inputs.Add(source);
        }
        return inputs;
    }

    private static void RejectLocalStateSource(string repositoryRoot, string source)
    {
        if (PathSafety.ContainsAgentDocsDirectory(source, repositoryRoot))
            throw new InvalidDataException(
                "agent workflow sources cannot publish the reserved .agent-docs directory");
    }

    private static void RejectSecrets(string text, string source)
    {
        if (text.Contains("BEGIN PRIVATE KEY", StringComparison.OrdinalIgnoreCase)
            || text.Contains("BEGIN RSA PRIVATE KEY", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"agent workflow page appears to contain a private key: {source}");
        foreach (Match match in SecretAssignmentRegex().Matches(text))
        {
            string value = match.Groups[2].Value;
            if (!PlaceholderRegex().IsMatch(value))
                throw new InvalidDataException(
                    $"agent workflow page appears to contain a credential assignment: {source}");
        }
    }

    [GeneratedRegex(@"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")]
    private static partial Regex WorkflowRouteRegex();
    [GeneratedRegex("(?im)\\b(api[_-]?key|secret|token|password)\\b\\s*[:=]\\s*['\\\"]?([A-Za-z0-9_+./=-]{16,})")]
    private static partial Regex SecretAssignmentRegex();
    [GeneratedRegex(@"(?i)(example|placeholder|redacted|changeme|replace|dummy|sample|test)")]
    private static partial Regex PlaceholderRegex();
}
