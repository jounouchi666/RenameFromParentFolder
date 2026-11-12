$ErrorActionPreference = 'Stop'

$python = (Get-Command python.exe -CommandType Application | Select-Object -First 1).Source
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "pythonw.exe was not found alongside $python"
}
& $python -c 'import tkinter'
if ($LASTEXITCODE -ne 0) {
    throw 'Python with Tkinter is required.'
}

$directory = Join-Path $env:LOCALAPPDATA 'RenameFromParentFolder'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$source = Join-Path $PSScriptRoot 'ExplorerDropTarget.cpp'
$server = Join-Path $directory ('ExplorerDropTarget-' + (Get-FileHash -LiteralPath $source).Hash.Substring(0, 12) + '.dll')
if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    $visualStudio = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $visualStudio) {
        throw 'Visual Studio Build Tools with Desktop development with C++ are required.'
    }
    Import-Module (Join-Path $visualStudio 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
    Enter-VsDevShell -VsInstallPath $visualStudio -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64'
    $object = [IO.Path]::ChangeExtension($server, '.obj')
    $library = [IO.Path]::ChangeExtension($server, '.lib')
    & cl.exe /nologo /std:c++17 /EHsc /O2 /MT /LD /utf-8 "/Fo$object" $source /link "/OUT:$server" "/IMPLIB:$library" /EXPORT:DllGetClassObject /EXPORT:DllCanUnloadNow ole32.lib shell32.lib uuid.lib
    if ($LASTEXITCODE -ne 0) {
        throw 'Explorer handler compilation failed.'
    }
}

$script = Join-Path $directory 'RenameFromParentFolder.py'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'RenameFromParentFolder.py') -Destination $script -Force
[IO.File]::WriteAllText((Join-Path $directory 'pythonw.path'), $pythonw)

$shell = New-Object -ComObject WScript.Shell
$programs = [Environment]::GetFolderPath('Programs')
$settingsShortcut = $shell.CreateShortcut((Join-Path $programs '親フォルダの名前に変更の設定.lnk'))
$settingsShortcut.TargetPath = $pythonw
$settingsShortcut.Arguments = '"{0}" --explorer --settings' -f $script
$settingsShortcut.WorkingDirectory = $directory
$settingsShortcut.Save()

$clsid = '{9F59A969-3CD7-489A-BC10-82E5AFDB0FAA}'
$classes = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Classes')
try {
    $key = $classes.CreateSubKey("CLSID\$clsid\InprocServer32")
    $key.SetValue('', $server)
    $key.SetValue('ThreadingModel', 'Apartment')
    $key.Dispose()

    $menu = $classes.CreateSubKey('*\shell\RenameFromParentFolder')
    $menu.SetValue('', '親フォルダの名前に変更')
    $menu.SetValue('MultiSelectModel', 'Player')
    $dropTarget = $menu.CreateSubKey('DropTarget')
    $dropTarget.SetValue('CLSID', $clsid)
    $dropTarget.Dispose()
    $legacyCommand = $menu.CreateSubKey('command')
    $legacyCommand.SetValue('', '')
    $legacyCommand.Dispose()
    $menu.Dispose()

    $classes.DeleteSubKeyTree('*\shell\RenameFromParentFolderSettings', $false)
}
finally {
    $classes.Dispose()
}

$oldShortcut = Join-Path ([Environment]::GetFolderPath('SendTo')) '親フォルダ名に一括変更.lnk'
if (Test-Path -LiteralPath $oldShortcut -PathType Leaf) {
    $shortcut = $shell.CreateShortcut($oldShortcut)
    $previousScript = Join-Path $PSScriptRoot 'RenameFromParentFolder.py'
    if ($shortcut.Arguments -eq ('"{0}" --explorer --' -f $previousScript)) {
        Remove-Item -LiteralPath $oldShortcut
    }
}
