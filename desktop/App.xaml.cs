using System.Windows;
namespace FlowLens;
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        DispatcherUnhandledException += (_, ex) => { MessageBox.Show(ex.Exception.Message,"FlowLens",MessageBoxButton.OK,MessageBoxImage.Error); ex.Handled=true; };
        base.OnStartup(e);
    }
}
