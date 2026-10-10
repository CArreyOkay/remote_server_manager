Windows Enterprise OrchestratorA distributed, zero-footprint Windows administration console and remote execution engine. The platform pairs a modern Material Dark / Cybernetic desktop client built in Tkinter with an elevated, asynchronous FastAPI server running natively on target Windows Server environments.Manage Python runtime environments, Windows Scheduled Tasks, IIS Web Sites, and NSSM background daemons remotely over a chunked, real-time streaming REST interface secured by native Windows Integrated Authentication (SSPI / Kerberos / NTLM).Architecture OverviewPlaintext                                                        
                      ┌─────────────────────────────────────────┐
                      │   Client Workstation (Standard User)    │
                      │  Tkinter Cybernetic HUD (100% Stdlib)   │
                      └────────────────────┬────────────────────┘
                                           │
                      HTTP / Streaming REST │ Native SSPI Headers
                      Chunked Subprocess    │ (Negotiate / Kerberos)
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

Key Architectural TenetsDecoupled Privilege Model: The client runs under standard, unprivileged operator accounts. 
The backend server runs under an elevated Windows Administrator account, executing privileged system commands on behalf of validated callers.Authentication vs. 
Execution: Windows SSPI tokens validate identity and authorize connection requests against an Access Control List (ACL). 
Validated tasks execute under the server process's administrative Windows context.Zero-Dependency Operator Client: The frontend GUI runs strictly on Python's Standard Library (tkinter, ctypes, urllib, socket, threading, json). 
No pip install steps are required on operator workstations.Real-Time Streaming Output: Subprocesses stream standard output and standard error over chunked HTTP responses directly to the client's telemetry terminal.
Core CapabilitiesServer Health & Telemetry: Monitors real-time physical memory load (RAM committed vs. total) and tracks storage capacity and surplus on all mounted Windows volumes via Kernel32.dll.
Remote Filesystem Navigation: Interactive modal tree explorer to inspect drives, folders, and files directly on the remote server filesystem over REST.
Python Runtime Orchestration: Provisions remote virtual environments, updates pip, installs package requirements, and registers custom Jupyter kernels (ipykernel) in a single streaming pipeline.
Task Scheduler Management (schtasks.exe): Creates, inspects, runs, and deletes tasks with custom triggers (Daily, Hourly, Weekly, System Boot) and configurable integrity levels (/RL HIGHEST).
IIS Web Infrastructure (appcmd.exe): Provisions sites, configures host headers and port bindings, updates physical paths, and controls runtime states (Start, Stop, Delete).
NSSM Background Services (nssm.exe): Installs long-running processes as native Windows Services, assigns startup directories, updates arguments, and controls service lifecycles.
Persistent Security Audit Trail: Logs all inbound transactions to an elevated SQLite database, recording timestamps, calling domain identities, privilege states, target arguments, and execution statuses.Multi-Node Profiles: Persists and switches between connection targets (Localhost, Staging, Production) within the GUI.Repository StructurePlaintext.
├── server               # Elevated FastAPI backend engine & audit logger
├── client               # Futuristic Material-Dark Tkinter desktop interface
├── pyproject.toml       # Project configuration, metadata, and optional dependencies
├── requirements.py      # installs all dependencies in the venv
├── .gitignore           # Development and OS exclusion rules
└── README.md
Requirements & PrerequisitesServer NodeOS: Windows Server 2016+ / Windows 10+ (64-bit)Privileges: Administrator (Elevated Command Prompt or PowerShell)Python: Python 3.10+Dependencies: fastapi, uvicorn, pydanticOptional CLI Tools: nssm.exe (placed in PATH or configured directly in UI), IIS Features enabled (appcmd.exe)Client WorkstationOS: Windows 10 / 11 / Windows ServerPython: Python 3.10+Dependencies: None (uses built-in standard library packages)Quickstart Guide1. Backend Server Setup (Target Host)Open a terminal with Run as Administrator on the target Windows server:PowerShell# Clone or transfer the repository
git clone https://github.com/CarreyOkay/remote_server_manager.git
cd remote_server_manager

# Install server dependencies
python -m venv .venv
.venv\Scripts\activate
python requirements.py

# Launch the server with your authorized Windows users or domain patterns
cd server
python app.py --host 0.0.0.0 --port 8000 --allowed-users "CORP\*,DOMAIN\user,BUILTIN\Administrators" Server ArgumentsFlagDefaultDescription

    --host 0.0.0.0 : Network interface IP to bind.
    --port 8000 : Port for the REST API service.
    --allowed-users *Comma-delimited list of Windows accounts or wildcard patterns permitted to run actions.
    --audit-db : server_audit_trail.db
    Filepath for the SQLite audit database.2. 

Client Console Setup (Operator Workstation) Run the client from any standard, unprivileged terminal:PowerShell
cd client
python app.py

Select or input the Endpoint URL (e.g., [http://192.168.1.50:8000](http://192.168.1.50:8000)).Click PROBE PORT to verify TCP connectivity.Click AUTHENTICATE to trigger the SSPI handshake. 
Once the server validates the Windows identity against its allowed user list, the console unlocks all management modules.Operational ModulesPython Virtual Environment & JupyterTarget Venv Path: Destination path on the remote host (e.g., C:\Environments\data_pipeline).Host Python Bin: Remote path to base executable (e.g., C:\Program Files\Python311\python.exe).
Packages: Space-delimited package list installed via pip install.Kernel Display Name: Registers the venv directly with the remote host's Jupyter runtime via ipykernel install --name <id> --display-name <label>.

Scheduled Tasks (schtasks.exe)Task Identifier: Name registered within the Task Scheduler namespace.Target Script / Bin: Binary, batch script, or Python executable to invoke.Arguments: Script paths, CLI switches, or environment variables.
Frequency: Choose between MINUTE, HOURLY, DAILY, WEEKLY, ONSTART, or ONLOGON.
Elevate Integrity: Automatically injects the /RL HIGHEST flag for administrative runs.

IIS Matrix (appcmd.exe)Site Identifier: Name of the IIS web site.Physical Directory: Target folder hosting web.config or web assets.Binding Port & Host Header: Generates bindings matching http/*:<PORT>:<HEADER>.NSSM Background Daemons (nssm.exe)Executable Path: Path to nssm.exe on the server filesystem.
Service Identifier: System service name registered in services.msc.Working Directory: Injects AppDirectory configuration to prevent runtime path issues.
Security & Firewall ConfigurationInbound Firewall Rule (Server Host)If connecting across a local area network or VPN, open the chosen port on the server host:PowerShellNew-NetFirewallRule -DisplayName "Windows Remote Orchestrator API" `
                    -Direction Inbound `
                    -LocalPort 8000 `
                    -Protocol TCP `
                    -Action Allow

Access Control RulesThe --allowed-users parameter matches against client identity headers populated via Windows SSPI:DOMAIN\*: Permits any user under the specified Active Directory domain.
DOMAIN\Username: Restricts access to a single user account.BUILTIN\Administrators: Authorizes accounts that hold local administrator status on the client machine.
*: Permits all domain and local callers who complete the Windows authentication handshake.TroubleshootingError: WinError 10061 (Connection Refused)The client cannot reach the target host on the specified port.
Verify that server is actively running.
Verify the target IP address and ensure port 8000 is open on intermediate network firewalls.
Error: HTTP 401 Unauthorized / HTTP 403 Forbidden401: Client failed to produce valid Windows credentials via X-Windows-User / SSPI Negotiate token.403: The Windows identity (e.g., WORKGROUP\operator) is not covered by the server's --allowed-users configuration. 
Restart the server with updated wildcard or username rules.
Error: Elevated Privileges Required (Exit Code 5)server automatically terminates if launched without administrative privileges.
Restart the server process using Run as Administrator.
Development & Packaging Install development tools and packaging utilities using the pyproject.toml configurations:PowerShell# Install project with development dependencies
pip install -e ".[server,dev]"
