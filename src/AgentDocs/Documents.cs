namespace AgentDocs;

internal static class DocumentFiles
{
    private const int MaximumDocuments = 5_000;
    private const long MaximumDocumentBytes = 1024 * 1024;
    private const long MaximumTotalBytes = 25 * 1024 * 1024;
    private static readonly HashSet<string> ExcludedDirectories = new(
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal)
    {
        ".git", "_agents", "_assets", "_registry", "build", "bin", "obj", "node_modules"
    };

    internal static List<string> Walk(ResolvedSpace space)
    {
        List<string> files = [];
        Recurse(space.DocsDirAbsolute);
        files.Sort(StringComparer.Ordinal);
        if (files.Count > MaximumDocuments)
            throw new InvalidDataException($"documentation tree exceeds {MaximumDocuments} files");
        long total = 0;
        foreach (string file in files)
        {
            long length = new FileInfo(file).Length;
            if (length > MaximumDocumentBytes)
                throw new InvalidDataException(
                    $"documentation file exceeds 1 MiB: {TextUtilities.RelativePosix(file, space.DocsDirAbsolute)}");
            total += length;
            if (total > MaximumTotalBytes)
                throw new InvalidDataException("documentation tree exceeds 25 MiB");
        }
        return files;

        void Recurse(string directory)
        {
            PathSafety.EnsureNoReparse(space.DocsDirAbsolute, directory, "documentation tree");
            foreach (string entry in Directory.GetFileSystemEntries(directory)
                         .Order(StringComparer.Ordinal))
            {
                if (PathSafety.IsReparsePoint(entry))
                    throw new InvalidDataException(
                        $"documentation tree contains a symbolic link or reparse point: {entry}");
                string name = Path.GetFileName(entry);
                if (Directory.Exists(entry))
                {
                    if (!ExcludedDirectories.Contains(name))
                        Recurse(entry);
                    continue;
                }
                if (!name.EndsWith(".md", StringComparison.Ordinal))
                    continue;
                string relative = TextUtilities.RelativePosix(entry, space.DocsDirAbsolute);
                if (!PathSafety.IsPortableRelative(relative))
                    throw new InvalidDataException($"documentation path is not portable: {relative}");
                files.Add(Path.GetFullPath(entry));
            }
        }
    }

    internal static bool DirectoryHasDocuments(ResolvedSpace space, string directory)
    {
        PathSafety.EnsureNoReparse(space.DocsDirAbsolute, directory, "documentation navigation");
        foreach (string entry in Directory.GetFileSystemEntries(directory))
        {
            if (PathSafety.IsReparsePoint(entry))
                throw new InvalidDataException(
                    $"documentation navigation contains a symbolic link or reparse point: {entry}");
            string name = Path.GetFileName(entry);
            if (File.Exists(entry) && name.EndsWith(".md", StringComparison.Ordinal))
                return true;
            if (Directory.Exists(entry) && !ExcludedDirectories.Contains(name)
                && DirectoryHasDocuments(space, entry))
                return true;
        }
        return false;
    }

    internal static bool IsExcludedDirectory(string name) => ExcludedDirectories.Contains(name);
}

public sealed class RouteResolver
{
    private readonly ResolvedSpace _space;

    public RouteResolver(ResolvedSpace space) => _space = space;

    public string Route(string markdownAbsolute)
    {
        string stem = CanonicalStem(markdownAbsolute);
        string relative = stem switch
        {
            "index" => "",
            _ when stem.EndsWith("/index", StringComparison.Ordinal) => stem[..^6],
            _ => stem,
        };
        string prefix = _space.Id.Length == 0 ? "" : "/" + _space.Id;
        string route = prefix + (relative.Length == 0 ? "" : "/" + relative);
        return route.Length == 0 ? "/" : route;
    }

    public string ContentRelative(string markdownAbsolute)
    {
        string prefix = _space.Id.Length == 0 ? "" : _space.Id + "/";
        return prefix + CanonicalStem(markdownAbsolute) + ".json";
    }

    private string CanonicalStem(string markdownAbsolute)
    {
        string relative = TextUtilities.RelativePosix(markdownAbsolute, _space.DocsDirAbsolute);
        if (!PathSafety.IsPortableRelative(relative) || !relative.EndsWith(".md", StringComparison.Ordinal))
            throw new InvalidDataException($"invalid documentation route source: {relative}");
        string directory = Path.GetDirectoryName(relative)?.Replace('\\', '/') ?? "";
        string name = Path.GetFileName(relative);
        if (name == "_index.md")
            return directory.Length == 0 ? "index" : directory + "/index";
        return relative[..^3];
    }
}

internal sealed class SourcePolicy
{
    private static readonly HashSet<string> GeneratedDirectories = new(
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal)
    {
        ".git", "build", "bin", "obj", "node_modules"
    };
    private readonly ResolvedSpace _space;
    private readonly IReadOnlyList<string> _excludedAbsolute;

    internal SourcePolicy(ResolvedSpace space)
    {
        _space = space;
        _excludedAbsolute = space.ExcludedSourcePaths.Select(path => ResolveRelative(path, "excluded source path"))
            .ToList();
    }

    internal bool IsAllowed(string absolute)
    {
        string full = Path.GetFullPath(absolute);
        if (!PathSafety.IsSameOrUnder(full, _space.SourceRootAbsolute) || IsExcluded(full))
            return false;
        PathSafety.EnsureNoReparse(_space.SourceRootAbsolute, full, "published source");
        string relative = TextUtilities.RelativePosix(full, _space.SourceRootAbsolute);
        if (_space.BrowsableRootFiles.Contains(relative, StringComparer.Ordinal))
            return ExtensionAllowed(relative);
        return _space.SourceTrees.Any(tree => relative == tree
            || relative.StartsWith(tree + "/", StringComparison.Ordinal))
            && ExtensionAllowed(relative);
    }

    internal string ResolveAllowed(string relative)
    {
        if (!PathSafety.IsPortableRelative(relative))
            throw new InvalidDataException($"source path is not portable: {relative}");
        string absolute = ResolveRelative(relative, "source path");
        if (!File.Exists(absolute) || !IsAllowed(absolute))
            throw new InvalidDataException($"source path is outside the publication allowlist: {relative}");
        return absolute;
    }

    internal IReadOnlyList<string> EnumerateFiles()
    {
        List<string> result = [];
        foreach (string rootFile in _space.BrowsableRootFiles)
        {
            string absolute = ResolveRelative(rootFile, "browsable root file");
            if (File.Exists(absolute) && IsAllowed(absolute))
                result.Add(absolute);
        }
        foreach (string tree in _space.SourceTrees)
        {
            string root = ResolveRelative(tree, "source tree");
            if (!Directory.Exists(root))
                throw new DirectoryNotFoundException($"configured source tree does not exist: {tree}");
            Walk(root);
        }
        return result.Distinct(PathComparer).Order(StringComparer.Ordinal).ToList();

        void Walk(string directory)
        {
            PathSafety.EnsureNoReparse(_space.SourceRootAbsolute, directory, "source tree");
            foreach (string entry in Directory.GetFileSystemEntries(directory).Order(StringComparer.Ordinal))
            {
                if (PathSafety.IsReparsePoint(entry))
                    throw new InvalidDataException(
                        $"source tree contains a symbolic link or reparse point: {entry}");
                if (IsExcluded(entry))
                    continue;
                if (Directory.Exists(entry))
                    Walk(entry);
                else if (IsAllowed(entry))
                    result.Add(entry);
            }
        }
    }

    internal string? SourceUrl(string relative, int? line = null)
    {
        if (_space.SourceUrlBase is null)
            return null;
        string escaped = string.Join('/', relative.Split('/').Select(Uri.EscapeDataString));
        return new Uri(_space.SourceUrlBase, escaped).AbsoluteUri
             + (line is null ? "" : "#L" + line.Value);
    }

    internal static string Lexer(string path)
    {
        string name = Path.GetFileName(path);
        if (name.EndsWith(".config.json", StringComparison.OrdinalIgnoreCase))
            return "json";
        return Path.GetExtension(name).ToLowerInvariant() switch
        {
            ".cs" => "csharp",
            ".ts" or ".js" => "typescript",
            ".json" => "json",
            ".xml" or ".csproj" or ".slnx" => "xml",
            ".cpp" or ".cppm" or ".hpp" or ".h" => "cpp",
            ".ps1" => "powershell",
            ".sh" or ".bash" => "bash",
            ".py" => "python",
            ".css" => "css",
            ".html" => "markup",
            _ => "text",
        };
    }

    private string ResolveRelative(string relative, string label)
    {
        string absolute = Path.GetFullPath(Path.Combine(_space.SourceRootAbsolute,
            relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!PathSafety.IsSameOrUnder(absolute, _space.SourceRootAbsolute))
            throw new InvalidDataException($"{label} escapes sourceRoot: {relative}");
        PathSafety.EnsureNoReparse(_space.SourceRootAbsolute, absolute, label);
        return absolute;
    }

    private bool IsExcluded(string path)
    {
        string relative = TextUtilities.RelativePosix(path, _space.SourceRootAbsolute);
        if (relative.Split('/').Any(GeneratedDirectories.Contains))
            return true;
        return _excludedAbsolute.Any(excluded => PathSafety.IsSameOrUnder(path, excluded));
    }

    internal static bool ContainsGeneratedDirectory(string relative) =>
        relative.Split('/').Any(GeneratedDirectories.Contains);

    private bool ExtensionAllowed(string relative) =>
        _space.SourceExtensions.Any(extension =>
            relative.EndsWith(extension, StringComparison.OrdinalIgnoreCase));

    private static StringComparer PathComparer => OperatingSystem.IsWindows()
        ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
}
