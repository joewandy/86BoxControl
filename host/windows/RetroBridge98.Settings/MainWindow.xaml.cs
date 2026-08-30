using System.IO;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Win32;
using RetroBridge98.Settings.Core;

namespace RetroBridge98.Settings;

public partial class MainWindow : Window
{
    private readonly SettingsViewModel viewModel;
    private readonly CancellationTokenSource cancellation = new();
    private readonly DispatcherTimer statusTimer = new()
    {
        Interval = TimeSpan.FromSeconds(5),
    };

    public MainWindow(SettingsViewModel viewModel)
    {
        this.viewModel = viewModel;
        DataContext = viewModel;
        InitializeComponent();
        statusTimer.Tick += StatusTimer_Tick;
        statusTimer.Start();
        Closed += (_, _) =>
        {
            statusTimer.Stop();
            cancellation.Cancel();
            Application.Current.Shutdown();
        };
    }

    private async void StatusTimer_Tick(object? sender, EventArgs e)
    {
        if (viewModel.IsBusy)
        {
            return;
        }
        await RunAsync(() => viewModel.RefreshDiagnosticsAsync(cancellation.Token));
    }

    private void StepButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: string tag } && int.TryParse(tag, out var step))
        {
            viewModel.CurrentStep = step;
        }
    }

    private void Back_Click(object sender, RoutedEventArgs e) => viewModel.Back();
    private void Next_Click(object sender, RoutedEventArgs e) => viewModel.Next();

    private void BrowseDownloads_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog
        {
            Title = "Choose where RetroBridge98 downloads are saved",
            InitialDirectory = Directory.Exists(viewModel.DownloadDirectory)
                ? viewModel.DownloadDirectory
                : Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        };
        if (dialog.ShowDialog(this) == true)
        {
            viewModel.DownloadDirectory = dialog.FolderName;
        }
    }

    private async void EdgeSignIn_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => viewModel.SignInAsync("edge-personal", cancellation.Token));

    private async void ChromeSignIn_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => viewModel.SignInAsync("chrome-personal", cancellation.Token));

    private async void CreatePairing_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => viewModel.PairAsync(cancellation.Token));

    private async void Refresh_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => viewModel.RefreshDiagnosticsAsync(cancellation.Token));

    private async void Stop_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => viewModel.StopAsync(cancellation.Token));

    private async void Validate_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => viewModel.ValidateAsync(cancellation.Token));

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        await RunAsync(async () =>
        {
            if (await viewModel.ApplyAsync(cancellation.Token))
            {
                viewModel.CurrentStep = 4;
            }
        });
    }

    private void Launch_Click(object sender, RoutedEventArgs e)
    {
        App.LaunchConsole();
        Close();
    }

    private static async Task RunAsync(Func<Task> action)
    {
        try
        {
            await action();
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                exception.Message,
                "RetroBridge98 Settings",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }
}
