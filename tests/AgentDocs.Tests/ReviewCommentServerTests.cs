using System.Net;
using System.Net.Sockets;
using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentDocs.Tests;

public sealed class ReviewCommentServerTests
{
    private const string Endpoint = "/__agent-docs/review/comments";

    [Fact]
    public async Task Mounted_review_api_persists_filters_replies_and_resolves_comments()
    {
        using TempRepository repo = BuildRepository();
        string dataPath = Path.Combine(repo.Root, ".agent-docs", "review-comments.json");
        await using ServerSession server = await ServerSession.StartAsync(repo);

        using (HttpResponseMessage empty = await server.GetAsync(server.Api))
        {
            Assert.Equal(HttpStatusCode.OK, empty.StatusCode);
            Assert.Equal("no-store", empty.Headers.CacheControl?.ToString());
            using JsonDocument json = await ReadJsonAsync(empty);
            Assert.Equal(1, json.RootElement.GetProperty("schemaVersion").GetInt32());
            Assert.Empty(json.RootElement.GetProperty("comments").EnumerateArray());
        }
        Assert.False(File.Exists(dataPath));
        Assert.False(Directory.Exists(Path.GetDirectoryName(dataPath)));

        using HttpResponseMessage created = await SendJsonAsync(
            server, HttpMethod.Post, server.Api,
            """
            {"route":"/authoring/extensions","anchor":"local-review","quote":"Selected text","body":"Please clarify this."}
            """);
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        using JsonDocument createdJson = await ReadJsonAsync(created);
        JsonElement comment = createdJson.RootElement.GetProperty("comment");
        string id = comment.GetProperty("id").GetString()!;
        Assert.Matches("^rc_[0-9a-f]{32}$", id);
        Assert.Equal("open", comment.GetProperty("status").GetString());
        Assert.Equal(comment.GetProperty("createdAt").GetString(),
                     comment.GetProperty("updatedAt").GetString());
        Assert.Matches(
            "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{7}Z$",
            comment.GetProperty("createdAt").GetString()!);
        Assert.True(File.Exists(dataPath));
        Assert.False(File.Exists(Path.Combine(repo.Output, ".agent-docs", "review-comments.json")));

        Uri filteredUri = new(server.Api.AbsoluteUri + "?route=%2Fauthoring%2Fextensions");
        using (HttpResponseMessage filtered = await server.GetAsync(filteredUri))
        {
            Assert.Equal(HttpStatusCode.OK, filtered.StatusCode);
            using JsonDocument json = await ReadJsonAsync(filtered);
            Assert.Single(json.RootElement.GetProperty("comments").EnumerateArray());
        }
        using (HttpResponseMessage other = await server.GetAsync(
                   new Uri(server.Api.AbsoluteUri + "?route=%2Fother")))
        {
            using JsonDocument json = await ReadJsonAsync(other);
            Assert.Empty(json.RootElement.GetProperty("comments").EnumerateArray());
        }

        Uri item = new(server.Api.AbsoluteUri + "/" + id);
        using (HttpResponseMessage prematureResolve = await SendJsonAsync(
                   server, HttpMethod.Patch, item, "{\"status\":\"resolved\"}"))
        {
            Assert.Equal(HttpStatusCode.BadRequest, prematureResolve.StatusCode);
        }
        using HttpResponseMessage answered = await SendJsonAsync(
            server, HttpMethod.Patch, item, "{\"reply\":\"Use the local review workflow.\"}");
        Assert.Equal(HttpStatusCode.OK, answered.StatusCode);
        using (JsonDocument json = await ReadJsonAsync(answered))
        {
            Assert.Equal("answered",
                json.RootElement.GetProperty("comment").GetProperty("status").GetString());
        }

        using HttpResponseMessage resolved = await SendJsonAsync(
            server, HttpMethod.Patch, item, "{\"status\":\"resolved\"}");
        Assert.Equal(HttpStatusCode.OK, resolved.StatusCode);
        using (JsonDocument json = await ReadJsonAsync(resolved))
        {
            JsonElement updated = json.RootElement.GetProperty("comment");
            Assert.Equal("resolved", updated.GetProperty("status").GetString());
            Assert.Equal("Use the local review workflow.",
                         updated.GetProperty("reply").GetString());
        }

        using (HttpResponseMessage replyWhileResolved = await SendJsonAsync(
                   server, HttpMethod.Patch, item, "{\"reply\":\"Changed reply\"}"))
        {
            Assert.Equal(HttpStatusCode.BadRequest, replyWhileResolved.StatusCode);
        }
        using (HttpResponseMessage reopened = await SendJsonAsync(
                   server, HttpMethod.Patch, item, "{\"status\":\"open\"}"))
        using (JsonDocument json = await ReadJsonAsync(reopened))
        {
            JsonElement updated = json.RootElement.GetProperty("comment");
            Assert.Equal("open", updated.GetProperty("status").GetString());
            Assert.Equal("Use the local review workflow.",
                         updated.GetProperty("reply").GetString());
        }
        using (HttpResponseMessage cleared = await SendJsonAsync(
                   server, HttpMethod.Patch, item, "{\"reply\":null}"))
        using (JsonDocument json = await ReadJsonAsync(cleared))
        {
            JsonElement updated = json.RootElement.GetProperty("comment");
            Assert.Equal("open", updated.GetProperty("status").GetString());
            Assert.False(updated.TryGetProperty("reply", out _));
        }

        using JsonDocument stored = JsonDocument.Parse(File.ReadAllText(dataPath));
        Assert.Equal(1, stored.RootElement.GetProperty("schemaVersion").GetInt32());
        Assert.Single(stored.RootElement.GetProperty("comments").EnumerateArray());
        Assert.DoesNotContain('\r', File.ReadAllText(dataPath));
        Assert.Empty(Directory.GetFiles(Path.GetDirectoryName(dataPath)!, "*.tmp"));
        Assert.Equal("agent-docs-review-lock-v1\n", File.ReadAllText(
            Path.Combine(Path.GetDirectoryName(dataPath)!, ".review-comments.json.lock")));
    }

    [Fact]
    public async Task Review_writes_reject_cross_origin_non_json_oversize_and_non_strict_input()
    {
        using TempRepository repo = BuildRepository();
        await using ServerSession server = await ServerSession.StartAsync(repo);

        using HttpRequestMessage plainRequest = new(HttpMethod.Post, server.Api)
        {
            Content = new StringContent("{}", Encoding.UTF8, "text/plain"),
        };
        using HttpResponseMessage plain = await server.SendAsync(plainRequest);
        Assert.Equal(HttpStatusCode.UnsupportedMediaType, plain.StatusCode);

        using HttpRequestMessage crossOriginRequest = JsonRequest(
            HttpMethod.Post, server.Api,
            "{\"route\":\"/\",\"body\":\"Comment\"}");
        crossOriginRequest.Headers.TryAddWithoutValidation("Origin", "https://example.test");
        using HttpResponseMessage crossOrigin = await server.SendAsync(crossOriginRequest);
        Assert.Equal(HttpStatusCode.Forbidden, crossOrigin.StatusCode);

        using HttpRequestMessage crossSiteRequest = JsonRequest(
            HttpMethod.Post, server.Api,
            "{\"route\":\"/\",\"body\":\"Comment\"}");
        crossSiteRequest.Headers.TryAddWithoutValidation("Sec-Fetch-Site", "cross-site");
        using HttpResponseMessage crossSite = await server.SendAsync(crossSiteRequest);
        Assert.Equal(HttpStatusCode.Forbidden, crossSite.StatusCode);

        using HttpRequestMessage optionsRequest = new(HttpMethod.Options, server.Api);
        using HttpResponseMessage options = await server.SendAsync(optionsRequest);
        Assert.Equal(HttpStatusCode.MethodNotAllowed, options.StatusCode);
        Assert.False(options.Headers.Contains("Access-Control-Allow-Origin"));

        using HttpResponseMessage unknown = await SendJsonAsync(
            server, HttpMethod.Post, server.Api,
            "{\"route\":\"/\",\"body\":\"Comment\",\"id\":\"client-owned\"}");
        Assert.Equal(HttpStatusCode.BadRequest, unknown.StatusCode);

        using HttpResponseMessage duplicate = await SendJsonAsync(
            server, HttpMethod.Post, server.Api,
            "{\"route\":\"/\",\"body\":\"One\",\"body\":\"Two\"}");
        Assert.Equal(HttpStatusCode.BadRequest, duplicate.StatusCode);

        using HttpResponseMessage badRoute = await SendJsonAsync(
            server, HttpMethod.Post, server.Api,
            "{\"route\":\"/one//two\",\"body\":\"Comment\"}");
        Assert.Equal(HttpStatusCode.BadRequest, badRoute.StatusCode);

        string oversizedBody = new('x', ReviewCommentStore.MaximumRequestBytes + 1);
        using HttpResponseMessage oversized = await SendJsonAsync(
            server, HttpMethod.Post, server.Api,
            JsonSerializer.Serialize(new { route = "/", body = oversizedBody }));
        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, oversized.StatusCode);
        Assert.Equal("no-store", oversized.Headers.CacheControl?.ToString());

        using HttpResponseMessage missing = await SendJsonAsync(
            server, HttpMethod.Patch,
            new Uri(server.Api.AbsoluteUri + "/rc_00000000000000000000000000000000"),
            "{\"status\":\"resolved\"}");
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
    }

    [Fact]
    public async Task Invalid_or_oversize_stored_data_is_not_returned_or_overwritten()
    {
        using TempRepository repo = BuildRepository();
        string dataPath = repo.Write(
            ".agent-docs/review-comments.json",
            "{\"schemaVersion\":1,\"comments\":[],\"unknown\":true}\n");
        await using ServerSession server = await ServerSession.StartAsync(repo);

        using (HttpResponseMessage invalid = await server.GetAsync(server.Api))
        {
            Assert.Equal(HttpStatusCode.InternalServerError, invalid.StatusCode);
            Assert.Equal("no-store", invalid.Headers.CacheControl?.ToString());
        }
        Assert.Contains("\"unknown\":true", File.ReadAllText(dataPath),
                        StringComparison.Ordinal);

        File.WriteAllText(dataPath, new string(' ', ReviewCommentStore.MaximumFileBytes + 1));
        using HttpResponseMessage oversized = await server.GetAsync(server.Api);
        Assert.Equal(HttpStatusCode.InternalServerError, oversized.StatusCode);
        Assert.Equal(ReviewCommentStore.MaximumFileBytes + 1, new FileInfo(dataPath).Length);
    }

    [Fact]
    public async Task Static_preview_mode_does_not_enable_or_create_review_data()
    {
        using TempRepository repo = BuildRepository();
        await using ServerSession server = await ServerSession.StartAsync(
            repo, enableReview: false);

        using HttpResponseMessage response = await server.GetAsync(server.Api);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.False(File.Exists(Path.Combine(
            repo.Root, ".agent-docs", "review-comments.json")));
        Assert.DoesNotContain(
            Directory.EnumerateFiles(repo.Output, "*", SearchOption.AllDirectories),
            path => path.Contains("review-comments", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task Direct_store_serializes_concurrent_creates_atomically()
    {
        using TempRepository repo = BuildRepository();
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);

        ReviewComment[] created = await Task.WhenAll(
            Enumerable.Range(0, 24).Select(index =>
                store.CreateAsync("/guide", null, null, "Comment " + index)));

        Assert.Equal(created.Length, created.Select(comment => comment.Id).Distinct().Count());
        ReviewCommentData data = await store.GetAsync(null);
        Assert.Equal(24, data.Comments.Count);
        string directory = Path.Combine(repo.Root, ".agent-docs");
        Assert.Empty(Directory.GetFiles(directory, "*.tmp"));
    }

    [Fact]
    public async Task Patch_timestamp_never_moves_before_future_created_or_previous_update()
    {
        using TempRepository repo = BuildRepository();
        const string id = "rc_00000000000000000000000000000001";
        const string createdAt = "2099-01-01T00:00:00.0000000Z";
        const string updatedAt = "2099-01-02T00:00:00.0000000Z";
        repo.Write(".agent-docs/review-comments.json",
            $$"""
            {"schemaVersion":1,"comments":[{"id":"{{id}}","route":"/","body":"Future comment","status":"open","createdAt":"{{createdAt}}","updatedAt":"{{updatedAt}}"}]}
            """);
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);

        ReviewComment patched = await store.PatchAsync(
            id, hasReply: true, "Handled safely.", hasStatus: false, status: null);

        Assert.Equal(updatedAt, patched.UpdatedAt);
        ReviewComment persisted = Assert.Single((await store.GetAsync(null)).Comments);
        Assert.Equal(updatedAt, persisted.UpdatedAt);
        Assert.Equal(ReviewStatus.Answered, persisted.Status);
    }

    [Fact]
    public async Task Persistent_lock_reuses_exact_header_and_invalid_header_releases_lock()
    {
        using TempRepository repo = BuildRepository();
        ReviewCommentStore first = ReviewCommentStore.Create(repo.Root, null, repo.Output);
        await first.CreateAsync("/", null, null, "First");
        string lockPath = Path.Combine(
            repo.Root, ".agent-docs", ".review-comments.json.lock");
        Assert.Equal("agent-docs-review-lock-v1\n", File.ReadAllText(lockPath));

        ReviewCommentStore second = ReviewCommentStore.Create(repo.Root, null, repo.Output);
        await second.CreateAsync("/", null, null, "Second");
        byte[] before = File.ReadAllBytes(Path.Combine(
            repo.Root, ".agent-docs", "review-comments.json"));
        File.WriteAllText(lockPath, "invalid-lock\n");

        await Assert.ThrowsAsync<InvalidDataException>(() =>
            second.CreateAsync("/", null, null, "Rejected"));
        Assert.Equal(before, File.ReadAllBytes(Path.Combine(
            repo.Root, ".agent-docs", "review-comments.json")));

        File.WriteAllText(lockPath, "agent-docs-review-lock-v1\n");
        await first.CreateAsync("/", null, null, "After release");
        Assert.Equal(3, (await first.GetAsync(null)).Comments.Count);
    }

    [Fact]
    public async Task Empty_persistent_lock_is_initialized_only_after_acquisition()
    {
        using TempRepository repo = BuildRepository();
        string lockPath = repo.Write(".agent-docs/.review-comments.json.lock", "");
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);

        await store.CreateAsync("/", null, null, "Comment");

        Assert.Equal("agent-docs-review-lock-v1\n", File.ReadAllText(lockPath));
    }

    [Fact]
    public async Task Python_skill_lock_blocks_server_mutation_without_changing_store()
    {
        using TempRepository repo = BuildRepository();
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);
        ReviewComment comment = await store.CreateAsync("/", null, null, "Comment");
        string dataPath = Path.Combine(repo.Root, ".agent-docs", "review-comments.json");
        byte[] before = File.ReadAllBytes(dataPath);
        string scriptDirectory = Path.Combine(FindRepositoryRoot(),
            "_agents", "skills", "docs-authoring", "scripts");
        const string holdScript =
            "import sys,time;sys.path.insert(0,sys.argv[2]);import review_comments as r;" +
            "repo,path=r.resolve_review_data(sys.argv[1],r.DEFAULT_REVIEW_DATA);" +
            "lock=r.acquire_review_data_lock(repo,path);print('locked',flush=True);" +
            "time.sleep(15)";
        using Process process = new()
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = "python",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            },
        };
        process.StartInfo.ArgumentList.Add("-B");
        process.StartInfo.ArgumentList.Add("-c");
        process.StartInfo.ArgumentList.Add(holdScript);
        process.StartInfo.ArgumentList.Add(repo.Root);
        process.StartInfo.ArgumentList.Add(scriptDirectory);
        bool started = false;
        try
        {
            try
            {
                process.Start();
                started = true;
            }
            catch (Win32Exception exception)
            {
                Assert.Skip("python is unavailable: " + exception.Message);
            }
            string? ready = await process.StandardOutput.ReadLineAsync(
                TestContext.Current.CancellationToken);
            Assert.Equal("locked", ready);

            ReviewApiException error = await Assert.ThrowsAsync<ReviewApiException>(() =>
                store.PatchAsync(comment.Id, hasReply: true, "Blocked",
                                 hasStatus: false, status: null));

            Assert.Equal((int)HttpStatusCode.Conflict, error.StatusCode);
            Assert.Equal(before, File.ReadAllBytes(dataPath));
        }
        finally
        {
            if (started && !process.HasExited)
                process.Kill(entireProcessTree: true);
            if (started)
                await process.WaitForExitAsync(TestContext.Current.CancellationToken);
        }
    }

    [Fact]
    public async Task Unix_store_and_lock_modes_are_private_and_existing_mode_is_preserved()
    {
        if (OperatingSystem.IsWindows())
        {
            Assert.Skip("Unix file modes are unavailable on Windows");
            return;
        }
        using TempRepository repo = BuildRepository();
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);
        ReviewComment comment = await store.CreateAsync("/", null, null, "Comment");
        string dataPath = Path.Combine(repo.Root, ".agent-docs", "review-comments.json");
        string lockPath = Path.Combine(repo.Root, ".agent-docs", ".review-comments.json.lock");
        UnixFileMode privateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        Assert.Equal(privateMode, File.GetUnixFileMode(dataPath));
        Assert.Equal(privateMode, File.GetUnixFileMode(lockPath));
        UnixFileMode existingMode = privateMode | UnixFileMode.GroupRead;
        File.SetUnixFileMode(dataPath, existingMode);

        await store.PatchAsync(comment.Id, hasReply: true, "Done",
                               hasStatus: false, status: null);

        Assert.Equal(existingMode, File.GetUnixFileMode(dataPath));
    }

    [Fact]
    public async Task Review_text_limits_count_utf16_code_units_like_browser_maxlength()
    {
        using TempRepository repo = BuildRepository();
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);
        string overLimit = string.Concat(Enumerable.Repeat("😀", 4001));
        Assert.Equal(8002, overLimit.Length);

        ReviewApiException error = await Assert.ThrowsAsync<ReviewApiException>(() =>
            store.CreateAsync("/", null, null, overLimit));

        Assert.Equal((int)HttpStatusCode.BadRequest, error.StatusCode);
        Assert.False(File.Exists(Path.Combine(
            repo.Root, ".agent-docs", "review-comments.json")));
    }

    [Theory]
    [InlineData("/one//two")]
    [InlineData("/.")]
    [InlineData("/../two")]
    [InlineData("/one/./two")]
    [InlineData("/trailing/")]
    [InlineData("/white space")]
    public async Task Review_routes_require_a_normalized_absolute_path(string route)
    {
        using TempRepository repo = BuildRepository();
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);

        await Assert.ThrowsAsync<ReviewApiException>(() =>
            store.CreateAsync(route, null, null, "Comment"));
    }

    [Theory]
    [InlineData("two words")]
    [InlineData("#heading")]
    [InlineData(" heading")]
    public async Task Review_anchors_reject_whitespace_and_fragment_markers(string anchor)
    {
        using TempRepository repo = BuildRepository();
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);

        await Assert.ThrowsAsync<ReviewApiException>(() =>
            store.CreateAsync("/", anchor, null, "Comment"));
    }

    [Fact]
    public async Task Review_store_enforces_the_one_thousand_comment_limit()
    {
        using TempRepository repo = BuildRepository();
        const string timestamp = "2026-08-24T00:00:00.0000000Z";
        object[] comments = Enumerable.Range(0, ReviewCommentStore.MaximumComments)
            .Select(index => (object)new
            {
                id = "rc_" + index.ToString("x32"),
                route = "/",
                body = "Comment " + index,
                status = "open",
                createdAt = timestamp,
                updatedAt = timestamp,
            }).ToArray();
        repo.Write(".agent-docs/review-comments.json",
            JsonSerializer.Serialize(new { schemaVersion = 1, comments }) + "\n");
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);

        ReviewApiException error = await Assert.ThrowsAsync<ReviewApiException>(() =>
            store.CreateAsync("/", null, null, "One too many"));

        Assert.Equal((int)HttpStatusCode.Conflict, error.StatusCode);
        Assert.Equal(ReviewCommentStore.MaximumComments,
                     (await store.GetAsync(null)).Comments.Count);
    }

    [Theory]
    [InlineData("{\"schemaVersion\":1,\"comments\":[],\"extra\":true}")]
    [InlineData("{\"schemaVersion\":1,\"schemaVersion\":1,\"comments\":[]}")]
    [InlineData("{\"schemaVersion\":1,\"comments\":[{\"id\":\"rc_00000000000000000000000000000000\",\"route\":\"/\",\"body\":\"Comment\",\"status\":\"open\",\"reply\":null,\"createdAt\":\"2026-08-24T00:00:00.0000000Z\",\"updatedAt\":\"2026-08-24T00:00:00.0000000Z\"}]}")]
    [InlineData("{\"schemaVersion\":1,\"comments\":[{\"id\":\"rc_00000000000000000000000000000000\",\"route\":\"/\",\"body\":\"Comment\",\"status\":\"answered\",\"createdAt\":\"2026-08-24T00:00:00.0000000Z\",\"updatedAt\":\"2026-08-24T00:00:00.0000000Z\"}]}")]
    [InlineData("{\"schemaVersion\":1,\"comments\":[{\"id\":\"rc_00000000000000000000000000000000\",\"route\":\"/\",\"body\":\"Comment\",\"status\":\"resolved\",\"createdAt\":\"2026-08-24T00:00:00.0000000Z\",\"updatedAt\":\"2026-08-24T00:00:00.0000000Z\"}]}")]
    public async Task Review_store_rejects_non_strict_persisted_documents(string json)
    {
        using TempRepository repo = BuildRepository();
        repo.Write(".agent-docs/review-comments.json", json + "\n");
        ReviewCommentStore store = ReviewCommentStore.Create(repo.Root, null, repo.Output);

        await Assert.ThrowsAsync<InvalidDataException>(() => store.GetAsync(null));
    }

    [Fact]
    public void Review_data_path_must_be_a_file_under_reserved_local_state()
    {
        using TempRepository repo = new();
        string inside = StaticDocsServer.ResolveReviewDataPath(
            repo.Root, ".agent-docs/private/comments.json", repo.Output);
        Assert.Equal(Path.Combine(repo.Root, ".agent-docs", "private", "comments.json"),
                     inside);

        Assert.Throws<InvalidDataException>(() => StaticDocsServer.ResolveReviewDataPath(
            repo.Root, repo.Root, repo.Output));
        Assert.Throws<InvalidDataException>(() => StaticDocsServer.ResolveReviewDataPath(
            repo.Root, ".agent-docs", repo.Output));
        Assert.Throws<InvalidDataException>(() => StaticDocsServer.ResolveReviewDataPath(
            repo.Root, "private/comments.json", repo.Output));
        Assert.Throws<InvalidDataException>(() => StaticDocsServer.ResolveReviewDataPath(
            repo.Root, " ", repo.Output));
        Assert.Throws<InvalidDataException>(() => StaticDocsServer.ResolveReviewDataPath(
            repo.Root, repo.WriteOutside("comments.json", "{}"), repo.Output));
        Assert.Throws<InvalidDataException>(() => StaticDocsServer.ResolveReviewDataPath(
            repo.Root, "build/comments.json", Path.Combine(repo.Root, "build")));
    }

    [Fact]
    public void Review_data_rejects_any_sentinel_owned_output_ancestor()
    {
        using TempRepository repo = new();
        repo.Write(".agent-docs/.agent-docs-output", OutputDirectory.SentinelValue);

        Assert.Throws<InvalidDataException>(() => StaticDocsServer.ResolveReviewDataPath(
            repo.Root, ".agent-docs/team-review.json", repo.Output));
    }

    [Fact]
    public void Reserved_local_state_is_excluded_from_source_publication()
    {
        using TempRepository repo = new();
        repo.Write("source/visible.cs", "public sealed class Visible {}\n");
        repo.Write("source/.agent-docs/private.cs", "REVIEW_DATA_MUST_NOT_RENDER\n");
        repo.WriteConfiguration(enableSnippets: true, publishCode: true,
            sourceTrees: ["source"], sourceExtensions: [".cs"]);

        string dataPath = StaticDocsServer.ResolveReviewDataPath(
            repo.Root, null, repo.Output, repo.ConfigPath);
        AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);

        Assert.Equal(Path.Combine(repo.Root, ".agent-docs", "review-comments.json"),
                     dataPath);
        Assert.DoesNotContain(Directory.EnumerateFiles(
                repo.Output, "*", SearchOption.AllDirectories),
            file => File.ReadAllText(file).Contains(
                "REVIEW_DATA_MUST_NOT_RENDER", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Review_enabled_public_server_rejects_workflow_local_state_input()
    {
        using TempRepository repo = BuildRepository();
        repo.Write(".agent-docs/workflow.md", "# Local state\n");
        repo.Write("workflow.json",
            "{\"version\":1,\"label\":\"Workflow\",\"pages\":[{\"source\":\".agent-docs/workflow.md\",\"route\":\"local\",\"title\":\"Local\"}]}\n");
        repo.WriteConfiguration(config => config["agentWorkflows"] = new JsonObject
        {
            ["enabled"] = true,
            ["spaceId"] = "",
            ["manifest"] = "workflow.json",
            ["routePrefix"] = "agent-workflows",
        });

        await Assert.ThrowsAsync<InvalidDataException>(() => StaticDocsServer.RunAsync(
            repo.Output, 4173, "/", repo.Root, null, repo.ConfigPath,
            CancellationToken.None));
    }

    [Theory]
    [InlineData("docsDir")]
    [InlineData("sourceRoot")]
    public void Configuration_cannot_select_reserved_local_state_for_publication(string field)
    {
        using TempRepository repo = new();
        repo.Write(".agent-docs/docs/_index.md", "# Private\n");
        repo.Write(".agent-docs/source/file.cs", "private\n");
        repo.WriteConfiguration(config =>
        {
            JsonObject space = TempRepository.OnlySpace(config);
            if (field == "docsDir")
                space["docsDir"] = ".agent-docs/docs";
            else
            {
                space["sourceRoot"] = ".agent-docs";
                space["enableSnippets"] = true;
                space["sourceTrees"] = new JsonArray("source");
                space["sourceExtensions"] = new JsonArray(".cs");
            }
        });

        Assert.Throws<InvalidDataException>(() =>
            ConfigurationLoader.Load(repo.Root, repo.ConfigPath));
    }

    [Theory]
    [InlineData(".agent-docs")]
    [InlineData(".AGENT-DOCS")]
    [InlineData(".Agent-Docs")]
    public void Reserved_local_state_matching_is_case_insensitive_on_every_platform(
        string spelling)
    {
        using TempRepository repo = new();
        string candidate = Path.Combine(repo.Root, spelling, "review-comments.json");

        Assert.True(PathSafety.ContainsAgentDocsDirectory(candidate, repo.Root));
        Assert.True(SourcePolicy.ContainsGeneratedDirectory(
            spelling + "/review-comments.json"));
    }

    [Fact]
    public void Review_data_path_rejects_a_reparse_directory()
    {
        using TempRepository repo = new();
        string outside = Path.Combine(repo.Workspace, "outside-review");
        Directory.CreateDirectory(Path.Combine(repo.Root, ".agent-docs"));
        string linked = Path.Combine(repo.Root, ".agent-docs", "linked-review");
        Directory.CreateDirectory(outside);
        try
        {
            Directory.CreateSymbolicLink(linked, outside);
        }
        catch (Exception exception) when (exception is UnauthorizedAccessException
                                          or IOException or PlatformNotSupportedException)
        {
            Assert.Skip($"directory links unavailable: {exception.GetType().Name}");
        }

        InvalidDataException error = Assert.Throws<InvalidDataException>(() =>
            StaticDocsServer.ResolveReviewDataPath(
                repo.Root, ".agent-docs/linked-review/comments.json", repo.Output));
        Assert.Contains("symbolic link or reparse point", error.Message,
                        StringComparison.Ordinal);
    }

    private static TempRepository BuildRepository()
    {
        TempRepository repo = new();
        repo.WriteConfiguration();
        AgentDocsBuilder.Build(repo.Root, repo.ConfigPath, repo.Output);
        return repo;
    }

    private static string FindRepositoryRoot()
    {
        DirectoryInfo? current = new(AppContext.BaseDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "AgentDocs.slnx")))
                return current.FullName;
            current = current.Parent;
        }
        throw new InvalidOperationException("cannot locate the Agent Docs repository root");
    }

    private static HttpRequestMessage JsonRequest(HttpMethod method, Uri uri, string json) =>
        new(method, uri)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        };

    private static async Task<HttpResponseMessage> SendJsonAsync(
        ServerSession server, HttpMethod method, Uri uri, string json)
    {
        using HttpRequestMessage request = JsonRequest(method, uri, json);
        request.Headers.TryAddWithoutValidation("Origin", server.Origin);
        return await server.SendAsync(request);
    }

    private static async Task<JsonDocument> ReadJsonAsync(HttpResponseMessage response) =>
        JsonDocument.Parse(await response.Content.ReadAsStringAsync(
            TestContext.Current.CancellationToken));

    private sealed class ServerSession : IAsyncDisposable
    {
        private readonly CancellationTokenSource cancellation;
        private readonly Task server;

        private ServerSession(
            HttpClient client, Uri api, string origin,
            CancellationTokenSource cancellation, Task server)
        {
            Client = client;
            Api = api;
            Origin = origin;
            this.cancellation = cancellation;
            this.server = server;
        }

        internal HttpClient Client { get; }
        internal Uri Api { get; }
        internal string Origin { get; }

        internal Task<HttpResponseMessage> GetAsync(Uri uri) =>
            Client.GetAsync(uri, TestContext.Current.CancellationToken);

        internal Task<HttpResponseMessage> SendAsync(HttpRequestMessage request) =>
            Client.SendAsync(request, TestContext.Current.CancellationToken);

        internal static async Task<ServerSession> StartAsync(
            TempRepository repo, bool enableReview = true)
        {
            int port = ReserveLoopbackPort();
            string origin = $"http://127.0.0.1:{port}";
            Uri mount = new(origin + "/preview");
            CancellationTokenSource cancellation = new();
            Task server = enableReview
                ? StaticDocsServer.RunAsync(
                    repo.Output, port, "/preview", repo.Root, null, repo.ConfigPath,
                    cancellation.Token)
                : StaticDocsServer.RunAsync(
                    repo.Output, port, "/preview", cancellation.Token);
            using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(15));
            Exception? lastError = null;
            while (true)
            {
                if (server.IsCompleted)
                    await server;
                try
                {
                    if (await StaticDocsServer.ProbeAsync(mount, timeout.Token))
                        break;
                }
                catch (HttpRequestException exception)
                {
                    lastError = exception;
                }
                try
                {
                    await Task.Delay(TimeSpan.FromMilliseconds(25), timeout.Token);
                }
                catch (OperationCanceledException)
                {
                    cancellation.Cancel();
                    throw new InvalidOperationException("review server did not become ready", lastError);
                }
            }
            SocketsHttpHandler handler = new() { UseProxy = false };
            HttpClient client = new(handler);
            return new ServerSession(
                client, new Uri(mount.AbsoluteUri + Endpoint), origin, cancellation, server);
        }

        public async ValueTask DisposeAsync()
        {
            Client.Dispose();
            cancellation.Cancel();
            try
            {
                await server.WaitAsync(TimeSpan.FromSeconds(5));
            }
            finally
            {
                cancellation.Dispose();
            }
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
    }
}
