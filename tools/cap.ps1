param(
  [Parameter(Mandatory=$true)][string]$Out,
  [Parameter(Mandatory=$true)][string]$ProcName,
  [int]$WarmMs = 0
)

Add-Type -AssemblyName System.Drawing
$sig = @'
using System;
using System.Runtime.InteropServices;
using System.Drawing;
public class WinCap2 {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public static Bitmap Capture(IntPtr h) {
        RECT r; GetWindowRect(h, out r);
        int w = Math.Max(1, r.Right - r.Left), ht = Math.Max(1, r.Bottom - r.Top);
        Bitmap bmp = new Bitmap(w, ht);
        using (Graphics g = Graphics.FromImage(bmp)) {
            IntPtr hdc = g.GetHdc();
            bool ok = PrintWindow(h, hdc, 2);
            g.ReleaseHdc(hdc);
            if (!ok) { g.CopyFromScreen(r.Left, r.Top, 0, 0, new Size(w, ht)); }
        }
        return bmp;
    }
}
'@
if (-not ("WinCap2" -as [type])) { Add-Type -TypeDefinition $sig -ReferencedAssemblies System.Drawing }

$p = Get-Process -Name $ProcName -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output "NO_WINDOW"; exit 2 }
$h = $p.MainWindowHandle
if ($WarmMs -gt 0) { Start-Sleep -Milliseconds $WarmMs }
[void][WinCap2]::ShowWindow($h, 9)
[void][WinCap2]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 900
$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$bmp = [WinCap2]::Capture($h)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output ("OK " + $bmp.Width + "x" + $bmp.Height + " -> " + $Out)
$bmp.Dispose()
