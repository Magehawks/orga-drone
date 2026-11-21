// Isolated desat kernel POC (#551) — build with: rustc -O desat_kernel.rs
// Not linked into Orga-Drone.
fn main() {
    let w = 1125usize;
    let h = 1984usize;
    let n = w * h;
    let mut img = vec![0.5f64; n * 3];
    let mask: Vec<bool> = (0..n).map(|i| i % 2 == 0).collect();
    let t0 = std::time::Instant::now();
    for i in 0..n {
        if mask[i] {
            let r = img[i*3];
            let g = img[i*3+1];
            let b = img[i*3+2];
            let y = 0.2126*r + 0.7152*g + 0.0722*b;
            img[i*3] = y; img[i*3+1] = y; img[i*3+2] = y;
        }
    }
    let dt = t0.elapsed().as_secs_f64();
    let mp = (n as f64) / 1e6;
    println!("{{"lang":"rust","median_s":{dt},"mp_per_s":{}}}", mp/dt);
}
