param([int]$Port = 8791)
$ErrorActionPreference = 'SilentlyContinue'

# 必须先加载程序集，再编译引用它们的类型，否则 Add-Type 会静默失败、DPI 感知不生效
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Add-Type -TypeDefinition @"
using System;
public class DpiHelper {
  [System.Runtime.InteropServices.DllImport("user32.dll")]
  public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  public static void Enable() { try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch {} }
}
"@
[DpiHelper]::Enable()

# 按当前 DPI 缩放固定尺寸，避免高缩放下文字被裁切
$script:dpiScale = 1.0
try {
  $gfx = [System.Drawing.Graphics]::FromHwnd([IntPtr]::Zero)
  $script:dpiScale = [double]$gfx.DpiX / 96.0
  $gfx.Dispose()
} catch {}
function S([double]$v) { return [int][math]::Round($v * $script:dpiScale) }

Add-Type -TypeDefinition @"
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

public class Md3Colors : ProfessionalColorTable {
  public override Color ToolStripDropDownBackground { get { return Color.FromArgb(252,252,253); } }
  public override Color ImageMarginGradientBegin { get { return Color.FromArgb(252,252,253); } }
  public override Color ImageMarginGradientMiddle { get { return Color.FromArgb(252,252,253); } }
  public override Color ImageMarginGradientEnd { get { return Color.FromArgb(252,252,253); } }
  public override Color MenuBorder { get { return Color.FromArgb(223,226,232); } }
  public override Color MenuItemBorder { get { return Color.Transparent; } }
  public override Color MenuItemSelected { get { return Color.FromArgb(233,242,251); } }
  public override Color MenuItemSelectedGradientBegin { get { return Color.FromArgb(233,242,251); } }
  public override Color MenuItemSelectedGradientEnd { get { return Color.FromArgb(233,242,251); } }
  public override Color MenuItemPressedGradientBegin { get { return Color.FromArgb(214,232,248); } }
  public override Color MenuItemPressedGradientEnd { get { return Color.FromArgb(214,232,248); } }
  public override Color SeparatorDark { get { return Color.FromArgb(232,234,238); } }
  public override Color SeparatorLight { get { return Color.FromArgb(252,252,253); } }
}

public class Md3Renderer : ToolStripProfessionalRenderer {
  public Color Surface = Color.FromArgb(252,252,253);
  public Color Border = Color.FromArgb(223,226,232);
  public Color Hover = Color.FromArgb(233,242,251);
  public Md3Renderer() : base(new Md3Colors()) { RoundedEdges = false; }

  static GraphicsPath Round(Rectangle r, int radius) {
    GraphicsPath p = new GraphicsPath();
    int d = radius * 2;
    p.AddArc(r.X, r.Y, d, d, 180, 90);
    p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
    p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
    p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
    p.CloseFigure();
    return p;
  }

  protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e) {
    e.Graphics.Clear(Surface);
  }

  protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e) {
    using (Pen pen = new Pen(Border)) {
      e.Graphics.DrawRectangle(pen, 0, 0, e.ToolStrip.Width - 1, e.ToolStrip.Height - 1);
    }
  }

  protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e) {
    if (!e.Item.Selected || !e.Item.Enabled) return;
    Rectangle r = new Rectangle(4, 1, e.Item.Width - 9, e.Item.Height - 3);
    SmoothingMode old = e.Graphics.SmoothingMode;
    e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
    using (GraphicsPath path = Round(r, 9))
    using (SolidBrush brush = new SolidBrush(Hover)) {
      e.Graphics.FillPath(brush, path);
    }
    e.Graphics.SmoothingMode = old;
  }

  protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e) {
    using (Pen pen = new Pen(Color.FromArgb(232,234,238))) {
      int y = e.Item.Height / 2;
      e.Graphics.DrawLine(pen, 12, y, e.Item.Width - 12, y);
    }
  }
}
"@ -ReferencedAssemblies System.Windows.Forms, System.Drawing

$url     = "http://127.0.0.1:$Port/"
$root    = $PSScriptRoot
$logPath = Join-Path $root 'app\data\hp_offline.log'
$dataDir = Join-Path $root 'app\data'
$icoPath = Join-Path $root 'app\ui\favicon.ico'

$C_TEXT    = [System.Drawing.Color]::FromArgb(26, 28, 30)
$C_TEXT2   = [System.Drawing.Color]::FromArgb(96, 103, 114)
$C_SURFACE = [System.Drawing.Color]::FromArgb(252, 252, 253)
$C_HOVER   = [System.Drawing.Color]::FromArgb(233, 242, 251)

function New-Glyph([string]$kind, [int]$size = 18, [System.Drawing.Color]$color = $C_TEXT2) {
  $b = New-Object System.Drawing.Bitmap $size, $size
  $g = [System.Drawing.Graphics]::FromImage($b)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.Clear([System.Drawing.Color]::Transparent)
  $pen = New-Object System.Drawing.Pen $color, 1.7
  $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
  $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
  $s = $size / 16.0
  switch ($kind) {
    'open'    { $g.DrawRectangle($pen, 2*$s, 3*$s, 10*$s, 10*$s); $g.DrawLine($pen, 8*$s, 5*$s, 8*$s, 11*$s); $g.DrawLine($pen, 5.5*$s, 8.5*$s, 8*$s, 11*$s); $g.DrawLine($pen, 10.5*$s, 8.5*$s, 8*$s, 11*$s) }
    'scan'    { $g.DrawLine($pen, 3*$s, 6*$s, 3*$s, 3*$s); $g.DrawLine($pen, 3*$s, 3*$s, 6*$s, 3*$s); $g.DrawLine($pen, 10*$s, 3*$s, 13*$s, 3*$s); $g.DrawLine($pen, 13*$s, 3*$s, 13*$s, 6*$s); $g.DrawLine($pen, 3*$s, 10*$s, 3*$s, 13*$s); $g.DrawLine($pen, 3*$s, 13*$s, 6*$s, 13*$s); $g.DrawLine($pen, 10*$s, 13*$s, 13*$s, 13*$s); $g.DrawLine($pen, 13*$s, 13*$s, 13*$s, 10*$s) }
    'log'     { $g.DrawLine($pen, 3*$s, 4*$s, 13*$s, 4*$s); $g.DrawLine($pen, 3*$s, 8*$s, 13*$s, 8*$s); $g.DrawLine($pen, 3*$s, 12*$s, 10*$s, 12*$s) }
    'folder'  { $g.DrawRectangle($pen, 2*$s, 5*$s, 12*$s, 8*$s); $g.DrawLine($pen, 2*$s, 5*$s, 6*$s, 5*$s); $g.DrawLine($pen, 6*$s, 5*$s, 7*$s, 3*$s); $g.DrawLine($pen, 7*$s, 3*$s, 11*$s, 3*$s); $g.DrawLine($pen, 11*$s, 3*$s, 11*$s, 5*$s) }
    'restart' { $g.DrawArc($pen, 2.5*$s, 2.5*$s, 11*$s, 11*$s, 40, 280); $g.DrawLine($pen, 11*$s, 2*$s, 13.5*$s, 4.5*$s); $g.DrawLine($pen, 13.5*$s, 4.5*$s, 11*$s, 6.5*$s) }
    'exit'    { $g.DrawLine($pen, 4*$s, 4*$s, 12*$s, 12*$s); $g.DrawLine($pen, 12*$s, 4*$s, 4*$s, 12*$s) }
  }
  $pen.Dispose(); $g.Dispose()
  return $b
}

function Stop-HpServer {
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*server.py*' -and $_.CommandLine -like '*hp-offline*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if (Test-Path $icoPath) { $icon = New-Object System.Drawing.Icon $icoPath }
else {
  $bmp = New-Object System.Drawing.Bitmap 32, 32
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::FromArgb(0,150,214)); $g.Dispose()
  $icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
}

$ni = New-Object System.Windows.Forms.NotifyIcon
$ni.Icon = $icon
$ni.Text = 'HP Offline - 局域网直连'
$ni.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$menu.Font = New-Object System.Drawing.Font 'Microsoft YaHei UI', 9.5
$menu.ShowImageMargin = $true
$menu.ShowCheckMargin = $false
$menu.DropShadowEnabled = $true
$menu.BackColor = $C_SURFACE
$menu.ForeColor = $C_TEXT
$menu.Padding = New-Object System.Windows.Forms.Padding 6, 6, 6, 6
$menu.ImageScalingSize = New-Object System.Drawing.Size (S 18), (S 18)
$menu.Renderer = New-Object Md3Renderer
$menu.Renderer.Surface = $C_SURFACE
$menu.Renderer.Hover = $C_HOVER

function Add-Item([string]$text, [string]$glyph, [scriptblock]$action, [bool]$bold = $false) {
  $it = New-Object System.Windows.Forms.ToolStripMenuItem $text
  $it.AutoSize = $false
  $it.Size = New-Object System.Drawing.Size (S 232), (S 38)
  $it.Padding = New-Object System.Windows.Forms.Padding (S 4), 0, (S 10), 0
  $it.ForeColor = $C_TEXT
  $it.Image = (New-Glyph $glyph (S 18))
  $it.ImageAlign = 'MiddleLeft'
  if ($bold) { $it.Font = New-Object System.Drawing.Font 'Microsoft YaHei UI', 9.5, ([System.Drawing.FontStyle]::Bold) }
  $it.Add_Click($action)
  [void]$menu.Items.Add($it)
  return $it
}

$header = New-Object System.Windows.Forms.ToolStripMenuItem '正在读取打印机…'
$header.Enabled = $false
$header.AutoSize = $false
$header.Size = New-Object System.Drawing.Size (S 232), (S 40)
$header.Padding = New-Object System.Windows.Forms.Padding (S 10), 0, (S 10), 0
$header.ForeColor = $C_TEXT2
$header.Font = New-Object System.Drawing.Font 'Microsoft YaHei UI', 8.5
[void]$menu.Items.Add($header)
[void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

[void](Add-Item '打开界面' 'open' { Start-Process $url } $true)
[void](Add-Item '重新扫描打印机' 'scan' {
  try { Invoke-WebRequest -Uri "${url}api/printers/discover" -Method POST -TimeoutSec 60 -UseBasicParsing | Out-Null } catch {}
  Start-Process $url
})
[void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void](Add-Item '打开日志' 'log' { Start-Process notepad.exe $logPath })
[void](Add-Item '打开数据目录' 'folder' { Start-Process explorer.exe $dataDir })
[void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void](Add-Item '重启服务' 'restart' {
  Stop-HpServer
  Start-Sleep -Milliseconds 800
  Start-Process -FilePath 'python' -ArgumentList @((Join-Path $root 'app\server.py'), '--port', $Port) -WindowStyle Hidden
  Start-Sleep -Seconds 3
  $ni.ShowBalloonTip(2500, 'HP Offline', '服务已重启', [System.Windows.Forms.ToolTipIcon]::Info)
})
[void](Add-Item '退出（停止服务）' 'exit' {
  Stop-HpServer
  $ni.Visible = $false
  $ni.Dispose()
  [System.Windows.Forms.Application]::Exit()
})

$menu.Add_Opening({
  try {
    $r = Invoke-RestMethod -Uri "${url}api/printers" -TimeoutSec 2
    if ($r.printers -and $r.printers.Count -gt 0) {
      $p = $r.printers[0]
      $st = switch ($p.state) { 'idle' { '就绪' } 'processing' { '工作中' } 'stopped' { '已停止' } default { '未知' } }
      if (-not $p.online) { $st = '离线' }
      $header.Text = "  $($p.name)  ·  $st"
    } else { $header.Text = '  尚未注册打印机' }
  } catch { $header.Text = '  服务未响应' }
})

$ni.ContextMenuStrip = $menu
$ni.Add_DoubleClick({ Start-Process $url })
$ni.ShowBalloonTip(3000, 'HP Offline', '服务已启动，右键图标打开菜单，双击打开界面', [System.Windows.Forms.ToolTipIcon]::Info)

[System.Windows.Forms.Application]::Run()
