#!/usr/bin/env bash
set -euo pipefail

# The data branch contains only the current CSV. It never changes main or Pages.
ref=refs/heads/ratings-data
previous=$(git ls-remote --refs origin "$ref" | cut -f1)
commit_args=(-m 'Refresh daily player ratings CSV')
if [[ -n "$previous" ]]; then
    git fetch --no-tags origin "$ref"
    commit_args+=(-p "$previous")
fi

blob=$(git hash-object -w "$1")
tree=$(printf '100644 blob %s\tplayer-ratings.csv\n' "$blob" | git mktree)
if [[ -n "$previous" && "$tree" == "$(git rev-parse "$previous^{tree}")" ]]; then
    exit 0
fi
commit=$(git -c user.name='github-actions[bot]' \
             -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
             commit-tree "$tree" "${commit_args[@]}")
git push origin "$commit:$ref"
