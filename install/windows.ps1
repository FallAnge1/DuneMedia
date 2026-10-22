# Установка программы-загрузчика видеоархива на Windows.
# Обычно запускается из файла «Установить (Windows).bat», который создаёт invite.bat.
# Можно и вручную в PowerShell:
#   $env:VA_INVITE='КОД'; irm https://raw.githubusercontent.com/FallAnge1/DuneMedia/main/install/windows.ps1 | iex
#
# Код результата — в $global:VA_RESULT (0 — успех): exit здесь закрыл бы окно PowerShell при ручном запуске.
#
# Что делает: скачивает свежий установщик из GitHub Releases, ставит программу без лишних вопросов,
# записывает настройки из приглашения (сайт, канал, токен, по желанию api_id/api_hash) и запускает программу.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # без этого Invoke-WebRequest качает в десятки раз медленнее
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }

# Куда установщик на самом деле поставил программу. Inno Setup запоминает прошлую папку установки,
# поэтому она может отличаться от стандартной %LOCALAPPDATA%\Programs\VideoArchive.
$AppKey = '{6E0B8E5A-4F7B-4C5E-9F7A-2D1C0B9A8E11}_is1'
function Get-InstallDir {
  foreach ($root in 'HKCU:', 'HKLM:') {
    foreach ($sub in 'Software\Microsoft\Windows\CurrentVersion\Uninstall', 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall') {
      $item = Get-ItemProperty -Path "$root\$sub\$AppKey" -ErrorAction SilentlyContinue
      if ($item -and $item.InstallLocation) { return $item.InstallLocation.TrimEnd('\') }
    }
  }
  return $null
}
function Find-VideoArchive {
  $dirs = @()
  $reg = Get-InstallDir
  if ($reg) { $dirs += $reg }
  $dirs += (Join-Path $env:LOCALAPPDATA 'Programs\VideoArchive')
  if ($env:ProgramFiles) { $dirs += (Join-Path $env:ProgramFiles 'VideoArchive') }
  $script:searched = $dirs | Select-Object -Unique
  foreach ($d in $script:searched) {
    $exe = Join-Path $d 'VideoArchive.exe'
    if (Test-Path $exe) { return $exe }
  }
  return $null
}
function Show-LogTail($path) {
  if (Test-Path $path) {
    Say ''
    Say 'Последние строки журнала установки:' 'DarkGray'
    Get-Content -Path $path -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { Say "  $_" 'DarkGray' }
  }
}

try {
  Say ''
  Say 'Видеоархив — установка программы-загрузчика' 'White'
  Say '-------------------------------------------'

  # ---- приглашение ----
  $invite = $null
  if ($env:VA_INVITE) {
    $b64 = $env:VA_INVITE.Trim().Replace('-', '+').Replace('_', '/')
    switch ($b64.Length % 4) { 2 { $b64 += '==' } 3 { $b64 += '=' } }
    $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
    $invite = $json | ConvertFrom-Json
    Say "Приглашение для: $($invite.name)"
  } else {
    Say 'Приглашения нет — программа установится, настройки введёте в мастере.' 'Yellow'
  }
  $repo = if ($invite -and $invite.repo) { $invite.repo } else { 'FallAnge1/DuneMedia' }

  if (-not [Environment]::Is64BitOperatingSystem) { throw 'Нужна 64-битная Windows 10 или 11.' }

  # ---- скачать и установить ----
  $url = "https://github.com/$repo/releases/download/uploader-latest/VideoArchive-Setup.exe"
  $setup = Join-Path $env:TEMP 'VideoArchive-Setup.exe'
  Say "Скачиваю программу (около 150 МБ)..."
  Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing
  Say 'Устанавливаю...'
  $log = Join-Path $env:TEMP 'VideoArchive-install.log'
  $p = Start-Process -FilePath $setup -ArgumentList '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', "/LOG=`"$log`"" -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "Установщик завершился с кодом $($p.ExitCode). Подробности: $log" }
  Remove-Item $setup -ErrorAction SilentlyContinue
  $exe = Find-VideoArchive
  if (-not $exe) {
    $dir = Get-InstallDir
    if ($dir -and (Test-Path (Join-Path $dir '_internal'))) {
      # Папка есть, а самого exe нет — его почти наверняка удалил антивирус.
      Say ''
      Say "Программа установилась в $dir, но файл VideoArchive.exe пропал — скорее всего, его удалил антивирус." 'Yellow'
      Say 'Защитник Windows иногда ошибочно принимает неподписанные программы за вирус. Что сделать:' 'Yellow'
      Say '  1. Пуск -> «Безопасность Windows» -> «Защита от вирусов и угроз» -> «Журнал защиты».'
      Say '  2. Найдите запись про VideoArchive.exe -> «Действия» -> «Разрешить на устройстве» (или «Восстановить»).'
      Say '  3. Запустите этот файл ещё раз.'
      throw 'VideoArchive.exe удалён антивирусом'
    }
    Show-LogTail $log
    throw "Программа не найдена после установки (искал в $($script:searched -join '; '))"
  }
  Say 'Программа установлена.' 'Green'

  # ---- настройки из приглашения ----
  if ($invite) {
    $dir = Join-Path $env:APPDATA 'VideoArchive'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $cfgPath = Join-Path $dir 'config.json'
    $cfg = if (Test-Path $cfgPath) { Get-Content -Raw -Encoding UTF8 $cfgPath | ConvertFrom-Json } else { [pscustomobject]@{} }
    $fields = @{ site_url = $invite.site_url; uploader_token = $invite.uploader_token; channel = $invite.channel }
    if ($invite.api_id) { $fields.api_id = [int64]$invite.api_id; $fields.api_hash = $invite.api_hash }
    foreach ($k in $fields.Keys) {
      if ($null -ne $fields[$k] -and $fields[$k] -ne '') { $cfg | Add-Member -NotePropertyName $k -NotePropertyValue $fields[$k] -Force }
    }
    $out = $cfg | ConvertTo-Json -Depth 10
    # Без BOM: программа читает файл как чистый UTF-8.
    [IO.File]::WriteAllText($cfgPath, $out, (New-Object Text.UTF8Encoding $false))
    Say 'Настройки из приглашения записаны.' 'Green'
  }

  if (-not $env:VA_NO_LAUNCH) { Start-Process -FilePath $exe }
  Say ''
  Say 'Готово! Программа откроется сама.' 'Green'
  Say 'В мастере настройки введите свой номер телефона, нажмите «Получить код» и введите код из Telegram.'
  Say 'Остальные шаги уже заполнены — просто нажимайте «Далее».'
  $global:VA_RESULT = 0
} catch {
  Say ''
  Say "Ошибка: $($_.Exception.Message)" 'Red'
  Say 'Проверьте интернет и запустите файл ещё раз. Если не помогло — пришлите скриншот этого окна.'
  $global:VA_RESULT = 1
}
