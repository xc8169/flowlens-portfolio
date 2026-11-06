namespace FlowLens;

/// <summary>Await each stage; stop on failure/cancellation and reuse cached stages.</summary>
public sealed class WorkflowNavigator(
    Func<Task<bool>> ensureClassification,
    Func<string> classifiedPattern,
    Func<bool, Task<bool>> ensureInterface,
    Func<bool, Task<bool>> ensureMotion,
    Action<string> skipInterface)
{
    public bool IsAdvancing { get; private set; }
    public static bool HasInterface(string pattern) => pattern switch
    {
        "ST" or "ST_MI" or "DW_O_O" or "DO_W_W" or "DUAL" => true,
        "DW_O" or "DO_W" or "FULL" => false,
        _ => throw new InvalidOperationException("Run flow-pattern classification before continuing.")
    };
    public Task<bool> ContinueFromClassificationAsync() =>
        AdvanceAsync(goToMotion: false, forceInterface: false, forceMotion: false);

    public Task<bool> ContinueFromInterfaceAsync() =>
        AdvanceAsync(goToMotion: true, forceInterface: false, forceMotion: false);

    public Task<bool> OpenInterfaceAsync(bool force = false) =>
        AdvanceAsync(goToMotion: false, forceInterface: force, forceMotion: false);

    public Task<bool> OpenMotionAsync(bool force = false) =>
        AdvanceAsync(goToMotion: true, forceInterface: false, forceMotion: force);

    private async Task<bool> AdvanceAsync(bool goToMotion, bool forceInterface, bool forceMotion)
    {
        if (IsAdvancing) return false;
        IsAdvancing = true;
        try
        {
            if (!await ensureClassification()) return false;

            string pattern = classifiedPattern();
            if (!HasInterface(pattern))
            {
                skipInterface(pattern);
                return await ensureMotion(forceMotion);
            }

            if (!await ensureInterface(forceInterface)) return false;
            return !goToMotion || await ensureMotion(forceMotion);
        }
        finally
        {
            IsAdvancing = false;
        }
    }
}
