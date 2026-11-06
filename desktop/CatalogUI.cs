using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace FlowLens;

public partial class MainWindow
{
    private sealed record Dataset(string Label,string? Path);
    private sealed record Option(double Value,string Label);
    private readonly List<Recording> recordings=[];
    private bool catalogUpdating;

    private void InitializeCatalog()
    {
        string data=Environment.GetEnvironmentVariable("FLOWLENS_DATA_DIR")??Path.Combine(root,"data");
        if(Directory.Exists(data))
        {
            try
            {
                foreach(var p in Directory.EnumerateFiles(data,"*.cine",SearchOption.AllDirectories).OrderBy(p=>p))
                    if(ExperimentCatalog.TryParse(Path.GetFileName(p),out double vm,out int wc)) recordings.Add(new(p,vm,wc));
            }
            catch(IOException) { }
            catch(UnauthorizedAccessException) { }
        }
        if(recordings.Count>0) Experiment.Items.Add(new Dataset("Experimental recordings",null));
        foreach(var name in new[]{"research-excerpt.npz","synthetic-translation.npz"})
        {
            string p=Path.Combine(root,"samples",name);
            if(File.Exists(p)) Experiment.Items.Add(new Dataset(name.StartsWith("research")?"Included research excerpt":"Synthetic validation",p));
        }
        if(Experiment.Items.Count>0) Experiment.SelectedIndex=0;
    }

    private async Task SelectDataset()
    {
        if(Experiment.SelectedItem is not Dataset dataset) return;
        bool experimental=dataset.Path==null;
        ConditionPanel.Visibility=experimental?Visibility.Visible:Visibility.Collapsed;
        if(!experimental) { await LoadSource(dataset.Path!); return; }
        catalogUpdating=true;
        var options=recordings.Select(r=>r.Vm).Distinct().OrderBy(v=>v).Select(v=>new Option(v,$"{v:0.0} m/s")).ToList();
        VmSelector.ItemsSource=options;
        VmSelector.SelectedItem=options.FirstOrDefault(o=>o.Value==.5)??options.FirstOrDefault();
        RefreshWaterCuts(40);
        catalogUpdating=false;
        await LoadCondition();
    }

    private void RefreshWaterCuts(int preferred)
    {
        if(VmSelector.SelectedItem is not Option vm) return;
        var options=recordings.Where(r=>r.Vm==vm.Value).Select(r=>r.Wc).Distinct().OrderBy(v=>v).Select(v=>new Option(v,$"{v}%")).ToList();
        WcSelector.ItemsSource=options;
        WcSelector.SelectedItem=options.FirstOrDefault(o=>o.Value==preferred)??options.FirstOrDefault();
    }

    private async void Vm_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(!IsLoaded||busy||catalogUpdating) return;
        int wc=WcSelector.SelectedItem is Option previous?(int)previous.Value:40;
        catalogUpdating=true; RefreshWaterCuts(wc); catalogUpdating=false;
        await LoadCondition();
    }

    private async void Wc_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(!IsLoaded||busy||catalogUpdating) return;
        await LoadCondition();
    }

    private async Task LoadCondition()
    {
        if(VmSelector.SelectedItem is not Option vm||WcSelector.SelectedItem is not Option wc) return;
        var matches=recordings.Where(r=>r.Vm==vm.Value&&r.Wc==(int)wc.Value).ToList();
        if(matches.Count!=1) { Error("This condition has multiple recordings. Use Open recording to choose a specific file."); return; }
        ConditionSummary.Text=$"Vm {vm.Value:0.0} m/s · WC {wc.Value:0}%";
        await LoadSource(matches[0].Path);
    }

    private void OpenExternal(string path)
    {
        var dataset=new Dataset("Opened recording",path);
        Experiment.Items.Add(dataset); Experiment.SelectedItem=dataset;
    }

    private void UpdateConditionSummary(JsonElement meta)
    {
        if(meta.TryGetProperty("experimental_conditions",out var c)&&c.ValueKind==JsonValueKind.Object)
            ConditionSummary.Text=$"Vm {c.GetProperty("mixture_velocity_m_per_s").GetDouble():0.0} m/s · WC {c.GetProperty("water_cut_percent").GetInt32()}%\nExperimental labels from filename";
        else ConditionSummary.Text="No Vm / WC experimental labels";
    }
}
