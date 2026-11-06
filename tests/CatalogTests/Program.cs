using FlowLens;
int count=0;
foreach(var pair in new[]{("02",.2),("05",.5),("08",.8),("12",1.2)})
    foreach(int wc in new[]{20,40,60,80})
    {
        string name=$"vm{pair.Item1}wc{wc}.cine";
        if(!ExperimentCatalog.TryParse(name,out double vm,out int result)||vm!=pair.Item2||result!=wc) throw new Exception("Wrong mapping: "+name);
        count++;
    }
foreach(string name in new[]{"synthetic.npz","vm05wc140.cine","vm00wc40.cine"})
    if(ExperimentCatalog.TryParse(name,out _,out _)) throw new Exception("Should reject "+name);
if(!ExperimentCatalog.TryParse("VM12WC80.CINE",out double upper,out int water)||upper!=1.2||water!=80) throw new Exception("Case handling");
if(!ExperimentCatalog.TryParse("vm0.5wc40.cine",out double dec,out _)||dec!=.5) throw new Exception("Decimal handling");
Console.WriteLine($"PASS: {count} Vm/WC combinations, invalid labels, case and decimal input.");
