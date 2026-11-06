using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Microsoft.Win32;

namespace FlowLens;

public partial class MainWindow
{
    private Rect ImageBounds()
    {
        if(imageWidth<=0||imageHeight<=0||ImageHost.ActualWidth<=0||ImageHost.ActualHeight<=0) return Rect.Empty;
        double s=Math.Min(ImageHost.ActualWidth/imageWidth,ImageHost.ActualHeight/imageHeight);
        return new((ImageHost.ActualWidth-imageWidth*s)/2,(ImageHost.ActualHeight-imageHeight*s)/2,imageWidth*s,imageHeight*s);
    }
    private Point ImagePoint(Point p)
    { var b=ImageBounds();return new(Math.Clamp((p.X-b.X)/b.Width*imageWidth,0,imageWidth),Math.Clamp((p.Y-b.Y)/b.Height*imageHeight,0,imageHeight)); }
    private void DrawRegion()
    {
        if(!IsLoaded||imageWidth<=0) { if(SelectionRect!=null) SelectionRect.Visibility=Visibility.Collapsed;return; }
        Rect b=ImageBounds();if(b.IsEmpty) return;
        if(!int.TryParse(RoiX.Text,out int x)||!int.TryParse(RoiY.Text,out int y)||!int.TryParse(RoiW.Text,out int w)||!int.TryParse(RoiH.Text,out int h)||w<=0||h<=0) { SelectionRect.Visibility=Visibility.Collapsed;return; }
        SelectionRect.Visibility=Visibility.Visible;Canvas.SetLeft(SelectionRect,b.X+x*b.Width/imageWidth);Canvas.SetTop(SelectionRect,b.Y+y*b.Height/imageHeight);
        SelectionRect.Width=w*b.Width/imageWidth;SelectionRect.Height=h*b.Height/imageHeight;
    }
    private void ImageHost_SizeChanged(object sender,SizeChangedEventArgs e)=>DrawRegion();
    private void Region_Down(object sender,MouseButtonEventArgs e)
    {
        var b=ImageBounds();if(busy||b.IsEmpty||!b.Contains(e.GetPosition(ImageHost))) return;
        StopPlayback();dragStart=ImagePoint(e.GetPosition(ImageHost));dragging=true;SelectionCanvas.CaptureMouse();
    }
    private void Region_Move(object sender,MouseEventArgs e)
    {
        if(!dragging) return;var p=ImagePoint(e.GetPosition(ImageHost));updating=true;
        RoiX.Text=((int)Math.Min(p.X,dragStart.X)).ToString(Inv);RoiY.Text=((int)Math.Min(p.Y,dragStart.Y)).ToString(Inv);
        RoiW.Text=((int)Math.Abs(p.X-dragStart.X)).ToString(Inv);RoiH.Text=((int)Math.Abs(p.Y-dragStart.Y)).ToString(Inv);updating=false;DrawRegion();
    }
    private void Region_Up(object sender,MouseButtonEventArgs e)
    { if(!dragging) return;Region_Move(sender,e);dragging=false;SelectionCanvas.ReleaseMouseCapture();MotionAndInterfaceInputsChanged(); }
    private void ResetRoi_Click(object sender,RoutedEventArgs e)
    { updating=true;RoiX.Text="0";RoiY.Text="0";RoiW.Text=imageWidth.ToString(Inv);RoiH.Text=imageHeight.ToString(Inv);updating=false;MotionAndInterfaceInputsChanged(); }
    private void Export_Click(object sender,RoutedEventArgs e)
    {
        if(session.Motion==null&&session.Classification==null&&session.Interface==null) return;
        var dlg=new SaveFileDialog { Title="Export all saved results",Filter="Result bundle (*.zip)|*.zip",FileName="FlowLens-session-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+".zip" };
        if(dlg.ShowDialog(this)!=true) return;
        try
        {
            SessionExporter.Write(dlg.FileName,session,source);
            Status.Text="Exported all saved results to "+dlg.FileName;
        }
        catch(Exception ex) { Error(ex.Message); }
    }
    private void Results_Click(object sender,RoutedEventArgs e)
    {
        string? folder=WorkspaceTabs.SelectedIndex switch { 0=>session.Classification?.Directory,1=>session.Interface?.Directory,_=>session.Motion?.Directory };
        folder??=session.Motion?.Directory??session.Interface?.Directory??session.Classification?.Directory??Path.Combine(root,"runs");
        if(Directory.Exists(folder)) Process.Start(new ProcessStartInfo { FileName=folder,UseShellExecute=true });
    }
    private void MetricsHelp_Click(object sender,RoutedEventArgs e)
    {
        MessageBox.Show(this,"WORKFLOW\n1. Classify flow pattern → 2. Interface detection (skip for fully dispersed/mixed flow) → 3. Droplet motion analysis. Continue buttons start the next calculation automatically. Tabs and step buttons show saved results without rerunning. Use Re-run only when you want a fresh calculation. Changing the recording/range/timing invalidates all results. ROI or spatial calibration invalidates interface and motion; optical-flow settings invalidate only motion. Interface detection uses a PyTorch boundary network trained from your saved labels. Auto selects CUDA with CPU fallback; CPU can also be selected explicitly. Flow classification and optical-flow motion still use CPU.\n\nSYNCHRONIZED MOTION\nVideo, yellow arrows and row profile are displayed together. The vector/profile frame pair is always labeled. During full-video playback, the last analyzed pair remains displayed until the next sampled pair. Pause and use the pair slider or A/B to inspect an exact pair.\n\nVELOCITY\nHorizontal motion × acquisition FPS × mm/pixel ÷ 1000 gives image-feature velocity in m/s. The supplied pipe scale is 50 mm / approximately 600 pixels. At 300 fps, 1 px/frame is approximately 0.025 m/s. Arrow display scale never enters this calculation.\n\nTEXTURE\nCoverage is the fraction of image pixels with enough detail, not tracking accuracy. Missing texture leaves gaps in the profile.\n\nAI\nThe classifier is experimental: held-out-recording accuracy is 35.9% on 12 eligible recordings; four classes have only one recording. Scores are uncalibrated. The known Vm/WC label is separate from the image prediction.","FlowLens measurement help",MessageBoxButton.OK,MessageBoxImage.Information);
    }
}
