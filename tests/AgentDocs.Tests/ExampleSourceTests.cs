using AgentDocs.Examples;

namespace AgentDocs.Tests;

public sealed class ExampleSourceTests
{
    [Fact]
    public void Greeting_formatter_trims_the_name()
    {
        Assert.Equal("Hello, Ada.", GreetingFormatter.Format("  Ada  "));
    }

    [Fact]
    public void Greeting_formatter_rejects_a_blank_name()
    {
        Assert.Throws<ArgumentException>(() => GreetingFormatter.Format("   "));
    }
}
