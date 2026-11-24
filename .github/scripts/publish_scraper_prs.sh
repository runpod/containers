#!/usr/bin/env bash
# Opens or updates one draft PR per family from what the research jobs left
# behind. This is the write half of .github/workflows/staleness-scraper.yml.
#
# No model runs here. The agent that read untrusted upstream text hands over two
# things only, a patch and a title/body, and both are treated as data: the patch
# is rejected unless every path it touches is under ALLOWED_PATHS, and the body
# reaches `gh` through a file rather than the command line. Every other decision
# (which branch, whether a PR exists, whether to request a review) is taken from
# the repository's own state.
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${RESULTS:?RESULTS is required}"
: "${ALLOWED_PATHS:?ALLOWED_PATHS is required}"
PR_REVIEWER="${PR_REVIEWER:-}"
LABEL="staleness-scraper"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

gh label create "$LABEL" --color ededed \
  --description "Opened by the weekly staleness scraper" >/dev/null 2>&1 || true

# Back to a clean develop between families. Uses origin/develop rather than a
# local branch: the checkout is detached and carries no local `develop`.
reset_tree() {
  git checkout --force --quiet --detach origin/develop
  git clean -fdq
}

# Request a review only when nobody is on the PR yet: one opened before the
# reviewer was configured has none, and re-requesting resets a review already
# left. Runs for an up-to-date PR too, which is why it is not inside the
# "there is something to push" path below.
request_review() {
  pr_number="$1"
  [ -n "$PR_REVIEWER" ] || return 0
  on_pr="$(gh pr view "$pr_number" --json reviewRequests,reviews \
    --jq '[.reviewRequests[].login] + [.reviews[].author.login] | unique | join(",")')" || return 0
  [ -z "$on_pr" ] || return 0
  gh pr edit "$pr_number" --add-reviewer "$PR_REVIEWER" >/dev/null ||
    echo "::warning::could not request a review from ${PR_REVIEWER} on #${pr_number}"
}

# One family. Every fallible step returns non-zero rather than letting `set -e`
# take the whole script down: a push that fails for pytorch must not stop
# sandbox-ubuntu from being published.
publish_family() {
  dir="$1"
  family="$(basename "$dir")"
  family="${family#scraper-}"

  # Only an explicit veto stops a family. A missing note is not one: the patch
  # and pr.json below say everything needed, and `research` has already failed
  # the family if the agent crashed or wrote outside the template tree.
  status="$(cat "$dir/status" 2>/dev/null || true)"
  case "$status" in
    failed:*)
      echo "::notice::${family}: skipped, research reported '${status}'"
      return 0
      ;;
    ok) ;;
    *) echo "::warning::${family}: research left no status note; judging by its output" ;;
  esac

  branch="staleness-scraper/${family}"
  # --head is a prefix match, not an exact one: `staleness-scraper/pytorch` also
  # returns the pytorch-cluster PR, and taking .[0] picks whichever the API
  # happens to list first. Filter on the exact ref. BRANCH goes through the
  # environment so the jq program stays free of shell interpolation.
  number="$(BRANCH="$branch" gh pr list --label "$LABEL" --head "$branch" --state open \
    --json number,headRefName \
    --jq 'map(select(.headRefName == env.BRANCH))[0].number // empty')" || return 1

  patch="$dir/changes.patch"
  if [ ! -s "$patch" ]; then
    # Nothing new to push, but an existing PR may still be waiting for a
    # reviewer: one opened before PR_REVIEWER was configured has none, and this
    # is the only pass that will look at it.
    if [ -n "$number" ]; then
      request_review "$number"
      echo "::notice::${family}: already current; #${number} left as it is"
    else
      echo "::notice::${family}: already current, nothing to open"
    fi
    return 0
  fi

  # Containment. The scraper bumps pins in template files and nothing else, so a
  # patch reaching outside that tree is the one shape an injected instruction
  # would need to edit a workflow, the playbook, or a script that runs later.
  stray="$(grep -v "^${ALLOWED_PATHS}" "$dir/changed-files" || true)"
  if [ -n "$stray" ]; then
    echo "::error::${family}: patch touches paths outside ${ALLOWED_PATHS}, refused:"
    printf '%s\n' "$stray" | sed 's/^/  /'
    return 1
  fi

  if [ ! -s "$dir/pr.json" ]; then
    echo "::error::${family}: changed files but left no pr.json"
    return 1
  fi
  title="$(jq -r '.title // empty' "$dir/pr.json")"
  jq -r '.body // empty' "$dir/pr.json" > "$dir/body.md"
  if [ -z "$title" ] || [ ! -s "$dir/body.md" ]; then
    echo "::error::${family}: pr.json has no usable title or body"
    return 1
  fi

  reset_tree
  if [ -n "$number" ]; then
    git fetch --quiet origin "$branch" || return 1
    git checkout --force --quiet -B "$branch" FETCH_HEAD || return 1
  else
    # A closed PR leaves its branch behind, and a branch freshly cut from
    # develop shares no history with it, so a plain push would be rejected and
    # we never force. Delete the dead one first; the closed PR keeps its commits.
    # Deleting a branch closes any PR on it, so ask about the branch rather than
    # about our label: a scraper PR someone un-labelled is still a live PR, and
    # the lookup above would not have seen it.
    # `|| return 1`, not a bare call: errexit is off in here, and a failed
    # lookup would read as "no open PR" and delete a branch that has one.
    any_open="$(BRANCH="$branch" gh pr list --head "$branch" --state open \
      --json number,headRefName \
      --jq 'map(select(.headRefName == env.BRANCH))[0].number // empty')" || return 1
    if [ -n "$any_open" ]; then
      echo "::warning::${family}: #${any_open} is open on ${branch} without the ${LABEL} label; leaving it alone"
      reset_tree
      return 0
    fi
    if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
      echo "::notice::${family}: removing leftover ${branch} (no open PR uses it)"
      git push --quiet origin --delete "$branch" || return 1
    fi
    git checkout --force --quiet -B "$branch" origin/develop || return 1
  fi

  if ! git apply --3way --index "$patch" 2>/dev/null; then
    echo "::error::${family}: the research patch does not apply to ${branch}"
    reset_tree
    return 1
  fi

  # Re-check what actually landed, with rename detection off. `--name-only`
  # collapses a rename to its destination, so a move out of .github/ into
  # official-templates/ passes the list check above while still deleting a file
  # outside the allowed tree. This looks at the applied result rather than at a
  # file the agent wrote, which makes it the check that counts.
  applied="$(git diff --cached --name-only --no-renames | grep -v "^${ALLOWED_PATHS}" || true)"
  if [ -n "$applied" ]; then
    echo "::error::${family}: applying the patch reached outside ${ALLOWED_PATHS}:"
    printf '%s\n' "$applied" | sed 's/^/  /'
    reset_tree
    return 1
  fi

  if git diff --cached --quiet; then
    # Nothing new to commit, but this is still an open PR that may never have
    # been given a reviewer. Same reason as the empty-patch path above.
    [ -z "$number" ] || request_review "$number"
    echo "::notice::${family}: ${branch} already carries these changes"
    reset_tree
    return 0
  fi

  git commit --quiet -m "$title" || return 1
  git push --quiet origin "$branch" || return 1

  if [ -n "$number" ]; then
    gh pr edit "$number" --title "$title" --body-file "$dir/body.md" >/dev/null || return 1
    echo "::notice::${family}: updated #${number}"
  else
    url="$(gh pr create --draft --base develop --head "$branch" \
      --title "$title" --body-file "$dir/body.md" --label "$LABEL")" || return 1
    number="${url##*/}"
    echo "::notice::${family}: opened #${number}"
  fi

  request_review "$number"
  published=$((published + 1))
  reset_tree
}

failed=0
published=0

# A family is called through `if !`, which both contains its failure and, as a
# side effect, disables errexit inside it. That is why publish_family guards its
# own fallible commands with `|| return 1` instead of relying on `set -e`.
for dir in "$RESULTS"/scraper-*; do
  [ -d "$dir" ] || continue
  if ! publish_family "$dir"; then
    name="$(basename "$dir")"
    echo "::error::${name#scraper-}: not published; continuing with the other families"
    failed=1
  fi
  reset_tree
done

echo "::notice::staleness scraper published ${published} PR(s)"
exit "$failed"
