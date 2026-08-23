using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentDocs.Tests;

public sealed class ConfigurationLoaderTests
{
    [Fact]
    public void Load_accepts_a_minimal_repository_configuration()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration();

        ResolvedConfiguration resolved = ConfigurationLoader.Load(repo.Root, repo.ConfigPath);

        Assert.Equal("Fixture Docs", resolved.Title);
        Assert.Null(resolved.SiteUrl);
        ResolvedSpace space = Assert.Single(resolved.Spaces);
        Assert.Equal("Guide", space.Label);
        Assert.Equal(Path.Combine(repo.Root, "docs"), space.DocsDirAbsolute);
        Assert.Equal(repo.Root, space.SourceRootAbsolute);
        Assert.False(space.EnableSnippets);
        Assert.False(space.PublishCode);
    }

    [Fact]
    public void Load_rejects_an_unknown_root_field()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config => config["unexpected"] = true);

        JsonException error = Assert.Throws<JsonException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("unexpected", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Load_rejects_an_unknown_space_field()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config =>
            TempRepository.OnlySpace(config)["extraPermission"] = true);

        JsonException error = Assert.Throws<JsonException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("extraPermission", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Load_rejects_a_space_that_omits_its_required_id()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config =>
            TempRepository.OnlySpace(config).Remove("id"));

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("explicit id", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("a--b")]
    [InlineData("a---b")]
    public void Load_rejects_space_ids_with_empty_hyphenated_parts(string id)
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config =>
            TempRepository.OnlySpace(config)["id"] = id);

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("space id is invalid", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Load_treats_property_names_as_case_sensitive()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config =>
        {
            config.Remove("schemaVersion");
            config["SchemaVersion"] = 1;
        });

        JsonException error = Assert.Throws<JsonException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("SchemaVersion", error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("../docs")]
    [InlineData("docs/../docs")]
    [InlineData("docs\\section")]
    [InlineData("/docs")]
    [InlineData("C:/docs")]
    [InlineData("docs/")]
    [InlineData(" docs")]
    [InlineData("CON")]
    [InlineData("aux.txt")]
    [InlineData("folder/LPT1.log")]
    [InlineData("trailing.")]
    public void Load_rejects_nonportable_documentation_paths(string configured)
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config =>
            TempRepository.OnlySpace(config)["docsDir"] = configured);

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("normalized repository-relative path", error.Message,
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("../source")]
    [InlineData("source/../allowed")]
    [InlineData("source\\allowed")]
    [InlineData("source//allowed")]
    [InlineData("source/")]
    [InlineData(".")]
    public void Load_rejects_nonportable_source_tree_entries(string configured)
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: [configured],
            sourceExtensions: [".cs"]);

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("sourceTrees", error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("build")]
    [InlineData("bin")]
    [InlineData("obj")]
    [InlineData("node_modules")]
    [InlineData(".git")]
    [InlineData("examples/obj/generated")]
    public void Load_rejects_generated_source_tree_entries(string configured)
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(
            enableSnippets: true,
            sourceTrees: [configured],
            sourceExtensions: [".cs"]);

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("cannot publish", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Load_requires_complete_source_allowlists_for_snippets()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(enableSnippets: true);

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("requires sourceTrees and sourceExtensions", error.Message,
            StringComparison.Ordinal);
    }

    [Fact]
    public void Load_rejects_a_configuration_outside_the_repository()
    {
        using TempRepository repo = new();
        string valid = repo.WriteConfiguration();
        string outside = repo.WriteOutside("outside.json", File.ReadAllText(valid));

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, outside));

        Assert.Contains("inside the repository root", error.Message,
            StringComparison.Ordinal);
    }

    [Fact]
    public void Load_rejects_root_files_when_source_browsing_is_disabled()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config =>
            TempRepository.OnlySpace(config)["browsableRootFiles"] =
                new JsonArray("README.md"));

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("browsableRootFiles requires publishCode", error.Message,
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(".hidden")]
    [InlineData("-notes.md")]
    public void Load_rejects_nonportable_browsable_root_filenames(string filename)
    {
        using TempRepository repo = new();
        repo.Write("examples/Allowed.cs", "internal static class Allowed;\n");
        repo.WriteConfiguration(
            config => TempRepository.OnlySpace(config)["browsableRootFiles"] =
                new JsonArray(filename),
            publishCode: true,
            sourceTrees: ["examples"],
            sourceExtensions: [".cs"]);

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("invalid or duplicate browsable root file", error.Message,
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("a")]
    [InlineData("a-b")]
    [InlineData("one/two-three")]
    public void Load_accepts_normalized_workflow_route_prefixes(string routePrefix)
    {
        using TempRepository repo = new();
        repo.Write("workflow.json", "{}\n");
        repo.WriteConfiguration(config => config["agentWorkflows"] = Workflow(
            enabled: true, routePrefix));

        ResolvedConfiguration resolved = ConfigurationLoader.Load(repo.Root, repo.ConfigPath);

        Assert.Equal(routePrefix, resolved.AgentWorkflows!.RoutePrefix);
    }

    [Theory]
    [InlineData("ab-")]
    [InlineData("-ab")]
    [InlineData("one//two")]
    [InlineData("one/two-")]
    public void Load_rejects_malformed_workflow_route_prefixes(string routePrefix)
    {
        using TempRepository repo = new();
        repo.Write("workflow.json", "{}\n");
        repo.WriteConfiguration(config => config["agentWorkflows"] = Workflow(
            enabled: true, routePrefix));

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("routePrefix is invalid", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Load_rejects_publication_fields_on_a_disabled_workflow_projection()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config => config["agentWorkflows"] = new JsonObject
        {
            ["enabled"] = false,
            ["routePrefix"] = "agent-workflows",
        });

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("disabled agentWorkflows", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Load_rejects_a_workflow_projection_that_omits_enabled()
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config => config["agentWorkflows"] = new JsonObject());

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.Contains("enabled", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("spaces")]
    [InlineData("spaceElement")]
    [InlineData("sourceTrees")]
    public void Load_rejects_null_for_required_objects_and_collections(string target)
    {
        using TempRepository repo = new();
        repo.WriteConfiguration(config =>
        {
            if (target == "spaces")
                config["spaces"] = null;
            else if (target == "spaceElement")
                config["spaces"] = new JsonArray((JsonNode?)null);
            else
                TempRepository.OnlySpace(config)["sourceTrees"] = null;
        });

        Exception? error = Record.Exception(
            () => ConfigurationLoader.Load(repo.Root, repo.ConfigPath));

        Assert.NotNull(error);
        Assert.True(error is JsonException or InvalidDataException,
            $"Expected a controlled configuration error, received {error.GetType().Name}: {error.Message}");
    }

    private static JsonObject Workflow(bool enabled, string routePrefix) => new()
    {
        ["enabled"] = enabled,
        ["spaceId"] = "",
        ["manifest"] = "workflow.json",
        ["routePrefix"] = routePrefix,
    };
}
