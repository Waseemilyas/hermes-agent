# Agent Edits to the Active Profile Config

By default the agent's file tools refuse to write `HERMES_HOME/config.yaml`.
That file *is* the security policy — `approvals.mode`, the deny rules, the
permanent-approval allowlist, the `security.*` gates, plugin enablement and the
secret bindings all live there — and the config cache is keyed on the file's
mtime, so a write takes effect mid-session. A prompt-injected agent that could
write it could disable its own approval gate and immediately use the hole.

Some operators still want the agent to maintain its own profile config: model
routing, context pins, timeouts, display knobs. `security.allow_active_profile_config_edits`
opens exactly that, and nothing else.

```yaml
security:
  allow_active_profile_config_edits: true   # default: false
```

## What the opt-in allows

* **Only this profile's own config.** `HERMES_HOME/config.yaml` when
  `HERMES_HOME` is a named profile (`<root>/profiles/<name>`). The shared root
  config at `<root>/config.yaml` and every other profile's config stay refused
  with or without the opt-in — they steer sessions this one is not running.
  Active-config (and root) lookup is keyed by this turn's Hermes home,
  including `set_hermes_home_override()`, so a multiplexed process that
  filled the cache as profile A does not keep classifying A's config as
  `active` on a later profile-B turn.
* **Only a profile session.** A profile-less session's config *is* the shared
  root config, so it keeps the hard refusal even with the flag set.
* **Nothing else moves.** `.env`, `auth.json`, `mcp-tokens/`, the browser
  profile snapshot, `state.db`, `sessions/` and every other protected path keep
  the guards they already had. So do `/etc`, `~/.ssh`, `AGENTS.md`/`CLAUDE.md`/
  `SOUL.md`, and project-local `.hermes` config trees.

## What stays locked, opt-in or not

A write is refused outright — no prompt, nothing applied — when it would change
any of these keys, whether by editing, adding or removing them:

| Key | Why |
| --- | --- |
| `approvals` | approval mode, deny rules, cron / single-query behaviour |
| `security` | every security gate, including this opt-in itself |
| `command_allowlist` | pre-approved shell commands |
| `hooks_auto_accept` | silent acceptance of hook output |
| `secrets` | secret-manager binding |
| `plugins` | in-process code with full agent privileges |
| `mcp_servers` | spawned stdio processes; auto-reloaded on config change |
| `code_execution.mode` | where `execute_code` runs |
| `skills.write_approval`, `skills.guard_agent_created`, `skills.inline_shell` | skill authoring and execution gates |
| `memory.write_approval` | memory write gate |
| `delegation.subagent_auto_approve` | subagent approval inheritance |
| `dashboard.basic_auth`, `dashboard.oauth` | dashboard authentication |
| `terminal.credential_files` | credential-file handling |
| `gateway.media_delivery_allow_dirs` | which files can leave as attachments |

Because the opt-in itself lives under `security`, the agent can never widen its
own permission. Only the user can, by editing the file by hand or with
`hermes config`. The list lives in `_LOCKED_CONFIG_KEYS` in
`tools/file_tools.py`; add to it there.

## Every write still needs a human

An allowed write is not a free write. It goes through the same one-operation
approval contract as the protected instruction files:

* the user is asked **every time** — nothing is remembered for the session;
* `--yolo` / `approvals.mode: off` / a permanent allowlist entry do **not**
  bypass it;
* with no interactive user and no gateway (cron, background jobs, scripts) the
  write fails closed.

The prompt names the file and the top-level sections the write changes.

## How each tool is checked

* **`write_file`** supplies the whole document, so the locked keys are diffed
  between the file on disk and the proposed content *before* the approval
  prompt, then re-read and re-diffed inside the path lock immediately before
  the write. The resolved active-config path is bound at approval; if the
  path no longer resolves to exactly that file (a retargeted symlink, or a
  sibling replacing the target) the write is refused. If the file's contents
  moved while the prompt was on screen and applying the approved document
  would now change a locked key, the write is refused. Content that is not
  a YAML mapping — or a file on disk that no longer parses — is refused, so a
  bad write cannot leave the loader silently falling back to defaults.
* **`patch`** cannot be pre-checked: the patch engine, not the caller, produces
  the resulting document. The approval happens first, binding the same
  resolved active-config path; then the file is snapshotted, patched, and
  re-checked inside the same path lock. If the live target is no longer that
  file, or the result changes a locked key or stops parsing, the pre-patch
  contents are restored (when a snapshot exists) and the tool reports the
  rejection.
* A patch or write that touches the config **and** any other file is refused, so
  a single approval naming the config never carries other files with it.

## Limits (read this before relying on it)

This gate is defense-in-depth, not a boundary — the same framing as the rest of
[SECURITY.md](../../SECURITY.md) §2.4:

* The **terminal tool** runs as the same OS user and can write `config.yaml`
  with `sed`/`tee`/`>`. That path is gated by the dangerous-command approval
  patterns (`_HERMES_CONFIG_PATH` in `tools/approval.py`), which — unlike this
  gate — *are* bypassed by `--yolo` and can be pre-approved. The locked-key rule
  cannot be enforced there, because the check would have to predict what a shell
  command produces.
* **`execute_code`** runs arbitrary Python and is approved per script, not per
  file write (documented limitation, upstream #30882).
* Nothing here protects against a user who approves a write they did not read.

Turning the opt-in off restores the historical hard refusal on the file-tool
paths; it does not change the terminal or `execute_code` behaviour, which were
never a hard refusal.
