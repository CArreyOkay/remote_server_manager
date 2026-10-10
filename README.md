# Windows Enterprise Orchestrator

A distributed, zero-footprint Windows administration console and remote execution engine. The platform pairs a modern Material Dark / Cybernetic desktop client built in Tkinter with an elevated, asynchronous FastAPI server running natively on target Windows Server environments.

Manage Python runtime environments, Windows Scheduled Tasks, IIS Web Sites, and NSSM background daemons remotely over a chunked, real-time streaming REST interface secured by native Windows Integrated Authentication (SSPI / Kerberos / NTLM).

---

## Architecture Overview

```
┌─────────────────────────────────────────┐
│   Client Workstation (Standard User)    │
│  Tkinter Cybernetic HUD (100% Stdlib)   │
└────────────────────┬────────────────────┘
                     │ HTTP / Streaming REST
                     │ Native SSPI Headers (Negotiate / Kerberos)
                     ▼
┌─────────────────────────────────────────┐
│    Target Windows Host (Remote Server)  │
│      FastAPI / Uvicorn (Elevated)       │
├────────────────────┬────────────────────┤
│  Auth ACL Layer    │ SQLite Audit Trail │
└─────────┬──────────┴────────────────────┘
          │ High-Integrity Subprocess Calls
          ▼
┌───────────────┬────────────────┬───────────────┬──────────────┐
▼               ▼                ▼               ▼              ▼
Python Venvs    schtasks.exe      appcmd.exe       nssm.exe      Kernel32
& ipykernel    (Task Scheduler)   (IIS Manager)    (Services)   (Telemetry)
```

### Key Architectural Tenets  

Decoupled Privilege Model: The client runs under standard, unprivileged operator accounts. The backend server runs under an elevated Windows Administrator account, executing privileged system commands on behalf of validated callers.   

Authentication vs. Execution: Windows SSPI tokens validate identity and authorize connection requests against an Access Control List (ACL). Validated tasks execute under the server process's administrative Windows context.   

Zero-Dependency Operator Client: The frontend GUI runs strictly on Python's Standard Library (tkinter, ctypes, urllib, socket, threading, json). No pip install steps are required on operator workstations.   

Real-Time Streaming Output: Subprocesses stream standard output and standard error over chunked HTTP responses directly to the client's telemetry terminal.   

### Core Capabilities   

Server Health & Telemetry: Monitors real-time physical memory load (RAM committed vs. total) and tracks storage capacity on all mounted Windows volumes via Kernel32.dll.   

Remote Filesystem Navigation: Interactive modal tree explorer to inspect drives, folders, and files directly on the remote server filesystem over REST.   

Python Runtime Orchestration: Provisions remote virtual environments, updates pip, installs package requirements, and registers custom Jupyter kernels (ipykernel) in a single streaming pipeline.   

Task Scheduler Management (schtasks.exe): Creates, inspects, runs, and deletes tasks with custom triggers (Daily, Hourly, Weekly, System Boot) and configurable integrity levels (/RL HIGHEST).   

IIS Web Infrastructure (appcmd.exe): Provisions sites, configures host headers and port bindings, updates physical paths, and controls runtime states (Start, Stop, Delete).   

NSSM Background Services (nssm.exe): Installs long-running processes as native Windows Services, assigns startup directories, updates arguments, and controls service lifecycles.   

Persistent Security Audit Trail: Logs all inbound transactions to an elevated SQLite database, recording timestamps, calling domain identities, privilege states, target arguments, and execution statuses.   

Multi-Node Profiles: Persists and switches between connection targets (Localhost, Staging, Production) within the GUI.   

### Repository Structure
```
.
├── client/              # Futuristic Material-Dark Tkinter desktop interface
├── server/              # Elevated FastAPI backend engine & audit logger
├── app.py               # Root application entrypoint
├── pyproject.toml       # Project configuration, metadata, and optional dependencies
├── requirements.py      # Script to install dependencies into virtual environment
├── .gitignore           # Development and OS exclusion rules
└── README.md            # Project documentation
```
### Requirements & Prerequisites
  ## Server Node
    OS: Windows Server 2016+ / Windows 10+ (64-bit)
    
    Privileges: Administrator (Elevated Command Prompt or PowerShell)
    
    Python: Python 3.10+
    
    Dependencies: fastapi, uvicorn, pydantic
    
    Optional CLI Tools: nssm.exe (in PATH or configured via UI), IIS Management Tools (appcmd.exe)

  ## Client Workstation
    OS: Windows 10 / 11 / Windows Server

    Python: Python 3.10+
    
    Dependencies: None (uses built-in Python standard library)
### Quickstart Guide

## 1. Backend Server Setup (Target Host)
  Open PowerShell or Command Prompt with Run as Administrator on the target Windows server:

    ```
    # Clone the repository
    git clone https://github.com/CArreyOkay/remote_server_manager.git
    cd remote_server_manager
    
    # Create and activate virtual environment
    python -m venv .venv
    .venv\Scripts\activate
    
    # Install server dependencies
    python requirements.py
    
    # Launch the server with authorized Windows users or domain wildcards
    cd server
    python app.py --host 0.0.0.0 --port 8000 --allowed-users "CORP\*,DOMAIN\user,BUILTIN\Administrators"
    ```
    ## Server Arguments
    
    Flag,  Default,  Description
    --host,  0.0.0.0,  Network interface IP address to bind.
    --port,  8000,  Port for the REST API service.
    --allowed-users,  *,  Comma-delimited list of Windows accounts or wildcard patterns permitted to run actions.
    --audit-db,  server_audit_trail.db,  Filepath for the SQLite audit database.

  ## 2. Client Console Setup (Operator Workstation)
    Run the client from any standard, unprivileged terminal:
    
    ```
    cd client
    python app.py
    ```
    Enter the target server endpoint URL (e.g., [http://192.168.1.50:8000](http://192.168.1.50:8000)).
    
    Click PROBE PORT to verify TCP network reachability.
    
    Click AUTHENTICATE to perform the SSPI handshake.
    
    Once authenticated, access all remote management tabs.
### Operational Modules
  ## Python Virtual Environment & Jupyter:
    Target Venv Path: Destination path on the remote host (e.g., C:\Environments\data_pipeline).

    Host Python Bin: Remote base Python executable (e.g., C:\Program Files\Python311\python.exe).
    
    Packages: Space-delimited package list installed via pip install.
    
    Kernel Display Name: Registers the environment directly with Jupyter via ipykernel install --name <id> --display-name <name>.
  ## Scheduled Tasks (schtasks.exe):
    Configure task identifier, executable, script arguments, and trigger frequency (MINUTE, HOURLY, DAILY, WEEKLY, ONSTART, ONLOGON).

    Toggle elevated execution using the /RL HIGHEST switch.

  ## IIS Matrix (appcmd.exe):
    Configure site name, physical directory, port bindings, and custom host headers matching http/*:<port>:<host>.
  ## NSSM Background Daemons (nssm.exe):
    Register services by executable path, service identifier, and startup directory (AppDirectory).

### Security & Firewall Configuration
  ## Inbound Firewall Rule (Server Host)
    To permit traffic over the target port across your local network or VPN:
    ``` New-NetFirewallRule -DisplayName "Windows Remote Orchestrator API" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow ```
  ## Access Control Rules
    The ```--allowed-users``` parameter matches against client identity headers populated via Windows SSPI:
      ```DOMAIN\*```: Permits any user within the specified Active Directory domain.

      ```DOMAIN\Username```: Restricts access to a single user account.
      
      ```BUILTIN\Administrators```: Authorizes accounts that hold local administrator privileges on the client machine.
      
      ```*```: Permits all domain and local callers who successfully complete authentication.
### Troubleshooting
  ## WinError 10061 (Connection Refused):
    The server is not reachable on the given IP or port. Verify the server is running and that port 8000 is permitted through the Windows Firewall.
  ## HTTP 401 Unauthorized:
    The client failed to negotiate credentials via Windows SSPI / Negotiate tokens.
  ## HTTP 403 Forbidden:
    The calling identity was verified, but does not match any entry in the ```--allowed-users``` rule list.
  ## Elevated Privileges Required (Exit Code 5):
    The backend server was started without administrative privileges. Launch the server process using Run as Administrator.

### Development
  ``` pip install -e ".[server,dev]" ```
