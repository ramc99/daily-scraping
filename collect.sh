#!/bin/bash
# Collects code + outputs from all scrapers into a dated folder and pushes to git.
# Usage: bash collect.sh

DATE=$(date +%Y-%m-%d)
DEST=~/daily-scraping/$DATE

echo "Collecting code + outputs → $DEST"
mkdir -p "$DEST"

# Copy each project folder entirely (excluding .git and __pycache__)
for project in maps-scraper seniorly-2 seniorly-providers seniorly-scraper; do
    src=~/$project
    if [ -d "$src" ]; then
        rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' "$src/" "$DEST/$project/"
        echo "  ✓ $project"
    fi
done

# Push to git
cd ~/daily-scraping
git add "$DATE/"
git commit -m "Daily scraping outputs + code $DATE"
git push

echo "Done. Pushed to github.com/ramc99/daily-scraping"
