// CIG .NET bridge - entry point. .NET calls StartupHook.Initialize() (a type with this exact name, in no namespace)
// before the program's Main when DOTNET_STARTUP_HOOKS names this assembly - an official, documented .NET feature.
// CIG sets that variable only for programs it launches itself.
//
// The bridge opens ONE loopback-only TCP listener on a random port, writes {port, token, pid} to the channel file CIG
// named in CIG_BRIDGE_CHANNEL, and answers one JSON line per request. Every request must carry the token. Nothing is
// sent anywhere else.
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;

internal class StartupHook
{
    public static void Initialize()
    {
        string channel = Environment.GetEnvironmentVariable("CIG_BRIDGE_CHANNEL");
        if (string.IsNullOrEmpty(channel)) return;                     // not launched by CIG: do nothing at all
        Environment.SetEnvironmentVariable("DOTNET_STARTUP_HOOKS", null);  // child processes do not inherit the hook
        Environment.SetEnvironmentVariable("CIG_BRIDGE_CHANNEL", null);
        var t = new Thread(() => Cig.Bridge.Server.Run(channel)) { IsBackground = true, Name = "cig-bridge" };
        t.Start();
    }
}

namespace Cig.Bridge
{
    internal static class Server
    {
        public static void Run(string channelPath)
        {
            try
            {
                var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
                var listener = new TcpListener(IPAddress.Loopback, 0);
                listener.Start();
                int port = ((IPEndPoint)listener.LocalEndpoint).Port;
                var info = JsonSerializer.Serialize(new
                {
                    host = "127.0.0.1", port, token, pid = Environment.ProcessId, bridge = "dotnet", protocol = 1
                });
                var tmp = channelPath + ".tmp";
                File.WriteAllText(tmp, info);
                File.Move(tmp, channelPath, true);
                while (true)
                {
                    using var client = listener.AcceptTcpClient();
                    if (!((IPEndPoint)client.Client.RemoteEndPoint).Address.Equals(IPAddress.Loopback)) continue;
                    using var stream = client.GetStream();
                    using var reader = new StreamReader(stream, Encoding.UTF8);
                    using var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true };
                    string line;
                    while ((line = reader.ReadLine()) != null)
                        writer.WriteLine(Handle(line, token));
                }
            }
            catch (Exception e)
            {
                try { File.WriteAllText(channelPath + ".error", e.ToString()); } catch { }
            }
        }

        static string Handle(string line, string token)
        {
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                if (!root.TryGetProperty("token", out var tk) || tk.GetString() != token)
                    return JsonSerializer.Serialize(new { ok = false, error = "bad token" });
                string cmd = root.GetProperty("cmd").GetString();
                var args = root.TryGetProperty("args", out var a) ? a : default;
                object result = cmd switch
                {
                    "ping" => new { ok = true, framework = Ui.Framework(), pid = Environment.ProcessId },
                    "tree" => Ui.Tree(),
                    "act" => Ui.Act(args),
                    _ => new { ok = false, error = "unknown cmd " + cmd },
                };
                return JsonSerializer.Serialize(result);
            }
            catch (Exception e)
            {
                return JsonSerializer.Serialize(new { ok = false, error = e.GetBaseException().Message });
            }
        }
    }
}
