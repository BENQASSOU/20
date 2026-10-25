# Safqa: AI assistant for Moroccan public procurement (public works)

Safqa (صفقة, "contract") is an Android app written in Python (Kivy) for small construction
companies, engineering consultancies (BET) and project managers who execute public works
contracts in Morocco. Its interface is in French, the working language of Moroccan public
procurement.

## Features

| Area | What it does |
|---|---|
| **Documents** | Import a CPS, a contract, the CCAG-T, a BPDE, an RC, amendments or minutes (PDF, Word .docx, text) from the phone. Scanned PDFs go to the AI. |
| **Extraction with citations** | Pulls out obligations (who must do what), deadlines with their start event, penalties (daily rate, cap, base), guarantees (provisional and final bonds, 10 %/7 % retention), price type, payment terms and documents to deliver. **Every item points to its article and page.** |
| **Offline rule engine** | Runs with no network: French numbers in words ("trente (30) jours"), percentages, 1/1000 rates, amounts in DH, derogations from the CCAG-T, risky clauses ("à ses frais", "sans indemnité", "sans mise en demeure"…). |
| **AI analysis (Claude)** | A deeper second pass. The model must quote each article verbatim. Each quote is **checked automatically** against the source text ("citation vérifiée" / "à vérifier"), and an unverified AI value never overrides a contract term. |
| **Contract execution tracking** | Work orders (start, stop, restart, extension) give the contractual end date with suspensions. Also tracks BPDE quantities (CSV import or AI extraction), payment statements (VAT 20 %, retention capped at 7 %, penalties, previous statements), payment delays and provisional/final acceptance with the warranty period. |
| **Risks** | Late final bond, late start order, late work and estimated penalties, penalty cap close to being reached (termination risk), quantity overruns, increase in total value above 10 % (amendment needed), unpaid statements past 60 days (late-payment interest), uncleared reservations, final acceptance or release of guarantees due, and missing documents per phase. |
| **Assistant** | Questions about the contract, answered with clickable article references ([Art. 12] opens the article). |
| **Exports** | Full HTML report and payment statements as CSV, saved to *Downloads/Safqa* and shared via WhatsApp or e-mail. |
| **Subscriptions** | Essentiel 199 DH, Pro 449 DH, Entreprise 799 DH per month, a 14-day trial, and signed licence keys. |

Regulatory references (decree 2-22-431 of 2023, CCAG-T decree 2-14-394, decree 2-16-344 on
payment delays) are indicative defaults. The values extracted from the CPS always take
precedence, and each value can be corrected by hand.

## Get the APK on your phone

The APK is built by GitHub Actions (`.github/workflows/build-apk.yml`) on every push:

1. On GitHub, open **Actions → Build Android APK** and wait for the run to finish (about 30–45 min the first time, faster after that thanks to the cache).
2. Open **Releases**. Each build publishes `Safqa-<version>-build<N>.apk`.
3. On the phone, download the APK, open it and allow "Install unknown apps" for your browser.

The APK is signed with a debug key, which is fine for direct installation. For the Play Store,
build with `buildozer android release` and sign it with your own key.

## Run on a computer

```bash
pip install kivy==2.3.1 pypdf==5.9.0 certifi
python main.py
```

Tests (rule engine, tracking, risks, licences, and an AI client tested against a local fake API):

```bash
pip install pytest pypdf==5.9.0 certifi
python -m pytest -q
```

## Turning on the AI

The **Compte** tab has two modes:

* **Personal API key**: each user enters their own Anthropic key. The model can be chosen
  (Claude Opus 5.5 by default, Sonnet 5.5 or Haiku 5.5 to cut costs).
* **Safqa server** (recommended for selling subscriptions): you run `tools/proxy_server.py`
  on a server. It holds your Anthropic key, checks the subscriber's licence key, applies the
  plan's monthly quota and forwards the request. Subscribers need nothing beyond their licence key.

  ```bash
  export ANTHROPIC_API_KEY=sk-ant-...
  export SAFQA_LICENSE_SECRET='a-long-random-secret'
  python tools/proxy_server.py --port 8080   # behind HTTPS (Caddy/Nginx/Cloudflare Tunnel)
  ```
  Then put its URL in `DEFAULT_PROXY_URL` in `safqa/config.py`.

The app calls the Messages API directly over HTTPS with streaming and structured JSON output.
It does not use the `anthropic` SDK, because the SDK depends on compiled packages
(pydantic-core, jiter) that python-for-android cannot build. Server-side fallback is enabled
in case the model declines a request.

## Selling subscriptions

1. Create a repository secret `SAFQA_LICENSE_SECRET` (Settings → Secrets → Actions). The build embeds it in the APK.
2. Set your contact details in `safqa/config.py` (WhatsApp, e-mail, payment terms).
3. When a payment arrives, generate the key:
   ```bash
   export SAFQA_LICENSE_SECRET='same secret'
   python tools/make_license.py PRO 2027-01-31 "BTP Atlas SARL"
   ```
4. The customer enters the key under **Compte → Clé d'activation**.

Offline checking is enough to launch. Once you have volume, move the check to the server,
because a secret embedded in an APK can be extracted.

## Architecture

```
main.py                 entry point
safqa/
  textract.py           PDF (pypdf) / DOCX / TXT text, page by page
  segment.py            split into articles (stable citations A12, page)
  textnum.py            French numbers and amounts
  rules.py              offline rule engine + document-level checks
  regulation.py         defaults, checklists, legal texts
  ai.py                 Claude client (SSE streaming, JSON schema, quote verification)
  analysis.py           pipeline: extraction → rules → AI → contract terms
  tracking.py           schedule, quantities, payment statements, acceptance
  risk.py               risk engine
  billing.py            plans, trial, licences
  report.py             HTML report, CSV statement
  storage.py            SQLite (phone's private storage)
  platform_android.py   document picker, Downloads, sharing (pyjnius)
  ui/                   Kivy screens
tools/                  make_license.py, proxy_server.py
```
