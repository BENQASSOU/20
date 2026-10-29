# Safqa ERP: managing Moroccan public works contracts

An Android ERP app written in Python ([Flet](https://flet.dev), Material Design interface)
for construction companies, engineering consultancies (BET) and project managers who
execute public works contracts in Morocco. The interface is in French, the working
language of Moroccan public procurement.

## Modules

| Module | Contents |
|---|---|
| **Dashboard** | Order backlog, billed for the year, receivables, gross margin, supplier payables, outstanding guarantees, priority alerts, upcoming deadlines, 12-month chart, tender pipeline |
| **Contracts** | Search and filters, then a 12-tab workspace for each contract (below) |
| **Tenders** | Pipeline from monitoring to submitted to won or lost, filing-deadline countdown, bid-to-estimate gap, win rate, provisional bond, one-tap conversion of a won tender into a contract |
| **Finance** | 6-month cash-flow forecast, receivables with aging, expenses and purchases (committed, invoiced, paid), register of bank guarantees with expiry dates, fees and totals per bank |
| **Schedule** | Every deadline from every module: bid filing, guarantee expiry, end of contract period, payments due, supplier invoices, end of warranty, tasks |
| **Third parties** | Clients, suppliers, subcontractors, banks, BET (ICE, RC, IF, contacts) |
| **AI assistant** | Questions about a contract, answered with clickable article references |
| **Reports** | PDFs (portfolio, cash flow, guarantees, contract report, contract analysis, official-style payment statements with the amount in words) and CSV/Excel files, shared via WhatsApp or e-mail or saved to the device |
| **Settings** | Company profile (shown on reports), AI, backup and restore, demo data, diagnostics |

Contract workspace tabs: overview (time used, physical progress, billing, forecast margin),
documents and AI (CPS/CCAG-T analysis with article citations and a document checklist),
obligations, planning (Gantt chart), work orders, measurements and BPDE quantities,
payment statements, budget and costs (budget vs actual per cost category, cost at completion),
site journal, guarantees, acceptance and risks.

The analysis engine works offline (rules with article citations). The AI layer (Claude)
goes deeper, and every quote it returns is checked against the source document.

## Getting the APK

On every push, `.github/workflows/build-apk.yml` runs these steps:
1. Runs the tests.
2. Builds the APK with `flet build apk`. Every build is signed with the same key, so
   each update installs over the previous version.
3. Installs the APK on an Android emulator and runs the on-device self-test: demo data,
   CPS analysis, PDF generation, cash flow and backup.
4. Publishes the APK under **Releases**: download it on the phone and open it.

To keep a permanent signing key (required for the Play Store), set the repository
secrets `ANDROID_KEYSTORE_BASE64` and `ANDROID_KEYSTORE_PASSWORD` (key alias `safqa`).

## Running on a computer

```bash
pip install flet==1.0.5 pypdf==5.9.0 certifi
cd src && python main.py              # desktop window
flet run --web src/main.py            # or in the browser
```

Tests:

```bash
pip install pytest pypdf==5.9.0 certifi
python -m pytest -q
```

## Selling subscriptions

- Plans: Essentiel 199 DH, Pro 449 DH and Entreprise 799 DH per month, with a 14-day trial.
- The repository secret `SAFQA_LICENSE_SECRET` is embedded in the APK at build time.
- Keys are generated with `python tools/make_license.py PRO 2027-01-31 "Company SARL"`.
- Optional relay server: `tools/proxy_server.py`. Subscribers then use the AI with their
  licence key only; the server holds the Anthropic API key and enforces each plan's quota.
- Contact details and payment terms: `src/safqa/config.py`.

## Architecture

```
src/main.py                  entry point (ft.run)
src/safqa/
  storage.py                 SQLite + migrations, backup/restore
  erp.py                     KPIs, budget/margin, cash flow, aging, tenders, guarantees, schedule
  textract / segment / rules / analysis / ai.py   document analysis (offline + Claude)
  tracking.py                schedule, work orders, quantities, payment statements, acceptance
  risk.py                    risk engine (contract, schedule, finance, guarantees)
  pdf.py / reports.py        dependency-free PDF engine and reports
  textnum.py                 French numbers (parsing, amounts in words)
  billing.py                 plans, trial, licence keys
  demo.py / selftest.py      demo data, on-device self-test
  gui/                       Flet interface (app.py, ui.py, views/)
tests/                       44 tests
tools/                       licence keys, AI relay
```

Regulatory references (decree 2-22-431, CCAG-T decree 2-14-394, decree 2-16-344) are
indicative defaults. The values in your CPS take precedence and every value can be corrected.
