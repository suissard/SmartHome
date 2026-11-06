"""
Module d'action d'information système (batterie, CPU, mémoire, disque, température, uptime).
La sortie est renvoyée au LLM qui la reformule à voix haute.
Supporte Linux et Windows.
"""

from actions.base import BaseAction

_SYSTEM_INFO_SCRIPT = r"""
echo "Uptime : $(uptime -p 2>/dev/null | sed 's/^up //')"
echo "Charge CPU (1/5/15 min) : $(cut -d' ' -f1-3 /proc/loadavg) sur $(nproc) cœurs"
free -m | awk '/^Mem:/ {printf "Mémoire : %d Mo utilisés sur %d Mo (%d%%)\n", $3, $2, $3*100/$2}'
df -h / | awk 'NR==2 {printf "Disque racine : %s utilisés sur %s (%s), %s libres\n", $3, $2, $5, $4}'

for bat in /sys/class/power_supply/BAT*; do
    [ -d "$bat" ] || continue
    echo "Batterie $(basename "$bat") : $(cat "$bat/capacity")% ($(cat "$bat/status"))"
done

for zone in /sys/class/thermal/thermal_zone*; do
    [ -r "$zone/temp" ] || continue
    TYPE=$(cat "$zone/type" 2>/dev/null)
    case "$TYPE" in
        x86_pkg_temp|k10temp|cpu*|coretemp)
            echo "Température CPU : $(( $(cat "$zone/temp") / 1000 ))°C"
            break
            ;;
    esac
done
exit 0
"""

_SYSTEM_INFO_SCRIPT_WINDOWS = r"""
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
if ($os) {
    $uptime = (Get-Date) - $os.LastBootUpTime
    Write-Output ("Uptime : {0}j {1}h {2}m" -f $uptime.Days, $uptime.Hours, $uptime.Minutes)
    $memUsed = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1024)
    $memTotal = [math]::Round($os.TotalVisibleMemorySize / 1024)
    $memPct = [math]::Round($memUsed * 100 / $memTotal)
    Write-Output ("Mémoire : {0} Mo utilisés sur {1} Mo ({2}%)" -f $memUsed, $memTotal, $memPct)
}
$cpu = (Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Measure-Object -Property LoadPercentage -Average).Average
if ($cpu -ne $null) {
    Write-Output ("Charge CPU : {0}%" -f $cpu)
}
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" -ErrorAction SilentlyContinue
if ($disk) {
    $diskFree = [math]::Round($disk.FreeSpace / 1GB, 1)
    $diskTotal = [math]::Round($disk.Size / 1GB, 1)
    Write-Output ("Disque C: : {0} Go libres sur {1} Go" -f $diskFree, $diskTotal)
}
$bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
if ($bat) {
    Write-Output ("Batterie : {0}%" -f $bat.EstimatedChargeRemaining)
}
exit 0
"""


class SystemInfoAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SYSTEM_INFO",
            done_message="${OUTPUT}",
            description="Lire l'état de l'ordinateur : batterie, charge CPU, mémoire, disque, température, temps d'allumage.",
            script_code=_SYSTEM_INFO_SCRIPT,
            script_code_windows=_SYSTEM_INFO_SCRIPT_WINDOWS,
            example_prompt="Quel est l'état de mon ordinateur ?",
            example_response="[SYSTEM_INFO] Je regarde l'état de la machine."
        )


ACTIONS = [SystemInfoAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/system_info.py")
    code, out, err = ACTIONS[0].execute_sync()
    print(f"Code : {code}\n{out}{err}")
