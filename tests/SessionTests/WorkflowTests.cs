using FlowLens;

static class WorkflowTests
{
    static void Check(bool value,string text) { if(!value) throw new Exception(text); }
    public static async Task Run()
    {
        var workers=new List<string>();bool classified=false,detected=false,motion=false;
        var navigation=new WorkflowNavigator(
            ()=> { if(!classified) { workers.Add("classify");classified=true; }return Task.FromResult(true); },
            ()=>"ST_MI",
            force=> { if(force||!detected) { workers.Add("interface");detected=true; }return Task.FromResult(true); },
            force=> { if(force||!motion) { workers.Add("motion");motion=true; }return Task.FromResult(true); },
            _=>throw new Exception("Layered pattern must not skip"));
        Check(await navigation.ContinueFromClassificationAsync(),"Classification Continue must complete interface detection");
        Check(string.Join(",",workers)=="classify,interface","Layered order must be classify then interface");
        Check(await navigation.ContinueFromInterfaceAsync(),"Interface Continue must automatically calculate motion");
        Check(string.Join(",",workers)=="classify,interface,motion","Continue must calculate motion without a separate step-button click");
        await navigation.ContinueFromClassificationAsync();await navigation.ContinueFromInterfaceAsync();
        Check(workers.Count==3,"Continue must reuse saved results");
        await navigation.OpenMotionAsync(true);Check(workers.Count==4&&workers[^1]=="motion","Explicit motion rerun must rerun only motion");
        foreach(string pattern in new[]{"DW_O","DO_W","FULL"})
        {
            var order=new List<string>();
            var skipped=new WorkflowNavigator(()=> { order.Add("classify");return Task.FromResult(true); },()=>pattern,
                _=>throw new Exception("Excluded pattern must never call interface worker"),
                _=> { order.Add("motion");return Task.FromResult(true); },_=>order.Add("skip"));
            Check(await skipped.ContinueFromClassificationAsync(),"Excluded Continue must calculate motion");
            Check(string.Join(",",order)=="classify,skip,motion","Excluded pattern must skip interface then run motion");
        }
        int later=0;
        var failedClassification=new WorkflowNavigator(()=>Task.FromResult(false),()=>"ST",_=> { later++;return Task.FromResult(true); },_=> { later++;return Task.FromResult(true); },_=>later++);
        Check(!await failedClassification.ContinueFromInterfaceAsync()&&later==0,"Failed/cancelled classification must stop the pipeline");
        var failedInterface=new WorkflowNavigator(()=>Task.FromResult(true),()=>"ST",_=>Task.FromResult(false),_=> { later++;return Task.FromResult(true); },_=>later++);
        Check(!await failedInterface.ContinueFromInterfaceAsync()&&later==0,"Failed/cancelled interface stage must not start motion");
        var completion=new TaskCompletionSource<bool>();int starts=0;
        var guarded=new WorkflowNavigator(()=> { starts++;return completion.Task; },()=>"ST",_=>Task.FromResult(true),_=>Task.FromResult(true),_=>{});
        var first=guarded.ContinueFromClassificationAsync();
        Check(!await guarded.ContinueFromClassificationAsync(),"Repeated Continue must not start a concurrent pipeline");
        completion.SetResult(true);Check(await first&&starts==1&&!guarded.IsAdvancing,"In-flight stage must be awaited and lock released");
        Console.WriteLine("PASS: real Continue orchestration, layered order, automatic motion, three excluded patterns, cached reuse, failure/cancellation stop and duplicate-click guard.");
    }
}
