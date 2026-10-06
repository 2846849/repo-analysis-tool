#!/usr/bin/env bash
# Clone the three reference repositories used to validate the metric engine.
# The CSV reference files were generated at the current HEAD of each repo,
# so a plain clone of the default branch reproduces the exact commit set.
set -u
cd "$(dirname "$0")/clones" || exit 1

for spec in \
  "cJSON|https://github.com/DaveGamble/cJSON.git" \
  "redis|https://github.com/redis/redis.git" \
  "git|https://github.com/git/git.git"
do
  name="${spec%%|*}"
  url="${spec#*|}"
  if [ -d "$name/.git" ]; then
    echo "$name: already cloned"
    continue
  fi
  echo "$name: cloning from $url ..."
  if git clone -q "$url" "$name"; then
    echo "$name: clone OK"
  else
    echo "$name: clone FAILED"
  fi
done
echo "ALL_CLONES_DONE"
