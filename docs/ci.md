# proofreel in CI

Saved flows run again on each pull request. The pull request gets one comment with the verdict of each journey, a
picture, and a link to the full review page. A teammate sees it with no install. It uses no model and no tokens: a
flow is a list of commands, so a run costs only runner minutes (about 2 minutes for three journeys).

## Copy-paste workflow (a web app)

Put your flows in `.proofreel/flows/` (see [flows](flows.md)), and use `${URL}` for the address of the app. Then add
`.github/workflows/proofreel.yml`:

```yaml
name: proofreel
on: pull_request

permissions:
  contents: read

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci                      # your own build steps
      - uses: YGao2005/proofreel@v1
        with:
          start: npm start &             # starts the app in the background
          url: http://127.0.0.1:3000     # the action waits for this, and flows read it as ${URL}

  publish:
    needs: run
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: YGao2005/proofreel/publish@v1
```

There are two jobs on purpose. A flow can run shell commands (`check cmd`), and the `run` job runs the code of the
pull request, so it has a read-only token. The `publish` job has the write token, and it runs nothing from the pull
request: it does not check out the code. It downloads the review folder, copies only `runs.json` and the `.mp4` and
`.jpg` files of each run (a link in the folder is an error), and writes `index.html` again with its own proofreel.

## The `run` action

| Input | Default | Meaning |
|---|---|---|
| `flows` | `.proofreel/flows` | Flow files or folders, separated by spaces. |
| `start` | none | A shell command that starts the app. It runs in the background. |
| `url` | none | The action waits until it answers. Flows read it as `${URL}`. |
| `wait-for` | `url` | Another URL to wait for. |
| `wait-timeout` | `60` | Seconds to wait for the app. |
| `title` | the repository name | The title of the review page. |
| `version` | the action tag | `latest`, a version such as `1.2.2`, or `source`. A tag `v1.2.2` installs 1.2.2, `v1` the newest 1.x, and a branch or SHA the code of the action. |
| `fail-on-problem` | `true` | Fail the job when a journey has the verdict problem. |
| `working-directory` | `.` | The folder to run in. |
| `args` | none | More arguments for `proofreel suite`, such as `--set NAME=value`. |

The action runs on Linux and macOS runners, uses the Chrome of the runner, and adds `--no-sandbox` to
`PROOFREEL_CHROME_FLAGS`. It uploads the review folder as the artifact `proofreel-review`.

The job result comes from the verdict of each journey in the review folder, not from the exit code alone. A journey
with no checks has the verdict "no checks". The comment shows it as that, never as a pass, and the job log has a
warning for it. Add `check` lines to the flow.

## The `publish` action

| Input | Default | Meaning |
|---|---|---|
| `publish` | `auto` | `pages`, `artifact`, or `auto`. |
| `artifact` | `proofreel-review` | The artifact of the `run` action. |
| `token` | the job token | Needs `contents: write` and `pull-requests: write`. |

Outputs: `mode` (`pages` or `artifact`) and `link`.

**Pages.** The review goes to the `gh-pages` branch under `pr/NUMBER/`, and every other folder stays. When another job
pushes first, the action fetches the new head and pushes again (6 tries). The link is
`https://OWNER.github.io/REPO/pr/NUMBER/`. In the settings of the repository, set Pages to serve the `gh-pages`
branch. The folder of an old pull request stays until you delete it.

**Artifact.** The review stays in the artifact of the run, and the link goes to the run. The comment has no picture.

`auto` uses Pages for a pull request from the same repository. It uses the artifact for a fork, or when the push
fails, and the comment says why.

**The comment.** There is one comment on each pull request. The action finds it by a hidden marker and changes it in
place. It names the commit that it ran on, and each push replaces the text. It has a line for each journey (the
verdict, the failed check, the time), the poster of the first journey with a problem (or the first journey), and the
link. The same text goes to the job summary.

## Pull requests from forks

On a `pull_request` event from a fork, GitHub gives the whole run a read-only token. The `run` job works, and the
review stays in the artifact. The `publish` job cannot write to Pages or to the pull request, so it keeps the
artifact link in the job summary.

Do not use `pull_request_target` to get a comment. It runs the code of the fork with the secrets and the write token
of your repository. If you need comments on fork pull requests, use two workflows: the `run` job above on
`pull_request`, and a second workflow on `workflow_run` that downloads the artifact of that run and publishes it,
with no checkout of the fork. The `publish` action does not read `workflow_run` events yet, so that second workflow
needs its own step to give the pull request number.

## Run it on your machine

```bash
proofreel suite .proofreel/flows --out review --title "My app"
proofreel ci check review                  # the verdicts; exit 1 when a journey has a problem
proofreel ci comment review --link https://example.com/pr/1/   # print the comment
```
