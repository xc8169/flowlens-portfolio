using System.Globalization;
using System.Windows;
using System.Windows.Media;

namespace FlowLens;

public sealed class VelocityProfileChart : FrameworkElement
{
    private double?[] median=[],top=[],reference=[];
    private int[] rows=[];
    private double xmin=-1,xmax=1;
    private string units="m/s";
    private bool showReference=true;
    public void SetProfile(double?[] m,double?[] t,double?[] r,int[] y,double min,double max,string label,bool compare)
    { median=m;top=t;reference=r;rows=y;xmin=min;xmax=max;units=label;showReference=compare;InvalidateVisual(); }

    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);
        dc.DrawRectangle(Brushes.White,null,new Rect(0,0,ActualWidth,ActualHeight));
        if(rows.Length<2||ActualWidth<160||ActualHeight<140) return;
        var ink=new SolidColorBrush(Color.FromRgb(45,67,76));
        var teal=new SolidColorBrush(Color.FromRgb(23,109,118));
        var amber=new SolidColorBrush(Color.FromRgb(187,124,32));
        var gray=new SolidColorBrush(Color.FromRgb(130,141,147));
        double left=62,right=ActualWidth-14,upper=38,bottom=ActualHeight-45;
        var plot=new Rect(left,upper,right-left,bottom-upper);
        double pixels=VisualTreeHelper.GetDpi(this).PixelsPerDip;
        void Text(string value,double x,double y,double size=10,Brush? color=null)
        { dc.DrawText(new FormattedText(value,CultureInfo.InvariantCulture,FlowDirection.LeftToRight,new Typeface("Segoe UI"),size,color??ink,pixels),new Point(x,y)); }
        double X(double x)=>left+(x-xmin)/(xmax-xmin)*plot.Width;
        double Y(double y)=>upper+(y-rows[0])/(rows[^1]-rows[0])*plot.Height;
        Text("Median",left,8,10,teal);Text("Top 10%",left+60,8,10,amber);
        if(showReference) Text("Range reference",left+127,8,10,gray);
        var gridPen=new Pen(new SolidColorBrush(Color.FromRgb(226,233,235)),.7);
        for(int tick=0;tick<=4;tick++)
        {
            double v=xmin+(xmax-xmin)*tick/4,xx=X(v);
            dc.DrawLine(gridPen,new Point(xx,upper),new Point(xx,bottom));
            Text(v.ToString("0.###",CultureInfo.InvariantCulture),xx-15,bottom+6,9);
            double row=rows[0]+(rows[^1]-rows[0])*tick/4,yy=Y(row);
            dc.DrawLine(gridPen,new Point(left,yy),new Point(right,yy));Text(row.ToString("0"),left-33,yy-6,9);
        }
        dc.DrawLine(new Pen(ink,1),new Point(left,upper),new Point(left,bottom));
        dc.DrawLine(new Pen(ink,1),new Point(left,bottom),new Point(right,bottom));
        Text((units=="m/s"?"Horizontal velocity":"Horizontal motion")+" ("+units+")",left+Math.Max(0,(plot.Width-190)/2),bottom+26,10);
        double labelY=upper+plot.Height/2+33;
        dc.PushTransform(new RotateTransform(-90,6,labelY));Text("Image row (px)",6,labelY,10);dc.Pop();
        dc.PushClip(new RectangleGeometry(plot));
        void Curve(double?[] values,Pen pen)
        {
            var geo=new StreamGeometry();
            using(var g=geo.Open())
            {
                bool started=false;
                for(int i=0;i<Math.Min(rows.Length,values.Length);i++)
                {
                    if(values[i] is not double v||!double.IsFinite(v)) { started=false;continue; }
                    var point=new Point(X(v),Y(rows[i]));
                    if(!started) { g.BeginFigure(point,false,false);started=true; }
                    else g.LineTo(point,true,false);
                }
            }
            dc.DrawGeometry(null,pen,geo);
        }
        if(showReference) Curve(reference,new Pen(gray,1) { DashStyle=DashStyles.Dash });
        Curve(top,new Pen(amber,1.4));Curve(median,new Pen(teal,2));
        dc.Pop();
    }
}
