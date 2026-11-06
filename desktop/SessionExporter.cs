using System.IO;
using System.IO.Compression;
using System.Text.Json;

namespace FlowLens;

public static class SessionExporter
{
    public static void Write(string destination,AnalysisSessionState session,string? source)
    {
        if(session.Classification==null&&session.Motion==null&&session.Interface==null) throw new InvalidOperationException("No saved results to export.");
        using var zip=new ZipArchive(new FileStream(destination,FileMode.Create),ZipArchiveMode.Create);
        void Add(SavedAnalysis? saved,string category)
        {
            if(saved==null) return;
            foreach(var path in Directory.EnumerateFiles(saved.Directory))
                zip.CreateEntryFromFile(path,category+"/"+Path.GetFileName(path));
        }
        Add(session.Classification,"classification");Add(session.Motion,"motion");Add(session.Interface,"interface");
        if(session.InterfaceSkippedPattern!=null)
        {
            var skip=zip.CreateEntry("interface/skip.json");using var skipWriter=new StreamWriter(skip.Open());
            skipWriter.Write(JsonSerializer.Serialize(new { pattern=session.InterfaceSkippedPattern,reason=session.InterfaceSkipReason }));
        }
        var entry=zip.CreateEntry("session.json");
        using var writer=new StreamWriter(entry.Open());
        writer.Write(JsonSerializer.Serialize(new { source,has_classification=session.Classification!=null,has_motion=session.Motion!=null,has_interface=session.Interface!=null,interface_skipped=session.InterfaceSkippedPattern!=null,selected_pair=session.SelectedPair },new JsonSerializerOptions { WriteIndented=true }));
    }
}
