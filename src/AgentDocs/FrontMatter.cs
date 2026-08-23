using System.Text.RegularExpressions;

namespace AgentDocs;

public sealed record FrontMatter(
    IReadOnlyDictionary<string, string> Scalars,
    IReadOnlyDictionary<string, IReadOnlyList<string>> Lists)
{
    public string? Scalar(string key) => Scalars.GetValueOrDefault(key);
    public IReadOnlyList<string>? List(string key) => Lists.GetValueOrDefault(key);
}

public static partial class FrontMatterParser
{
    public static (FrontMatter Meta, string Body) Split(string text)
    {
        Match match = BlockRegex().Match(text);
        Dictionary<string, string> scalars = new(StringComparer.Ordinal);
        Dictionary<string, IReadOnlyList<string>> lists = new(StringComparer.Ordinal);
        if (!match.Success)
            return (new(scalars, lists), text);

        string[] lines = match.Groups[1].Value.Split('\n');
        for (int index = 0; index < lines.Length;)
        {
            string line = lines[index];
            int colon = line.IndexOf(':');
            if (colon <= 0 || line.TrimStart().StartsWith("- ", StringComparison.Ordinal))
            {
                index++;
                continue;
            }
            string key = line[..colon].Trim();
            string value = line[(colon + 1)..].Trim();
            if (!KeyRegex().IsMatch(key))
                throw new InvalidDataException($"invalid front-matter key: {key}");
            if (value == "[]")
            {
                lists.Add(key, []);
                index++;
                continue;
            }
            if (value.Length == 0)
            {
                List<string> items = [];
                int next = index + 1;
                while (next < lines.Length && lines[next].TrimStart().StartsWith("- ", StringComparison.Ordinal))
                {
                    items.Add(lines[next].TrimStart()[2..].Trim());
                    next++;
                }
                if (items.Count > 0)
                {
                    lists.Add(key, items);
                    index = next;
                    continue;
                }
            }
            scalars.Add(key, value);
            index++;
        }
        return (new(scalars, lists), text[match.Length..]);
    }

    [GeneratedRegex(@"^---\s*\n(.*?)\n---\s*\n", RegexOptions.Singleline)]
    private static partial Regex BlockRegex();
    [GeneratedRegex(@"^[a-z][a-z0-9_-]*$")]
    private static partial Regex KeyRegex();
}
