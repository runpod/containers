# shellcheck shell=bash
# Sourced by composite actions. A failed job can only be re-run after the
# whole workflow run finishes, so transient registry/mirror errors are
# retried inside the step instead.
#
# retry <attempts> <base-delay-seconds> <label> <command...>
#   Runs <command> up to <attempts> times, sleeping attempt*<base-delay>
#   between tries. Retry notices go to stderr so callers can capture stdout.
retry() {
  local max_attempts="$1" base_delay="$2" label="$3"
  shift 3
  if ! [[ "${max_attempts}" =~ ^[1-9][0-9]*$ && "${base_delay}" =~ ^[0-9]+$ ]]; then
    echo "::error::retry: invalid attempts='${max_attempts}' or delay='${base_delay}'" >&2
    return 2
  fi
  local attempt
  for attempt in $(seq 1 "${max_attempts}"); do
    "$@" && return 0
    if [ "${attempt}" -lt "${max_attempts}" ]; then
      echo "::warning::${label} failed (attempt ${attempt}/${max_attempts}), retrying in $((attempt * base_delay))s" >&2
      sleep $((attempt * base_delay))
    fi
  done
  echo "::error::${label} failed after ${max_attempts} attempts" >&2
  return 1
}
