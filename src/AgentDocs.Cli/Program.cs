using AgentDocs;
using System.Net;

return await AgentDocsCli.RunAsync(args);

internal static class AgentDocsCli
{
    internal static async Task<int> RunAsync(string[] arguments)
    {
        try
        {
            string command = arguments.Length > 0 && !arguments[0].StartsWith("--", StringComparison.Ordinal)
                ? arguments[0] : "render";
            int offset = command == "render" && (arguments.Length == 0
                         || arguments[0].StartsWith("--", StringComparison.Ordinal)) ? 0 : 1;
            Options options = Options.Parse(arguments[offset..], command);
            return command switch
            {
                "render" => Render(options),
                "serve" => await ServeAsync(options),
                "probe" => await ProbeAsync(options),
                _ => throw new InvalidDataException($"unknown command: {command}"),
            };
        }
        catch (Exception exception) when (exception is InvalidDataException or IOException
                                          or UnauthorizedAccessException or ArgumentException
                                          or HttpRequestException or HttpListenerException
                                          or OperationCanceledException)
        {
            Console.Error.WriteLine("error: " + exception.Message);
            return 2;
        }
    }

    private static int Render(Options options)
    {
        BuildReport report = AgentDocsBuilder.Build(options.Repository, options.Configuration,
                                                    options.Output);
        PrintReport(report);
        return options.Check && report.Broken > 0 ? 1 : 0;
    }

    private static async Task<int> ServeAsync(Options options)
    {
        if (!options.NoRender)
        {
            BuildReport report = AgentDocsBuilder.Build(options.Repository, options.Configuration,
                                                        options.Output);
            PrintReport(report);
            if (options.Check && report.Broken > 0)
                return 1;
        }
        using CancellationTokenSource stopped = new();
        Console.CancelKeyPress += (_, eventArgs) =>
        {
            eventArgs.Cancel = true;
            stopped.Cancel();
        };
        string mount = StaticDocsServer.NormalizeBasePath(options.BasePath);
        Console.WriteLine($"Serving read-only preview at http://127.0.0.1:{options.Port}{mount}");
        await StaticDocsServer.RunAsync(options.Output, options.Port, mount, stopped.Token);
        return 0;
    }

    private static async Task<int> ProbeAsync(Options options)
    {
        string mount = StaticDocsServer.NormalizeBasePath(options.BasePath);
        Uri target = new($"http://127.0.0.1:{options.Port}{mount}");
        bool healthy = await StaticDocsServer.ProbeAsync(target, CancellationToken.None);
        Console.WriteLine(healthy ? "healthy" : "unhealthy");
        return healthy ? 0 : 1;
    }

    private static void PrintReport(BuildReport report)
    {
        Console.WriteLine($"Rendered {report.Documents} documents, {report.Fragments} fragments, "
                          + $"and {report.CodeFiles} code files; {report.Broken} gate errors.");
        foreach (SpaceBuildResult space in report.Spaces)
        {
            Print("broken link", space.Diagnostics.BrokenLinks);
            Print("broken anchor", space.Diagnostics.BrokenAnchors);
            Print("navigation", space.Diagnostics.NavigationErrors);
            Print("unlisted document", space.Diagnostics.UnlistedDocuments);
            Print("undeclared section", space.Diagnostics.UndeclaredSections);
            Print("snippet", space.Diagnostics.SnippetErrors);
            Print("figure", space.Diagnostics.FigureErrors);
        }
    }

    private static void Print(string category, IEnumerable<string> messages)
    {
        foreach (string message in messages)
            Console.Error.WriteLine($"{category}: {message}");
    }

    private sealed class Options
    {
        internal required string Repository { get; init; }
        internal required string Configuration { get; init; }
        internal required string Output { get; init; }
        internal bool Check { get; init; }
        internal bool NoRender { get; init; }
        internal int Port { get; init; }
        internal string BasePath { get; init; } = "/";

        internal static Options Parse(string[] args, string command)
        {
            if (command is not ("render" or "serve" or "probe"))
                throw new InvalidDataException($"unknown command: {command}");
            string repository = Directory.GetCurrentDirectory();
            string? config = null;
            string? output = null;
            string basePath = "/";
            int port = 4173;
            bool check = false;
            bool noRender = false;
            bool portSet = false;
            bool baseSet = false;
            bool repoSet = false;
            for (int index = 0; index < args.Length; index++)
            {
                string option = args[index];
                string Value()
                {
                    if (++index >= args.Length)
                        throw new InvalidDataException($"{option} requires a value");
                    return args[index];
                }
                switch (option)
                {
                    case "--repo": repository = Path.GetFullPath(Value()); repoSet = true; break;
                    case "--config": config = Value(); break;
                    case "--out": output = Value(); break;
                    case "--port" when int.TryParse(Value(), out int parsed): port = parsed; portSet = true; break;
                    case "--base": basePath = Value(); baseSet = true; break;
                    case "--check": check = true; break;
                    case "--no-render": noRender = true; break;
                    case "--help": throw new InvalidDataException(Usage());
                    default: throw new InvalidDataException($"unknown option: {option}");
                }
            }
            if (port is < 1 or > 65_535)
                throw new InvalidDataException("--port must be between 1 and 65535");
            if (command != "serve" && noRender)
                throw new InvalidDataException("--no-render is only valid with serve");
            if (noRender && check)
                throw new InvalidDataException("--check cannot be combined with --no-render");
            if (command == "render" && (portSet || baseSet))
                throw new InvalidDataException("--port and --base are only valid with serve or probe");
            if (command == "probe" && (check || noRender || config is not null || output is not null
                                        || repoSet))
                throw new InvalidDataException("probe accepts only --port and --base");
            string configPath = config is null ? Path.Combine(repository, "agent-docs.json")
                : Path.IsPathFullyQualified(config) ? Path.GetFullPath(config)
                : Path.GetFullPath(Path.Combine(repository, config));
            string outputPath = output is null ? Path.Combine(repository, "build")
                : Path.IsPathFullyQualified(output) ? Path.GetFullPath(output)
                : Path.GetFullPath(Path.Combine(repository, output));
            return new()
            {
                Repository = Path.GetFullPath(repository),
                Configuration = configPath,
                Output = outputPath,
                Check = check,
                NoRender = noRender,
                Port = port,
                BasePath = basePath,
            };
        }

        private static string Usage() =>
            "agent-docs [render|serve|probe] [--repo PATH] [--config PATH] [--out PATH] "
            + "[--check] [--port 4173] [--base /prefix] [--no-render]";
    }
}
