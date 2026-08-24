using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;

namespace AgentDocs.Tests;

public sealed class StaticDocsServerTests
{
    [Fact]
    public async Task Server_is_loopback_read_only_mounted_and_cancellable()
    {
        using TempRepository repo = new();
        repo.Write("docs/section/_index.md", "# Section\n\nNested landing.\n");
        repo.Write("docs/.details.md", "# Dot-prefixed details\n");
        repo.Write("examples/.sample.cs", "internal static class DotSample;\n");
        repo.WriteConfiguration(
            mutate: config => config["siteUrl"] = "https://docs.example.test/manual",
            publishCode: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);
        repo.Write("web/index.html",
            "<!doctype html><html data-base=\"/\"><body>preview shell</body></html>\n");
        AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);
        Assert.Contains("data-base=\"/manual\"",
            File.ReadAllText(Path.Combine(repo.Output, "index.html")),
            StringComparison.Ordinal);
        repo.Write("web/app.js", "globalThis.changedAfterBuild = true;\n");
        int port = ReserveLoopbackPort();
        Uri mount = new($"http://127.0.0.1:{port}/preview");
        using CancellationTokenSource serverCancellation = new();
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(15));
        Task server = StaticDocsServer.RunAsync(
            repo.Output,
            port,
            "/preview/",
            serverCancellation.Token);

        try
        {
            await WaitForProbeAsync(mount, server, timeout.Token);
            using SocketsHttpHandler handler = new() { UseProxy = false };
            using HttpClient client = new(handler);

            using HttpResponseMessage shell = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, shell.StatusCode);
            string shellText = await shell.Content.ReadAsStringAsync(timeout.Token);
            Assert.Contains("data-base=\"/preview\"", shellText, StringComparison.Ordinal);
            Assert.DoesNotContain("data-base=\"/manual\"", shellText,
                StringComparison.Ordinal);
            Assert.Contains("preview shell", shellText, StringComparison.Ordinal);
            Assert.Equal("frame-ancestors 'none'",
                Assert.Single(shell.Headers.GetValues("Content-Security-Policy")));
            Assert.Equal("DENY",
                Assert.Single(shell.Headers.GetValues("X-Frame-Options")));

            using HttpResponseMessage siteIndex = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/index.json"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, siteIndex.StatusCode);
            Assert.Contains("Fixture Docs",
                await siteIndex.Content.ReadAsStringAsync(timeout.Token),
                StringComparison.Ordinal);

            using HttpResponseMessage script = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/app.js"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, script.StatusCode);
            string scriptText = await script.Content.ReadAsStringAsync(timeout.Token);
            Assert.Contains("agentDocsPreview", scriptText, StringComparison.Ordinal);
            Assert.DoesNotContain("changedAfterBuild", scriptText, StringComparison.Ordinal);

            using HttpResponseMessage spa = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/guide"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, spa.StatusCode);
            Assert.Contains("preview shell",
                await spa.Content.ReadAsStringAsync(timeout.Token),
                StringComparison.Ordinal);
            Assert.Equal("frame-ancestors 'none'",
                Assert.Single(spa.Headers.GetValues("Content-Security-Policy")));
            Assert.Equal("DENY",
                Assert.Single(spa.Headers.GetValues("X-Frame-Options")));

            using HttpResponseMessage missingCandidate = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/content/section.json"), timeout.Token);
            Assert.Equal(HttpStatusCode.NotFound, missingCandidate.StatusCode);
            using HttpResponseMessage nestedIndex = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/content/section/index.json"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, nestedIndex.StatusCode);
            Assert.Contains("Section",
                await nestedIndex.Content.ReadAsStringAsync(timeout.Token),
                StringComparison.Ordinal);
            using HttpResponseMessage missingAsset = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/missing.js"), timeout.Token);
            Assert.Equal(HttpStatusCode.NotFound, missingAsset.StatusCode);

            using HttpResponseMessage dotDocumentRoute = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/.details"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, dotDocumentRoute.StatusCode);
            using HttpResponseMessage dotDocument = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/content/.details.json"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, dotDocument.StatusCode);
            Assert.Contains("Dot-prefixed details",
                await dotDocument.Content.ReadAsStringAsync(timeout.Token),
                StringComparison.Ordinal);

            using HttpResponseMessage dotCodeRoute = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/code/examples/.sample.cs"), timeout.Token);
            Assert.Equal(HttpStatusCode.OK, dotCodeRoute.StatusCode);
            using HttpResponseMessage dotCode = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/content/code/examples/.sample.cs.json"),
                timeout.Token);
            Assert.Equal(HttpStatusCode.OK, dotCode.StatusCode);
            Assert.Contains("DotSample",
                await dotCode.Content.ReadAsStringAsync(timeout.Token),
                StringComparison.Ordinal);

            using HttpResponseMessage sentinel = await client.GetAsync(
                new Uri(mount.AbsoluteUri + "/.agent-docs-output"), timeout.Token);
            Assert.False(sentinel.IsSuccessStatusCode);

            using HttpRequestMessage headRequest = new(
                HttpMethod.Head, new Uri(mount.AbsoluteUri + "/index.json"));
            using HttpResponseMessage head = await client.SendAsync(
                headRequest, timeout.Token);
            Assert.Equal(HttpStatusCode.OK, head.StatusCode);
            Assert.True(head.Content.Headers.ContentLength > 0);
            Assert.Empty(await head.Content.ReadAsByteArrayAsync(timeout.Token));

            foreach (HttpMethod method in new[] { HttpMethod.Post, HttpMethod.Put, HttpMethod.Delete })
            {
                using HttpRequestMessage mutation = new(
                    method, new Uri(mount.AbsoluteUri + "/index.json"));
                using HttpResponseMessage rejected = await client.SendAsync(
                    mutation, timeout.Token);
                Assert.Equal(HttpStatusCode.MethodNotAllowed, rejected.StatusCode);
                Assert.Equal(new[] { "GET", "HEAD" }, rejected.Content.Headers.Allow);
            }

            using HttpResponseMessage outsideMount = await client.GetAsync(
                new Uri($"http://127.0.0.1:{port}/index.json"), timeout.Token);
            Assert.Equal(HttpStatusCode.NotFound, outsideMount.StatusCode);

            using (HttpRequestMessage rebound = new(HttpMethod.Get,
                       new Uri(mount.AbsoluteUri + "/")))
            {
                rebound.Headers.Host = $"docs.attacker.test:{port}";
                using HttpResponseMessage rejected = await client.SendAsync(
                    rebound, timeout.Token);
                Assert.Equal(HttpStatusCode.BadRequest, rejected.StatusCode);
            }
            using (HttpRequestMessage wrongPort = new(HttpMethod.Get,
                       new Uri(mount.AbsoluteUri + "/__agent-docs/review/comments")))
            {
                wrongPort.Headers.Host = $"127.0.0.1:{port + 1}";
                using HttpResponseMessage rejected = await client.SendAsync(
                    wrongPort, timeout.Token);
                Assert.Equal(HttpStatusCode.BadRequest, rejected.StatusCode);
            }

            string traversal = await SendRawRequestAsync(
                port, "/preview/%2e%2e/index.json", timeout.Token);
            Assert.Contains(" 400 ", traversal, StringComparison.Ordinal);

            await AssertNotServedOnNonLoopbackAsync(port, timeout.Token);
        }
        finally
        {
            serverCancellation.Cancel();
            await server.WaitAsync(TimeSpan.FromSeconds(5), timeout.Token);
        }

        Assert.True(server.IsCompletedSuccessfully);
    }

    [Fact]
    public async Task Server_rejects_a_tampered_output_sentinel()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();
        repo.Write("web/index.html", "<!doctype html><html data-base=\"/\"></html>\n");
        AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);
        File.WriteAllText(
            Path.Combine(repo.Output, ".agent-docs-output"),
            "invalid marker\n");
        using CancellationTokenSource cancelled = new();
        cancelled.Cancel();

        InvalidDataException error = await Assert.ThrowsAsync<InvalidDataException>(() =>
            StaticDocsServer.RunAsync(
                repo.Output,
                ReserveLoopbackPort(),
                "/",
                cancelled.Token));

        Assert.Contains("completed Agent Docs build", error.Message,
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task Probe_rejects_nonloopback_and_non_http_targets_before_connecting()
    {
        Uri nonLoopback = new UriBuilder(
            Uri.UriSchemeHttp, new IPAddress([192, 0, 2, 1]).ToString(), 8080).Uri;
        Uri secureLoopback = new UriBuilder(
            Uri.UriSchemeHttps, IPAddress.Loopback.ToString(), 8080).Uri;

        await Assert.ThrowsAsync<InvalidDataException>(() =>
            StaticDocsServer.ProbeAsync(nonLoopback, CancellationToken.None));
        await Assert.ThrowsAsync<InvalidDataException>(() =>
            StaticDocsServer.ProbeAsync(secureLoopback, CancellationToken.None));
    }

    [Theory]
    [InlineData("docs")]
    [InlineData("//docs")]
    [InlineData("/docs/../site")]
    [InlineData("/docs\\site")]
    [InlineData("/docs?mode=test")]
    [InlineData("/docs#section")]
    [InlineData("/café")]
    public void Base_path_rejects_non_simple_or_ambiguous_values(string configured)
    {
        Assert.Throws<InvalidDataException>(() =>
            StaticDocsServer.NormalizeBasePath(configured));
    }

    [Theory]
    [InlineData("", "/")]
    [InlineData("/", "/")]
    [InlineData(" /docs/ ", "/docs")]
    [InlineData("/docs/reference", "/docs/reference")]
    public void Base_path_is_normalized_for_safe_mounts(string configured, string expected)
    {
        Assert.Equal(expected, StaticDocsServer.NormalizeBasePath(configured));
    }

    [Theory]
    [InlineData("127.0.0.1:4173", "http://127.0.0.1:4173")]
    public void Loopback_authority_accepts_ip_literals_and_exact_port(
        string authority, string expectedOrigin)
    {
        Assert.True(StaticDocsServer.TryNormalizeLoopbackAuthority(
            authority, 4173, out string origin));
        Assert.Equal(expectedOrigin, origin);
    }

    [Fact]
    public void Loopback_authority_accepts_the_ipv6_loopback_literal()
    {
        string authority = "[" + "::1" + "]:4173";
        string expectedOrigin = "http://" + authority;

        Assert.True(StaticDocsServer.TryNormalizeLoopbackAuthority(
            authority, 4173, out string origin));
        Assert.Equal(expectedOrigin, origin);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("localhost:4173")]
    [InlineData("docs.attacker.test:4173")]
    [InlineData("127.0.0.1:4174")]
    [InlineData("127.0.0.1:4173/path")]
    [InlineData("user@127.0.0.1:4173")]
    [InlineData(" 127.0.0.1:4173")]
    public void Loopback_authority_rejects_names_malformed_values_and_wrong_ports(
        string? authority)
    {
        Assert.False(StaticDocsServer.TryNormalizeLoopbackAuthority(
            authority, 4173, out string origin));
        Assert.Empty(origin);
    }

    private static int ReserveLoopbackPort()
    {
        TcpListener listener = new(IPAddress.Loopback, 0);
        listener.Start();
        try
        {
            return ((IPEndPoint)listener.LocalEndpoint).Port;
        }
        finally
        {
            listener.Stop();
        }
    }

    private static async Task WaitForProbeAsync(
        Uri mount, Task server, CancellationToken cancellationToken)
    {
        Exception? lastError = null;
        try
        {
            while (true)
            {
                if (server.IsCompleted)
                    await server;
                try
                {
                    if (await StaticDocsServer.ProbeAsync(mount, cancellationToken))
                        return;
                }
                catch (HttpRequestException exception)
                {
                    lastError = exception;
                }
                await Task.Delay(TimeSpan.FromMilliseconds(25), cancellationToken);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw new InvalidOperationException("preview server did not become ready", lastError);
        }
    }

    private static async Task<string> SendRawRequestAsync(
        int port, string target, CancellationToken cancellationToken)
    {
        using TcpClient client = new();
        await client.ConnectAsync(IPAddress.Loopback, port, cancellationToken);
        await using NetworkStream stream = client.GetStream();
        byte[] request = Encoding.ASCII.GetBytes(
            $"GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
        await stream.WriteAsync(request, cancellationToken);
        using StreamReader reader = new(stream, Encoding.ASCII);
        return await reader.ReadLineAsync(cancellationToken) ?? "";
    }

    private static async Task AssertNotServedOnNonLoopbackAsync(
        int port, CancellationToken cancellationToken)
    {
        IPAddress? address;
        try
        {
            address = Dns.GetHostAddresses(Dns.GetHostName())
                .FirstOrDefault(candidate => candidate.AddressFamily == AddressFamily.InterNetwork
                                             && !IPAddress.IsLoopback(candidate));
        }
        catch (SocketException)
        {
            return;
        }
        if (address is null)
            return;

        using SocketsHttpHandler handler = new() { UseProxy = false };
        using HttpClient client = new(handler) { Timeout = TimeSpan.FromSeconds(1) };
        try
        {
            using HttpResponseMessage response = await client.GetAsync(
                new UriBuilder(Uri.UriSchemeHttp, address.ToString(), port).Uri,
                cancellationToken);
            Assert.NotEqual(HttpStatusCode.OK, response.StatusCode);
        }
        catch (HttpRequestException)
        {
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
        }
    }
}
