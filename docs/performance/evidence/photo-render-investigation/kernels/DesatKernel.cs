// Isolated desat kernel POC (#551) — build with: dotnet script or csc /o
// Not linked into Orga-Drone.
using System;
using System.Diagnostics;
class DesatKernel {
  static void Main() {
    int w=1125, h=1984, n=w*h;
    var img = new double[n*3];
    var mask = new bool[n];
    for (int i=0;i<n;i++){ img[i*3]=img[i*3+1]=img[i*3+2]=0.5; mask[i]= (i%2)==0; }
    var sw = Stopwatch.StartNew();
    for (int i=0;i<n;i++){
      if (!mask[i]) continue;
      double r=img[i*3], g=img[i*3+1], b=img[i*3+2];
      double y=0.2126*r+0.7152*g+0.0722*b;
      img[i*3]=img[i*3+1]=img[i*3+2]=y;
    }
    sw.Stop();
    double dt=sw.Elapsed.TotalSeconds, mp=n/1e6;
    Console.WriteLine($"{{"lang":"csharp","median_s":{dt},"mp_per_s":{mp/dt}}}");
  }
}
