using System.Text.Json.Serialization;

namespace RetroBridge98.Settings.Core;

public sealed class ApiEnvelope<T>
{
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; set; }

    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("data")]
    public T? Data { get; set; }

    [JsonPropertyName("errors")]
    public List<ApiError> Errors { get; set; } = [];
}

public sealed class ApiError
{
    [JsonPropertyName("code")]
    public string Code { get; set; } = "unknown";

    [JsonPropertyName("field")]
    public string Field { get; set; } = "";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "Unknown error";
}

public sealed class ConfigShowData
{
    [JsonPropertyName("exists")]
    public bool Exists { get; set; }

    [JsonPropertyName("path")]
    public string Path { get; set; } = "";

    [JsonPropertyName("settings")]
    public RetroSettings? Settings { get; set; }
}

public sealed class ApplyData
{
    [JsonPropertyName("path")]
    public string Path { get; set; } = "";

    [JsonPropertyName("settings")]
    public RetroSettings? Settings { get; set; }

    [JsonPropertyName("autostart_installed")]
    public bool AutostartInstalled { get; set; }
}

public sealed class RetroSettings
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("browser")]
    public BrowserSettings Browser { get; set; } = new();

    [JsonPropertyName("network")]
    public NetworkSettings Network { get; set; } = new();

    [JsonPropertyName("downloads")]
    public DownloadSettings Downloads { get; set; } = new();

    [JsonPropertyName("startup")]
    public StartupSettings Startup { get; set; } = new();
}

public sealed class BrowserSettings
{
    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "private-chromium";
}

public sealed class NetworkSettings
{
    [JsonPropertyName("listen")]
    public string Listen { get; set; } = "127.0.0.1";

    [JsonPropertyName("port")]
    public int Port { get; set; } = 9866;

    [JsonPropertyName("guest_address")]
    public string GuestAddress { get; set; } = "10.0.2.2";
}

public sealed class DownloadSettings
{
    [JsonPropertyName("directory")]
    public string Directory { get; set; } = "";

    [JsonPropertyName("max_megabytes")]
    public int MaxMegabytes { get; set; } = 100;
}

public sealed class StartupSettings
{
    [JsonPropertyName("start_with_windows")]
    public bool StartWithWindows { get; set; }
}

public sealed class BrowserListData
{
    [JsonPropertyName("browsers")]
    public List<BrowserInfo> Browsers { get; set; } = [];
}

public sealed class BrowserInfo
{
    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("available")]
    public bool Available { get; set; }

    [JsonPropertyName("executable")]
    public string? Executable { get; set; }

    [JsonPropertyName("source")]
    public string Source { get; set; } = "";
}

public sealed class DiagnosticsData
{
    [JsonPropertyName("settings")]
    public DiagnosticSettings Settings { get; set; } = new();

    [JsonPropertyName("pairing")]
    public PairingStatus Pairing { get; set; } = new();

    [JsonPropertyName("runtime")]
    public RuntimeStatus Runtime { get; set; } = new();

    [JsonPropertyName("autostart")]
    public AutostartStatus Autostart { get; set; } = new();

    [JsonPropertyName("checks")]
    public List<DiagnosticCheck> Checks { get; set; } = [];
}

public sealed class DiagnosticSettings
{
    [JsonPropertyName("exists")]
    public bool Exists { get; set; }

    [JsonPropertyName("valid")]
    public bool Valid { get; set; }
}

public sealed class PairingStatus
{
    [JsonPropertyName("ready")]
    public bool Ready { get; set; }

    [JsonPropertyName("guest_server")]
    public string? GuestServer { get; set; }

    [JsonPropertyName("guest_port")]
    public int? GuestPort { get; set; }
}

public sealed class RuntimeStatus
{
    [JsonPropertyName("running")]
    public bool Running { get; set; }

    [JsonPropertyName("guest_connected")]
    public bool GuestConnected { get; set; }

    [JsonPropertyName("log_file")]
    public string LogFile { get; set; } = "";
}

public sealed class AutostartStatus
{
    [JsonPropertyName("installed")]
    public bool Installed { get; set; }

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    [JsonPropertyName("loaded")]
    public bool Loaded { get; set; }
}

public sealed class DiagnosticCheck
{
    [JsonPropertyName("code")]
    public string Code { get; set; } = "";

    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("informational")]
    public bool Informational { get; set; }
}
