#!/bin/bash
# Collects outputs from all scrapers into a dated folder and pushes to git.
# Usage: bash collect.sh

DATE=$(date +%Y-%m-%d)
DEST=~/daily-scraping/$DATE

echo "Collecting outputs → $DEST"
mkdir -p "$DEST"

# maps-scraper
if [ -d ~/maps-scraper/outputs ]; then
    cp -r ~/maps-scraper/outputs "$DEST/maps-scraper"
    echo "  ✓ maps-scraper"
fi

# seniorly-2
if [ -d ~/seniorly-2/output ]; then
    cp -r ~/seniorly-2/output "$DEST/seniorly-2"
    echo "  ✓ seniorly-2"
fi

# seniorly-providers
if [ -d ~/seniorly-providers/outputs ]; then
    cp -r ~/seniorly-providers/outputs "$DEST/seniorly-providers"
    echo "  ✓ seniorly-providers"
fi

# seniorly-scraper
if [ -d ~/seniorly-scraper/output ]; then
    cp -r ~/seniorly-scraper/output "$DEST/seniorly-scraper"
    echo "  ✓ seniorly-scraper"
fi

# Push to git
cd ~/daily-scraping
git add "$DATE/"
git commit -m "Daily scraping outputs $DATE"
git push

echo "Done. Pushed to github.com/ramc99/daily-scraping"
