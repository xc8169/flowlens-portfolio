using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace FlowLens;

public partial class MainWindow
{
    private bool interfaceSliderMoving;
    private string InterfaceModels=>Path.Combine(root,"interface-models");
    private string ClassifiedPatternId=>session.Classification?.Data.GetProperty("prediction").GetProperty("id").GetString()??"";
    private string ClassifiedPatternName=>session.Classification?.Data.GetProperty("prediction").GetProperty("name").GetString()??"Not classified yet";
    private void InitializeInterface()
    {
        try
        {
            using var pointer=JsonDocument.Parse(File.ReadAllText(Path.Combine(InterfaceModels,"current.json")));
            string directory=pointer.RootElement.GetProperty("directory").GetString()!;
            using var document=JsonDocument.Parse(File.ReadAllText(Path.Combine(InterfaceModels,directory,"model_card.json")));
            var card=document.RootElement;var validation=card.GetProperty("validation");
            string evidence=validation.GetProperty("mean_absolute_error_px").ValueKind==JsonValueKind.Null?"Independent-video accuracy not established.":
                $"Held-out video MAE: {validation.GetProperty("mean_absolute_error_px").GetDouble():0.0} px · detected {100*validation.GetProperty("detected_fraction").GetDouble():0.0}% of annotated columns.";
            InterfaceModelStatus.Text=$"PyTorch boundary network · {card.GetProperty("positive_frames").GetInt32()} labelled frames / {card.GetProperty("videos").GetInt32()} videos\n{evidence}\nAuto uses NVIDIA CUDA when available; otherwise CPU.\nPredictions require review; scores are uncalibrated.";
        }
        catch(Exception) { InterfaceModelStatus.Text="Research model not included in this source portfolio. See docs/models.md to install your local model. The synthetic motion demo needs no model."; }
    }
    private void ResetInterfaceForSource()
    { ResetInterfaceTrackDisplay();RenderInterface(); }
    private void InterfaceCompute_Changed(object sender,SelectionChangedEventArgs e)
    {
        if(!IsLoaded||busy) return;
        session.InvalidateInterface();ResetInterfaceTrackDisplay();RenderInterface();UpdateControls();
        Status.Text="Interface compute changed · continue or re-run to calculate a new prediction";Progress.Value=0;
    }
    private void MotionAndInterfaceInputsChanged()
    {
        if(updating||busy) return;
        MotionInputsChanged();session.InvalidateInterface();ResetInterfaceTrackDisplay();RenderInterface();UpdateControls();
    }
    private void ResetInterfaceTrackDisplay()
    {
        if(InterfaceSlider==null) return;
        interfaceSliderMoving=true;InterfaceSlider.Value=0;interfaceSliderMoving=false;InterfaceSlider.IsEnabled=false;
        InterfaceOverlayCheck.IsChecked=false;
        InterfaceTimelineImage.Source=null;SetImage(InterfaceImage,previewPath);
        InterfaceResultText.Text="No saved interface prediction.";
        InterfaceCaption.Text="Continue starts interface detection for the selected frame range.";
    }
    private void UpdateInterfaceControls(bool ready)
    {
        bool saved=session.Interface!=null;
        InterfaceCompute.IsEnabled=ready;
        DetectInterfaceButton.IsEnabled=ready;RedetectInterfaceButton.IsEnabled=ready;InterfaceContinueButton.IsEnabled=ready;
        DetectInterfaceButton.Content=saved?"2. Show saved interface":session.InterfaceSkippedPattern!=null?"2. Interface skipped":"2. Detect interface";
        InterfaceSlider.IsEnabled=ready&&saved;InterfaceOverlayCheck.IsEnabled=saved;
        string pattern=ClassifiedPatternId;
        InterfacePatternText.Text="AI flow pattern: "+ClassifiedPatternName;
        ContinueButton.Content=string.IsNullOrEmpty(pattern)?"Classify and continue →":
            WorkflowNavigator.HasInterface(pattern)?"Continue to interface detection →":"Skip interface · continue to motion →";
    }
    private async void Interface_Click(object sender,RoutedEventArgs e)=>await AdvanceWorkflow(()=>navigation.OpenInterfaceAsync(false));
    private async void RedetectInterface_Click(object sender,RoutedEventArgs e)=>await AdvanceWorkflow(()=>navigation.OpenInterfaceAsync(true));
    private void SkipInterface(string pattern)
    {
        string reason="Interface detection skipped: AI classified "+ClassifiedPatternName+". This pattern has no single oil–water layer interface.";
        session.SkipInterface(pattern,reason);ResetInterfaceTrackDisplay();RenderInterface();UpdateControls();
        Status.Text="Interface skipped · starting motion analysis…";
    }
    private void RenderInterface()
    {
        InterfacePatternText.Text="AI flow pattern: "+ClassifiedPatternName;
        if(session.Interface!=null) { ShowInterfaceTrackFrame(session.SelectedInterfaceFrame);return; }
        SetImage(InterfaceImage,previewPath);InterfaceTimelineImage.Source=null;
        if(session.InterfaceSkipReason is string reason)
        {
            InterfaceResultText.Text=reason;InterfaceCaption.Text="Skipped automatically · continue to motion analysis.";
            if(WorkspaceTabs.SelectedIndex==1) Notes.Text=reason+" Motion analysis is available for this pattern.";
        }
        else
        {
            InterfaceResultText.Text="The bundled model will detect the interface in the selected range. Cyan curves and the time trace appear here.";
            InterfaceCaption.Text="Prediction only · shared ROI and frame settings are in Input & setup.";
            if(WorkspaceTabs.SelectedIndex==1) Notes.Text="Continue starts the next calculation automatically. Fully dispersed and fully mixed patterns skip interface detection.";
        }
    }
    private async Task<bool> DetectInterfaceAsync(bool force)
    {
        if(busy||source==null||metadata==null) return false;
        StopPlayback();WorkspaceTabs.SelectedIndex=1;
        if(!force&&session.Interface!=null)
        { RenderInterface();Status.Text="Showing saved interface results · no processing required";return true; }
        try
        {
            if(!WorkflowNavigator.HasInterface(ClassifiedPatternId)) throw new InvalidOperationException("This pattern skips interface detection.");
            bool completed=false;var r=Range();int[] roi=[Int(RoiX,"ROI X"),Int(RoiY,"ROI Y"),Int(RoiW,"ROI width"),Int(RoiH,"ROI height")];double scale=Num(Scale,"Spatial scale");
            string dir=NewRun("interface-tracking");activeDir=dir;cancelRequested=false;
            string request=WriteRequest(dir,new { source,output=dir,start=r.Start,pairs=r.Pairs,pair_step=r.Step,roi,pattern=ClassifiedPatternId,
                pattern_source="AI flow-pattern classification",models_dir=InterfaceModels,device=InterfaceCompute.SelectedIndex==1?"cpu":"auto",fps=Num(Fps,"FPS"),mm_per_pixel=scale,
                calibration_confirmed=CalibrationConfirmed.IsChecked==true,calibration_is_approximate=Math.Abs(scale-50.0/600)<1e-9 });
            SetBusy(true,"Detecting interface with your trained model…",true);
            await worker.RunAsync("interface-track",request,ev=>
            {
                ProgressEvent(ev);if(ev.GetProperty("type").GetString()!="interface_result"||cancelRequested) return;
                session.StoreInterface(ev.GetProperty("result"),dir);completed=true;interfaceSliderMoving=true;
                InterfaceSlider.Maximum=ev.GetProperty("result").GetProperty("frames").GetArrayLength()-1;interfaceSliderMoving=false;
                SetImage(InterfaceTimelineImage,Path.Combine(dir,"interface_timeline.png"));ShowInterfaceTrackFrame(0);InterfaceOverlayCheck.IsChecked=true;
                Progress.Value=100;Status.Text="Interface saved · continue to motion analysis";
            });
            if(cancelRequested) Status.Text="Interface detection cancelled · later stages were not started";
            return completed&&!cancelRequested;
        }
        catch(Exception ex) { Error(ex.Message);return false; }
        finally { activeDir=null;SetBusy(false); }
    }
    private void ShowInterfaceTrackFrame(int index)
    {
        if(session.Interface is not SavedAnalysis saved) return;
        var data=saved.Data;var frames=data.GetProperty("frames");index=Math.Clamp(index,0,frames.GetArrayLength()-1);session.SelectedInterfaceFrame=index;
        var f=frames[index];SetImage(InterfaceImage,Path.Combine(saved.Directory,f.GetProperty("preview").GetString()!));
        SetImage(InterfaceTimelineImage,Path.Combine(saved.Directory,"interface_timeline.png"));
        interfaceSliderMoving=true;InterfaceSlider.Value=index;interfaceSliderMoving=false;
        string row=f.GetProperty("median_row_px").ValueKind==JsonValueKind.Null?"No reliable boundary detected":$"Median image row: {f.GetProperty("median_row_px").GetDouble():0.0} px (downward)";
        string displacement=f.GetProperty("displacement_mm").ValueKind==JsonValueKind.Null?"":$"\nRelative displacement: {(data.GetProperty("calibration_approximate").GetBoolean()?"≈ ":"")}{f.GetProperty("displacement_mm").GetDouble():+0.00;-0.00;0.00} mm";
        var runtime=data.GetProperty("runtime");
        string compute=$"{runtime.GetProperty("backend").GetString()} · {runtime.GetProperty("device_name").GetString()}";
        string fallback=runtime.GetProperty("fallback_reason").ValueKind==JsonValueKind.Null?"":"\n"+runtime.GetProperty("fallback_reason").GetString();
        InterfaceResultText.Text=compute+fallback+"\n"+row+displacement+$"\nAccepted columns: {100*f.GetProperty("coverage").GetDouble():0.0}%\nModel score: {100*f.GetProperty("model_score").GetDouble():0.0}% (uncalibrated)\nReview required."+
            (data.GetProperty("training_source").GetBoolean()?"\nThis video contributed training labels.":"")+
            (data.GetProperty("unseen_pattern").GetBoolean()?"\nThis pattern was not represented in the model's boundary labels.":"");
        InterfaceCaption.Text=$"Sample {index+1}/{frames.GetArrayLength()} · original frame {f.GetProperty("original_frame").GetInt32():N0} · cyan = predicted interface";
        if(WorkspaceTabs.SelectedIndex==1) Notes.Text="Review the predicted boundary, then Continue starts motion analysis automatically. Displacement is relative image motion, not water-layer height.";
        UpdateControls();
    }
    private void InterfaceSlider_Changed(object sender,RoutedPropertyChangedEventArgs<double> e)
    { if(IsLoaded&&!interfaceSliderMoving&&session.Interface!=null) ShowInterfaceTrackFrame((int)e.NewValue); }
    private string InterfaceOverlayPath(int frame,string fallback)
    {
        if(InterfaceOverlayCheck.IsChecked!=true||session.Interface is not SavedAnalysis saved) return fallback;
        foreach(var f in saved.Data.GetProperty("frames").EnumerateArray())
            if(f.GetProperty("frame").GetInt32()==frame) return Path.Combine(saved.Directory,f.GetProperty("preview").GetString()!);
        return fallback;
    }
    private void InterfaceOverlay_Changed(object sender,RoutedEventArgs e)
    { if(IsLoaded&&session.Motion!=null&&!busy) ShowPair(session.SelectedPair,!playbackTimer.IsEnabled); }
}
