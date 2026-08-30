using System.Text.Json;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using RetroBridge98.Settings.Core;

namespace RetroBridge98.Settings.Tests;

[TestClass]
public sealed class ContractTests
{
    [TestMethod]
    public void ConfigContractUsesPythonSnakeCaseFields()
    {
        const string json = """
        {
          "contract_version": 1,
          "ok": true,
          "data": {
            "exists": true,
            "path": "C:\\RetroBridge98\\settings.json",
            "settings": {
              "schema_version": 1,
              "browser": {"mode": "edge-personal"},
              "network": {"listen": "127.0.0.1", "port": 9866, "guest_address": "10.0.2.2"},
              "downloads": {"directory": "C:\\Downloads", "max_megabytes": 100},
              "startup": {"start_with_windows": false}
            }
          },
          "errors": []
        }
        """;
        var envelope = JsonSerializer.Deserialize<ApiEnvelope<ConfigShowData>>(json);
        Assert.IsNotNull(envelope?.Data?.Settings);
        Assert.AreEqual("edge-personal", envelope.Data.Settings.Browser.Mode);
        Assert.IsFalse(envelope.Data.Settings.Startup.StartWithWindows);
    }

    [TestMethod]
    public async Task ViewModelLoadsBrowserDetectionAndFirstRunDefaults()
    {
        var cli = new FakeCli(new Dictionary<string, string>
        {
            ["config"] = Envelope("""
                {"exists":false,"path":"C:\\RetroBridge98\\settings.json","settings":{"schema_version":1,"browser":{"mode":"private-chromium"},"network":{"listen":"127.0.0.1","port":9866,"guest_address":"10.0.2.2"},"downloads":{"directory":"C:\\Downloads","max_megabytes":100},"startup":{"start_with_windows":false}}}
                """, ok: false, errors: "[{\"code\":\"settings_missing\",\"field\":\"settings\",\"message\":\"Setup required\"}]"),
            ["browsers"] = Envelope("""
                {"browsers":[{"mode":"private-chromium","name":"Private Chromium","available":true,"executable":null,"source":"playwright"},{"mode":"edge-personal","name":"Edge","available":true,"executable":"C:\\Edge.exe","source":"test"},{"mode":"chrome-personal","name":"Chrome","available":false,"executable":null,"source":"not-found"}]}
                """),
            ["diagnostics"] = Envelope("""
                {"settings":{"exists":false,"valid":false},"pairing":{"ready":false},"runtime":{"running":false,"guest_connected":false,"log_file":"C:\\log"},"autostart":{"installed":false,"loaded":false},"checks":[]}
                """),
        });
        var viewModel = new SettingsViewModel(cli, @"C:\RetroBridge98\settings.json");
        await viewModel.InitializeAsync();
        Assert.AreEqual("private-chromium", viewModel.BrowserMode);
        Assert.IsTrue(viewModel.EdgeAvailable);
        Assert.IsFalse(viewModel.ChromeAvailable);
        Assert.IsFalse(viewModel.StartWithWindows);
        Assert.IsFalse(viewModel.ConfigurationExists);
    }

    [TestMethod]
    public void WizardNavigationStaysWithinFiveSteps()
    {
        var viewModel = new SettingsViewModel(new FakeCli(new Dictionary<string, string>()), "settings.json");
        for (var index = 0; index < 10; index++) viewModel.Next();
        Assert.AreEqual(4, viewModel.CurrentStep);
        for (var index = 0; index < 10; index++) viewModel.Back();
        Assert.AreEqual(0, viewModel.CurrentStep);
    }

    [TestMethod]
    public async Task PythonFieldErrorsArePresentedWithoutCSharpValidationRules()
    {
        var cli = new FakeCli(new Dictionary<string, string>
        {
            ["config"] = Envelope("{}", ok: false, errors: "[{\"code\":\"settings_invalid\",\"field\":\"network.port\",\"message\":\"Port is already in use\"}]"),
        });
        var viewModel = new SettingsViewModel(cli, "settings.json")
        {
            DownloadDirectory = @"C:\Downloads",
        };

        Assert.IsFalse(await viewModel.ValidateAsync());
        Assert.AreEqual(1, viewModel.Errors.Count);
        Assert.AreEqual("network.port", viewModel.Errors[0].Field);
        Assert.AreEqual("Port is already in use", viewModel.Errors[0].Message);
    }

    [TestMethod]
    public async Task DiagnosticsRefreshesRendererAutostartPortAndGuestStatus()
    {
        var cli = new FakeCli(new Dictionary<string, string>
        {
            ["diagnostics"] = Envelope("""
                {"settings":{"exists":true,"valid":true},"pairing":{"ready":true},"runtime":{"running":true,"guest_connected":true,"log_file":"C:\\log"},"autostart":{"installed":true,"enabled":true,"loaded":true},"checks":[{"code":"port","ok":true,"message":"Port belongs to RetroBridge98","informational":false}]}
                """),
        });
        var viewModel = new SettingsViewModel(cli, "settings.json");

        await viewModel.RefreshDiagnosticsAsync();

        Assert.IsTrue(viewModel.RendererRunning);
        Assert.IsTrue(viewModel.GuestConnected);
        Assert.AreEqual("Windows startup is currently enabled", viewModel.AutostartStatus);
        Assert.AreEqual("Port belongs to RetroBridge98", viewModel.PortStatus);
    }

    [TestMethod]
    public void LaunchRoutingRequiresLaunchModeValidSettingsAndPairing()
    {
        Assert.IsTrue(LaunchRouting.ShouldLaunchConsole(["--launch"], true, true, true));
        Assert.IsFalse(LaunchRouting.ShouldLaunchConsole([], true, true, true));
        Assert.IsFalse(LaunchRouting.ShouldLaunchConsole(["--launch"], false, true, true));
        Assert.IsFalse(LaunchRouting.ShouldLaunchConsole(["--launch"], true, false, true));
        Assert.IsFalse(LaunchRouting.ShouldLaunchConsole(["--launch"], true, true, false));
    }

    [TestMethod]
    public async Task CliRunnerHonorsCancellation()
    {
        if (!OperatingSystem.IsLinux())
        {
            Assert.Inconclusive("The portable WPF contract suite exercises process cancellation in WSL.");
        }
        var cli = new RetroBridgeCli("/bin/sh");
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));

        await Assert.ThrowsAsync<OperationCanceledException>(
            () => cli.RunJsonAsync<object>(["-c", "sleep 5"], cancellationToken: cancellation.Token));
    }

    [TestMethod]
    public async Task CliRunnerReportsTimeoutAndTerminatesTheChild()
    {
        if (!OperatingSystem.IsLinux())
        {
            Assert.Inconclusive("The portable WPF contract suite exercises process timeouts in WSL.");
        }
        var cli = new RetroBridgeCli("/bin/sh");

        var result = await cli.RunJsonAsync<object>(["-c", "sleep 5"], timeout: TimeSpan.FromMilliseconds(100));

        Assert.IsFalse(result.Envelope.Ok);
        Assert.AreEqual("cli_timeout", result.Envelope.Errors.Single().Code);
    }

    private static string Envelope(string data, bool ok = true, string errors = "[]")
        => $"{{\"contract_version\":1,\"ok\":{ok.ToString().ToLowerInvariant()},\"data\":{data},\"errors\":{errors}}}";

    private sealed class FakeCli(IReadOnlyDictionary<string, string> responses) : IRetroBridgeCli
    {
        public Task<CliCallResult<T>> RunJsonAsync<T>(
            IReadOnlyList<string> arguments,
            string? standardInput = null,
            TimeSpan? timeout = null,
            CancellationToken cancellationToken = default)
        {
            var key = arguments[0];
            var json = responses.TryGetValue(key, out var value)
                ? value
                : Envelope("{}", ok: false, errors: "[{\"code\":\"missing_fake\",\"field\":\"\",\"message\":\"No fake response\"}]");
            var envelope = JsonSerializer.Deserialize<ApiEnvelope<T>>(json)
                ?? throw new InvalidOperationException("Invalid fake response");
            return Task.FromResult(new CliCallResult<T>(envelope, envelope.Ok ? 0 : 2, ""));
        }
    }
}
