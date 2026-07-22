param(
    [ValidateSet("main", "settings", "help")]
    [string]$Form = "main"
)

$map = @{
    main = "main_window.ui"
    settings = "settings_dialog.ui"
    help = "help_dialog.ui"
}

$path = Join-Path $PSScriptRoot "src\import_localize\ui\forms\$($map[$Form])"
pyside6-designer $path
