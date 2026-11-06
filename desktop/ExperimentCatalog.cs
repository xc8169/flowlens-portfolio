using System.Globalization;
using System.Text.RegularExpressions;

namespace FlowLens;

public static class ExperimentCatalog
{
    // The experiment's compact Vm code is in tenths of m/s: 05 -> 0.5, 12 -> 1.2.
    public static bool TryParse(string name, out double vm, out int wc)
    {
        vm=0; wc=0;
        var match=Regex.Match(name,@"^vm(?<vm>\d{2,}|\d+\.\d+)wc(?<wc>\d{1,3})(?:\.|$)",RegexOptions.IgnoreCase);
        if(!match.Success) return false;
        string value=match.Groups["vm"].Value;
        if(!double.TryParse(value,NumberStyles.AllowDecimalPoint,CultureInfo.InvariantCulture,out vm)
            ||!int.TryParse(match.Groups["wc"].Value,out wc)) return false;
        if(!value.Contains('.')) vm/=10.0;
        return vm>0 && wc>=0 && wc<=100;
    }
}
