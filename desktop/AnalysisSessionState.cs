using System.Text.Json;

namespace FlowLens;

public sealed record SavedAnalysis(JsonElement Data,string Directory);

/// <summary>Independent caches. Navigation never mutates either result.</summary>
public sealed class AnalysisSessionState
{
    public SavedAnalysis? Motion { get; private set; }
    public SavedAnalysis? Classification { get; private set; }
    public SavedAnalysis? Interface { get; private set; }
    public string? InterfaceSkippedPattern { get; private set; }
    public string? InterfaceSkipReason { get; private set; }
    public void SkipInterface(string pattern,string reason) { InvalidateInterface();InterfaceSkippedPattern=pattern;InterfaceSkipReason=reason; }
    public int SelectedInterfaceFrame { get; set; }
    public void StoreInterface(JsonElement data,string directory) { Interface=new(data.Clone(),directory);InterfaceSkippedPattern=null;InterfaceSkipReason=null;SelectedInterfaceFrame=0; }
    public void InvalidateInterface() { Interface=null;InterfaceSkippedPattern=null;InterfaceSkipReason=null;SelectedInterfaceFrame=0; }
    public int SelectedPair { get; set; }
    public void StoreMotion(JsonElement data,string directory) { Motion=new(data.Clone(),directory);SelectedPair=0; }
    public void StoreClassification(JsonElement data,string directory) { Classification=new(data.Clone(),directory); }
    public void InvalidateMotion() { Motion=null;SelectedPair=0; }
    public void InvalidateClassification() => Classification=null;
    public void InvalidateShared() { InvalidateMotion();InvalidateClassification();InvalidateInterface(); }
}
