using System.Diagnostics;
using System.IO;
using System.Windows;
using RetroBridge98.Settings.Core;

namespace RetroBridge98.Settings;

public partial class App : Application
{
    public static string SupportDirectory { get; private set; } = "";
    public static string RetroBridgeExecutable { get; private set; } = "";
    public static string SettingsPath { get; private set; } = "";

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var applicationDirectory = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        SupportDirectory = Directory.GetParent(applicationDirectory)?.FullName ?? applicationDirectory;
        RetroBridgeExecutable = Path.Combine(SupportDirectory, "venv", "Scripts", "retrobridge.exe");
        SettingsPath = Path.Combine(SupportDirectory, "settings.json");
        var viewModel = new SettingsViewModel(new RetroBridgeCli(RetroBridgeExecutable), SettingsPath);
        try
        {
            await viewModel.InitializeAsync();
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"RetroBridge98 Settings could not initialize.\n\n{exception.Message}",
                "RetroBridge98 Settings",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
        if (LaunchRouting.ShouldLaunchConsole(
                e.Args,
                viewModel.ConfigurationExists,
                viewModel.ConfigurationValid,
                viewModel.PairingReady))
        {
            LaunchConsole();
            Shutdown();
            return;
        }
        var window = new MainWindow(viewModel);
        MainWindow = window;
        window.Show();
    }

    public static void LaunchConsole()
    {
        var commandProcessor = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe";
        Process.Start(new ProcessStartInfo
        {
            FileName = commandProcessor,
            Arguments = $"/d /k \"\"{RetroBridgeExecutable}\" console --settings-file \"{SettingsPath}\"\"",
            WorkingDirectory = SupportDirectory,
            UseShellExecute = true,
        });
    }
}
