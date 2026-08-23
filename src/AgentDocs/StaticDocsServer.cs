using System.Net;
using System.Text;

namespace AgentDocs;

/// <summary>A loopback-only, read-only preview server for the generated site.</summary>
public static class StaticDocsServer
{
    public static async Task RunAsync(string outputRoot, int port, string basePath,
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
            || !File.Exists(Path.Combine(output, "app.css")))
            throw new InvalidDataException("output is not a completed Agent Docs build");
        string outputVolume = Path.GetPathRoot(output)!;
        PathSafety.EnsureNoReparse(outputVolume, output, "build output");
        foreach (string required in new[] { "index.json", "index.html", "app.js", "app.css" })
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
                await HandleAsync(request, output, mount).ConfigureAwait(false);
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

    private static async Task HandleAsync(HttpListenerContext context, string output, string mount)
    {
        try
        {
            if (context.Request.HttpMethod is not ("GET" or "HEAD"))
            {
                context.Response.StatusCode = (int)HttpStatusCode.MethodNotAllowed;
                context.Response.Headers[HttpResponseHeader.Allow] = "GET, HEAD";
                context.Response.Close();
                return;
            }
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
