namespace AgentDocs.Tests;

public sealed class PathSafetyTests
{
    [Fact]
    public void Filesystem_root_contains_a_real_descendant()
    {
        using TempRepository repo = new();
        string root = Path.GetPathRoot(repo.Root)!;

        Assert.True(PathSafety.IsSameOrUnder(repo.Root, root));
        PathSafety.EnsureNoReparse(root, repo.Root, "temporary repository");
    }

    [Fact]
    public void A_sibling_with_the_same_textual_prefix_is_not_a_descendant()
    {
        using TempRepository repo = new();
        string sibling = repo.Root + "-other";

        Assert.False(PathSafety.IsSameOrUnder(sibling, repo.Root));
        Assert.False(PathSafety.Overlaps(sibling, repo.Root));
    }

    [Fact]
    public void EnsureNoReparse_rejects_a_target_outside_its_trusted_root()
    {
        using TempRepository repo = new();
        string outside = Path.Combine(repo.Workspace, "outside");

        InvalidDataException error = Assert.Throws<InvalidDataException>(
            () => PathSafety.EnsureNoReparse(repo.Root, outside, "candidate"));

        Assert.Contains("escapes its trusted root", error.Message, StringComparison.Ordinal);
    }
}
