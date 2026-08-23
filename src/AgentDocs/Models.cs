using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AgentDocs;

public static class JsonFormat
{
    public static readonly JsonSerializerOptions Output = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}

public sealed record NavLink(string Route, string Title);

public sealed record PageFragment(
    string Title,
    string Crumb,
    string Html,
    IReadOnlyList<object[]> Toc,
    NavLink? Prev,
    NavLink? Next);

public sealed record SearchEntry(
    string Route,
    string Title,
    string Text,
    string SpaceId,
    string Space,
    string Path);

public sealed record SpaceSummary(
    string Id,
    string NavKey,
    string Label,
    string Route,
    int Docs,
    int Fragments,
    int Code,
    bool HasCode,
    bool ShowInMenu);

public sealed class RenderDiagnostics
{
    public List<string> BrokenLinks { get; } = [];
    public List<string> BrokenAnchors { get; } = [];
    public List<string> NavigationErrors { get; } = [];
    public List<string> UnlistedDocuments { get; } = [];
    public List<string> UndeclaredSections { get; } = [];
    public List<string> SnippetErrors { get; } = [];
    public List<string> FigureErrors { get; } = [];
    public int CheckedAnchors { get; internal set; }
    public int CuratedSections { get; internal set; }

    public int Broken => BrokenLinks.Count + BrokenAnchors.Count + NavigationErrors.Count
                       + UnlistedDocuments.Count + UndeclaredSections.Count
                       + SnippetErrors.Count + FigureErrors.Count;
}

public sealed record BuildReport(
    int Documents,
    int Fragments,
    int CodeFiles,
    IReadOnlyList<SpaceBuildResult> Spaces)
{
    public int Broken => Spaces.Sum(space => space.Diagnostics.Broken);
}

public sealed class PageAnchors
{
    public HashSet<string> Ids { get; } = new(StringComparer.Ordinal);
    public List<string> Links { get; } = [];
}

public sealed class RouteAnchors
{
    private readonly IReadOnlySet<string>? _ids;
    private readonly int _lineCount;

    private RouteAnchors(IReadOnlySet<string>? ids, int lineCount)
    {
        _ids = ids;
        _lineCount = lineCount;
    }

    public static RouteAnchors ForPage(IReadOnlySet<string> ids) => new(ids, 0);
    public static RouteAnchors ForCode(int lineCount) => new(null, lineCount);

    public bool Contains(string fragment) => _ids is not null
        ? _ids.Contains(fragment)
        : fragment.StartsWith("L-", StringComparison.Ordinal)
          && int.TryParse(fragment.AsSpan(2), out int line)
          && line >= 1 && line <= _lineCount;
}

internal sealed record RenderedPage(
    string Route,
    string? Previous,
    string? Next,
    IReadOnlyList<string> InternalRoutes,
    IReadOnlyList<string> AnchorLinks);

public sealed class SpaceBuildResult
{
    internal SpaceBuildResult(
        ResolvedSpace space,
        int documents,
        int fragments,
        int codeFiles,
        IReadOnlySet<string> routes,
        IReadOnlyDictionary<string, RouteAnchors> anchors,
        IReadOnlyList<RenderedPage> renderedPages,
        IReadOnlyList<SearchEntry> search,
        RenderDiagnostics diagnostics)
    {
        Space = space;
        Documents = documents;
        Fragments = fragments;
        CodeFiles = codeFiles;
        Routes = routes;
        Anchors = anchors;
        RenderedPages = renderedPages;
        Search = search;
        Diagnostics = diagnostics;
    }

    public ResolvedSpace Space { get; }
    public int Documents { get; }
    public int Fragments { get; }
    public int CodeFiles { get; }
    public RenderDiagnostics Diagnostics { get; }
    internal IReadOnlySet<string> Routes { get; }
    internal IReadOnlyDictionary<string, RouteAnchors> Anchors { get; }
    internal IReadOnlyList<RenderedPage> RenderedPages { get; }
    internal IReadOnlyList<SearchEntry> Search { get; }
}
