using System.Diagnostics;
using System.Windows;

namespace FlowLens;

public partial class AboutWindow : Window
{
    private readonly string projectRoot;
    public AboutWindow(string root)
    {
        InitializeComponent();projectRoot=root;
    }
    private void ProjectFiles_Click(object sender,RoutedEventArgs e)
    {
        try { Process.Start(new ProcessStartInfo { FileName=projectRoot,UseShellExecute=true }); }
        catch(Exception ex) { MessageBox.Show(this,ex.Message,"Cannot open project files",MessageBoxButton.OK,MessageBoxImage.Information); }
    }
    private void Close_Click(object sender,RoutedEventArgs e)=>Close();
}

public partial class MainWindow
{
    private void About_Click(object sender,RoutedEventArgs e)=>new AboutWindow(root) { Owner=this }.ShowDialog();
}
