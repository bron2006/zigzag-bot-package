<#
.SYNOPSIS
    ONE-TIME SETUP for unattended autostart of vwap_executor.py (Крок
    3.1, 2026-08-22). Run this YOURSELF - it is never run automatically
    by Claude or any other process.

.DESCRIPTION
    Registers run_vwap_executor.ps1 as a Windows Scheduled Task that
    starts "At startup" (system boot, not "At log on") - this is what
    lets the executor survive an unattended reboot (e.g. a Windows
    Update restart) while you're away for the week.

    Runs as SYSTEM by default - NO PASSWORD NEEDED. This isn't a
    shortcut; it's the more robust choice for this exact use case. The
    alternative ("run as your own account, whether logged on or not")
    requires Register-ScheduledTask to validate your account password
    directly, which fails with "The user name or password is incorrect"
    (HRESULT 0x8007052e) for any account signed into Windows via a
    Microsoft Account (checked on this machine 2026-08-22:
    `Get-LocalUser -Name $env:USERNAME` reports
    PrincipalSource=MicrosoftAccount) - Windows Hello PIN/biometric
    sign-in is NOT the same credential Task Scheduler validates against,
    and people almost always type the PIN out of habit, which is why
    this fails even when you're certain the password is right. SYSTEM
    has no such problem (it's a built-in account, not a user credential)
    and vwap_executor.py needs nothing user-profile-specific (its own
    repo path and Python path are absolute, .env/logs live in the repo,
    not in your user profile) - so there's no real downside here.

    Pass -RunAsCurrentUser only if you specifically need the task to run
    as your own Windows account (e.g. it needs access to something tied
    to your profile) - see the MSA note above before fighting the
    password prompt; if you want to go this route, you may first need to
    set/reconfirm an explicit password for your Microsoft Account
    (Settings -> Accounts -> Sign-in options -> Password) rather than
    relying on a PIN you use for daily sign-in.

.NOTES
    Run from an ELEVATED PowerShell (Right-click PowerShell -> Run as
    Administrator).

    To remove later: scripts\unregister_vwap_executor_task.ps1
#>

param(
    [switch]$RunAsCurrentUser
)

$ErrorActionPreference = "Stop"

$TaskName = "ZigZagBot-VwapExecutor"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$WrapperScript = Join-Path $RepoRoot "run_vwap_executor.ps1"

if (-not (Test-Path $WrapperScript)) {
    throw "Не знайдено $WrapperScript - переконайся, що запускаєш це з репозиторію zigzag_bot."
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Задача '$TaskName' вже існує (статус: $($existing.State))."
    $answer = Read-Host "Перереєструвати (видалить стару, створить заново)? (y/N)"
    if ($answer -ne "y") {
        Write-Host "Скасовано."
        return
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WrapperScript`""

$trigger = New-ScheduledTaskTrigger -AtStartup

# ExecutionTimeLimit=0 is important and easy to miss: Task Scheduler's
# own default is often 3 days (PT72H) for tasks created via some
# templates, which would silently kill a week-long unattended run.
# RestartCount/RestartInterval here are Task Scheduler's OWN restart-on-
# failure for the WRAPPER SCRIPT itself (a second, independent safety
# net from the wrapper's own internal crash/hang restart loop - see
# run_vwap_executor.ps1's own header comment for why these are separate
# layers covering different failure points).
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

$description = "Нагляд + автоперезапуск vwap_executor.py (Крок 3.1, READ-ONLY) через run_vwap_executor.ps1 - запускається при старті системи."

try {
    if ($RunAsCurrentUser) {
        Write-Host ""
        Write-Host "УВАГА: якщо цей акаунт входить в Windows через Microsoft Account" -ForegroundColor Yellow
        Write-Host "(перевірено на цій машині - так і є), звичайний пароль/PIN для" -ForegroundColor Yellow
        Write-Host "щоденного входу НЕ ПІДІЙДЕ тут - потрібен саме пароль облікового" -ForegroundColor Yellow
        Write-Host "запису, не PIN Windows Hello. Якщо не singleFactor, розглянь запуск" -ForegroundColor Yellow
        Write-Host "без -RunAsCurrentUser (за замовчуванням, під SYSTEM, без пароля)." -ForegroundColor Yellow
        Write-Host ""
        $credential = Get-Credential -UserName "$env:COMPUTERNAME\$env:USERNAME" -Message "Пароль для облікового запису $env:USERNAME"

        Register-ScheduledTask -TaskName $TaskName `
            -Action $action -Trigger $trigger -Settings $settings `
            -User $credential.UserName -Password $credential.GetNetworkCredential().Password `
            -RunLevel Highest -Description $description `
            -ErrorAction Stop | Out-Null
    } else {
        Register-ScheduledTask -TaskName $TaskName `
            -Action $action -Trigger $trigger -Settings $settings `
            -User "SYSTEM" -RunLevel Highest -Description $description `
            -ErrorAction Stop | Out-Null
    }
} catch {
    Write-Host ""
    Write-Host "ПОМИЛКА: Register-ScheduledTask провалився - задачу НЕ зареєстровано." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    if ($RunAsCurrentUser) {
        Write-Host "Якщо помилка про невірний пароль/користувача (HRESULT 0x8007052e) -" -ForegroundColor Yellow
        Write-Host "дуже ймовірно проблема саме в Microsoft Account/PIN, описана вище в" -ForegroundColor Yellow
        Write-Host "цьому скрипті. Спробуй без -RunAsCurrentUser (SYSTEM, без пароля)." -ForegroundColor Yellow
    }
    exit 1
}

# Явна перевірка постфактум, а не лише довіра до відсутності винятку -
# саме тут раніше (2026-08-22) ховався баг: Register-ScheduledTask падав
# з реальною помилкою автентифікації, але скрипт однаково друкував
# "успіх", бо помилка не спливала як termination exception за замовчуванням.
$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $registered) {
    Write-Host ""
    Write-Host "ПОМИЛКА: Register-ScheduledTask не викинув виняток, але Get-ScheduledTask" -ForegroundColor Red
    Write-Host "підтверджує, що задачі '$TaskName' насправді немає. Реєстрація НЕ вдалась." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Задачу '$TaskName' зареєстровано (підтверджено через Get-ScheduledTask)." -ForegroundColor Green
Write-Host "Обліковий запис: $($registered.Principal.UserId)"
Write-Host "Перевірити статус:      Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Запустити зараз (тест, не чекаючи перезавантаження): Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Лог нагляду:            $RepoRoot\logs\vwap_executor_supervisor.log"
Write-Host "Видалити задачу:        scripts\unregister_vwap_executor_task.ps1"
