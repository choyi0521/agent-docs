using System.Net;
using System.Text;
using System.Text.Json;

namespace AgentDocs;

/// <summary>A loopback-only preview server for generated docs and local review data.</summary>
public static class StaticDocsServer
{
    private const string ReviewEndpoint = "/__agent-docs/review/comments";
    private static readonly HashSet<string> CreateReviewFields = new(StringComparer.Ordinal)
    {
        "route", "anchor", "quote", "body",
    };
    private static readonly HashSet<string> PatchReviewFields = new(StringComparer.Ordinal)
    {
        "reply", "status",
    };

    public static Task RunAsync(string outputRoot, int port, string basePath,
                                CancellationToken cancellationToken) =>
        RunCoreAsync(outputRoot, port, basePath, null, cancellationToken);

    public static Task RunAsync(string outputRoot, int port, string basePath,
                                string repositoryRoot, string? reviewDataPath,
                                string configurationPath,
                                CancellationToken cancellationToken)
    {
        ReviewCommentStore store = ReviewCommentStore.Create(
            repositoryRoot, reviewDataPath, outputRoot);
        ResolvedConfiguration configuration = ConfigurationLoader.Load(
            repositoryRoot, configurationPath);
        ReviewCommentStore.EnsureOutsidePublicationInputs(store.DataPath, configuration);
        return RunCoreAsync(outputRoot, port, basePath, store, cancellationToken);
    }

    public static string ResolveReviewDataPath(
        string repositoryRoot, string? reviewDataPath, string outputRoot) =>
        ReviewCommentStore.Create(repositoryRoot, reviewDataPath, outputRoot).DataPath;

    public static string ResolveReviewDataPath(
        string repositoryRoot, string? reviewDataPath, string outputRoot,
        string configurationPath)
    {
        ReviewCommentStore store = ReviewCommentStore.Create(
            repositoryRoot, reviewDataPath, outputRoot);
        ResolvedConfiguration configuration = ConfigurationLoader.Load(
            repositoryRoot, configurationPath);
        ReviewCommentStore.EnsureOutsidePublicationInputs(store.DataPath, configuration);
        return store.DataPath;
    }

    private static async Task RunCoreAsync(string outputRoot, int port, string basePath,
                                           ReviewCommentStore? reviewStore,
                                           CancellationToken cancellationToken)
    {
        if (port is < 1 or > 65_535)
            throw new ArgumentOutOfRangeException(nameof(port), "port must be between 1 and 65535");
        string mount = NormalizeBasePath(basePath);
        string output = Path.GetFullPath(outputRoot);
        if (!Directory.Exists(output)
            || !OutputDirectory.HasValidSentinel(output)
            || !File.Exists(Path.Combine(output, "index.json"))
            || !File.Exists(Path.Combine(output, "index.html"))
            || !File.Exists(Path.Combine(output, "app.js"))
            || !File.Exists(Path.Combine(output, "app.css"))
            || !File.Exists(Path.Combine(output, "prism.js")))
            throw new InvalidDataException("output is not a completed Agent Docs build");
        string outputVolume = Path.GetPathRoot(output)!;
        PathSafety.EnsureNoReparse(outputVolume, output, "build output");
        foreach (string required in new[] { "index.json", "index.html", "app.js", "app.css", "prism.js" })
            PathSafety.EnsureNoReparse(output, Path.Combine(output, required), "generated web asset");

        using HttpListener listener = new();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                HttpListenerContext request;
                try
                {
                    request = await listener.GetContextAsync().WaitAsync(cancellationToken)
                        .ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    break;
                }
                await HandleAsync(request, output, mount, reviewStore,
                                  $"http://127.0.0.1:{port}", cancellationToken)
                    .ConfigureAwait(false);
            }
        }
        finally
        {
            listener.Stop();
        }
    }

    public static async Task<bool> ProbeAsync(Uri baseUri, CancellationToken cancellationToken)
    {
        if (baseUri.Scheme != Uri.UriSchemeHttp || !IPAddress.TryParse(baseUri.Host, out IPAddress? host)
            || !IPAddress.IsLoopback(host))
            throw new InvalidDataException("preview probe must target a loopback HTTP address");
        Uri health = new(baseUri.AbsoluteUri.TrimEnd('/') + "/health");
        using HttpClient client = new() { Timeout = TimeSpan.FromSeconds(5) };
        using HttpResponseMessage response = await client.GetAsync(health, cancellationToken)
            .ConfigureAwait(false);
        return response.IsSuccessStatusCode;
    }

    public static string NormalizeBasePath(string configured)
    {
        string value = string.IsNullOrWhiteSpace(configured) ? "/" : configured.Trim();
        if (!value.StartsWith('/') || value.StartsWith("//", StringComparison.Ordinal)
            || value.Contains('\\') || value.Contains('?') || value.Contains('#')
            || value.Any(character => character > 127))
            throw new InvalidDataException("base path must be a simple absolute URL path");
        value = "/" + string.Join('/', value.Split('/', StringSplitOptions.RemoveEmptyEntries));
        if (value == "/")
            return value;
        foreach (string segment in value[1..].Split('/'))
            if (segment.Length == 0 || segment is "." or ".."
                || segment.Any(character => !char.IsAsciiLetterOrDigit(character)
                                                    && character is not '-' and not '_' and not '.'))
                throw new InvalidDataException("base path contains an invalid segment");
        return value;
    }

    private static async Task HandleAsync(
        HttpListenerContext context, string output, string mount,
        ReviewCommentStore? reviewStore, string expectedOrigin,
        CancellationToken cancellationToken)
    {
        try
        {
            string rawTarget = context.Request.RawUrl ?? "/";
            int query = rawTarget.IndexOf('?');
            string path = Uri.UnescapeDataString(query < 0 ? rawTarget : rawTarget[..query]);
            if (mount != "/")
            {
                if (path != mount && !path.StartsWith(mount + "/", StringComparison.Ordinal))
                {
                    context.Response.StatusCode = (int)HttpStatusCode.NotFound;
                    context.Response.Close();
                    return;
                }
                path = path.Length == mount.Length ? "/" : path[mount.Length..];
            }
            if (path == ReviewEndpoint || path.StartsWith(ReviewEndpoint + "/", StringComparison.Ordinal))
            {
                if (reviewStore is null)
                {
                    await SendReviewErrorAsync(context, (int)HttpStatusCode.NotFound,
                                               "review API is not enabled").ConfigureAwait(false);
                    return;
                }
                await HandleReviewAsync(context, path, query < 0 ? "" : rawTarget[query..],
                                        reviewStore, expectedOrigin, cancellationToken)
                    .ConfigureAwait(false);
                return;
            }
            if (path.StartsWith("/__agent-docs/", StringComparison.Ordinal))
            {
                context.Response.StatusCode = (int)HttpStatusCode.NotFound;
                context.Response.Headers[HttpResponseHeader.CacheControl] = "no-store";
                context.Response.Close();
                return;
            }
            if (context.Request.HttpMethod is not ("GET" or "HEAD"))
            {
                context.Response.StatusCode = (int)HttpStatusCode.MethodNotAllowed;
                context.Response.Headers[HttpResponseHeader.Allow] = "GET, HEAD";
                context.Response.Close();
                return;
            }
            if (path == "/health")
            {
                await SendAsync(context, "ok\n", "text/plain; charset=utf-8").ConfigureAwait(false);
                return;
            }
            string relative = SafeRequestPath(path);
            string? file = ResolveFile(output, relative);
            if (file is not null)
            {
                await SendFileAsync(context, file, mount).ConfigureAwait(false);
                return;
            }
            if (RequiresConcreteFile(relative))
            {
                context.Response.StatusCode = (int)HttpStatusCode.NotFound;
                context.Response.Close();
                return;
            }
            string shell = ResolveFile(output, "index.html")
                ?? throw new InvalidDataException("generated web entry point is unavailable");
            await SendFileAsync(context, shell, mount).ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is InvalidDataException or IOException
                                          or UnauthorizedAccessException or UriFormatException
                                          or HttpListenerException)
        {
            try
            {
                if (context.Response.OutputStream.CanWrite)
                {
                    context.Response.StatusCode = (int)HttpStatusCode.BadRequest;
                    context.Response.Close();
                }
            }
            catch (HttpListenerException) { }
        }
    }

    private static async Task HandleReviewAsync(
        HttpListenerContext context, string path, string rawQuery,
        ReviewCommentStore store, string expectedOrigin,
        CancellationToken cancellationToken)
    {
        try
        {
            bool collection = path == ReviewEndpoint;
            string? id = collection ? null : path[(ReviewEndpoint.Length + 1)..];
            if (!collection && (id!.Length == 0 || id.Contains('/')))
                throw new ReviewApiException(404, "review API route not found");

            if (collection && context.Request.HttpMethod == "GET")
            {
                string? route = ParseRouteQuery(rawQuery);
                ReviewCommentData data = await store.GetAsync(route).ConfigureAwait(false);
                await SendReviewJsonAsync(context, (int)HttpStatusCode.OK, data)
                    .ConfigureAwait(false);
                return;
            }
            if (collection && context.Request.HttpMethod == "POST")
            {
                RequireNoQuery(rawQuery);
                ValidateWriteRequest(context.Request, expectedOrigin);
                using JsonDocument document = await ReadRequestJsonAsync(
                    context.Request, cancellationToken).ConfigureAwait(false);
                JsonElement body = document.RootElement;
                RequireFields(body, CreateReviewFields, "create request");
                ReviewComment created = await store.CreateAsync(
                    RequiredString(body, "route"), OptionalString(body, "anchor"),
                    OptionalString(body, "quote"), RequiredString(body, "body"))
                    .ConfigureAwait(false);
                await SendReviewJsonAsync(context, (int)HttpStatusCode.Created,
                    new { schemaVersion = ReviewCommentStore.SchemaVersion, comment = created })
                    .ConfigureAwait(false);
                return;
            }
            if (!collection && context.Request.HttpMethod == "PATCH")
            {
                RequireNoQuery(rawQuery);
                ReviewCommentStore.ValidateId(id!);
                ValidateWriteRequest(context.Request, expectedOrigin);
                using JsonDocument document = await ReadRequestJsonAsync(
                    context.Request, cancellationToken).ConfigureAwait(false);
                JsonElement body = document.RootElement;
                RequireFields(body, PatchReviewFields, "patch request");
                bool hasReply = body.TryGetProperty("reply", out JsonElement replyElement);
                bool hasStatus = body.TryGetProperty("status", out JsonElement statusElement);
                string? reply = hasReply ? NullableString(replyElement, "reply") : null;
                string? status = hasStatus ? StrictString(statusElement, "status") : null;
                ReviewComment updated = await store.PatchAsync(
                    id!, hasReply, reply, hasStatus, status).ConfigureAwait(false);
                await SendReviewJsonAsync(context, (int)HttpStatusCode.OK,
                    new { schemaVersion = ReviewCommentStore.SchemaVersion, comment = updated })
                    .ConfigureAwait(false);
                return;
            }

            context.Response.StatusCode = (int)HttpStatusCode.MethodNotAllowed;
            context.Response.Headers[HttpResponseHeader.Allow] = collection ? "GET, POST" : "PATCH";
            context.Response.Headers[HttpResponseHeader.CacheControl] = "no-store";
            context.Response.Close();
        }
        catch (ReviewApiException exception)
        {
            await SendReviewErrorAsync(context, exception.StatusCode, exception.Message)
                .ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is InvalidDataException or IOException
                                          or UnauthorizedAccessException or JsonException)
        {
            await SendReviewErrorAsync(context, (int)HttpStatusCode.InternalServerError,
                                       "review data is unavailable").ConfigureAwait(false);
        }
    }

    private static void ValidateWriteRequest(HttpListenerRequest request, string expectedOrigin)
    {
        string mediaType = (request.ContentType ?? "").Split(';', 2)[0].Trim();
        if (!string.Equals(mediaType, "application/json", StringComparison.OrdinalIgnoreCase))
            throw new ReviewApiException((int)HttpStatusCode.UnsupportedMediaType,
                                         "Content-Type must be application/json");
        string? origin = request.Headers["Origin"];
        if (origin is not null && !string.Equals(origin, expectedOrigin, StringComparison.Ordinal))
            throw new ReviewApiException((int)HttpStatusCode.Forbidden,
                                         "cross-origin review writes are forbidden");
        if (string.Equals(request.Headers["Sec-Fetch-Site"], "cross-site",
                          StringComparison.OrdinalIgnoreCase))
            throw new ReviewApiException((int)HttpStatusCode.Forbidden,
                                         "cross-site review writes are forbidden");
    }

    private static async Task<JsonDocument> ReadRequestJsonAsync(
        HttpListenerRequest request, CancellationToken cancellationToken)
    {
        if (request.ContentLength64 > ReviewCommentStore.MaximumRequestBytes)
            throw new ReviewApiException((int)HttpStatusCode.RequestEntityTooLarge,
                                         "request JSON exceeds 16 KiB");
        using MemoryStream buffer = new();
        byte[] block = new byte[4096];
        while (true)
        {
            int read = await request.InputStream.ReadAsync(block, cancellationToken)
                .ConfigureAwait(false);
            if (read == 0)
                break;
            if (buffer.Length + read > ReviewCommentStore.MaximumRequestBytes)
                throw new ReviewApiException((int)HttpStatusCode.RequestEntityTooLarge,
                                             "request JSON exceeds 16 KiB");
            await buffer.WriteAsync(block.AsMemory(0, read), cancellationToken)
                .ConfigureAwait(false);
        }
        if (buffer.Length == 0)
            throw new ReviewApiException((int)HttpStatusCode.BadRequest,
                                         "request JSON is required");
        try
        {
            return JsonDocument.Parse(buffer.ToArray(), new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 4,
            });
        }
        catch (JsonException exception)
        {
            throw new ReviewApiException((int)HttpStatusCode.BadRequest,
                                         "request body is not strict JSON", exception);
        }
    }

    private static void RequireFields(
        JsonElement element, IReadOnlySet<string> allowed, string label)
    {
        if (element.ValueKind != JsonValueKind.Object)
            throw new ReviewApiException(400, label + " must be an object");
        HashSet<string> found = new(StringComparer.Ordinal);
        foreach (JsonProperty property in element.EnumerateObject())
        {
            if (!found.Add(property.Name))
                throw new ReviewApiException(400, label + " contains a duplicate field");
            if (!allowed.Contains(property.Name))
                throw new ReviewApiException(400,
                    label + " contains an unknown field: " + property.Name);
        }
    }

    private static string RequiredString(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out JsonElement value))
            throw new ReviewApiException(400, name + " is required");
        return StrictString(value, name);
    }

    private static string? OptionalString(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out JsonElement value))
            return null;
        return StrictString(value, name);
    }

    private static string StrictString(JsonElement value, string name)
    {
        if (value.ValueKind != JsonValueKind.String)
            throw new ReviewApiException(400, name + " must be a string");
        return value.GetString()!;
    }

    private static string? NullableString(JsonElement value, string name)
    {
        if (value.ValueKind == JsonValueKind.Null)
            return null;
        return StrictString(value, name);
    }

    private static string? ParseRouteQuery(string rawQuery)
    {
        if (rawQuery.Length == 0)
            return null;
        string query = rawQuery.StartsWith('?') ? rawQuery[1..] : rawQuery;
        string[] pairs = query.Split('&');
        if (pairs.Length != 1)
            throw new ReviewApiException(400, "GET accepts only one optional route query");
        int equals = pairs[0].IndexOf('=');
        if (equals < 0 || pairs[0][..equals] != "route")
            throw new ReviewApiException(400, "GET accepts only one optional route query");
        string route;
        try
        {
            route = Uri.UnescapeDataString(pairs[0][(equals + 1)..].Replace('+', ' '));
        }
        catch (UriFormatException exception)
        {
            throw new ReviewApiException(400, "route query is invalid", exception);
        }
        ReviewCommentStore.ValidateRoute(route);
        return route;
    }

    private static void RequireNoQuery(string rawQuery)
    {
        if (rawQuery.Length != 0)
            throw new ReviewApiException(400, "write routes do not accept query parameters");
    }

    private static Task SendReviewErrorAsync(
        HttpListenerContext context, int statusCode, string message) =>
        SendReviewJsonAsync(context, statusCode, new { error = message });

    private static async Task SendReviewJsonAsync(
        HttpListenerContext context, int statusCode, object value)
    {
        byte[] bytes = ReviewCommentStore.SerializeResponse(value);
        context.Response.StatusCode = statusCode;
        context.Response.ContentType = "application/json; charset=utf-8";
        context.Response.ContentLength64 = bytes.Length;
        context.Response.Headers[HttpResponseHeader.CacheControl] = "no-store";
        await context.Response.OutputStream.WriteAsync(bytes).ConfigureAwait(false);
        context.Response.Close();
    }

    private static string SafeRequestPath(string path)
    {
        if (path.Contains('\\') || path.Contains('\0') || path.Contains("//", StringComparison.Ordinal))
            throw new InvalidDataException("unsafe request path");
        string[] segments = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Any(segment => segment is "." or ".."
                                    || string.Equals(segment, OutputDirectory.SentinelName,
                                                     StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("unsafe request path");
        return string.Join(Path.DirectorySeparatorChar, segments);
    }

    private static string? ResolveFile(string root, string relative)
    {
        if (relative.Length == 0)
            return null;
        string candidate = Path.GetFullPath(Path.Combine(root, relative));
        if (!PathSafety.IsSameOrUnder(candidate, root) || !File.Exists(candidate))
            return null;
        PathSafety.EnsureNoReparse(root, candidate, "served file");
        return candidate;
    }

    private static bool RequiresConcreteFile(string relative)
    {
        string extension = Path.GetExtension(relative).ToLowerInvariant();
        return extension is ".json" or ".js" or ".css" or ".svg" or ".png" or ".ico"
            or ".map" or ".txt" or ".xml" or ".woff" or ".woff2" or ".ttf";
    }

    private static async Task SendFileAsync(HttpListenerContext context, string path, string mount)
    {
        if (Path.GetFileName(path) == "index.html")
        {
            string html = TextUtilities.ReadText(path);
            string baseValue = mount == "/" ? "/" : mount;
            html = System.Text.RegularExpressions.Regex.Replace(html,
                "data-base=\"[^\"]*\"", $"data-base=\"{baseValue}\"",
                System.Text.RegularExpressions.RegexOptions.CultureInvariant);
            await SendAsync(context, html, "text/html; charset=utf-8").ConfigureAwait(false);
            return;
        }
        context.Response.ContentType = ContentType(path);
        FileInfo info = new(path);
        context.Response.ContentLength64 = info.Length;
        context.Response.Headers[HttpResponseHeader.CacheControl] = "no-store";
        if (context.Request.HttpMethod == "GET")
        {
            await using FileStream stream = File.OpenRead(path);
            await stream.CopyToAsync(context.Response.OutputStream).ConfigureAwait(false);
        }
        context.Response.Close();
    }

    private static async Task SendAsync(HttpListenerContext context, string text, string contentType)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(text);
        context.Response.ContentType = contentType;
        context.Response.ContentLength64 = bytes.Length;
        context.Response.Headers[HttpResponseHeader.CacheControl] = "no-store";
        if (context.Request.HttpMethod == "GET")
            await context.Response.OutputStream.WriteAsync(bytes).ConfigureAwait(false);
        context.Response.Close();
    }

    private static string ContentType(string path) => Path.GetExtension(path).ToLowerInvariant() switch
    {
        ".html" => "text/html; charset=utf-8",
        ".css" => "text/css; charset=utf-8",
        ".js" => "text/javascript; charset=utf-8",
        ".json" => "application/json; charset=utf-8",
        ".svg" => "image/svg+xml",
        ".png" => "image/png",
        ".ico" => "image/x-icon",
        _ => "application/octet-stream",
    };
}
