# Windows Native Support

This checklist defines the minimum native Windows acceptance path for ccwhat.

## Install

Run in PowerShell:

```powershell
uv tool install git+https://github.com/PacemakerG/CCWhat.git
uv tool install mitmproxy
```

Alternatives:

```powershell
pipx install git+https://github.com/PacemakerG/CCWhat.git
pipx install mitmproxy
```

```powershell
py -m pip install --user git+https://github.com/PacemakerG/CCWhat.git
py -m pip install --user mitmproxy
```

Verify:

```powershell
ccwhat --version
mitmdump --version
```

## Manual Acceptance

1. Verify CLI startup:

   ```powershell
   ccwhat --help
   ccwhat --version
   ```

2. Verify Codex viewer startup:

   ```powershell
   ccwhat web --agent codex
   ```

   Confirm the browser opens and `/api/projects` lists sessions from `%USERPROFILE%\.codex\sessions` when Codex sessions exist.

3. Verify proxy startup:

   ```powershell
   ccwhat proxy --preset codex
   ```

   If Windows rejects the port with `WinError 10013`, choose another port:

   ```powershell
   ccwhat proxy --preset codex --port 18088
   ```

4. Verify runtime launch:

   ```powershell
   ccwhat -- codex
   ```

   Confirm the target process receives `HTTP_PROXY`, `HTTPS_PROXY`, and `NODE_EXTRA_CA_CERTS`, and that the viewer can open the recorded run.

5. Verify task segmentation:

   Open a Codex session in the viewer, create a manual task, then click automatic segmentation. If the backend fails, the manual task list must remain visible.

6. Verify Dataset save/export:

   Save confirmed tasks as a Dataset and export the session archive.

## CA Certificate

mitmproxy creates a local CA certificate at:

```text
%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem
```

ccwhat does not automatically import this certificate into Windows trust stores. Import it manually into Trusted Root Certification Authorities, or set `NODE_EXTRA_CA_CERTS` only for the target process when that is sufficient.

## Remaining Risks

- Claude and OpenCode on native Windows follow their current adapter behavior but still need real-machine validation beyond the minimum Codex path.
- Corporate endpoint protection or system policies may block localhost proxying or mitmproxy certificate trust.
- Windows TCP excluded port ranges may vary by machine. Use the diagnostic command from ccwhat errors:

  ```powershell
  netsh interface ipv4 show excludedportrange protocol=tcp
  ```
