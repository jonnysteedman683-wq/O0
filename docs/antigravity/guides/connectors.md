# O0 connectors: UniSync, GitHub stack, dispatch

`extensions/connectors/` joins O0 to Jonny's wider stack. Stdlib only, opt-in, fail-open.

| Piece | What it does | Needs |
|---|---|---|
| `unisync.UnisyncClient` | Posts O0's heartbeat, scoped memory and escalations to the shared UniSync ledger. | `UNISYNC_SUPABASE_URL`, `UNISYNC_SUPABASE_KEY` (O0's gateway token) |
| `github.GitHubConnector` / `github_stack()` | Probes each project by its GitHub repo: reachable, default branch, head commit, last push. | Optional `GITHUB_TOKEN` (private repos) |
| `dispatch.Dispatcher` | Hands a task to `sebastian`, `lestinxor`, `hermes`, `jules` or `claude` as a `task.request`. | UniSync |

## Safety

- O0 is a UniSync **orchestrator**: it may request work, never claim, complete or approve it.
- Every request O0 posts has `requires_approval: true`, so it waits for Jonny's `approval.decision`.
  The client refuses any other form.
- Task ids are `o0-` plus 16 hex of `sha256(prev, title)`. `prev` is unique, so ids never collide
  (a duplicate would break every reader's replay).
- The client re-verifies the head digest before writing and never shows its key.
- Nothing here runs another agent or edits another repo.

## Setup (once)

1. Merge LESTINXOR-AGENT's "register O0 on UniSync" PR **first**: readers reject unknown senders.
2. In the Supabase SQL editor, register O0 and mint its token (shown once; only its hash is stored):

```sql
insert into public.unisync_agents (name, role, repos)
values ('o0', 'orchestrator', '{jonnysteedman683-wq/O0}')
on conflict (name) do nothing;

with t as (select encode(extensions.gen_random_bytes(32), 'hex') as tok),
ins as (
  insert into public.unisync_tokens (agent, token_hash, kinds)
  select 'o0', encode(extensions.digest(tok, 'sha256'), 'hex'),
         '{heartbeat,memory.write,escalate,task.request}'
  from t
  returning id
)
select tok as o0_token from t;
```

3. Wherever O0 runs, set:

```
UNISYNC_SUPABASE_URL=https://dcjqwnapxgocitvntzzm.supabase.co/functions/v1/unisync
UNISYNC_SUPABASE_KEY=<o0_token from step 2>
GITHUB_TOKEN=<optional, read-only fine-grained token for private repos>
```

## Use

```bash
python -m extensions.connectors status                     # every project repo
python -m extensions.connectors heartbeat                  # prove O0 is on the ledger
python -m extensions.connectors dispatch sebastian "Run the red-team evals" --detail "after B64"
```

Revoke O0 at any time: `update public.unisync_tokens set revoked_at = now() where agent = 'o0';`
