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
# local branch: on a test run the checkout is the PR's head and no local
# `develop` exists.
reset_tree() {
  git checkout --force --quiet --detach origin/develop
  git clean -fdq
}

failed=0
published=0

for dir in "$RESULTS"/scraper-*; do
  [ -d "$dir" ] || continue
  family="$(basename "$dir")"
  family="${family#scraper-}"

  # Only an explicit veto stops a family. A missing note is not one: the patch
  # and pr.json below say everything needed, and `research` has already failed
  # the family if the agent crashed or wrote outside the template tree.
  status="$(cat "$dir/status" 2>/dev/null || true)"
  case "$status" in
    failed:*)
      echo "::notice::${family}: skipped, research reported '${status}'"
      continue
      ;;
    ok) ;;
    *) echo "::warning::${family}: research left no status note; judging by its output" ;;
  esac

  patch="$dir/changes.patch"
  if [ ! -s "$patch" ]; then
    echo "::notice::${family}: already current, nothing to open"
    continue
  fi

  # Containment. The scraper bumps pins in template files and nothing else, so a
  # patch reaching outside that tree is the one shape an injected instruction
  # would need to edit a workflow, the playbook, or a script that runs later.
  stray="$(grep -v "^${ALLOWED_PATHS}" "$dir/changed-files" || true)"
  if [ -n "$stray" ]; then
    echo "::error::${family}: patch touches paths outside ${ALLOWED_PATHS}, refused:"
    printf '%s\n' "$stray" | sed 's/^/  /'
    failed=1
    continue
  fi

  if [ ! -s "$dir/pr.json" ]; then
    echo "::error::${family}: changed files but left no pr.json"
    failed=1
    continue
  fi
  title="$(jq -r '.title // empty' "$dir/pr.json")"
  jq -r '.body // empty' "$dir/pr.json" > "$dir/body.md"
  if [ -z "$title" ] || [ ! -s "$dir/body.md" ]; then
    echo "::error::${family}: pr.json has no usable title or body"
    failed=1
    continue
  fi

  branch="staleness-scraper/${family}"
  number="$(gh pr list --label "$LABEL" --head "$branch" --state open \
    --json number --jq '.[0].number // empty')"

  reset_tree
  if [ -n "$number" ]; then
    git fetch --quiet origin "$branch"
    git checkout --force --quiet -B "$branch" FETCH_HEAD
  else
    # A closed PR leaves its branch behind, and a branch freshly cut from
    # develop shares no history with it, so a plain push would be rejected and
    # we never force. Delete the dead one first; the closed PR keeps its commits.
    # Deleting a branch closes any PR on it, so ask about the branch rather than
    # about our label: a scraper PR someone un-labelled is still a live PR, and
    # the lookup above would not have seen it.
    any_open="$(gh pr list --head "$branch" --state open --json number \
      --jq '.[0].number // empty')"
    if [ -n "$any_open" ]; then
      echo "::warning::${family}: #${any_open} is open on ${branch} without the ${LABEL} label; leaving it alone"
      reset_tree
      continue
    fi
    if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
      echo "::notice::${family}: removing leftover ${branch} (no open PR uses it)"
      git push --quiet origin --delete "$branch"
    fi
    git checkout --force --quiet -B "$branch" origin/develop
  fi

  if ! git apply --3way --index "$patch" 2>/dev/null; then
    echo "::error::${family}: the research patch does not apply to ${branch}"
    reset_tree
    failed=1
    continue
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
    failed=1
    continue
  fi

  if git diff --cached --quiet; then
    echo "::notice::${family}: ${branch} already carries these changes"
    reset_tree
    continue
  fi

  git commit --quiet -m "$title"
  git push --quiet origin "$branch"

  if [ -n "$number" ]; then
    gh pr edit "$number" --title "$title" --body-file "$dir/body.md" >/dev/null
    echo "::notice::${family}: updated #${number}"
  else
    url="$(gh pr create --draft --base develop --head "$branch" \
      --title "$title" --body-file "$dir/body.md" --label "$LABEL")"
    number="${url##*/}"
    echo "::notice::${family}: opened #${number}"
  fi

  # Request a review only when nobody is on the PR yet: one opened before the
  # reviewer was configured has none, and re-requesting resets a review that has
  # already been left.
  if [ -n "$PR_REVIEWER" ]; then
    on_pr="$(gh pr view "$number" --json reviewRequests,reviews \
      --jq '[.reviewRequests[].login] + [.reviews[].author.login] | unique | join(",")')"
    if [ -z "$on_pr" ]; then
      gh pr edit "$number" --add-reviewer "$PR_REVIEWER" >/dev/null ||
        echo "::warning::${family}: could not request a review from ${PR_REVIEWER}"
    fi
  fi

  published=$((published + 1))
  reset_tree
done

echo "::notice::staleness scraper published ${published} PR(s)"
exit "$failed"
