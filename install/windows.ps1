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
  $p = Start-Process -FilePath $setup -ArgumentList '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS' -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "Установщик завершился с кодом $($p.ExitCode)" }
  Remove-Item $setup -ErrorAction SilentlyContinue
  $exe = Join-Path $env:LOCALAPPDATA 'Programs\VideoArchive\VideoArchive.exe'
  if (-not (Test-Path $exe)) { throw "Программа не найдена после установки: $exe" }
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
