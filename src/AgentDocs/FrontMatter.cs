using System.Text.Json;
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

        string header = match.Groups[1].Value;
        string trimmed = header.TrimStart();
        if (trimmed.StartsWith('{') || trimmed.StartsWith('[')
            || trimmed.StartsWith("//", StringComparison.Ordinal)
            || trimmed.StartsWith("/*", StringComparison.Ordinal))
        {
            ReadJson(header, scalars, lists);
            return (new(scalars, lists), text[match.Length..]);
        }

        string[] lines = header.Split('\n');
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

    private static void ReadJson(string header, Dictionary<string, string> scalars,
                                 Dictionary<string, IReadOnlyList<string>> lists)
    {
        try
        {
            using JsonDocument document = JsonDocument.Parse(header, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
            });
            JsonElement root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
                throw new InvalidDataException("JSON front matter must be an object");
            RejectDuplicateKeys(root);

            foreach (JsonProperty property in root.EnumerateObject())
            {
                string key = property.Name;
                if (!KeyRegex().IsMatch(key))
                    throw new InvalidDataException($"invalid front-matter key: {key}");
                JsonElement value = property.Value;
                bool stringList = value.ValueKind == JsonValueKind.Array
                    && value.EnumerateArray().All(item => item.ValueKind == JsonValueKind.String);
                if (key is "title" or "crumb" or "nav_mode"
                    && value.ValueKind != JsonValueKind.String)
                    throw new InvalidDataException($"JSON front-matter {key} must be a string");
                if (key == "nav" && value.ValueKind != JsonValueKind.String && !stringList)
                    throw new InvalidDataException(
                        "JSON front-matter nav must be a string or an array of strings");
                if (key == "nav_exclude" && !stringList)
                    throw new InvalidDataException(
                        "JSON front-matter nav_exclude must be an array of strings");

                if (stringList)
                    lists.Add(key, value.EnumerateArray().Select(item => item.GetString()!).ToArray());
                else if (value.ValueKind == JsonValueKind.String)
                    scalars.Add(key, value.GetString()!);
                else if (value.ValueKind is JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False)
                    scalars.Add(key, value.GetRawText());
                // Structured metadata remains validated JSON, but is not flattened
                // into the renderer's scalar and string-list navigation surface.
            }
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("invalid JSON front matter", exception);
        }
    }

    private static void RejectDuplicateKeys(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            HashSet<string> keys = new(StringComparer.Ordinal);
            foreach (JsonProperty property in value.EnumerateObject())
            {
                if (!keys.Add(property.Name))
                    throw new InvalidDataException($"duplicate JSON front-matter key: {property.Name}");
                RejectDuplicateKeys(property.Value);
            }
        }
        else if (value.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement item in value.EnumerateArray())
                RejectDuplicateKeys(item);
        }
    }

    [GeneratedRegex(@"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\z)", RegexOptions.Singleline)]
    private static partial Regex BlockRegex();
    [GeneratedRegex(@"\A[a-z][a-z0-9_-]*\z")]
    private static partial Regex KeyRegex();
}
