# Code signing CIG for free - SignPath Foundation

SignPath Foundation signs open-source releases for free. The certificate is issued to *SignPath Foundation*, and
SignPath.io does the signing from our GitHub Actions build. Everything that can live in the repo is already here:

- `.github/workflows/release.yml` builds `cig.exe` from source on a GitHub-hosted runner, uploads it, submits it for
  signing, and publishes the release.
- `tools/build_exe.py` sets the product name and version in the exe, as SignPath requires.
- The **Code signing policy** section is in `README.md`.
- `.signpath/artifact-configuration.xml` is the artifact configuration to paste into SignPath.

**The steps below need the owner.** They involve accounts, identity, multi-factor authentication and accepting
SignPath's terms, which no agent does on anyone's behalf.

Requirements, read from signpath.org/terms on 2026-11-20:
- an OSI-approved licence (GPL-3.0-or-later qualifies)
- an actively maintained project
- already released in the form to be signed
- binaries built from source in a verifiable way, on GitHub-hosted runners
- a code signing policy on the project page
- product name and version metadata in every binary
- multi-factor authentication for everyone on the team, on both SignPath and GitHub
- no malware and no hacking tools

## Step 1 - the owner: make the first (unsigned) release

SignPath asks that the project is "already released in the form that should be signed".

1. Push the tag for the current version: `git tag v1.0.0`, then `git push origin v1.0.0`.
2. The `release` workflow builds, tests and publishes `cig.exe` unsigned, with its SHA-256. The signing step is skipped
   until Step 4 is done.

## Step 2 - the owner: turn on multi-factor authentication on GitHub

On GitHub: Settings > Password and authentication > Two-factor authentication. SignPath requires it for everyone with
access to the repository.

## Step 3 - the owner: apply at https://signpath.org/apply

The form needs the owner's own details: name, e-mail, the verification e-mail, and acceptance of the terms. Text to
paste where the form asks about the project:

> **Project:** Control Interface Generator (CIG) - https://github.com/ApocryphaRealm/ControlInterfaceGenerator
> **Licence:** GPL-3.0-or-later (OSI-approved), with no commercial dual licensing. All components are open source:
> Python, MCP SDK (MIT), pywinauto (BSD-3), uiautomation (Apache-2.0), comtypes (MIT), psutil (BSD-3), websockets
> (BSD-3), Pillow (MIT-CMU), PyInstaller (GPL-2.0 with the bootloader exception).
> **What it does:** an MCP server that lets an AI agent operate ordinary Windows programs through the accessibility
> interfaces their UI frameworks already publish: Microsoft UI Automation, the Chrome DevTools Protocol on programs
> it starts itself on a separate profile, and PowerShell command metadata. It is an automation and accessibility
> tool. It does not look for or exploit vulnerabilities, does not bypass security measures, never types into password
> fields (a deny rule that cannot be overridden), and refuses to act while the person at the computer is using it.
> **Binary to sign:** `cig.exe`, a single PyInstaller executable built from source by the `release` GitHub Actions
> workflow on GitHub-hosted runners.
> **Privacy:** it sends no information to other networked systems. It talks only to its MCP client over stdio, and to
> programs on the same machine over 127.0.0.1.
> **System changes:** it writes only to `%LOCALAPPDATA%\CIG` (logs, cache, backups). Registry keys that a program
> it launches is known to take over are restored when that program closes. **Uninstall:** delete `cig.exe` and
> `%LOCALAPPDATA%\CIG`.
> **Team:** ApocryphaRealm (author, reviewer and approver).

## Step 4 - the owner, after acceptance: connect SignPath to this repo

In SignPath:
1. Add the predefined **GitHub.com** Trusted Build System to the organization and link it to the project.
2. Create the artifact configuration from `.signpath/artifact-configuration.xml`.
3. Create a signing policy (for example `release-signing`) with the owner as approver.
4. Create an API token for a submitter user.

On GitHub (Settings > Secrets and variables > Actions):
- **Variables:** `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_SIGNING_POLICY_SLUG`, and
  `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` (optional; empty means SignPath's default configuration).
- **Secret:** `SIGNPATH_API_TOKEN`.

From the next tag on, the workflow signs `cig.exe`. The owner approves each signing request in SignPath, as the
policy requires, and the release ships the signed file.

## Notes

- `actions/upload-artifact` uploads a ZIP. That is why the artifact configuration's root is a `<zip-file>` holding
  `cig.exe`.
- The SignPath action's inputs were checked against its `action.yml` (tag `v3`, 2026-11-20). `connector-url` is
  required there, and the workflow sets SignPath's documented default.
- SignPath may turn a project down ("We're under no obligation to accept your project"). An unsigned release still
  works; Windows SmartScreen will just warn about it.
