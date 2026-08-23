using System.Text.RegularExpressions;

namespace AgentDocs;

public static partial class Snippets
{
    internal static SnippetResolution Resolve(string fileText, string name)
    {
        string[] lines = fileText.Replace("\r\n", "\n", StringComparison.Ordinal)
                                 .Replace('\r', '\n').Split('\n');
        List<string> body = [];
        int begins = 0;
        int ends = 0;
        int firstLine = -1;
        string? code = null;
        bool capture = false;
        for (int index = 0; index < lines.Length; index++)
        {
            Match marker = MarkerRegex().Match(lines[index]);
            if (!marker.Success)
                marker = BlockMarkerRegex().Match(lines[index]);
            if (!marker.Success)
                marker = XmlMarkerRegex().Match(lines[index]);
            if (marker.Success)
            {
                if (string.Equals(marker.Groups[2].Value, name, StringComparison.Ordinal))
                {
                    if (marker.Groups[1].Value == "begin")
                    {
                        begins++;
                        if (!capture && code is null)
                        {
                            capture = true;
                            firstLine = index + 2;
                        }
                    }
                    else
                    {
                        ends++;
                        if (capture && code is null)
                        {
                            code = TextUtilities.Dedent(string.Join('\n', body)).Trim('\n');
                            capture = false;
                        }
                    }
                }
                continue;
            }
            if (capture)
                body.Add(lines[index]);
        }
        if (capture)
        {
            code = null;
            firstLine = -1;
        }
        return new(code, firstLine, begins, ends);
    }

    [GeneratedRegex(@"^\s*(?://|#|--|;)\s*docs:(begin|end)\s+([A-Za-z0-9][A-Za-z0-9_-]*)\s*$")]
    private static partial Regex MarkerRegex();
    [GeneratedRegex(@"^\s*/\*\s*docs:(begin|end)\s+([A-Za-z0-9][A-Za-z0-9_-]*)\s*\*/\s*$")]
    private static partial Regex BlockMarkerRegex();
    [GeneratedRegex(@"^\s*<!--\s*docs:(begin|end)\s+([A-Za-z0-9][A-Za-z0-9_-]*)\s*-->\s*$")]
    private static partial Regex XmlMarkerRegex();
}

internal readonly record struct SnippetResolution(
    string? Code,
    int FirstLine,
    int BeginCount,
    int EndCount)
{
    public bool IsMissing => BeginCount == 0 && EndCount == 0;
    public string? Error => (BeginCount, EndCount, Code) switch
    {
        (1, 1, not null) => null,
        (1, 1, null) => "begin marker must precede its end marker",
        _ => $"expected one begin and one end marker; found {BeginCount} begin and {EndCount} end",
    };
}
