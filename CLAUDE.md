@AGENTS.md

# Notes for Claude Code

`AGENTS.md`, imported above, is the contract, and all of it applies. Two more
things, which are about how a Claude session commits rather than about this
project:

- **Commit messages go in a file, and through `git commit -F`.** Backticks in
  `git commit -m "..."` are shell command substitution. One such message ran
  `make fixtures-gm`, whose `>` redirect truncated a fixture to zero bytes
  before curl failed.
- **End every commit message with a `Co-Authored-By:` trailer** naming the
  model — `Co-Authored-By: Claude <model> <noreply@anthropic.com>` — as the log
  already does. It is what keeps "the owner directs; Claude Code builds"
  checkable rather than claimed.
