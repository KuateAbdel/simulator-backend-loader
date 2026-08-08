# ReadyScore Kafka simulation tools

Python utilities to **consume** ReadyScore loan/portfolio topics and **simulate repayments** using JSON behavior profiles or the Excel « Business Case Reevaluation » workbook.

---

## Repository layout

| Path | Purpose |
|------|---------|
| **`ready_scoring/`** | Python package (`kafka_consume`, `repayment_simulator`, `loan_tracker`, `push_commands`, …). |
| **`config/`** | Example behavior definitions (`behaviors.example.json`). |
| **`docs/`** | Internal playbook + Excel scenario workbook. |
| **`docs/KAFKA_LOAN_SIMULATION_READYSCORE.txt`** | Official topic names, `rpk` examples, supported Kafka commands. |
| **`docs/excel/Business Case Reevalution-V2.xlsx`** | Scenario coefficients (Individual / Corporate) → sampling weights in Excel mode. |
| **`requirements.txt`** | `confluent-kafka`, `openpyxl`. |

SSH keys or other secrets should stay **outside** Git or listed in `.gitignore` (see repo `.gitignore`).

---

## Prerequisites

1. **Python 3.10+**
2. **Kafka reachability** — bootstrap default `152.53.140.115:9092` (override with `KAFKA_BOOTSTRAP_SERVERS`).
3. **Tunnel or port-forward** — the cluster advertises `localhost:9092`. Before any tool, from the **repo root** (leave this session open; `-N` = tunnel only):

   ```powershell
   ssh -i ".\duhamel_key" -N -T -L 9092:localhost:9092 kafka_tunnel@152.53.140.115
   ```

   Enter the **passphrase for `duhamel_key` when prompted** (do not store it in this repo or in git).

   **Windows (elevated CMD)** alternative (no SSH):

   ```bat
   netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=9092 connectaddress=152.53.140.115 connectport=9092
   ```

---

## Install

From the **repository root** (`ready_scoring_v2`):

```powershell
python -m pip install -r requirements.txt
```

All CLI examples below assume your **current directory is the repo root**.

---

## How to run the tools

Use **module** invocation so imports resolve correctly:

```powershell
python -m ready_scoring.kafka_consume --help
python -m ready_scoring.repayment_simulator --help
python -m ready_scoring.loan_tracker --help
python -m ready_scoring.push_commands --help
python -m ready_scoring.portfolio_kpis --help
```

You can also run `ready_scoring/repayment_simulator.py` directly; it adds the repo root to `sys.path` for convenience.

Built-in behavior preset for delinquency/repayment scenarios:

```powershell
python -m ready_scoring.repayment_simulator `
  --builtin-behaviors-v1 `
  --run-id TEAM_SIM_001 `
  --from-beginning `
  --max-loans 10 `
  --dry-run `
  --seconds-per-day 0.2 `
  --trigger-rescoring `
  --rescore-topic lifecycle.scoring.input.v36
```

### Push commands to Kafka (live)

**Option A — simulator writes directly** — omit `--dry-run` so it produces to `readyscore.loan.commands.v1` (and the rescoring topic when `--trigger-rescoring` is on):

```powershell
python -m ready_scoring.repayment_simulator `
  --bootstrap-servers 152.53.140.115:9092 `
  --builtin-behaviors-v1 `
  --run-id TEAM_SIM_001 `
  --from-beginning `
  --max-loans 5 `
  --seconds-per-day 0.2
```

**Option B — replay a saved `runs/behaviors_*.json`** (manifest must include `original_remaining_at_discovery`; re-run simulator once if yours is older):

```powershell
python -m ready_scoring.push_commands `
  --bootstrap-servers 152.53.140.115:9092 `
  --from-behaviors runs/behaviors_20260511T141730Z.json `
  --execute
```

**Option C — raw JSONL** (one full command JSON per line, schema as in `docs/KAFKA_LOAN_SIMULATION_READYSCORE.txt`):

```powershell
python -m ready_scoring.push_commands `
  --bootstrap-servers 152.53.140.115:9092 `
  --file my_commands.jsonl `
  --execute
```

Always test with `--dry-run` first. `push_commands` only produces when **`--execute`** is set.

---

## Testing step by step

### 1. Confirm Kafka reads

```powershell
python -m ready_scoring.kafka_consume `
  --topic readyscore.loan.events.v1 `
  --bootstrap-servers 152.53.140.115:9092 `
  --from-beginning `
  --max-messages 5 `
  --json-pretty
```

**Expect:** `LOAN_CREATED` JSON on stdout. Persistent `127.0.0.1:9092` errors mean the tunnel/port-proxy is missing.

Optional — portfolio snapshots:

```powershell
python -m ready_scoring.kafka_consume `
  --topic readyscore.portfolio.daily_snapshots.v2 `
  --bootstrap-servers 152.53.140.115:9092 `
  --from-beginning `
  --max-messages 3 `
  --json-pretty
```

Optional — portfolio KPI indexing for Kibana:

```powershell
python -m ready_scoring.portfolio_kpis validate-topic `
  --from-beginning `
  --run-id 20260521222210 `
  --idle-exit-sec 20

python -m ready_scoring.portfolio_kpis consume-index `
  --from-beginning `
  --run-id 20260521222210 `
  --create-template `
  --idle-exit-sec 20
```

Kibana setup details are in `docs/KIBANA_PORTFOLIO_KPIS.md`.

### 2. Repayment simulator — JSON behaviors (dry-run first)

```powershell
python -m ready_scoring.repayment_simulator `
  --behaviors config/behaviors.example.json `
  --run-id TEAM_SIM_001 `
  --bootstrap-servers 152.53.140.115:9092 `
  --from-beginning `
  --max-loans 10 `
  --idle-exit-sec 20 `
  --dry-run `
  --verbose
```

**Expect:** Logged `[dry-run]` `REPAY_LOAN` lines; **no** writes to `readyscore.loan.commands.v1`.

### 3. Repayment simulator — JSON behaviors (live, small batch)

Remove `--dry-run`, keep `--max-loans` low:

```powershell
python -m ready_scoring.repayment_simulator `
  --behaviors config/behaviors.example.json `
  --run-id TEAM_SIM_001 `
  --bootstrap-servers 152.53.140.115:9092 `
  --from-beginning `
  --max-loans 3 `
  --idle-exit-sec 30 `
  --created-by local-test
```

Verify follow-up events with **§1** on `readyscore.loan.events.v1`.

### 4. Repayment simulator — Excel business case

Dry-run:

```powershell
python -m ready_scoring.repayment_simulator `
  --business-case-xlsx "docs/excel/Business Case Reevalution-V2.xlsx" `
  --run-id TEAM_SIM_001 `
  --bootstrap-servers 152.53.140.115:9092 `
  --from-beginning `
  --max-loans 10 `
  --idle-exit-sec 20 `
  --dry-run `
  --verbose
```

Tune symbolic **x%** phases with flags such as `--excel-partial-target`, `--excel-recovery-target`, `--excel-partial-steps`, `--excel-step-pause`. Use `--excel-equal-weights` to ignore workbook coefficients.

Live run: same command without `--dry-run`.

### 5. Reproducible random assignment

Add `--seed 42` to compare JSON vs Excel runs on the same discovered loans.

### 6. Snapshot at any given time

Get the latest portfolio snapshot(s) whose Kafka timestamp is <= a target time:

```powershell
python -m ready_scoring.loan_tracker snapshot-at `
  --at 2026-05-11T12:00:00Z `
  --run-id TEAM_SIM_001 `
  --bootstrap-servers 152.53.140.115:9092
```

Optional filters:
- `--country-code BF`
- `--topic readyscore.portfolio.daily_snapshots.v2`

Output is a JSON object with `results[]` entries by `(run_id, country_code)`.

### 7. Follow one client’s events

Stream events linked to a specific client:

```powershell
python -m ready_scoring.loan_tracker follow-client `
  --client-id RC-BF-IND-BFC921953 `
  --run-id TEAM_SIM_001 `
  --from-beginning `
  --include-commands `
  --bootstrap-servers 152.53.140.115:9092
```

How matching works:
- Direct match on `payload.client_id == --client-id`
- Plus loan tracking: once a `loan_id` is seen for that client, all future events/commands with that `loan_id` are also printed.

Use `Ctrl+C` to stop, or `--idle-exit-sec 30` for auto-exit after inactivity.

Follow one specific loan directly:

```powershell
python -m ready_scoring.loan_tracker follow-loan `
  --loan-id LOAN-TEAM_SIM_001-RC-BF-IND-BFC921953-b2d8ae0f `
  --run-id TEAM_SIM_001 `
  --from-beginning `
  --include-commands `
  --bootstrap-servers 152.53.140.115:9092
```

---

## Consumer groups

`repayment_simulator` discovers loans using `--group-id` (default `repayment-simulator-discover`). To **re-scan from the beginning**, use a **new** `--group-id` or reset offsets on the broker.

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| Connection failures to `127.0.0.1:9092` | Start SSH `-L` or `netsh` portproxy; leave tunnel open. |
| No loans found | Match `--run-id` to `LOAN_CREATED`; increase `--idle-exit-sec`; use `--from-beginning` + fresh `--group-id`. |
| Need more loans | Use `SEED_DEMO_PORTFOLIO` / `CREATE_LOAN` per `docs/KAFKA_LOAN_SIMULATION_READYSCORE.txt`. |
| PowerShell stderr noise | Librafka logs on stderr; check **process exit code**, not only warnings. |

---

## Customizing behaviors

- Copy **`config/behaviors.example.json`** to a new file and pass it with **`--behaviors`**.
- Excel weights come from **`docs/excel/Business Case Reevalution-V2.xlsx`**; see module docstring in `ready_scoring/excel_business_case.py` for Individual vs Corporate parsing rules.

---

## Full Kafka playbook

See **`docs/KAFKA_LOAN_SIMULATION_READYSCORE.txt`** for topics, `rpk` snippets, and supported command payloads (`REPAY_LOAN`, `SET_DPD`, etc.).



























































dry run locally

python -m ready_scoring.repayment_simulator --bootstrap-servers 152.53.140.115:9092 --builtin-behaviors-v1 --run-id TEAM_SIM_001 --from-beginning --max-loans 2 --dry-run --seconds-per-day 0.05 --verbose

push
python -m ready_scoring.repayment_simulator --bootstrap-servers 152.53.140.115:9092 --builtin-behaviors-v1 --run-id TEAM_SIM_001 --from-beginning --max-loans 2 --seconds-per-day 0.05 --verbose

snapshot
python -m ready_scoring.loan_tracker `
  --bootstrap-servers 152.53.140.115:9092 `
  --from-beginning `
  snapshot-at `
  --at 2026-05-11T14:30:00Z `
  --run-id TEAM_SIM_001 `
  --idle-exit-sec 20


allocate the 0.4 on the duration of the loan (15 days). to see the cash velocity (available cash to push to the market again.)


