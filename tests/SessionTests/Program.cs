using FlowLens;
using System.Text.Json;
var cache=new AnalysisSessionState();
JsonElement Data(string value) { using var doc=JsonDocument.Parse("{\"id\":\""+value+"\"}");return doc.RootElement.Clone(); }
void Check(bool condition,string message) { if(!condition) throw new Exception(message); }
cache.StoreClassification(Data("classification-1"),"classification-dir-1");
cache.StoreMotion(Data("motion-1"),"motion-dir-1");cache.SelectedPair=7;
Check(cache.Classification!.Data.GetProperty("id").GetString()=="classification-1","Motion must keep classification");
cache.StoreClassification(Data("classification-2"),"classification-dir-2");
Check(cache.Motion!.Data.GetProperty("id").GetString()=="motion-1","Classification must keep motion");
Check(cache.SelectedPair==7,"Classification must keep the selected pair");
var originalMotion=cache.Motion;var originalClass=cache.Classification;
for(int i=0;i<20;i++) { _=cache.Motion!.Data;_=cache.Classification!.Data; }
Check(ReferenceEquals(originalMotion,cache.Motion)&&ReferenceEquals(originalClass,cache.Classification),"Navigation/access must preserve saved results");
cache.InvalidateMotion();Check(cache.Motion==null&&ReferenceEquals(cache.Classification,originalClass),"ROI/calibration/flow settings must invalidate only motion");
cache.StoreMotion(Data("motion-2"),"motion-dir-2");cache.InvalidateClassification();
Check(cache.Motion!=null&&cache.Classification==null,"Reclassification must not invalidate motion");
cache.StoreClassification(Data("classification-3"),"classification-dir-3");cache.InvalidateShared();
Check(cache.Motion==null&&cache.Classification==null&&cache.SelectedPair==0,"Source/range/timing changes must invalidate both");
Console.WriteLine("PASS: classification->motion, motion->classification, repeated navigation, selected-pair retention, scoped invalidation and disposed JSON lifetime.");
string temp=Path.Combine(Path.GetTempPath(),"flowlens-session-"+Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(temp);
try
{
    string classDir=Path.Combine(temp,"classification"),motionDir=Path.Combine(temp,"motion");
    Directory.CreateDirectory(classDir);Directory.CreateDirectory(motionDir);
    File.WriteAllText(Path.Combine(classDir,"request.json"),"classification request");
    File.WriteAllText(Path.Combine(motionDir,"request.json"),"motion request");
    File.WriteAllText(Path.Combine(classDir,"classification.json"),"classification result");
    File.WriteAllText(Path.Combine(motionDir,"motion.csv"),"pair,velocity\n1,0.1");
    cache.StoreClassification(Data("classification"),classDir);cache.StoreMotion(Data("motion"),motionDir);cache.SelectedPair=4;
    string destination=Path.Combine(temp,"session.zip");
    SessionExporter.Write(destination,cache,"source.cine");
    using(var zip=System.IO.Compression.ZipFile.OpenRead(destination))
    {
        Check(zip.Entries.Count==5,"Combined export must include both analyses and session metadata");
        string Read(string name) { using var reader=new StreamReader(zip.GetEntry(name)!.Open());return reader.ReadToEnd(); }
        Check(Read("classification/request.json")=="classification request","Classification request must not collide with motion request");
        Check(Read("motion/request.json")=="motion request","Motion request must not collide with classification request");
        using var saved=JsonDocument.Parse(Read("session.json"));
        Check(saved.RootElement.GetProperty("selected_pair").GetInt32()==4,"Export must retain selected pair");
        Check(saved.RootElement.GetProperty("has_classification").GetBoolean()&&saved.RootElement.GetProperty("has_motion").GetBoolean(),"Export must identify both results");
    }
    string interfaceDir=Path.Combine(temp,"interface");Directory.CreateDirectory(interfaceDir);
    File.WriteAllText(Path.Combine(interfaceDir,"request.json"),"interface request");File.WriteAllText(Path.Combine(interfaceDir,"interface.json"),"interface result");
    cache.StoreInterface(Data("interface"),interfaceDir);cache.SelectedInterfaceFrame=2;
    SessionExporter.Write(destination,cache,"source.cine");
    using(var zip=System.IO.Compression.ZipFile.OpenRead(destination))
        Check(zip.Entries.Count==7&&zip.GetEntry("interface/request.json")!=null,"Session export must include the independent interface result");
    cache.StoreClassification(Data("classification-rerun"),classDir);cache.StoreMotion(Data("motion-rerun"),motionDir);
    Check(cache.Interface!=null&&cache.SelectedInterfaceFrame==2,"Motion/classification reruns must retain interface results and selection");
    cache.InvalidateInterface();Check(cache.Motion!=null&&cache.Classification!=null,"Interface invalidation must preserve other results");
    cache.InvalidateMotion();SessionExporter.Write(destination,cache,"source.cine");
    using(var zip=System.IO.Compression.ZipFile.OpenRead(destination))
        Check(zip.Entries.Count==3&&zip.GetEntry("motion/request.json")==null,"Classification-only export must exclude invalidated motion");
    cache.SkipInterface("FULL","No single layer interface");SessionExporter.Write(destination,cache,"source.cine");
    using(var zip=System.IO.Compression.ZipFile.OpenRead(destination))
    {
        Check(zip.GetEntry("interface/skip.json")!=null,"Skipped interface must have an explicit export record");
        using var reader=new StreamReader(zip.GetEntry("session.json")!.Open());using var state=JsonDocument.Parse(reader.ReadToEnd());
        Check(state.RootElement.GetProperty("interface_skipped").GetBoolean()&&!state.RootElement.GetProperty("has_interface").GetBoolean(),"Skip must not masquerade as a detected interface");
    }
    cache.InvalidateShared();Check(cache.InterfaceSkippedPattern==null,"Shared input change must clear a stale skip decision");
    Console.WriteLine("PASS: combined ZIP, colliding filenames, metadata, invalidation and explicit interface-skip export.");
}
finally { Directory.Delete(temp,true); }
await WorkflowTests.Run();
