using System.ComponentModel;
using System.Globalization;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace AgentDocs;

internal sealed class ReviewCommentStore
{
    internal const int SchemaVersion = 1;
    internal const int MaximumRequestBytes = 16 * 1024;
    internal const int MaximumFileBytes = 1024 * 1024;
    internal const int MaximumComments = 1000;
    internal const int MaximumRouteLength = 512;
    internal const int MaximumAnchorLength = 256;
    internal const int MaximumQuoteLength = 2000;
    internal const int MaximumBodyLength = 8000;
    internal const int MaximumReplyLength = 8000;
    internal const string DefaultRelativePath = ".agent-docs/review-comments.json";

    private const string TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'";
    private static readonly byte[] LockFileContent =
        "agent-docs-review-lock-v1\n"u8.ToArray();
    private static readonly TimeSpan LockWait = TimeSpan.FromSeconds(5);
    private static readonly TimeSpan LockRetry = TimeSpan.FromMilliseconds(50);
    private static readonly Regex IdPattern = new(
        "^rc_[0-9a-f]{32}$", RegexOptions.CultureInvariant);
    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        NewLine = "\n",
        WriteIndented = true,
    };
    private static readonly HashSet<string> StoreFields = new(StringComparer.Ordinal)
    {
        "schemaVersion", "comments",
    };
    private static readonly HashSet<string> CommentFields = new(StringComparer.Ordinal)
    {
        "id", "route", "anchor", "quote", "body", "status", "reply",
        "createdAt", "updatedAt",
    };
    private readonly SemaphoreSlim gate = new(1, 1);
    private readonly string repositoryRoot;
    private readonly string dataPath;

    private ReviewCommentStore(string repositoryRoot, string dataPath)
    {
        this.repositoryRoot = repositoryRoot;
        this.dataPath = dataPath;
    }

    internal string DataPath => dataPath;

    internal static ReviewCommentStore Create(
        string repositoryRoot, string? configuredPath, string outputRoot)
    {
        string repository = Path.GetFullPath(repositoryRoot);
        if (!Directory.Exists(repository))
            throw new InvalidDataException("review repository does not exist");
        string volume = Path.GetPathRoot(repository)
            ?? throw new InvalidDataException("review repository has no filesystem root");
        if (string.Equals(Path.TrimEndingDirectorySeparator(repository),
                          Path.TrimEndingDirectorySeparator(volume), PathComparison))
            throw new InvalidDataException("review repository cannot be a filesystem root");
        PathSafety.EnsureNoReparse(volume, repository, "review repository");

        string configured = configuredPath is null ? DefaultRelativePath : configuredPath;
        if (string.IsNullOrWhiteSpace(configured) || configured.IndexOf('\0') >= 0
            || configured != configured.Trim())
            throw new InvalidDataException("review data path is invalid");
        string path = Path.GetFullPath(Path.IsPathFullyQualified(configured)
            ? configured : Path.Combine(repository, configured));
        if (!PathSafety.IsSameOrUnder(path, repository)
            || string.Equals(Path.TrimEndingDirectorySeparator(path),
                             Path.TrimEndingDirectorySeparator(repository), PathComparison))
            throw new InvalidDataException("review data path must be a file inside the repository");
        string reserved = Path.Combine(repository, ".agent-docs");
        if (!PathSafety.IsSameOrUnder(path, reserved)
            || string.Equals(Path.TrimEndingDirectorySeparator(path),
                             Path.TrimEndingDirectorySeparator(reserved), PathComparison))
            throw new InvalidDataException(
                "review data path must be a file under the repository .agent-docs directory");
        if (Directory.Exists(path))
            throw new InvalidDataException("review data path cannot be a directory");
        PathSafety.EnsureNoReparse(repository, path, "review data path");

        string output = Path.GetFullPath(outputRoot);
        if (PathSafety.IsSameOrUnder(path, output))
            throw new InvalidDataException("review data path cannot be inside generated output");
        RejectOwnedOutputAncestor(repository, path);
        return new ReviewCommentStore(repository, path);
    }

    internal static void EnsureOutsidePublicationInputs(
        string dataPath, ResolvedConfiguration configuration)
    {
        string path = Path.GetFullPath(dataPath);
        string reserved = Path.Combine(configuration.RepoRoot, ".agent-docs");
        if (!PathSafety.IsSameOrUnder(path, reserved))
            throw new InvalidDataException(
                "review data path must remain under the reserved .agent-docs directory");

        // Configuration loading rejects explicitly selected local-state inputs, while
        // the document and source walkers skip every .agent-docs directory. Parsing
        // workflow inputs here closes the remaining manifest-driven publication path.
        _ = AgentWorkflowProjection.InputPaths(configuration);
    }

    private static void RejectOwnedOutputAncestor(string repository, string path)
    {
        string current = Path.GetDirectoryName(path)!;
        while (PathSafety.IsSameOrUnder(current, repository))
        {
            string sentinel = Path.Combine(current, OutputDirectory.SentinelName);
            PathSafety.EnsureNoReparse(repository, sentinel, "generated-output sentinel");
            if (OutputDirectory.HasValidSentinel(current))
                throw new InvalidDataException(
                    "review data path cannot be inside sentinel-owned generated output");
            if (string.Equals(Path.TrimEndingDirectorySeparator(current),
                              Path.TrimEndingDirectorySeparator(repository), PathComparison))
                break;
            current = Path.GetDirectoryName(current)
                ?? throw new InvalidDataException("review data path has no repository ancestor");
        }
    }

    internal async Task<ReviewCommentData> GetAsync(string? route)
    {
        await gate.WaitAsync().ConfigureAwait(false);
        try
        {
            ReviewCommentData data = await ReadAsync().ConfigureAwait(false);
            if (route is null)
                return data;
            ValidateRoute(route);
            return new ReviewCommentData
            {
                Comments = data.Comments.Where(comment => comment.Route == route).ToList(),
            };
        }
        finally
        {
            gate.Release();
        }
    }

    internal async Task<ReviewComment> CreateAsync(
        string route, string? anchor, string? quote, string body)
    {
        ValidateRoute(route);
        ValidateOptionalAnchor(anchor);
        ValidateOptionalText(quote, MaximumQuoteLength, "quote");
        body = NormalizeRequiredText(body, MaximumBodyLength, "body");

        await gate.WaitAsync().ConfigureAwait(false);
        try
        {
            using ReviewWriteLock writeLock = await AcquireWriteLockAsync().ConfigureAwait(false);
            ReviewCommentData data = await ReadAsync().ConfigureAwait(false);
            if (data.Comments.Count >= MaximumComments)
                throw new ReviewApiException(409, "review comment limit reached");
            string now = UtcTimestamp();
            ReviewComment comment = new()
            {
                Id = "rc_" + Guid.NewGuid().ToString("N"),
                Route = route,
                Anchor = anchor,
                Quote = quote,
                Body = body,
                Status = ReviewStatus.Open,
                CreatedAt = now,
                UpdatedAt = now,
            };
            data.Comments.Add(comment);
            await WriteAsync(data).ConfigureAwait(false);
            return comment;
        }
        finally
        {
            gate.Release();
        }
    }

    internal async Task<ReviewComment> PatchAsync(
        string id, bool hasReply, string? reply, bool hasStatus, string? status)
    {
        ValidateId(id);
        if (!hasReply && !hasStatus)
            throw new ReviewApiException(400, "PATCH requires reply or status");
        if (hasReply && reply is not null)
            reply = NormalizeRequiredText(reply, MaximumReplyLength, "reply");
        ReviewStatus? requestedStatus = hasStatus ? ParseStatus(status) : null;

        await gate.WaitAsync().ConfigureAwait(false);
        try
        {
            using ReviewWriteLock writeLock = await AcquireWriteLockAsync().ConfigureAwait(false);
            ReviewCommentData data = await ReadAsync().ConfigureAwait(false);
            ReviewComment? comment = data.Comments.SingleOrDefault(item => item.Id == id);
            if (comment is null)
                throw new ReviewApiException(404, "review comment not found");
            if (comment.Status == ReviewStatus.Resolved && requestedStatus is not null
                && requestedStatus is not ReviewStatus.Open and not ReviewStatus.Resolved)
                throw new ReviewApiException(400,
                    "resolved comments must be reopened before another status transition");
            if (comment.Status == ReviewStatus.Resolved && hasReply
                && requestedStatus != ReviewStatus.Open)
                throw new ReviewApiException(400,
                    "resolved comments must be reopened before changing the reply");

            if (hasReply)
                comment.Reply = reply;
            if (requestedStatus is not null)
            {
                comment.Status = requestedStatus.Value;
            }
            else if (hasReply && reply is not null)
            {
                comment.Status = ReviewStatus.Answered;
            }
            else if (hasReply && comment.Status == ReviewStatus.Answered)
            {
                comment.Status = ReviewStatus.Open;
            }
            if ((comment.Status is ReviewStatus.Answered or ReviewStatus.Resolved)
                && comment.Reply is null)
                throw new ReviewApiException(400,
                    "answered and resolved comments require a reply");
            comment.UpdatedAt = NextUpdatedTimestamp(comment);
            await WriteAsync(data).ConfigureAwait(false);
            return comment;
        }
        finally
        {
            gate.Release();
        }
    }

    internal static byte[] SerializeResponse(object value) =>
        JsonSerializer.SerializeToUtf8Bytes(value, WriteOptions);

    internal static void ValidateRoute(string route)
    {
        if (route.Length is < 1 or > MaximumRouteLength || route != route.Trim()
            || !route.StartsWith('/') || route.Contains("//", StringComparison.Ordinal)
            || (route.Length > 1 && route.EndsWith('/'))
            || route.Contains('\\') || route.Contains('?') || route.Contains('#')
            || route.Any(character => char.IsControl(character) || char.IsWhiteSpace(character)))
            throw new ReviewApiException(400, "route must be a normalized absolute site path");
        string[] segments = route.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Any(segment => segment is "." or ".."))
            throw new ReviewApiException(400, "route must be a normalized absolute site path");
    }

    internal static void ValidateId(string id)
    {
        if (!IdPattern.IsMatch(id))
            throw new ReviewApiException(400, "review comment id is invalid");
    }

    internal static void ValidateOptionalAnchor(string? anchor)
    {
        if (anchor is null)
            return;
        if (anchor.Length is < 1 or > MaximumAnchorLength || anchor != anchor.Trim()
            || anchor.Contains('#')
            || anchor.Any(character => char.IsControl(character) || char.IsWhiteSpace(character)))
            throw new ReviewApiException(400, "anchor is invalid");
    }

    private async Task<ReviewCommentData> ReadAsync()
    {
        PathSafety.EnsureNoReparse(repositoryRoot, dataPath, "review data path");
        if (!File.Exists(dataPath))
            return new ReviewCommentData();
        await using FileStream stream = new(
            dataPath, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete,
            bufferSize: 16 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
        if (stream.Length > MaximumFileBytes)
            throw new InvalidDataException("review data file exceeds 1 MiB");
        using MemoryStream buffer = new((int)stream.Length);
        await stream.CopyToAsync(buffer).ConfigureAwait(false);
        if (buffer.Length > MaximumFileBytes)
            throw new InvalidDataException("review data file exceeds 1 MiB");
        byte[] sourceBytes = buffer.ToArray();
        ReviewCommentData data = ParseData(sourceBytes);
        data.SourceBytes = sourceBytes;
        return data;
    }

    private async Task WriteAsync(ReviewCommentData data)
    {
        byte[] serialized = JsonSerializer.SerializeToUtf8Bytes(data, WriteOptions);
        _ = ParseData(serialized);
        if (serialized.Length + 1 > MaximumFileBytes)
            throw new ReviewApiException(409, "review data file would exceed 1 MiB");

        string parent = EnsureDataDirectory();
        PathSafety.EnsureNoReparse(repositoryRoot, dataPath, "review data path");
        await EnsureUnchangedAsync(data.SourceBytes).ConfigureAwait(false);

        UnixFileMode? originalMode = null;
        if (!OperatingSystem.IsWindows() && File.Exists(dataPath))
            originalMode = File.GetUnixFileMode(dataPath);

        string temporary = Path.Combine(parent,
            "." + Path.GetFileName(dataPath) + "." + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            await using (FileStream stream = new(
                temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                bufferSize: 16 * 1024, FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await stream.WriteAsync(serialized).ConfigureAwait(false);
                await stream.WriteAsync("\n"u8.ToArray()).ConfigureAwait(false);
                await stream.FlushAsync().ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }
            if (!OperatingSystem.IsWindows())
                File.SetUnixFileMode(temporary, originalMode
                    ?? (UnixFileMode.UserRead | UnixFileMode.UserWrite));
            await EnsureUnchangedAsync(data.SourceBytes).ConfigureAwait(false);
            if (File.Exists(dataPath))
                File.Replace(temporary, dataPath, null, ignoreMetadataErrors: false);
            else
                File.Move(temporary, dataPath);
        }
        finally
        {
            if (File.Exists(temporary))
                File.Delete(temporary);
        }
    }

    private async Task<ReviewWriteLock> AcquireWriteLockAsync()
    {
        string parent = EnsureDataDirectory();
        string lockPath = Path.Combine(parent, "." + Path.GetFileName(dataPath) + ".lock");
        PathSafety.EnsureNoReparse(repositoryRoot, lockPath, "review write lock");
        bool existed = File.Exists(lockPath);
        FileStream stream = new(
            lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.ReadWrite,
            bufferSize: 256, FileOptions.Asynchronous | FileOptions.WriteThrough);
        try
        {
            PathSafety.EnsureNoReparse(repositoryRoot, lockPath, "review write lock");
            if (!existed && !OperatingSystem.IsWindows())
                File.SetUnixFileMode(
                    lockPath, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
        catch
        {
            stream.Dispose();
            throw;
        }

        Stopwatch waiting = Stopwatch.StartNew();
        while (true)
        {
            if (TryAcquireFileLock(stream))
            {
                try
                {
                    await ValidateLockFileAsync(stream).ConfigureAwait(false);
                    return new ReviewWriteLock(stream);
                }
                catch
                {
                    try
                    {
                        ReleaseFileLock(stream);
                    }
                    finally
                    {
                        stream.Dispose();
                    }
                    throw;
                }
            }
            if (waiting.Elapsed >= LockWait)
            {
                stream.Dispose();
                throw new ReviewApiException(409,
                    "review data is locked by another writer; retry shortly");
            }
            await Task.Delay(LockRetry).ConfigureAwait(false);
        }
    }

    private static bool TryAcquireFileLock(FileStream stream)
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                stream.Lock(0, 1);
                return true;
            }
            catch (IOException)
            {
                return false;
            }
        }
        int result = NativeFlock(
            stream.SafeFileHandle.DangerousGetHandle(), LockExclusive | LockNonBlocking);
        if (result == 0)
            return true;
        int error = Marshal.GetLastPInvokeError();
        if (error is 4 or 11 or 35)
            return false;
        throw new IOException("cannot acquire the review write lock",
                              new Win32Exception(error));
    }

    private static async Task ValidateLockFileAsync(FileStream stream)
    {
        if (stream.Length == 0)
        {
            stream.Position = 0;
            stream.SetLength(0);
            await stream.WriteAsync(LockFileContent).ConfigureAwait(false);
            await stream.FlushAsync().ConfigureAwait(false);
            stream.Flush(flushToDisk: true);
            return;
        }
        if (stream.Length != LockFileContent.Length)
            throw new InvalidDataException("review write lock has invalid content");
        byte[] current = new byte[LockFileContent.Length];
        stream.Position = 0;
        await stream.ReadExactlyAsync(current).ConfigureAwait(false);
        if (!current.AsSpan().SequenceEqual(LockFileContent))
            throw new InvalidDataException("review write lock has invalid content");
    }

    private static void ReleaseFileLock(FileStream stream)
    {
        if (OperatingSystem.IsWindows())
        {
            stream.Unlock(0, 1);
            return;
        }
        if (NativeFlock(stream.SafeFileHandle.DangerousGetHandle(), LockUnlock) != 0)
            throw new IOException("cannot release the review write lock",
                new Win32Exception(Marshal.GetLastPInvokeError()));
    }

    private const int LockExclusive = 2;
    private const int LockNonBlocking = 4;
    private const int LockUnlock = 8;

    [DllImport("libc", EntryPoint = "flock", SetLastError = true)]
    private static extern int NativeFlock(IntPtr fileDescriptor, int operation);

    private string EnsureDataDirectory()
    {
        string parent = Path.GetDirectoryName(dataPath)!;
        PathSafety.EnsureNoReparse(repositoryRoot, parent, "review data directory");
        Directory.CreateDirectory(parent);
        PathSafety.EnsureNoReparse(repositoryRoot, parent, "review data directory");
        return parent;
    }

    private async Task EnsureUnchangedAsync(byte[]? expected)
    {
        PathSafety.EnsureNoReparse(repositoryRoot, dataPath, "review data path");
        if (!File.Exists(dataPath))
        {
            if (expected is not null)
                throw new ReviewApiException(409, "review data changed; reload and retry");
            return;
        }
        if (expected is null)
            throw new ReviewApiException(409, "review data changed; reload and retry");
        await using FileStream stream = new(
            dataPath, FileMode.Open, FileAccess.Read, FileShare.Read,
            bufferSize: 16 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
        if (stream.Length > MaximumFileBytes || stream.Length != expected.Length)
            throw new ReviewApiException(409, "review data changed; reload and retry");
        byte[] current = new byte[expected.Length];
        await stream.ReadExactlyAsync(current).ConfigureAwait(false);
        if (!current.AsSpan().SequenceEqual(expected))
            throw new ReviewApiException(409, "review data changed; reload and retry");
    }

    private static ReviewCommentData ParseData(byte[] bytes)
    {
        try
        {
            using JsonDocument document = JsonDocument.Parse(bytes, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 8,
            });
            JsonElement root = document.RootElement;
            RequireObject(root, StoreFields, "review data");
            if (!root.TryGetProperty("schemaVersion", out JsonElement version)
                || version.ValueKind != JsonValueKind.Number || !version.TryGetInt32(out int value)
                || value != SchemaVersion)
                throw new InvalidDataException("review data schemaVersion must be 1");
            if (!root.TryGetProperty("comments", out JsonElement comments)
                || comments.ValueKind != JsonValueKind.Array)
                throw new InvalidDataException("review data comments must be an array");
            if (comments.GetArrayLength() > MaximumComments)
                throw new InvalidDataException("review data contains more than 1000 comments");

            ReviewCommentData result = new();
            HashSet<string> ids = new(StringComparer.Ordinal);
            foreach (JsonElement element in comments.EnumerateArray())
            {
                RequireObject(element, CommentFields, "review comment");
                ReviewComment comment = new()
                {
                    Id = RequiredString(element, "id"),
                    Route = RequiredString(element, "route"),
                    Anchor = OptionalString(element, "anchor"),
                    Quote = OptionalString(element, "quote"),
                    Body = RequiredString(element, "body"),
                    Status = ParseStatus(RequiredString(element, "status")),
                    Reply = OptionalString(element, "reply"),
                    CreatedAt = RequiredString(element, "createdAt"),
                    UpdatedAt = RequiredString(element, "updatedAt"),
                };
                ValidateId(comment.Id);
                ValidateRoute(comment.Route);
                ValidateOptionalAnchor(comment.Anchor);
                ValidateOptionalText(comment.Quote, MaximumQuoteLength, "quote");
                if (NormalizeRequiredText(comment.Body, MaximumBodyLength, "body") != comment.Body)
                    throw new InvalidDataException("review comment body is not normalized");
                if (comment.Reply is not null
                    && NormalizeRequiredText(comment.Reply, MaximumReplyLength, "reply") != comment.Reply)
                    throw new InvalidDataException("review comment reply is not normalized");
                DateTime created = ParseTimestamp(comment.CreatedAt, "createdAt");
                DateTime updated = ParseTimestamp(comment.UpdatedAt, "updatedAt");
                if (updated < created)
                    throw new InvalidDataException("review comment updatedAt precedes createdAt");
                if ((comment.Status is ReviewStatus.Answered or ReviewStatus.Resolved)
                    && comment.Reply is null)
                    throw new InvalidDataException(
                        "answered and resolved review comments require a reply");
                if (!ids.Add(comment.Id))
                    throw new InvalidDataException("review data contains a duplicate id");
                result.Comments.Add(comment);
            }
            return result;
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("review data is not strict JSON", exception);
        }
        catch (ReviewApiException exception)
        {
            throw new InvalidDataException("review data is invalid: " + exception.Message, exception);
        }
    }

    private static void RequireObject(
        JsonElement element, HashSet<string> allowed, string label)
    {
        if (element.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException(label + " must be an object");
        HashSet<string> found = new(StringComparer.Ordinal);
        foreach (JsonProperty property in element.EnumerateObject())
        {
            if (!found.Add(property.Name))
                throw new InvalidDataException(label + " contains a duplicate field");
            if (!allowed.Contains(property.Name))
                throw new InvalidDataException(label + " contains an unknown field: " + property.Name);
        }
    }

    private static string RequiredString(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out JsonElement property)
            || property.ValueKind != JsonValueKind.String)
            throw new InvalidDataException($"review comment {name} must be a string");
        return property.GetString()!;
    }

    private static string? OptionalString(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out JsonElement property))
            return null;
        if (property.ValueKind != JsonValueKind.String)
            throw new InvalidDataException($"review comment {name} must be a string when present");
        return property.GetString();
    }

    private static string NormalizeRequiredText(string value, int maximum, string name)
    {
        string normalized = value.Trim();
        int length = normalized.Length;
        if (length < 1 || length > maximum
            || normalized.Any(character => char.IsControl(character)
                && character is not '\r' and not '\n' and not '\t'))
            throw new ReviewApiException(400, $"{name} must contain 1 to {maximum} safe characters");
        return normalized;
    }

    private static void ValidateOptionalText(string? value, int maximum, string name)
    {
        if (value is null)
            return;
        int length = value.Length;
        if (length < 1 || length > maximum || string.IsNullOrWhiteSpace(value)
            || value.Any(character => char.IsControl(character)
                && character is not '\r' and not '\n' and not '\t'))
            throw new ReviewApiException(400, $"{name} must contain 1 to {maximum} safe characters");
    }

    private static ReviewStatus ParseStatus(string? value) => value switch
    {
        "open" => ReviewStatus.Open,
        "answered" => ReviewStatus.Answered,
        "resolved" => ReviewStatus.Resolved,
        _ => throw new ReviewApiException(400, "status must be open, answered, or resolved"),
    };

    private static DateTime ParseTimestamp(string value, string name)
    {
        if (!DateTime.TryParseExact(value, TimestampFormat, CultureInfo.InvariantCulture,
                                    DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                                    out DateTime parsed))
            throw new InvalidDataException($"review comment {name} must be an exact UTC timestamp");
        return parsed;
    }

    private static string UtcTimestamp() =>
        DateTime.UtcNow.ToString(TimestampFormat, CultureInfo.InvariantCulture);

    private static string NextUpdatedTimestamp(ReviewComment comment)
    {
        DateTime latest = DateTime.UtcNow;
        DateTime created = ParseTimestamp(comment.CreatedAt, "createdAt");
        DateTime previous = ParseTimestamp(comment.UpdatedAt, "updatedAt");
        if (created > latest)
            latest = created;
        if (previous > latest)
            latest = previous;
        return latest.ToString(TimestampFormat, CultureInfo.InvariantCulture);
    }

    private static StringComparison PathComparison => OperatingSystem.IsWindows()
        ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;

    private sealed class ReviewWriteLock(FileStream stream) : IDisposable
    {
        public void Dispose()
        {
            try
            {
                ReleaseFileLock(stream);
            }
            catch (IOException)
            {
            }
            finally
            {
                stream.Dispose();
            }
        }
    }
}

internal sealed class ReviewCommentData
{
    public int SchemaVersion { get; init; } = ReviewCommentStore.SchemaVersion;
    public List<ReviewComment> Comments { get; init; } = [];
    internal byte[]? SourceBytes { get; set; }
}

internal sealed class ReviewComment
{
    public required string Id { get; init; }
    public required string Route { get; init; }
    public string? Anchor { get; init; }
    public string? Quote { get; init; }
    public required string Body { get; init; }
    public ReviewStatus Status { get; set; }
    public string? Reply { get; set; }
    public required string CreatedAt { get; init; }
    public required string UpdatedAt { get; set; }
}

[JsonConverter(typeof(JsonStringEnumConverter<ReviewStatus>))]
internal enum ReviewStatus
{
    [JsonStringEnumMemberName("open")]
    Open,
    [JsonStringEnumMemberName("answered")]
    Answered,
    [JsonStringEnumMemberName("resolved")]
    Resolved,
}

internal sealed class ReviewApiException : Exception
{
    internal ReviewApiException(int statusCode, string message) : base(message)
    {
        StatusCode = statusCode;
    }

    internal ReviewApiException(int statusCode, string message, Exception innerException)
        : base(message, innerException)
    {
        StatusCode = statusCode;
    }

    internal int StatusCode { get; }
}
