<#
.SYNOPSIS
S0(c) of #1228: does an MSIX-packaged interpreter drop gda's Job on the hosted image?

.DESCRIPTION
Wraps an unpackaged python.exe install in a self-signed runFullTrust MSIX, installs it
with Add-AppxPackage under Windows PowerShell 5.1, launches it through its app
execution alias, and runs the reporter's job_probe.py from #1225 with that alias as
the worker interpreter; the same probe then runs with the unpackaged copy as the
control. Every step lands in one JSON report whether it succeeds or not, and the
verdict is "yes", "no" or "inconclusive" with its reason, by the rule #1228 S0(c)
states: "yes" needs assign_ok and worker_in_job true, an identity read that reports
identity on the worker, and a child in no Job. The script exits 0 whenever it could
write the report; the report carries the outcome. Temporary: it goes with the probe
job that runs it.
#>
param(
    [Parameter(Mandatory = $true)][string]$PythonDir,
    [Parameter(Mandatory = $true)][string]$ProbeDir,
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [Parameter(Mandatory = $true)][string]$ReportPath
)

$ErrorActionPreference = 'Stop'
$script:failed = $null
$report = [ordered]@{ probe = 'msix'; steps = [ordered]@{}; verdict = $null; reason = $null }

$PackageName = 'GdaProbe.Python'
$Publisher = 'CN=gda-probe'
$AliasName = 'gdaprobepy.exe'
# A 1x1 transparent PNG: makeappx checks that the manifest's image files exist.
$PngBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII='

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    if ($script:failed) {
        $report.steps[$Name] = [ordered]@{ ok = $false; skipped = "step '$script:failed' failed" }
        return $null
    }
    try {
        $value = & $Body
        $report.steps[$Name] = [ordered]@{ ok = $true; value = $value }
        return $value
    } catch {
        $script:failed = $Name
        $report.steps[$Name] = [ordered]@{ ok = $false; error = $_.Exception.Message }
        Write-Host "::warning::msix probe: step '$Name' failed: $($_.Exception.Message)"
        return $null
    }
}

function Invoke-Capture([string]$Exe, [string[]]$Arguments, [string]$Tag) {
    # Start-Process keeps a native command's stderr out of PowerShell's error stream,
    # which $ErrorActionPreference = 'Stop' would otherwise turn into an exception.
    $out = Join-Path $WorkDir "$Tag.out.txt"
    $err = Join-Path $WorkDir "$Tag.err.txt"
    $quoted = $Arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    $process = Start-Process -FilePath $Exe -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    return [ordered]@{
        exit_code = $process.ExitCode
        stdout = [string](Get-Content -Raw -ErrorAction SilentlyContinue $out)
        stderr = [string](Get-Content -Raw -ErrorAction SilentlyContinue $err)
    }
}

function Read-RegistryValues([string]$Path) {
    if (-not (Test-Path $Path)) { return 'absent' }
    $key = Get-Item $Path
    $values = [ordered]@{}
    foreach ($name in $key.GetValueNames()) { $values[$name] = $key.GetValue($name) }
    return $values
}

function Read-Json([string]$Text, [string]$What) {
    if ([string]::IsNullOrWhiteSpace($Text)) { throw "$What printed nothing" }
    return ($Text | ConvertFrom-Json)
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$package = Join-Path $WorkDir 'package'
$msix = Join-Path $WorkDir 'gda-probe.msix'
$alias = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\$AliasName"
$unpackaged = Join-Path $PythonDir 'python.exe'
$certificate = $null
$installed = $null

try {
    Invoke-Step 'environment' {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        [ordered]@{
            powershell = $PSVersionTable.PSVersion.ToString()
            os_version = [Environment]::OSVersion.Version.ToString()
            is_administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            unpackaged_python = $unpackaged
            unpackaged_python_exists = (Test-Path $unpackaged)
            app_model_unlock_before = Read-RegistryValues 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
            appx_policy_before = Read-RegistryValues 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Appx'
        }
    } | Out-Null

    $tools = Invoke-Step 'sdk_tools' {
        $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        $found = [ordered]@{}
        foreach ($tool in 'makeappx.exe', 'signtool.exe') {
            $candidates = Get-ChildItem -Path $kits -Filter $tool -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\10\.0\.\d+\.\d+\\x64\\' } |
                Sort-Object FullName
            if (-not $candidates) { throw "$tool not found under $kits" }
            $found[$tool] = ($candidates | Select-Object -Last 1).FullName
        }
        $found
    }

    Invoke-Step 'sideload_policy' {
        # Developer Mode allows a trusted-signed sideload on its own, and the hosted
        # image has it on (run 40265329947 read AllowDevelopmentWithoutDevLicense=1),
        # so nothing is written while it is. Where it is off, both switches are
        # tried; a refused write is recorded, not fatal, because the install step
        # is the real test of the policy.
        $policy = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Appx'
        $unlock = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
        $before = Read-RegistryValues $unlock
        $result = [ordered]@{ developer_mode_before = $before; writes = [ordered]@{} }
        if (($before -isnot [string]) -and ($before['AllowDevelopmentWithoutDevLicense'] -eq 1)) {
            $result.action = 'none: Developer Mode is on'
        } else {
            $result.action = 'write both switches'
            foreach ($pair in @(@($policy, 'AllowAllTrustedApps'), @($unlock, 'AllowDevelopmentWithoutDevLicense'))) {
                try {
                    if (-not (Test-Path $pair[0])) { New-Item -Path $pair[0] -Force | Out-Null }
                    New-ItemProperty -Path $pair[0] -Name $pair[1] -Value 1 -PropertyType DWord -Force | Out-Null
                    $result.writes[$pair[1]] = 'ok'
                } catch {
                    $result.writes[$pair[1]] = "refused: $($_.Exception.Message)"
                }
            }
        }
        $result.appx_policy_after = Read-RegistryValues $policy
        $result.app_model_unlock_after = Read-RegistryValues $unlock
        $result
    } | Out-Null

    Invoke-Step 'layout' {
        New-Item -ItemType Directory -Force -Path (Join-Path $package 'Assets') | Out-Null
        Copy-Item -Path $PythonDir -Destination (Join-Path $package 'python') -Recurse
        Remove-Item -Path (Join-Path $package 'python\Lib\test') -Recurse -Force -ErrorAction SilentlyContinue
        $png = [Convert]::FromBase64String($PngBase64)
        foreach ($name in 'StoreLogo.png', 'Square150x150Logo.png', 'Square44x44Logo.png') {
            [IO.File]::WriteAllBytes((Join-Path $package "Assets\$name"), $png)
        }
        $manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap3 desktop rescap">
  <Identity Name="$PackageName" Publisher="$Publisher" Version="1.0.0.0" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>gda probe Python</DisplayName>
    <PublisherDisplayName>gda probe</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application Id="GdaProbePython" Executable="python\python.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="gda probe Python" Description="An unpackaged python.exe given package identity for the #1228 S0 probe" BackgroundColor="transparent" Square150x150Logo="Assets\Square150x150Logo.png" Square44x44Logo="Assets\Square44x44Logo.png" />
      <Extensions>
        <uap3:Extension Category="windows.appExecutionAlias" Executable="python\python.exe" EntryPoint="Windows.FullTrustApplication">
          <uap3:AppExecutionAlias>
            <desktop:ExecutionAlias Alias="$AliasName" />
          </uap3:AppExecutionAlias>
        </uap3:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"@
        [IO.File]::WriteAllText((Join-Path $package 'AppxManifest.xml'), $manifest, (New-Object Text.UTF8Encoding $false))
        $files = Get-ChildItem -Path $package -Recurse -File
        [ordered]@{
            file_count = @($files).Count
            total_bytes = ($files | Measure-Object -Property Length -Sum).Sum
            packaged_python_exists = (Test-Path (Join-Path $package 'python\python.exe'))
        }
    } | Out-Null

    Invoke-Step 'pack' {
        $result = Invoke-Capture $tools['makeappx.exe'] @('pack', '/o', '/d', $package, '/p', $msix) 'makeappx'
        if ($result.exit_code -ne 0) { throw "makeappx exited $($result.exit_code): $($result.stdout) $($result.stderr)" }
        $result
    } | Out-Null

    $certificate = Invoke-Step 'certificate' {
        # The Subject must equal the manifest's Publisher; the public half goes to the
        # machine's Trusted People store so Add-AppxPackage accepts the signature.
        $cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher -KeyUsage DigitalSignature `
            -FriendlyName 'gda probe package signing' -CertStoreLocation 'Cert:\CurrentUser\My' `
            -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
        $cer = Join-Path $WorkDir 'gda-probe.cer'
        Export-Certificate -Cert $cert -FilePath $cer | Out-Null
        Import-Certificate -FilePath $cer -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' | Out-Null
        $cert
    }

    Invoke-Step 'sign' {
        $result = Invoke-Capture $tools['signtool.exe'] @('sign', '/fd', 'SHA256', '/sha1', $certificate.Thumbprint, $msix) 'signtool'
        if ($result.exit_code -ne 0) { throw "signtool exited $($result.exit_code): $($result.stdout) $($result.stderr)" }
        $result
    } | Out-Null

    $installed = Invoke-Step 'install' {
        Add-AppxPackage -Path $msix
        $found = Get-AppxPackage -Name $PackageName
        if (-not $found) { throw 'Add-AppxPackage returned but Get-AppxPackage finds no package' }
        [ordered]@{
            package_full_name = $found.PackageFullName
            install_location = $found.InstallLocation
            signature_kind = "$($found.SignatureKind)"
        }
    }

    $aliasIdentity = Invoke-Step 'alias_identity' {
        if (-not (Test-Path $alias)) { throw "the app execution alias $alias does not exist" }
        $result = Invoke-Capture $alias @('-I', (Join-Path $ProbeDir 'identity_probe.py')) 'alias-identity'
        if ($result.exit_code -ne 0) { throw "the alias launch exited $($result.exit_code): $($result.stderr)" }
        [ordered]@{ alias = $alias; identity = (Read-Json $result.stdout 'identity_probe.py') }
    }

    $packaged = Invoke-Step 'job_probe_packaged' {
        $result = Invoke-Capture $unpackaged @('-I', (Join-Path $ProbeDir 'job_probe.py'), $alias) 'job-probe-packaged'
        if ($result.exit_code -ne 0) { throw "job_probe.py exited $($result.exit_code): $($result.stderr)" }
        Read-Json $result.stdout 'job_probe.py'
    }

    Invoke-Step 'job_probe_control' {
        $result = Invoke-Capture $unpackaged @('-I', (Join-Path $ProbeDir 'job_probe.py'), $unpackaged) 'job-probe-control'
        if ($result.exit_code -ne 0) { throw "job_probe.py exited $($result.exit_code): $($result.stderr)" }
        Read-Json $result.stdout 'job_probe.py'
    } | Out-Null

    if ($script:failed) {
        $report.verdict = 'inconclusive'
        $report.reason = "step '$script:failed' failed: $($report.steps[$script:failed].error)"
    } else {
        $identityCode = $packaged.worker_package.code
        if (-not ($packaged.assign_ok -eq $true) -or -not ($packaged.worker_in_job -eq $true)) {
            $report.verdict = 'inconclusive'
            $report.reason = "assignment or membership failed (assign_ok=$($packaged.assign_ok), worker_in_job=$($packaged.worker_in_job)); the probe releases the worker either way"
        } elseif ($identityCode -eq 15700) {
            $report.verdict = 'inconclusive'
            $report.reason = 'the worker has no package identity (GetPackageFullName 15700): the alias launch did not give it one, so the packaged configuration was not reached'
        } elseif ($identityCode -ne 122) {
            $report.verdict = 'inconclusive'
            $report.reason = "the worker's identity read gave code $identityCode (122 = identity, 15700 = none)"
        } elseif (($packaged.child_in_job -eq $false) -and ($packaged.child_in_any_job -eq $false)) {
            $report.verdict = 'yes'
            $report.reason = 'the packaged worker has identity and its child is in no Job'
        } elseif ($packaged.child_in_job -eq $true) {
            $report.verdict = 'no'
            $report.reason = 'the packaged worker has identity and its child inherited the Job'
        } else {
            $report.verdict = 'inconclusive'
            $report.reason = "membership read on the child did not answer (child_in_job=$($packaged.child_in_job), child_in_any_job=$($packaged.child_in_any_job))"
        }
    }
} finally {
    # Best-effort cleanup of what the probe added to the machine's trust and app set.
    try { if ($installed) { Remove-AppxPackage -Package $installed.package_full_name } } catch { }
    try {
        if ($certificate) {
            Get-ChildItem 'Cert:\LocalMachine\TrustedPeople', 'Cert:\CurrentUser\My' |
                Where-Object { $_.Thumbprint -eq $certificate.Thumbprint } | Remove-Item
        }
    } catch { }
    $json = $report | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($ReportPath, $json, (New-Object Text.UTF8Encoding $false))
    Write-Host $json
}
