using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;

namespace RetroBridge98.Settings.Core;

public sealed class SettingsViewModel : INotifyPropertyChanged
{
    private readonly IRetroBridgeCli cli;
    private readonly string settingsPath;
    private int currentStep;
    private bool isBusy;
    private string statusMessage = "Loading RetroBridge98 settings…";
    private string browserMode = "private-chromium";
    private string port = "9866";
    private string guestAddress = "10.0.2.2";
    private string downloadDirectory = "";
    private string maximumDownloadMegabytes = "100";
    private bool startWithWindows;
    private bool configurationExists;
    private bool configurationValid;
    private bool pairingReady;
    private bool rendererRunning;
    private bool guestConnected;
    private bool edgeAvailable;
    private bool chromeAvailable;
    private string autostartStatus = "Windows startup is off";
    private string portStatus = "Checking renderer port…";

    public SettingsViewModel(IRetroBridgeCli cli, string settingsPath)
    {
        this.cli = cli;
        this.settingsPath = settingsPath;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public ObservableCollection<ApiError> Errors { get; } = [];
    public ObservableCollection<DiagnosticCheck> Checks { get; } = [];

    public int CurrentStep
    {
        get => currentStep;
        set
        {
            if (Set(ref currentStep, Math.Clamp(value, 0, 4)))
            {
                OnPropertyChanged(nameof(CanGoBack));
                OnPropertyChanged(nameof(CanGoNext));
                OnPropertyChanged(nameof(StepHeading));
            }
        }
    }

    public bool CanGoBack => CurrentStep > 0;
    public bool CanGoNext => CurrentStep < 4;
    public string StepHeading => new[]
    {
        "Choose your browser",
        "Startup and downloads",
        "Pairing and connection",
        "Validate your setup",
        "Ready to bridge",
    }[CurrentStep];

    public bool IsBusy { get => isBusy; private set => Set(ref isBusy, value); }
    public string StatusMessage { get => statusMessage; private set => Set(ref statusMessage, value); }
    public string BrowserMode { get => browserMode; set => Set(ref browserMode, value); }
    public string Port { get => port; set => Set(ref port, value); }
    public string GuestAddress { get => guestAddress; set => Set(ref guestAddress, value); }
    public string DownloadDirectory { get => downloadDirectory; set => Set(ref downloadDirectory, value); }
    public string MaximumDownloadMegabytes { get => maximumDownloadMegabytes; set => Set(ref maximumDownloadMegabytes, value); }
    public bool StartWithWindows { get => startWithWindows; set => Set(ref startWithWindows, value); }
    public bool ConfigurationExists { get => configurationExists; private set => Set(ref configurationExists, value); }
    public bool ConfigurationValid { get => configurationValid; private set => Set(ref configurationValid, value); }
    public bool PairingReady { get => pairingReady; private set => Set(ref pairingReady, value); }
    public bool RendererRunning { get => rendererRunning; private set => Set(ref rendererRunning, value); }
    public bool GuestConnected { get => guestConnected; private set => Set(ref guestConnected, value); }
    public bool EdgeAvailable { get => edgeAvailable; private set => Set(ref edgeAvailable, value); }
    public bool ChromeAvailable { get => chromeAvailable; private set => Set(ref chromeAvailable, value); }
    public string EdgeStatus => EdgeAvailable ? "Detected and ready" : "Not detected";
    public string ChromeStatus => ChromeAvailable ? "Detected and ready" : "Not detected";
    public string PairingStatus => PairingReady ? "Pairing is ready" : "Pairing has not been created";
    public bool CanCreatePairing => !PairingReady;
    public string RendererStatus => RendererRunning ? "Renderer is running" : "Renderer is stopped";
    public string GuestStatus => GuestConnected ? "Windows 98 guest connected" : "Waiting for Windows 98 guest";
    public string AutostartStatus { get => autostartStatus; private set => Set(ref autostartStatus, value); }
    public string PortStatus { get => portStatus; private set => Set(ref portStatus, value); }
    public bool ReadyToLaunch => ConfigurationExists && ConfigurationValid && PairingReady;

    public void Next() => CurrentStep++;
    public void Back() => CurrentStep--;

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        await BusyAsync(async () =>
        {
            var configTask = cli.RunJsonAsync<ConfigShowData>(
                ["config", "show", "--json", "--settings-file", settingsPath],
                cancellationToken: cancellationToken);
            var browsersTask = cli.RunJsonAsync<BrowserListData>(
                ["browsers", "detect", "--json"],
                cancellationToken: cancellationToken);
            await Task.WhenAll(configTask, browsersTask);
            var config = await configTask;
            var browsers = await browsersTask;
            ShowErrors(config.Envelope.Errors.Concat(browsers.Envelope.Errors));
            if (config.Envelope.Data?.Settings is { } settings)
            {
                LoadSettings(settings);
                ConfigurationExists = config.Envelope.Data.Exists;
                ConfigurationValid = config.Envelope.Ok;
            }
            if (browsers.Envelope.Data is { } detected)
            {
                EdgeAvailable = detected.Browsers.Any(browser => browser.Mode == "edge-personal" && browser.Available);
                ChromeAvailable = detected.Browsers.Any(browser => browser.Mode == "chrome-personal" && browser.Available);
                OnPropertyChanged(nameof(EdgeStatus));
                OnPropertyChanged(nameof(ChromeStatus));
            }
            await RefreshDiagnosticsCoreAsync(cancellationToken);
            StatusMessage = ConfigurationExists ? "Settings loaded" : "Complete first-run setup";
        });
    }

    public async Task<bool> ValidateAsync(CancellationToken cancellationToken = default)
    {
        var settings = BuildSettings();
        if (settings is null)
        {
            return false;
        }
        return await BusyAsync(async () =>
        {
            var result = await cli.RunJsonAsync<object>(
                ["config", "validate", "--json-input", "-", "--settings-file", settingsPath],
                JsonSerializer.Serialize(settings),
                cancellationToken: cancellationToken);
            ShowErrors(result.Envelope.Errors);
            StatusMessage = result.Envelope.Ok ? "Configuration is valid" : "Configuration needs attention";
            return result.Envelope.Ok;
        });
    }

    public async Task<bool> ApplyAsync(CancellationToken cancellationToken = default)
    {
        var settings = BuildSettings();
        if (settings is null)
        {
            return false;
        }
        return await BusyAsync(async () =>
        {
            var result = await cli.RunJsonAsync<ApplyData>(
                ["config", "apply", "--json-input", "-", "--settings-file", settingsPath],
                JsonSerializer.Serialize(settings),
                TimeSpan.FromSeconds(60),
                cancellationToken);
            ShowErrors(result.Envelope.Errors);
            if (result.Envelope.Ok)
            {
                ConfigurationExists = true;
                ConfigurationValid = true;
                StatusMessage = "Settings saved";
                await RefreshDiagnosticsCoreAsync(cancellationToken);
            }
            else
            {
                StatusMessage = "Settings were not saved";
            }
            return result.Envelope.Ok;
        });
    }

    public async Task<bool> PairAsync(CancellationToken cancellationToken = default)
    {
        if (!int.TryParse(Port, out var parsedPort))
        {
            ShowErrors([new ApiError { Code = "settings_invalid", Field = "network.port", Message = "Enter a numeric port." }]);
            return false;
        }
        return await BusyAsync(async () =>
        {
            var result = await cli.RunJsonAsync<object>(
                ["pair", "--server", GuestAddress, "--port", parsedPort.ToString(), "--json"],
                timeout: TimeSpan.FromSeconds(30),
                cancellationToken: cancellationToken);
            ShowErrors(result.Envelope.Errors);
            StatusMessage = result.Envelope.Ok ? "Pairing created" : "Pairing could not be created";
            await RefreshDiagnosticsCoreAsync(cancellationToken);
            return result.Envelope.Ok;
        });
    }

    public async Task SignInAsync(string mode, CancellationToken cancellationToken = default)
    {
        await BusyAsync(async () =>
        {
            StatusMessage = "Complete sign-in in the visible browser, then close it";
            var result = await cli.RunJsonAsync<object>(
                ["browsers", "sign-in", "--mode", mode],
                timeout: TimeSpan.FromHours(2),
                cancellationToken: cancellationToken);
            ShowErrors(result.Envelope.Errors);
            StatusMessage = result.Envelope.Ok ? "Sign-in browser closed" : "Sign-in browser could not be opened";
        });
    }

    public async Task RefreshDiagnosticsAsync(CancellationToken cancellationToken = default)
    {
        await BusyAsync(() => RefreshDiagnosticsCoreAsync(cancellationToken));
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        await BusyAsync(async () =>
        {
            var result = await cli.RunJsonAsync<object>(
                ["stop", "--json"],
                timeout: TimeSpan.FromSeconds(30),
                cancellationToken: cancellationToken);
            if (!result.Envelope.Ok && result.Envelope.Errors.FirstOrDefault()?.Code == "cli_output_invalid")
            {
                // The legacy stop command intentionally remains human-readable.
                ShowErrors([]);
            }
            await RefreshDiagnosticsCoreAsync(cancellationToken);
            StatusMessage = "Stop request completed";
        });
    }

    private async Task RefreshDiagnosticsCoreAsync(CancellationToken cancellationToken)
    {
        var result = await cli.RunJsonAsync<DiagnosticsData>(
            ["diagnostics", "--json", "--settings-file", settingsPath],
            cancellationToken: cancellationToken);
        if (result.Envelope.Data is not { } diagnostics)
        {
            ShowErrors(result.Envelope.Errors);
            return;
        }
        PairingReady = diagnostics.Pairing.Ready;
        RendererRunning = diagnostics.Runtime.Running;
        GuestConnected = diagnostics.Runtime.GuestConnected;
        AutostartStatus = diagnostics.Autostart.Enabled
            ? "Windows startup is currently enabled"
            : "Windows startup is currently off";
        PortStatus = diagnostics.Checks.FirstOrDefault(check => check.Code == "port")?.Message
            ?? "Renderer port status is unavailable";
        Checks.Clear();
        foreach (var check in diagnostics.Checks)
        {
            Checks.Add(check);
        }
        OnPropertyChanged(nameof(PairingStatus));
        OnPropertyChanged(nameof(CanCreatePairing));
        OnPropertyChanged(nameof(RendererStatus));
        OnPropertyChanged(nameof(GuestStatus));
        OnPropertyChanged(nameof(ReadyToLaunch));
    }

    private RetroSettings? BuildSettings()
    {
        if (!int.TryParse(Port, out var parsedPort) || !int.TryParse(MaximumDownloadMegabytes, out var maximum))
        {
            ShowErrors([new ApiError { Code = "settings_invalid", Field = "settings", Message = "Port and download limit must be numbers." }]);
            StatusMessage = "Configuration needs attention";
            return null;
        }
        return new RetroSettings
        {
            Browser = new BrowserSettings { Mode = BrowserMode },
            Network = new NetworkSettings { Listen = "127.0.0.1", Port = parsedPort, GuestAddress = GuestAddress },
            Downloads = new DownloadSettings { Directory = DownloadDirectory, MaxMegabytes = maximum },
            Startup = new StartupSettings { StartWithWindows = StartWithWindows },
        };
    }

    private void LoadSettings(RetroSettings settings)
    {
        BrowserMode = settings.Browser.Mode;
        Port = settings.Network.Port.ToString();
        GuestAddress = settings.Network.GuestAddress;
        DownloadDirectory = settings.Downloads.Directory;
        MaximumDownloadMegabytes = settings.Downloads.MaxMegabytes.ToString();
        StartWithWindows = settings.Startup.StartWithWindows;
    }

    private void ShowErrors(IEnumerable<ApiError> errors)
    {
        Errors.Clear();
        foreach (var error in errors)
        {
            Errors.Add(error);
        }
    }

    private async Task BusyAsync(Func<Task> action)
    {
        IsBusy = true;
        try
        {
            await action();
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task<T> BusyAsync<T>(Func<Task<T>> action)
    {
        IsBusy = true;
        try
        {
            return await action();
        }
        finally
        {
            IsBusy = false;
        }
    }

    private bool Set<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return false;
        }
        field = value;
        OnPropertyChanged(propertyName);
        return true;
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
