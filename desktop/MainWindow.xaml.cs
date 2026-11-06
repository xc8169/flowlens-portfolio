using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using Microsoft.Win32;

namespace FlowLens;

public partial class MainWindow : Window
{
    private sealed record Recording(string Path,double Vm,int Wc);
    private sealed record PatternRank(string Label,string Score);
    private readonly string root;
    private readonly WorkerClient worker;
    private readonly WorkflowNavigator navigation;
    private readonly AnalysisSessionState session=new();
    private JsonElement? metadata,timeline;
    private string? source,previewPath,activeDir;
    private bool busy,updating,cancelRequested,dragging;
    private Point dragStart;
    private int imageWidth,imageHeight;
    private static readonly CultureInfo Inv=CultureInfo.InvariantCulture;

    public MainWindow()
    {
        InitializeComponent();root=FindRoot();worker=new(root);
        navigation=new(EnsureClassificationAsync,()=>ClassifiedPatternId,DetectInterfaceAsync,AnalyzeAsync,SkipInterface);
        InitializePlayback();Loaded+=OnLoaded;
    }
    private static string FindRoot()
    {
        DirectoryInfo? d=new(AppContext.BaseDirectory);
        while(d!=null) { if(Directory.Exists(Path.Combine(d.FullName,"engine"))) return d.FullName;d=d.Parent; }
        return AppContext.BaseDirectory;
    }
    private void OnLoaded(object sender,RoutedEventArgs e)
    {
        foreach(var box in new[]{StartFrame,PairCount,FrameGap,PairStep,Fps}) box.TextChanged+=(_,_)=>SharedInputsChanged();
        foreach(var box in new[]{RoiX,RoiY,RoiW,RoiH,Scale}) box.TextChanged+=(_,_)=>MotionAndInterfaceInputsChanged();
        WindowSize.SelectionChanged+=(_,_)=>MotionInputsChanged();
        CalibrationConfirmed.Checked+=(_,_)=>MotionAndInterfaceInputsChanged();CalibrationConfirmed.Unchecked+=(_,_)=>MotionAndInterfaceInputsChanged();
        InitializeInterface();InitializeCatalog();UpdateControls();
    }
    private void SharedInputsChanged()
    {
        if(updating||busy) return;
        StopPlayback();session.InvalidateShared();timeline=null;ClearVideoCache();ResetMotionDisplay();ResetInterfaceTrackDisplay();RenderClassification();UpdateControls();
        Status.Text="Frame range or timing changed · run the workflow for the new selection";
        Notes.Text="Classify flow, continue to interface detection (or skip), then continue to motion analysis.";
    }
    private void MotionInputsChanged()
    {
        if(updating||busy) return;
        StopPlayback();session.InvalidateMotion();timeline=null;ResetMotionDisplay();DrawRegion();UpdateControls();
        Status.Text=session.Classification!=null?"Motion settings changed · saved classification kept":"Motion settings changed";
        Notes.Text="Choose the analysis region and run step 3 for the new motion settings. Any saved classification remains available in step 1.";
    }
    private async void Experiment_SelectionChanged(object sender,SelectionChangedEventArgs e)
    { if(IsLoaded&&!busy&&!catalogUpdating) await SelectDataset(); }
    private void Open_Click(object sender,RoutedEventArgs e)
    {
        var dlg=new OpenFileDialog { Title="Open experimental recording",Filter="Video or excerpt|*.cine;*.mp4;*.avi;*.mov;*.mkv;*.npz|All files|*.*" };
        if(dlg.ShowDialog(this)==true) OpenExternal(dlg.FileName);
    }
    private async Task LoadSource(string path)
    {
        StopPlayback();session.InvalidateShared();timeline=null;metadata=null;source=path;previewPath=null;ClearVideoCache();
        imageWidth=imageHeight=0;VideoImage.Source=null;VideoHeading.Text="VIDEO / SELECT REGION";VideoFrameInfo.Text="";updating=true;StartFrame.Text="0";Scale.Text="0";CalibrationConfirmed.IsChecked=false;updating=false;
        ResetMotionDisplay();ClassificationImage.Source=null;RenderClassification();SourceLabel.Text=Path.GetFileName(path);
        WorkspaceTabs.SelectedIndex=0;await Probe(0,true);ResetInterfaceForSource();RenderClassification();
    }
    private string NewRun(string kind)
    {
        string dir=Path.Combine(root,"runs",kind+"-"+DateTime.Now.ToString("yyyyMMdd-HHmmss-fff")+"-"+Guid.NewGuid().ToString("N")[..6]);
        Directory.CreateDirectory(dir);return dir;
    }
    private async Task Probe(int frame,bool fresh)
    {
        if(source==null||busy) return;
        string dir=NewRun("preview");string file=WriteRequest(dir,new { source,frame,output=dir });SetBusy(true,"Reading recording…");
        try
        {
            await worker.RunAsync("probe",file,ev=>
            {
                if(ev.GetProperty("type").GetString()!="metadata") return;
                metadata=ev.GetProperty("metadata").Clone();var m=metadata.Value;
                imageWidth=m.GetProperty("width").GetInt32();imageHeight=m.GetProperty("height").GetInt32();previewPath=m.GetProperty("preview").GetString();
                if(fresh)
                {
                    updating=true;Fps.Text=m.GetProperty("fps").GetDouble().ToString("0.###",Inv);PairCount.Text=Math.Min(20,m.GetProperty("frame_count").GetInt32()-1).ToString(Inv);
                    FrameGap.Text="1";PairStep.Text="1";RoiX.Text="0";RoiY.Text="0";RoiW.Text=imageWidth.ToString(Inv);RoiH.Text=imageHeight.ToString(Inv);
                    if(m.GetProperty("name").GetString()=="research-excerpt.npz"&&imageWidth==1024&&imageHeight==700) { RoiX.Text="300";RoiY.Text="100";RoiW.Text="724";RoiH.Text="500"; }
                    bool research=m.TryGetProperty("experimental_conditions",out var c)&&c.ValueKind==JsonValueKind.Object;
                    Scale.Text=research?(50.0/600).ToString("R",Inv):"0";CalibrationConfirmed.IsChecked=research&&m.GetProperty("fps").GetDouble()>0;updating=false;
                    if(IsSyntheticSource) { updating=true;Scale.Text="0.1";CalibrationConfirmed.IsChecked=true;updating=false; }
                }
                SourceLabel.Text=$"{m.GetProperty("name").GetString()}\n{imageWidth} × {imageHeight} px · {m.GetProperty("frame_count").GetInt32():N0} frames · {m.GetProperty("fps").GetDouble():0.###} fps";
                UpdateConditionSummary(m);SetImage(VideoImage,previewPath);VideoHeading.Text=$"VIDEO · PREVIEW FRAME {frame:N0}";VideoFrameInfo.Text=$"Preview frame {frame:N0}";DrawRegion();
                if(session.Classification==null) SetImage(ClassificationImage,previewPath);
                if(fresh) Dispatcher.BeginInvoke(()=>SetupScroll.ScrollToTop());
            });
            Status.Text="Ready · classify flow → detect interface or skip → analyze motion";
        }
        catch(Exception ex) { Error(ex.Message); }
        finally { SetBusy(false); }
    }
    private async void Preview_Click(object sender,RoutedEventArgs e)
    {
        try
        {
            StopPlayback();WorkspaceTabs.SelectedIndex=2;
            if(session.Motion!=null) { showFrameB=false;ShowPair(0);Status.Text="Showing saved first pair · no processing required"; }
            else await Probe(Int(StartFrame,"Start frame"),false);
        }
        catch(Exception ex) { Error(ex.Message); }
    }
    private async void Continue_Click(object sender,RoutedEventArgs e)
    {
        if(IsSyntheticSource) await RunSyntheticMotionAsync();
        else await AdvanceWorkflow(navigation.ContinueFromClassificationAsync);
    }
    private async void ContinueToMotion_Click(object sender,RoutedEventArgs e)=>await AdvanceWorkflow(navigation.ContinueFromInterfaceAsync);
    private async Task AdvanceWorkflow(Func<Task<bool>> action)
    {
        if(busy||navigation.IsAdvancing||metadata==null) return;
        StopPlayback();
        try { await action(); } catch(Exception ex) { Error(ex.Message); }
        finally { UpdateControls(); }
    }
    private Task<bool> EnsureClassificationAsync()=>session.Classification!=null?Task.FromResult(true):ClassifyAsync(false);
    private static int Int(TextBox box,string name)
    { if(!int.TryParse(box.Text,NumberStyles.Integer,Inv,out int v)) throw new ArgumentException(name+" must be a whole number.");return v; }
    private static double Num(TextBox box,string name)
    { if(!double.TryParse(box.Text,NumberStyles.Float,Inv,out double v)||!double.IsFinite(v)||v<0) throw new ArgumentException(name+" must be a finite nonnegative number.");return v; }
    private (int Start,int Pairs,int Gap,int Step) Range()
    {
        if(metadata==null) throw new ArgumentException("Choose a recording first.");
        int start=Int(StartFrame,"Start frame"),pairs=Int(PairCount,"Pairs"),gap=Int(FrameGap,"Frame gap"),step=Int(PairStep,"Pair spacing");
        if(pairs<1||pairs>200||gap<1||gap>100||step<1||step>100000||start<0||(long)start+(long)(pairs-1)*step+gap>=metadata.Value.GetProperty("frame_count").GetInt32())
            throw new ArgumentException("Choose 1–200 pairs and a valid frame range within the recording.");
        return(start,pairs,gap,step);
    }
    private static string WriteRequest(string dir,object request)
    { string path=Path.Combine(dir,"request.json");File.WriteAllText(path,JsonSerializer.Serialize(request,new JsonSerializerOptions { WriteIndented=true }));return path; }
    private void ProgressEvent(JsonElement ev)
    {
        string? type=ev.GetProperty("type").GetString();
        if(type=="progress") { Progress.Value=ev.GetProperty("progress").GetInt32();Status.Text=ev.GetProperty("message").GetString(); }
        else if(type=="cancelled") cancelRequested=true;
    }
    private async void Classify_Click(object sender,RoutedEventArgs e)=>await ClassifyAsync(false);
    private async void Reclassify_Click(object sender,RoutedEventArgs e)=>await ClassifyAsync(true);
    private async Task<bool> ClassifyAsync(bool force)
    {
        if(busy||source==null||metadata==null) return false;
        StopPlayback();WorkspaceTabs.SelectedIndex=0;
        if(!force&&session.Classification!=null) { RenderClassification();Status.Text="Showing saved classification · no processing required";return true; }
        try
        {
            string oldPattern=ClassifiedPatternId;bool completed=false;var r=Range();string dir=NewRun("classification");activeDir=dir;cancelRequested=false;
            string file=WriteRequest(dir,new { source,output=dir,start=r.Start,pairs=r.Pairs,gap=r.Gap,pair_step=r.Step,fps=Num(Fps,"FPS"),model_dir=Path.Combine(root,"model") });
            SetBusy(true,"Classifying the flow pattern…",true);
            await worker.RunAsync("classify",file,ev=>
            {
                ProgressEvent(ev);
                if(ev.GetProperty("type").GetString()=="classification"&&!cancelRequested)
                { session.StoreClassification(ev.GetProperty("result"),dir);if(oldPattern!=ClassifiedPatternId) { session.InvalidateInterface();ResetInterfaceTrackDisplay(); }
                    completed=true;RenderClassification();Progress.Value=100;Status.Text="Classification saved · continue to interface detection (or skip)"; }
            });
            if(cancelRequested) Status.Text="Classification cancelled · any previous saved results kept";
            return completed&&!cancelRequested;
        }
        catch(Exception ex) { Error(ex.Message);return false; }
        finally { activeDir=null;SetBusy(false); }
    }
    private async void Analyze_Click(object sender,RoutedEventArgs e)
    {
        if(IsSyntheticSource) await RunSyntheticMotionAsync();
        else await AdvanceWorkflow(()=>navigation.OpenMotionAsync(false));
    }
    private async void Reanalyze_Click(object sender,RoutedEventArgs e)=>await AdvanceWorkflow(()=>navigation.OpenMotionAsync(true));
    private async Task<bool> AnalyzeAsync(bool force)
    {
        if(busy||source==null||metadata==null) return false;
        StopPlayback();WorkspaceTabs.SelectedIndex=2;
        if(!force&&session.Motion!=null) { ShowPair(session.SelectedPair);Status.Text="Showing saved motion results · no processing required";return true; }
        try
        {
            bool completed=false;var r=Range();int[] roi=[Int(RoiX,"ROI X"),Int(RoiY,"ROI Y"),Int(RoiW,"ROI width"),Int(RoiH,"ROI height")];
            if(roi[0]<0||roi[1]<0||roi[2]<16||roi[3]<16||(long)roi[0]+roi[2]>imageWidth||(long)roi[1]+roi[3]>imageHeight) throw new ArgumentException("The analysis region must fit inside the image and be at least 16 × 16 pixels.");
            double fps=Num(Fps,"FPS"),scale=Num(Scale,"Millimeters per pixel");bool physical=CalibrationConfirmed.IsChecked==true;
            if(physical&&(fps<=0||scale<=0)) throw new ArgumentException("Physical velocity needs positive FPS and spatial scale.");
            string dir=NewRun("motion");activeDir=dir;cancelRequested=false;
            string file=WriteRequest(dir,new { source,output=dir,start=r.Start,pairs=r.Pairs,gap=r.Gap,pair_step=r.Step,roi,fps,mm_per_pixel=scale,calibration_confirmed=physical,
                calibration_basis=Math.Abs(scale-50.0/600)<1e-9?"User supplied pipe ID 50 mm across approximately 600 original image pixels":"User entered spatial scale",calibration_is_approximate=Math.Abs(scale-50.0/600)<1e-9,
                winsize=int.Parse(((ComboBoxItem)WindowSize.SelectedItem).Content.ToString()!,Inv) });
            SetBusy(true,"Analyzing motion and preparing synchronized views…",true);
            await worker.RunAsync("analyze",file,ev=>
            {
                ProgressEvent(ev);
                if(ev.GetProperty("type").GetString()=="result"&&!cancelRequested)
                { session.StoreMotion(ev.GetProperty("result"),dir);completed=true;LoadMotion();Progress.Value=100;Status.Text="Motion saved · video, vectors and profile synchronized; classification kept"; }
            });
            if(cancelRequested) Status.Text="Motion analysis cancelled · any previous saved results kept";
            return completed&&!cancelRequested;
        }
        catch(Exception ex) { Error(ex.Message);return false; }
        finally { activeDir=null;SetBusy(false); }
    }
    private void SetBusy(bool value,string? message=null,bool allowCancel=false)
    {
        busy=value;InputPanel.IsEnabled=!value;CancelButton.IsEnabled=value&&allowCancel;
        if(value) StopPlayback();
        if(message!=null) { Status.Text=message;Progress.Value=0; }
        UpdateControls();
    }
    private void UpdateControls()
    {
        if(!IsLoaded) return;
        bool ready=!busy&&!navigation.IsAdvancing&&metadata!=null,hasMotion=session.Motion!=null,hasClass=session.Classification!=null;
        ClassifyButton.IsEnabled=ready;AnalyzeButton.IsEnabled=ready;ContinueButton.IsEnabled=ready;
        ClassifyButton.Content=hasClass?"1. Show saved classification":"1. Classify flow pattern";
        AnalyzeButton.Content=hasMotion?"3. Show saved motion":"3. Analyze droplet motion";
        ReclassifyButton.IsEnabled=ready;ReanalyzeButton.IsEnabled=ready;
        ClassificationTab.Header=hasClass?"1. Flow classification  ✓":"1. Flow classification";MotionTab.Header=hasMotion?"3. Droplet motion  ✓":"3. Droplet motion";
        InterfaceTab.Header=session.Interface!=null?"2. Interface detection  ✓":session.InterfaceSkippedPattern!=null?"2. Interface detection · skipped":"2. Interface detection";
        UpdateInterfaceControls(ready);
        ClassifyButton.IsEnabled=ready&&ResearchModelsAvailable&&!IsSyntheticSource;
        ReclassifyButton.IsEnabled=ClassifyButton.IsEnabled;
        AnalyzeButton.IsEnabled=ready&&(IsSyntheticSource||ResearchModelsAvailable);
        DetectInterfaceButton.IsEnabled=ready&&ResearchModelsAvailable&&!IsSyntheticSource;
        RedetectInterfaceButton.IsEnabled=DetectInterfaceButton.IsEnabled;
        InterfaceContinueButton.IsEnabled=DetectInterfaceButton.IsEnabled;
        ContinueButton.IsEnabled=ready&&(IsSyntheticSource||ResearchModelsAvailable);
        if(IsSyntheticSource)
        {
            AnalyzeButton.Content=hasMotion?"Show synthetic motion result":"Run synthetic motion demo";
            ContinueButton.Content="Run synthetic motion demo →";
        }
        WorkflowStatus.Text=$"Classification: {(hasClass?"saved":"not run")} · Interface: {(session.Interface!=null?"saved":session.InterfaceSkippedPattern!=null?"skipped":"not run")} · Motion: {(hasMotion?"saved":"not run")}";
        PlayButton.IsEnabled=ready&&hasMotion;PreviousPairButton.IsEnabled=ready&&hasMotion;NextPairButton.IsEnabled=ready&&hasMotion;ShowFrameBButton.IsEnabled=ready&&hasMotion;PairSlider.IsEnabled=ready&&hasMotion;TrendsExpander.IsEnabled=hasMotion;
        SelectionCanvas.IsHitTestVisible=ready;ExportButton.IsEnabled=!busy&&(hasMotion||hasClass||session.Interface!=null);ResultsButton.IsEnabled=ExportButton.IsEnabled;
        PatternSummary.Text=hasClass?"Flow pattern: "+session.Classification!.Data.GetProperty("prediction").GetProperty("code").GetString()+" · experimental prediction, review required":"Flow classification has not been run";
        if(IsSyntheticSource) PatternSummary.Text="Synthetic validation · no AI classification or interface prediction";
    }
    private void WorkspaceTabs_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(!IsLoaded||!ReferenceEquals(e.Source,WorkspaceTabs)) return;
        StopPlayback();
        if(WorkspaceTabs.SelectedIndex==0) RenderClassification();
        else if(WorkspaceTabs.SelectedIndex==1) RenderInterface();
        else if(session.Motion!=null) ShowPair(session.SelectedPair);
        else { DrawRegion();Notes.Text="Continue starts motion analysis automatically. Optical flow measures image-feature motion."; }
        UpdateControls();
    }
    private void RenderClassification()
    {
        if(session.Classification is not SavedAnalysis saved)
        {
            if(IsSyntheticSource)
            {
                AIPredictionText.Text="Synthetic motion validation";
                ClassificationDecision.Text="Generated texture · +2 pixels per source frame";
                KnownPatternText.Text="Run the motion demo without research recordings or model weights.";
                ClassScoreText.Text="No AI classification is performed on this generated example.";
                TrainingSourceText.Text="";RankingItems.ItemsSource=null;
                ValidationText.Text="Research classification and interface detection require optional local model assets. See docs/models.md.";
                SetImage(ClassificationImage,previewPath);
                Notes.Text="Expected motion: +2 px/source frame. At 100 fps and 0.1 mm/px, expected image velocity is 0.020 m/s.";
                return;
            }
            AIPredictionText.Text="Run step 1 to classify the selected range";KnownPatternText.Text="The image prediction and known experimental label will be displayed separately.";
            ClassificationDecision.Text="Experimental model · review required";
            ClassScoreText.Text="";TrainingSourceText.Text="";RankingItems.ItemsSource=null;ValidationText.Text="Experimental classifier; all predictions require review.";
            if(WorkspaceTabs.SelectedIndex==0) Notes.Text="Run flow classification, then Continue starts interface detection (or skips it) and advances the workflow.";
            SetImage(ClassificationImage,previewPath);return;
        }
        var r=saved.Data;AIPredictionText.Text=r.GetProperty("prediction").GetProperty("name").GetString();ClassificationDecision.Text=r.GetProperty("decision").GetString();
        ClassScoreText.Text=$"Model score: {100*r.GetProperty("model_score").GetDouble():0.0}% · uncalibrated, not accuracy\n{r.GetProperty("clips").GetArrayLength()} sampled clips; image features only";
        var known=r.GetProperty("known_experimental_label");KnownPatternText.Text=known.ValueKind==JsonValueKind.Null?"Known experimental label: not supplied":
            "Known experimental label (Vm/WC):\n"+known.GetProperty("name").GetString()+"\n"+(r.GetProperty("agrees_with_known_label").GetBoolean()?"Matches the supplied label.":"Differs from the supplied label; review the images.");
        RankingItems.ItemsSource=r.GetProperty("rankings").EnumerateArray().Take(3).Select(p=>new PatternRank(p.GetProperty("name").GetString()!, (100*p.GetProperty("score").GetDouble()).ToString("0.0",Inv)+"%"));
        TrainingSourceText.Text=r.GetProperty("training_source_note").GetString();
        var evaluation=r.GetProperty("evaluation");ValidationText.Text=$"Held-out-recording clip accuracy: {100*evaluation.GetProperty("held_out_recording_clip_accuracy").GetDouble():0.0}% on 12/16 eligible recordings. Four classes have only one recording and cannot be independently evaluated.";
        SetImage(ClassificationImage,Path.Combine(saved.Directory,r.GetProperty("preview").GetString()!));
        if(WorkspaceTabs.SelectedIndex==0) Notes.Text="Experimental classifier: use the prediction for review. Changing only motion ROI, optical-flow parameters or calibration keeps this classification. Both saved results are included when exporting.";
    }
    private static void SetImage(Image target,string? path)
    {
        if(path==null||!File.Exists(path)) { target.Source=null;return; }
        var im=new BitmapImage();im.BeginInit();im.CacheOption=BitmapCacheOption.OnLoad;im.UriSource=new Uri(Path.GetFullPath(path));im.EndInit();im.Freeze();target.Source=im;
    }
    private void Error(string message)
    { Status.Text="Could not complete the request · "+message;MessageBox.Show(this,message,"FlowLens",MessageBoxButton.OK,MessageBoxImage.Information); }
    private void Cancel_Click(object sender,RoutedEventArgs e)
    { if(activeDir==null) return;cancelRequested=true;File.WriteAllText(Path.Combine(activeDir,"cancel.flag"),"cancel");CancelButton.IsEnabled=false;Status.Text="Cancelling after the current processing step…"; }
    private void Window_Closing(object? sender,CancelEventArgs e) { StopPlayback();worker.Stop(); }
}
