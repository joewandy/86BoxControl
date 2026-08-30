namespace RetroBridge98.Settings.Core;

public static class LaunchRouting
{
    public static bool ShouldLaunchConsole(
        IEnumerable<string> arguments,
        bool configurationExists,
        bool configurationValid,
        bool pairingReady)
        => arguments.Any(argument => argument.Equals("--launch", StringComparison.OrdinalIgnoreCase))
           && configurationExists
           && configurationValid
           && pairingReady;
}
