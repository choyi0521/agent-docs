using System.Text;
using System.Text.Json;

namespace AgentDocs;

internal sealed record CodeBuildResult(
    int Count,
    IReadOnlySet<string> Routes,
    IReadOnlyDictionary<string, RouteAnchors> Anchors,
    IReadOnlyList<SearchEntry> Search,
    IReadOnlyList<Dictionary<string, object?>> Navigation);

public static class CodeBrowser
{
    private const long MaximumFileBytes = 1024 * 1024;
    private const long MaximumTotalBytes = 25 * 1024 * 1024;
    private const int MaximumFiles = 5_000;

    public static string RouteFor(ResolvedSpace space, string sourceRelative)
    {
        if (!PathSafety.IsPortableRelative(sourceRelative))
            throw new InvalidDataException($"source route is not portable: {sourceRelative}");
        string prefix = space.Id.Length == 0 ? "" : "/" + space.Id;
        return prefix + "/code/" + sourceRelative;
    }

    internal static CodeBuildResult Build(ResolvedSpace space, string output)
    {
        if (!space.PublishCode)
            return new(0, new HashSet<string>(), new Dictionary<string, RouteAnchors>(), [], []);
        SourcePolicy policy = new(space);
        IReadOnlyList<string> files = policy.EnumerateFiles();
        if (files.Count > MaximumFiles)
            throw new InvalidDataException($"code publication exceeds the {MaximumFiles} file limit");

        long total = 0;
        HashSet<string> routes = new(StringComparer.Ordinal);
        Dictionary<string, RouteAnchors> anchors = new(StringComparer.Ordinal);
        List<SearchEntry> search = [];
        List<Dictionary<string, object?>> navigation = [];
        foreach (string file in files)
        {
            FileInfo info = new(file);
            if (info.Length > MaximumFileBytes)
                throw new InvalidDataException(
                    $"published source exceeds the 1 MiB file limit: {TextUtilities.RelativePosix(file, space.SourceRootAbsolute)}");
            total += info.Length;
            if (total > MaximumTotalBytes)
                throw new InvalidDataException("published source exceeds the 25 MiB aggregate limit");

            string relative = TextUtilities.RelativePosix(file, space.SourceRootAbsolute);
            string route = RouteFor(space, relative);
            string text = TextUtilities.ReadText(file);
            string[] lines = text.Split('\n');
            if (lines.Length > 0 && lines[^1].Length == 0)
                lines = lines[..^1];
            string title = Path.GetFileName(relative);
            string language = SourcePolicy.Lexer(relative);
            string html = RenderLines(lines, language);
            object page = new
            {
                kind = "code",
                title,
                path = relative,
                language,
                lines,
                sourceUrl = policy.SourceUrl(relative),
                html,
            };
            string destination = Path.Combine(output, "content",
                route.TrimStart('/').Replace('/', Path.DirectorySeparatorChar) + ".json");
            WriteJson(destination, page);
            routes.Add(route);
            anchors.Add(route, RouteAnchors.ForCode(lines.Length));
            search.Add(new(route, title, text, space.Id, space.Label, relative));
            navigation.Add(new()
            {
                ["kind"] = "code",
                ["label"] = relative,
                ["route"] = route,
            });
        }
        return new(files.Count, routes, anchors, search, navigation);
    }

    private static string RenderLines(IReadOnlyList<string> lines, string language)
    {
        StringBuilder html = new("<div class=\"source-lines not-prose\"><table><tbody>");
        for (int index = 0; index < lines.Count; index++)
        {
            int number = index + 1;
            html.Append("<tr id=\"L-").Append(number).Append("\"><th><a href=\"#L-")
                .Append(number).Append("\" aria-label=\"line ").Append(number).Append("\">")
                .Append(number).Append("</a></th><td><pre><code class=\"language-")
                .Append(language).Append("\">")
                .Append(TextUtilities.HtmlEscape(lines[index]))
                .Append("</code></pre></td></tr>");
        }
        return html.Append("</tbody></table></div>").ToString();
    }

    internal static void WriteJson(string path, object value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(value, JsonFormat.Output),
                          new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    }
}
