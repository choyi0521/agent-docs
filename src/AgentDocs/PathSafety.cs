namespace AgentDocs;

public static class PathSafety
{
    private static readonly StringComparison PathComparison = OperatingSystem.IsWindows()
        ? StringComparison.OrdinalIgnoreCase
        : StringComparison.Ordinal;

    public static string Full(string path) => Path.GetFullPath(path);

    public static bool IsSameOrUnder(string candidate, string root)
    {
        string fullCandidate = Path.TrimEndingDirectorySeparator(Full(candidate));
        string fullRoot = Path.TrimEndingDirectorySeparator(Full(root));
        string prefix = Path.EndsInDirectorySeparator(fullRoot)
            ? fullRoot : fullRoot + Path.DirectorySeparatorChar;
        return string.Equals(fullCandidate, fullRoot, PathComparison)
            || fullCandidate.StartsWith(prefix, PathComparison);
    }

    public static bool Overlaps(string first, string second) =>
        IsSameOrUnder(first, second) || IsSameOrUnder(second, first);

    public static string ResolveRepoRelative(string repoRoot, string configured, string label,
                                             bool allowDot = false)
    {
        if (!IsPortableRelative(configured, allowDot))
            throw new InvalidDataException($"{label} must be a normalized repository-relative path");

        string resolved = Full(Path.Combine(repoRoot,
            configured.Replace('/', Path.DirectorySeparatorChar)));
        if (!IsSameOrUnder(resolved, repoRoot))
            throw new InvalidDataException($"{label} escapes the repository root");
        EnsureNoReparse(repoRoot, resolved, label);
        return resolved;
    }

    public static bool IsPortableRelative(string value, bool allowDot = false)
    {
        if (string.IsNullOrWhiteSpace(value) || value.Length > 512 || value != value.Trim()
            || Path.IsPathRooted(value) || value.Contains('\\') || value.Contains(':')
            || value.StartsWith('/') || value.EndsWith('/') || value.Contains("//", StringComparison.Ordinal))
            return false;
        if (allowDot && value == ".")
            return true;
        string[] segments = value.Split('/');
        return segments.All(IsPortableSegment);
    }

    public static void EnsureNoReparse(string trustedRoot, string target, string label)
    {
        string root = Full(trustedRoot);
        string fullTarget = Full(target);
        if (!IsSameOrUnder(fullTarget, root))
            throw new InvalidDataException($"{label} escapes its trusted root");

        string current = root;
        RejectReparseIfPresent(current, label);
        string relative = Path.GetRelativePath(root, fullTarget);
        if (relative == ".")
            return;
        foreach (string segment in relative.Split(Path.DirectorySeparatorChar,
                     StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, segment);
            RejectReparseIfPresent(current, label);
        }
    }

    public static bool IsReparsePoint(string path)
    {
        try
        {
            return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
        }
        catch (FileNotFoundException)
        {
            return false;
        }
        catch (DirectoryNotFoundException)
        {
            return false;
        }
    }

    private static void RejectReparseIfPresent(string path, string label)
    {
        if ((File.Exists(path) || Directory.Exists(path)) && IsReparsePoint(path))
            throw new InvalidDataException($"{label} contains a symbolic link or reparse point: {path}");
    }

    private static bool IsPortableSegment(string segment)
    {
        if (segment.Length == 0 || segment.Length > 255 || segment is "." or ".." || segment.EndsWith('.')
            || segment.Any(character => !char.IsAsciiLetterOrDigit(character)
                && character is not '-' and not '_' and not '.'))
            return false;
        string device = segment.Split('.')[0];
        return !device.Equals("CON", StringComparison.OrdinalIgnoreCase)
            && !device.Equals("PRN", StringComparison.OrdinalIgnoreCase)
            && !device.Equals("AUX", StringComparison.OrdinalIgnoreCase)
            && !device.Equals("NUL", StringComparison.OrdinalIgnoreCase)
            && !(device.Length == 4
                 && (device.StartsWith("COM", StringComparison.OrdinalIgnoreCase)
                     || device.StartsWith("LPT", StringComparison.OrdinalIgnoreCase))
                 && device[3] is >= '1' and <= '9');
    }
}

internal static class OutputDirectory
{
    internal const string SentinelName = ".agent-docs-output";
    internal const string SentinelValue = "agent-docs-output-v1\n";

    internal static bool HasValidSentinel(string output)
    {
        string sentinel = Path.Combine(output, SentinelName);
        return File.Exists(sentinel) && !PathSafety.IsReparsePoint(sentinel)
            && string.Equals(File.ReadAllText(sentinel), SentinelValue, StringComparison.Ordinal);
    }

    internal static string Prepare(string repoRoot, string requested,
                                   IEnumerable<string> protectedPaths)
    {
        string output = PathSafety.Full(requested);
        string root = Path.GetPathRoot(output)
            ?? throw new InvalidDataException("output directory has no filesystem root");
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (string.Equals(Path.TrimEndingDirectorySeparator(output),
                          Path.TrimEndingDirectorySeparator(root), PathStringComparison)
            || (!string.IsNullOrEmpty(home) && string.Equals(
                Path.TrimEndingDirectorySeparator(output), Path.TrimEndingDirectorySeparator(home),
                PathStringComparison)))
        {
            throw new InvalidDataException("refusing a filesystem root or home directory as output");
        }

        string repository = PathSafety.Full(repoRoot);
        if (PathSafety.IsSameOrUnder(repository, output))
            throw new InvalidDataException("output cannot be the repository root or one of its ancestors");
        foreach (string protectedPath in protectedPaths.Select(PathSafety.Full))
            if (PathSafety.Overlaps(output, protectedPath))
                throw new InvalidDataException($"output overlaps a protected input path: {protectedPath}");

        string trustedOutputRoot = Path.GetPathRoot(output)!;
        PathSafety.EnsureNoReparse(trustedOutputRoot, output, "output directory");

        Directory.CreateDirectory(output);
        PathSafety.EnsureNoReparse(trustedOutputRoot, output, "output directory");
        string sentinel = Path.Combine(output, SentinelName);
        string[] entries = Directory.GetFileSystemEntries(output);
        if ((File.Exists(sentinel) || Directory.Exists(sentinel)) && PathSafety.IsReparsePoint(sentinel))
            throw new InvalidDataException("output ownership sentinel cannot be a reparse point");
        if (!File.Exists(sentinel))
        {
            if (entries.Length != 0)
                throw new InvalidDataException(
                    $"refusing to clean a nonempty directory without {SentinelName}: {output}");
            File.WriteAllText(sentinel, SentinelValue);
        }
        else if (!HasValidSentinel(output))
        {
            throw new InvalidDataException($"invalid output ownership sentinel: {sentinel}");
        }

        foreach (string entry in Directory.GetFileSystemEntries(output))
        {
            if (string.Equals(Path.GetFileName(entry), SentinelName, StringComparison.Ordinal))
                continue;
            RejectReparseTree(entry);
            if (Directory.Exists(entry))
                Directory.Delete(entry, recursive: true);
            else
                File.Delete(entry);
        }
        return output;
    }

    private static void RejectReparseTree(string entry)
    {
        if (PathSafety.IsReparsePoint(entry))
            throw new InvalidDataException($"output contains a reparse entry: {entry}");
        if (!Directory.Exists(entry))
            return;
        foreach (string child in Directory.GetFileSystemEntries(entry))
            RejectReparseTree(child);
    }

    private static StringComparison PathStringComparison => OperatingSystem.IsWindows()
        ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
}
