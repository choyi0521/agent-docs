using System.Text.RegularExpressions;
using Markdig;
using Markdig.Extensions.CustomContainers;
using Markdig.Parsers;
using Markdig.Syntax;

namespace AgentDocs;

internal static partial class Plans
{
    internal static void AddParser(MarkdownPipelineBuilder builder) =>
        builder.BlockParsers.InsertBefore<FencedCodeBlockParser>(new CustomContainerParser());

    internal static bool IsPlan(CustomContainer container) =>
        string.Equals(container.Info?.ToString().Trim(), "plan", StringComparison.Ordinal);

    internal static string Title(CustomContainer container) =>
        container.Arguments?.ToString().Trim() ?? "";

    internal static int Count(string markdown)
    {
        int count = 0;
        bool inFence = false;
        int fenceLength = 0;
        foreach (string line in markdown.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n'))
        {
            Match fence = FenceRegex().Match(line);
            if (fence.Success)
            {
                int length = fence.Groups[1].Value.Length;
                if (!inFence)
                {
                    inFence = true;
                    fenceLength = length;
                }
                else if (length >= fenceLength)
                {
                    inFence = false;
                }
                continue;
            }
            if (!inFence && PlanOpenRegex().IsMatch(line))
                count++;
        }
        return count;
    }

    [GeneratedRegex(@"^\s*(`{3,})")]
    private static partial Regex FenceRegex();
    [GeneratedRegex(@"^:::plan\s+\S")]
    private static partial Regex PlanOpenRegex();
}
