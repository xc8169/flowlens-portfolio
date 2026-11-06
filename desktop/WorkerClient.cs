using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;

namespace FlowLens;

public sealed class WorkerClient
{
    public string Root { get; }
    public Process? Running { get; private set; }
    public WorkerClient(string root) => Root = root;

    public async Task RunAsync(string command, string request, Action<JsonElement> onEvent)
    {
        string packed = Path.Combine(Root,"engine-bin","FlowLensWorker.exe");
        string python = Path.Combine(Root,".venv","Scripts","python.exe");
        var info = new ProcessStartInfo
        {
            FileName = File.Exists(packed) ? packed : python,
            WorkingDirectory = Root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        if (!File.Exists(info.FileName)) throw new FileNotFoundException("Worker runtime missing. Run Setup.ps1 or use the complete packaged folder.");
        if (!File.Exists(packed)) { info.ArgumentList.Add("-u"); info.ArgumentList.Add(Path.Combine(Root,"engine","worker.py")); }
        info.ArgumentList.Add(command); info.ArgumentList.Add(request);
        info.Environment["PYTHONUTF8"]="1";
        info.Environment["MPLCONFIGDIR"]=Path.Combine(Root,".cache");
        using var proc = new Process { StartInfo=info };
        Running=proc;
        try
        {
            proc.Start();
            var errors=proc.StandardError.ReadToEndAsync();
            while (await proc.StandardOutput.ReadLineAsync() is string line)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                JsonDocument doc;
                try { doc=JsonDocument.Parse(line); }
                catch (JsonException) { continue; }
                using (doc) onEvent(doc.RootElement.Clone());
            }
            await proc.WaitForExitAsync();
            string stderr=await errors;
            File.WriteAllText(Path.Combine(Path.GetDirectoryName(request)!,"worker.log"),stderr);
            if (proc.ExitCode!=0) throw new InvalidOperationException("Analysis worker failed. " + (stderr.Split('\n',StringSplitOptions.RemoveEmptyEntries).LastOrDefault() ?? "See worker.log."));
        }
        finally { Running=null; }
    }

    public void Stop()
    {
        try { if (Running is { HasExited:false }) Running.Kill(entireProcessTree:true); }
        catch (InvalidOperationException) { }
    }
}
