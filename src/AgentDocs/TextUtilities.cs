using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace AgentDocs;

public static partial class TextUtilities
{
    public static string ReadText(string path)
    {
        string raw = File.ReadAllText(path, Encoding.UTF8);
        return raw.Replace("\r\n", "\n", StringComparison.Ordinal).Replace('\r', '\n');
    }

    public static string HtmlEscape(string value) => value
        .Replace("&", "&amp;", StringComparison.Ordinal)
        .Replace("<", "&lt;", StringComparison.Ordinal)
        .Replace(">", "&gt;", StringComparison.Ordinal)
        .Replace("\"", "&quot;", StringComparison.Ordinal)
        .Replace("'", "&#x27;", StringComparison.Ordinal);

    public static string HtmlUnescape(string value) => value
        .Replace("&lt;", "<", StringComparison.Ordinal)
        .Replace("&gt;", ">", StringComparison.Ordinal)
        .Replace("&quot;", "\"", StringComparison.Ordinal)
        .Replace("&#x27;", "'", StringComparison.Ordinal)
        .Replace("&#39;", "'", StringComparison.Ordinal)
        .Replace("&amp;", "&", StringComparison.Ordinal);

    public static string StripTags(string value) => TagRegex().Replace(value, "");

    public static string Slugify(string text)
    {
        string value = SlugDropRegex().Replace(text.ToLowerInvariant(), "").Trim();
        value = SlugDashRegex().Replace(value, "-");
        return value.Length == 0 ? "section" : value;
    }

    public static string Dedent(string text)
    {
        string[] lines = text.Split('\n');
        string? prefix = null;
        foreach (string line in lines)
        {
            if (line.Trim().Length == 0)
                continue;
            string leading = line[..(line.Length - line.TrimStart().Length)];
            prefix = prefix is null ? leading : CommonPrefix(prefix, leading);
        }
        prefix ??= "";
        for (int index = 0; index < lines.Length; index++)
            lines[index] = lines[index].Trim().Length == 0 ? ""
                : lines[index].StartsWith(prefix, StringComparison.Ordinal)
                    ? lines[index][prefix.Length..] : lines[index];
        return string.Join('\n', lines);
    }

    public static string Prettify(string name)
    {
        string[] words = name.Replace('_', ' ').Replace('-', ' ')
            .Split(' ', StringSplitOptions.RemoveEmptyEntries);
        return string.Join(' ', words.Select(word =>
            char.ToUpper(word[0], CultureInfo.InvariantCulture) + word[1..]));
    }

    public static string RelativePosix(string target, string root) =>
        Path.GetRelativePath(root, target).Replace('\\', '/');

    private static string CommonPrefix(string first, string second)
    {
        int length = Math.Min(first.Length, second.Length);
        int index = 0;
        while (index < length && first[index] == second[index])
            index++;
        return first[..index];
    }

    [GeneratedRegex("<[^>]+>")]
    private static partial Regex TagRegex();
    [GeneratedRegex(@"[^\w\s-]")]
    private static partial Regex SlugDropRegex();
    [GeneratedRegex(@"[\s_]+")]
    private static partial Regex SlugDashRegex();
}
