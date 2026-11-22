# The review page

The page is described in [the README](../README.md#the-review-page).

![The review page of a passing journey: the video, the flow with the current state lit, and Tracks folded.](review-page.png)

![A failed run: Tracks open with Budget failed, and the failed check in the flow.](budget-failed.png)

## Review inbox

`proofreel inbox add <review folder>` puts the page in a local inbox, and `proofreel inbox wait <id>` returns the
decision to the agent. See [the README](../README.md#review-inbox).

## Review on claude.ai

`proofreel publish <session> --out <review folder>` adds a run to a review folder: one page that holds every run of
one journey, so the link in a pull request never changes. It prints every file that the page uses (`files`, for all
the runs in the folder), the files of the new run (`new`), and the page's runtime capabilities. Claude then publishes the page as a claude.ai Artifact (the same file path or URL each time). On
claude.ai the page also has:

- **Comments** on any step or moment, through the artifact's own comments, which can go to the Claude session that
  published the page.
- **Review**: Approve or Needs work for each run, kept in the page's database, so Claude can read the verdict.
- **Ask about this moment**: Claude answers a question from the current video frame and the run's log.

Opened as a plain file, the page is a static review page.

The review folder keeps `runs.json` (`{"version": 2, "runs": [...]}`). It is the only copy of old runs, because
`clean` deletes sessions after 7 days. A folder that an older proofreel wrote is upgraded when you publish to it, and
its old file is kept as `runs.v1.json`. Publishing locks the folder and writes each file whole, so two agents can
publish to one folder at once.
