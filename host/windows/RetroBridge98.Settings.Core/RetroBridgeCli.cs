using System.Diagnostics;
using System.Text.Json;

namespace RetroBridge98.Settings.Core;

public sealed record CliCallResult<T>(ApiEnvelope<T> Envelope, int ExitCode, string StandardError);

public interface IRetroBridgeCli
{
    Task<CliCallResult<T>> RunJsonAsync<T>(
        IReadOnlyList<string> arguments,
        string? standardInput = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default);
}

public sealed class RetroBridgeCli : IRetroBridgeCli
{
    private readonly string executable;
    private readonly JsonSerializerOptions jsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public RetroBridgeCli(string executable)
    {
        this.executable = executable;
    }

    public async Task<CliCallResult<T>> RunJsonAsync<T>(
        IReadOnlyList<string> arguments,
        string? standardInput = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = executable,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                RedirectStandardInput = standardInput is not null,
                CreateNoWindow = true,
            },
        };
        foreach (var argument in arguments)
        {
            process.StartInfo.ArgumentList.Add(argument);
        }
        if (!process.Start())
        {
            return Failure<T>("cli_launch_failed", "RetroBridge could not be started.");
        }
        var stdoutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
        if (standardInput is not null)
        {
            await process.StandardInput.WriteAsync(standardInput.AsMemory(), cancellationToken);
            process.StandardInput.Close();
        }
        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(timeout ?? TimeSpan.FromSeconds(30));
        try
        {
            await process.WaitForExitAsync(timeoutSource.Token);
        }
        catch (OperationCanceledException)
        {
            try
            {
                process.Kill(entireProcessTree: true);
            }
            catch (InvalidOperationException)
            {
            }
            if (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            return Failure<T>("cli_timeout", "RetroBridge did not respond in time.");
        }
        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        try
        {
            var envelope = JsonSerializer.Deserialize<ApiEnvelope<T>>(stdout, jsonOptions);
            if (envelope is null || envelope.ContractVersion != 1)
            {
                return Failure<T>("cli_output_invalid", "RetroBridge returned an unsupported response.", process.ExitCode, stderr);
            }
            return new CliCallResult<T>(envelope, process.ExitCode, stderr);
        }
        catch (JsonException)
        {
            var detail = string.IsNullOrWhiteSpace(stderr) ? stdout.Trim() : stderr.Trim();
            return Failure<T>(
                "cli_output_invalid",
                string.IsNullOrWhiteSpace(detail) ? "RetroBridge returned no usable response." : detail,
                process.ExitCode,
                stderr);
        }
    }

    private static CliCallResult<T> Failure<T>(
        string code,
        string message,
        int exitCode = -1,
        string standardError = "")
    {
        return new CliCallResult<T>(
            new ApiEnvelope<T>
            {
                Ok = false,
                ContractVersion = 1,
                Errors = [new ApiError { Code = code, Message = message }],
            },
            exitCode,
            standardError);
    }
}
