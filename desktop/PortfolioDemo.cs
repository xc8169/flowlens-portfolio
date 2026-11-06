using System.IO;
using System.Text.Json;

namespace FlowLens;

public partial class MainWindow
{
    // Synthetic validation is a separate path. It never fabricates an AI class.
    private bool IsSyntheticSource => metadata is JsonElement data
        && data.TryGetProperty("provenance", out var provenance)
        && provenance.TryGetProperty("kind", out var kind)
        && kind.GetString() == "synthetic validation";

    private bool ResearchModelsAvailable => File.Exists(Path.Combine(root, "model", "visual_forest.npz"))
        && File.Exists(Path.Combine(root, "interface-models", "current.json"));

    private async Task RunSyntheticMotionAsync()
    {
        if (!IsSyntheticSource || busy) return;
        if (!await AnalyzeAsync(false)) return;
        Status.Text = "Synthetic motion validation complete · AI classification/interface inference were not run";
        Notes.Text = "Generated texture moves +2 px/source frame. Default timing/scale (100 fps, 0.1 mm/px) gives 0.020 m/s; edited settings change that conversion. This does not validate research model accuracy.";
    }
}
