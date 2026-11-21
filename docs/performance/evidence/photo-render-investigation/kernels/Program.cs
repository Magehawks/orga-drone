using System.Diagnostics;
using System.Text.Json;

// Isolated desat kernel POC for #551 — not linked into Orga-Drone.
int w = 1125, h = 1984, n = w * h;
var img = new double[n * 3];
var mask = new bool[n];
for (int i = 0; i < n; i++)
{
    img[i * 3] = img[i * 3 + 1] = img[i * 3 + 2] = 0.5;
    mask[i] = (i % 2) == 0;
}

// Warmup
Run(img, mask, n);
var times = new List<double>();
for (int r = 0; r < 5; r++)
{
    var sw = Stopwatch.StartNew();
    Run(img, mask, n);
    sw.Stop();
    times.Add(sw.Elapsed.TotalSeconds);
}
times.Sort();
double median = times[times.Count / 2];
double mp = n / 1e6;
Console.WriteLine(JsonSerializer.Serialize(new
{
    lang = "csharp-net8",
    size = new[] { w, h },
    runs = times,
    median_s = median,
    mp_per_s = mp / median
}));

static void Run(double[] img, bool[] mask, int n)
{
    for (int i = 0; i < n; i++)
    {
        if (!mask[i]) continue;
        double r = img[i * 3], g = img[i * 3 + 1], b = img[i * 3 + 2];
        double y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        img[i * 3] = img[i * 3 + 1] = img[i * 3 + 2] = y;
    }
}
