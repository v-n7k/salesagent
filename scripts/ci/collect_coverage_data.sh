#!/usr/bin/env bash
# Name the coverage data files the Coverage job combines, in combine order, one per line.
# Runs in the job's workspace, where the download steps put the artifacts:
#   .coverage                                                      the unit suite
#   bdd-coverage-shards/**/.coverage.bdd-<id>                      one per BDD shard id
#   integration-coverage-groups/**/.coverage.integration-<group>   one per host integration group
#   admin-coverage/.coverage.admin                                 the admin suite
# A missing file fails by name with a ::error:: annotation and nothing is listed, so a caller
# cannot combine a partial set. Errors go to stderr: the caller captures stdout.
# Contract: tests/unit/test_collect_coverage_data.py.
set -euo pipefail

usage() {
  echo "Usage: $0 --bdd-shards '<ids>' --host-groups '<groups>'" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case "$1" in
    --bdd-shards) bdd_shards="$2" ;;
    --host-groups) host_groups="$2" ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n "${bdd_shards+set}" && -n "${host_groups+set}" ]] || usage

# collect_data_files <array> <dir> <file prefix> <error prefix> <ids>
# Appends each id's data file under <dir> to <array>. A missing file or directory fails by name.
collect_data_files() {
  local -n collected_ref="$1"
  local dir="$2" prefix="$3" missing="$4" ids="$5" id found
  if [ -z "${ids}" ]; then
    echo "::error::${missing}: no ids to collect" >&2
    exit 1
  fi
  for id in ${ids}; do
    found=""
    # find on a missing directory would stop the script here, before the error below names the id.
    if [ -d "${dir}" ]; then
      found="$(find "${dir}" -name "${prefix}${id}" -type f | head -1)"
    fi
    if [ -z "${found}" ]; then
      echo "::error::${missing} ${id} (${prefix}${id})" >&2
      exit 1
    fi
    collected_ref+=("${found}")
  done
}

data_files=()
if [ ! -f .coverage ]; then
  echo "::error::Unit coverage data file missing." >&2
  exit 1
fi
data_files+=(.coverage)
collect_data_files data_files bdd-coverage-shards .coverage.bdd- \
  "Missing BDD coverage artifact for shard" "${bdd_shards}"
collect_data_files data_files integration-coverage-groups .coverage.integration- \
  "Missing integration coverage artifact for group" "${host_groups}"
if [ ! -f admin-coverage/.coverage.admin ]; then
  echo "::error::Missing admin coverage artifact (.coverage.admin)" >&2
  exit 1
fi
data_files+=(admin-coverage/.coverage.admin)
printf '%s\n' "${data_files[@]}"
