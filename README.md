# TMB bed watcher

Checks https://www.montourdumontblanc.com/en/availability and emails you when a watched hut night
goes from *Fully booked* / *Close* to *available*. Runs free on GitHub Actions.

- `watch.json`: the huts and nights to watch (edit freely; names must match the site exactly)
- `watch.py`: the checker (Python standard library only, no installs)
- `state.txt`: last-seen status of every hut and night on the site (committed after each run)
- `changes.csv`: every change seen across all huts, with UTC timestamps (use it to spot release patterns)

## Schedule

- Every 15 min at :03, :18, :33 and :48 past the hour.
- Every 5 min from 23:50 to about 00:55 Swiss time (in winter, 23:50 to 00:30).
- GitHub can delay scheduled runs by 5–15+ min when busy. The overlapping midnight checks cover for that.

## One-time setup

1. **Create a public GitHub repo** (public = unlimited free Actions minutes), e.g. `tmb-bed-watcher`.
2. **Push this folder:**
   ```bash
   cd ~/Downloads/tmb-bed-watcher
   git init -b main && git add . && git commit -m "TMB bed watcher"
   git remote add origin https://github.com/<you>/tmb-bed-watcher.git
   git push -u origin main
   ```
3. **Make a Gmail App Password:** Google Account → Security → 2-Step Verification must be ON →
   search "App passwords" → create one named `tmb-watcher` → copy the 16-character code.
4. **Add repo secrets:** repo → Settings → Secrets and variables → Actions → New repository secret:
   - `GMAIL_USER`: your Gmail address
   - `GMAIL_APP_PASSWORD`: the 16-character code (no spaces)
   - `ALERT_TO`: (optional) where alerts go; defaults to `GMAIL_USER`
5. **Allow the workflow to commit:** Settings → Actions → General → Workflow permissions →
   "Read and write permissions" → Save.

## Testing that email fires

Repo → **Actions** → *TMB bed watcher* → **Run workflow** → pick a mode:

| Mode | What it does | Expect |
|---|---|---|
| `test-email` | Sends a sample email with current status | Email "[TMB watcher] Test email - it works" within ~1 min |
| `simulate` | Pretends every currently-available watched night was full, runs the real alert path | Email "[TMB watcher] N bed opening(s)!" with booking links |
| `normal` | A real check, same as the schedule | Email only if something actually opened |

Neither `test-email` nor `simulate` changes the saved state. If no email arrives, open the run's log;
a login error means the App Password or 2-Step Verification is wrong. Also check Spam.

Locally (prints instead of emailing unless the env vars are set):
```bash
python3 watch.py --dry-run
```

## Keeping an eye on it

- Actions tab: every run, with logs. GitHub emails you if a run **fails** (e.g. the site layout changed).
- Commit history of `changes.csv`: proof it's running and a record of when beds move.
- GitHub pauses schedules in repos with no activity for 60 days. The state commits count as activity,
  so this shouldn't happen, but if it does, re-enable the workflow in the Actions tab.
