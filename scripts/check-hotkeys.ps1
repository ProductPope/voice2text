# Checks which candidate global hotkeys are free on this Windows machine.
# Run in PowerShell:  powershell -ExecutionPolicy Bypass -File .\scripts\check-hotkeys.ps1
#
# It tries to register each shortcut the same way the app will (RegisterHotKey)
# and releases it immediately. "ZAJĘTY" means another program already owns it.
# Limitation: programs that grab keys via keyboard hooks (some games, macro
# tools) and shortcuts reserved by Windows itself (Win+L etc.) are not detected,
# so after picking one, press it once in a normal window to be sure.
# Ctrl+Alt+<letter> equals AltGr+<letter> on Polish layouts: avoid a, c, e, l, n, o, s, x, z.

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class HotKeyProbe {
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool UnregisterHotKey(IntPtr hWnd, int id);
}
"@

$ALT = 0x1; $CTRL = 0x2; $SHIFT = 0x4; $WIN = 0x8; $NOREPEAT = 0x4000

$candidates = @(
    @{ Name = "Ctrl+Alt+Spacja";  Mods = $CTRL -bor $ALT;   Vk = 0x20 },
    @{ Name = "Ctrl+Shift+Spacja"; Mods = $CTRL -bor $SHIFT; Vk = 0x20 },
    @{ Name = "Ctrl+Alt+D";       Mods = $CTRL -bor $ALT;   Vk = 0x44 },
    @{ Name = "Ctrl+Alt+K (popraw ostatni)"; Mods = $CTRL -bor $ALT; Vk = 0x4B },
    @{ Name = "Win+Alt+D";        Mods = $WIN -bor $ALT;    Vk = 0x44 },
    @{ Name = "F9";               Mods = 0;                 Vk = 0x78 }
)

$id = 0xB000
foreach ($c in $candidates) {
    $id++
    $ok = [HotKeyProbe]::RegisterHotKey([IntPtr]::Zero, $id, [uint32]($c.Mods -bor $NOREPEAT), [uint32]$c.Vk)
    if ($ok) {
        [void][HotKeyProbe]::UnregisterHotKey([IntPtr]::Zero, $id)
        Write-Host ("{0,-30} wolny" -f $c.Name) -ForegroundColor Green
    } else {
        Write-Host ("{0,-30} ZAJĘTY" -f $c.Name) -ForegroundColor Red
    }
}
