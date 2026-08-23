namespace AgentDocs.Examples;

public static class GreetingFormatter
{
    // docs:begin greeting-format
    public static string Format(string name)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        return $"Hello, {name.Trim()}.";
    }
    // docs:end greeting-format
}
