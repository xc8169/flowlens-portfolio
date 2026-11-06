using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace FlowLens;

public partial class MainWindow
{
    private sealed record ClipFrame(string File,int Frame,int OriginalFrame,double? Seconds);
    private readonly List<ClipFrame> clips=[];
    private readonly DispatcherTimer playbackTimer=new(DispatcherPriority.Background) { Interval=TimeSpan.FromMilliseconds(20) };
    private readonly Stopwatch playbackClock=new();
    private bool movingPairSlider,showFrameB;
    private int clipIndex,clipStride=1;
    private double playbackOrigin;

    private void InitializePlayback()=>playbackTimer.Tick+=PlaybackTick;
    private void StopPlayback()
    { playbackTimer.Stop();playbackClock.Stop();if(PlayButton!=null) PlayButton.Content="▶ Play"; }
    private void ClearVideoCache() { StopPlayback();clips.Clear();clipIndex=0; }
    private void ResetMotionDisplay()
    {
        VectorImage.Source=null;VectorHeading.Text="MOTION VECTORS";MotionValue.Text="—";VelocityValue.Text="—";CoverageValue.Text="—";
        PairChart.SetProfile([],[],[],[],0,1,"m/s",false);
        movingPairSlider=true;PairSlider.Value=0;movingPairSlider=false;PairSlider.IsEnabled=false;
        PairInfo.Text="No saved motion result";PairCaption.Text="Run motion analysis once; all three views stay synchronized.";
        TimelineImage.Source=null;TraceImage.Source=null;TrendsExpander.IsEnabled=false;
    }
    private void LoadMotion()
    {
        if(session.Motion is not SavedAnalysis saved) return;
        using var doc=JsonDocument.Parse(File.ReadAllText(Path.Combine(saved.Directory,saved.Data.GetProperty("timeline").GetProperty("data").GetString()!)));
        timeline=doc.RootElement.Clone();
        movingPairSlider=true;PairSlider.Maximum=timeline.Value.GetProperty("pairs").GetArrayLength()-1;PairSlider.Value=0;movingPairSlider=false;
        showFrameB=false;SetImage(TimelineImage,Path.Combine(saved.Directory,"profile_timeline.png"));SetImage(TraceImage,Path.Combine(saved.Directory,"velocity_vs_time.png"));
        ShowPair(0);DrawRegion();UpdateControls();
    }
    private static double?[] Values(JsonElement array)=>array.EnumerateArray().Select(v=>v.ValueKind==JsonValueKind.Null?(double?)null:v.GetDouble()).ToArray();
    private void ShowPair(int index,bool updateVideo=true)
    {
        if(timeline is not JsonElement data||session.Motion is not SavedAnalysis saved) return;
        var pairs=data.GetProperty("pairs");index=Math.Clamp(index,0,pairs.GetArrayLength()-1);session.SelectedPair=index;
        movingPairSlider=true;PairSlider.Value=index;movingPairSlider=false;
        var pair=pairs[index];var profile=data.GetProperty("profiles")[index];
        if(updateVideo)
        {
            string key=showFrameB?"frame_b_preview":"frame_preview";
            SetImage(VideoImage,InterfaceOverlayPath(pair.GetProperty(showFrameB?"frame_b":"frame_a").GetInt32(),Path.Combine(saved.Directory,pair.GetProperty(key).GetString()!)));
            int number=pair.GetProperty(showFrameB?"original_frame_b":"original_frame_a").GetInt32();
            VideoHeading.Text="VIDEO · FRAME "+number.ToString("N0");VideoFrameInfo.Text="Selected pair frame "+(showFrameB?"B":"A");
        }
        SetImage(VectorImage,Path.Combine(saved.Directory,pair.GetProperty("vector_preview").GetString()!));
        VectorHeading.Text=$"VECTORS · {pair.GetProperty("original_frame_a").GetInt32():N0} → {pair.GetProperty("original_frame_b").GetInt32():N0}";
        int[] rows=data.GetProperty("rows").EnumerateArray().Select(v=>v.GetInt32()).ToArray();
        PairChart.SetProfile(Values(profile.GetProperty("median")),Values(profile.GetProperty("top10")),Values(data.GetProperty("average").GetProperty("median")),rows,
            data.GetProperty("x_min").GetDouble(),data.GetProperty("x_max").GetDouble(),data.GetProperty("units").GetString()!,CompareReference.IsChecked==true);
        var time=pair.GetProperty("midpoint_seconds_from_start");string timeLabel=time.ValueKind==JsonValueKind.Null?"time unavailable":$"t = {time.GetDouble():0.0000} s";
        PairInfo.Text=$"Pair {index+1}/{pairs.GetArrayLength()} · {timeLabel}";
        PairCaption.Text=$"Vectors and profile: frames {pair.GetProperty("original_frame_a").GetInt32():N0} → {pair.GetProperty("original_frame_b").GetInt32():N0} · timestamp at pair midpoint · fixed profile axes";
        var m=pair.GetProperty("median_dx_px_per_source_frame");var velocity=pair.GetProperty("velocity_m_per_s");
        MotionValue.Text=m.ValueKind==JsonValueKind.Null?"No texture":m.GetDouble().ToString("+0.000;-0.000;0.000",Inv)+" px/frame";
        VelocityValue.Text=velocity.ValueKind==JsonValueKind.Null?(data.GetProperty("physical_units").GetBoolean()?"No texture":"Not calibrated"):
            (data.GetProperty("calibration_approximate").GetBoolean()?"≈ ":"")+velocity.GetDouble().ToString("0.0000",Inv)+" m/s";
        CoverageValue.Text=(100*pair.GetProperty("texture_coverage").GetDouble()).ToString("0.0",Inv)+"%";
        if(WorkspaceTabs.SelectedIndex==2) Notes.Text="Video, arrows and row profile share the selected pair. During video playback, vectors/profile hold the most recent analyzed pair; their frame IDs remain visible. Use the pair slider or A/B to inspect an exact pair. Teal = median; gold = top 10% signed horizontal motion. Both analysis results stay saved.";
        DrawRegion();
    }
    private void PairSlider_Changed(object sender,RoutedPropertyChangedEventArgs<double> e)
    { if(!IsLoaded||movingPairSlider||timeline==null) return;StopPlayback();showFrameB=false;ShowPair((int)e.NewValue); }
    private void Reference_Changed(object sender,RoutedEventArgs e)
    { if(IsLoaded&&timeline!=null) ShowPair(session.SelectedPair,!playbackTimer.IsEnabled); }
    private void PreviousPair_Click(object sender,RoutedEventArgs e)
    { StopPlayback();showFrameB=false;ShowPair(session.SelectedPair-1); }
    private void NextPair_Click(object sender,RoutedEventArgs e)
    { StopPlayback();showFrameB=false;ShowPair(session.SelectedPair+1); }
    private void ShowFrameB_Click(object sender,RoutedEventArgs e)
    { StopPlayback();showFrameB=!showFrameB;ShowPair(session.SelectedPair); }
    private double Speed=>PlaybackSpeed.SelectedItem is ComboBoxItem item?double.Parse(item.Tag.ToString()!,Inv):.1;
    private double ClipTime(int index)=>clips[index].Seconds??(clips[index].Frame-clips[0].Frame)/30.0;
    private async void Play_Click(object sender,RoutedEventArgs e)
    {
        if(busy||session.Motion==null||source==null) return;
        if(playbackTimer.IsEnabled) { StopPlayback();Status.Text="Video paused · both saved analyses kept";return; }
        if(clips.Count==0)
        {
            try
            {
                var r=Range();string dir=NewRun("video");activeDir=dir;cancelRequested=false;
                string file=WriteRequest(dir,new { source,output=dir,start=r.Start,pairs=r.Pairs,gap=r.Gap,pair_step=r.Step,fps=Num(Fps,"FPS"),roi=new[]{0,0,imageWidth,imageHeight},mm_per_pixel=0,calibration_confirmed=false });
                SetBusy(true,"Preparing video playback · saved analyses are kept…",true);
                await worker.RunAsync("clip",file,ev=>
                {
                    ProgressEvent(ev);
                    if(ev.GetProperty("type").GetString()!="clip"||cancelRequested) return;
                    var clip=ev.GetProperty("clip");clipStride=clip.GetProperty("preview_stride").GetInt32();
                    foreach(var f in clip.GetProperty("frames").EnumerateArray())
                    { var seconds=f.GetProperty("seconds_from_start");clips.Add(new(Path.Combine(dir,f.GetProperty("file").GetString()!),f.GetProperty("frame").GetInt32(),f.GetProperty("original_frame").GetInt32(),seconds.ValueKind==JsonValueKind.Null?null:seconds.GetDouble())); }
                });
                if(cancelRequested) { ClearVideoCache();Status.Text="Playback preparation cancelled · saved analyses kept"; }
            }
            catch(Exception ex) { ClearVideoCache();Error(ex.Message); }
            finally { activeDir=null;SetBusy(false); }
        }
        if(clips.Count>0) StartVideo();
    }
    private void StartVideo()
    {
        if(clips.Count==0||timeline==null) return;
        var pair=timeline.Value.GetProperty("pairs")[session.SelectedPair];int frame=pair.GetProperty("frame_a").GetInt32();
        clipIndex=Enumerable.Range(0,clips.Count).MinBy(i=>Math.Abs(clips[i].Frame-frame));
        if(clipIndex>=clips.Count-1) clipIndex=0;
        playbackOrigin=ClipTime(clipIndex);playbackClock.Restart();playbackTimer.Start();PlayButton.Content="Ⅱ Pause";ShowVideoFrame(clipIndex);
        Status.Text="Playing video · vectors and profile remain linked to the labeled analyzed pair";
    }
    private void PlaybackTick(object? sender,EventArgs e)
    {
        if(clips.Count==0||WorkspaceTabs.SelectedIndex!=2) { StopPlayback();return; }
        double target=playbackOrigin+playbackClock.Elapsed.TotalSeconds*Speed;
        if(target>ClipTime(clips.Count-1))
        {
            if(LoopPlayback.IsChecked==true) { target=0;playbackOrigin=0;playbackClock.Restart(); }
            else { clipIndex=clips.Count-1;ShowVideoFrame(clipIndex);StopPlayback();return; }
        }
        int index=target<ClipTime(clipIndex)?0:clipIndex;
        while(index<clips.Count-1&&ClipTime(index+1)<=target) index++;
        if(index!=clipIndex) { clipIndex=index;ShowVideoFrame(index); }
    }
    private void ShowVideoFrame(int index)
    {
        if(timeline is not JsonElement data) return;
        var clip=clips[index];var pairs=data.GetProperty("pairs");int pairIndex=0;
        while(pairIndex<pairs.GetArrayLength()-1&&pairs[pairIndex+1].GetProperty("frame_a").GetInt32()<=clip.Frame) pairIndex++;
        if(pairIndex!=session.SelectedPair) ShowPair(pairIndex,false);
        SetImage(VideoImage,InterfaceOverlayPath(clip.Frame,clip.File));VideoHeading.Text=$"VIDEO · FRAME {clip.OriginalFrame:N0}";
        VideoFrameInfo.Text=(clip.Seconds is double t?$"Video t = {t:0.0000} s":"FPS unknown; display uses 30 fps")+(clipStride>1?$" · preview stride {clipStride}":"");DrawRegion();
    }
    private void Speed_Changed(object sender,SelectionChangedEventArgs e)
    {
        if(!IsLoaded||!playbackTimer.IsEnabled) return;
        playbackOrigin=ClipTime(clipIndex);playbackClock.Restart();
    }
}
