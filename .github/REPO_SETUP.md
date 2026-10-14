# GitHub Repository Setup Checklist

After pushing the code, configure these in GitHub's web UI for maximum discoverability:

## 1. Repository Description (Settings > General)
Set this as the repo description:
```
Free, open-source GUI to decrypt, browse, and extract files from encrypted iPhone/iPad backups. 100% offline. No tracking.
```

## 2. Repository Topics (Settings > General > Topics)
Add ALL of these topics/tags — they are how people find repos on GitHub:
```
iphone-backup
iphone
ipad
ios
itunes-backup
backup-extractor
backup-decrypt
encrypted-backup
iphone-data-recovery
ios-backup
data-recovery
python
tkinter
gui
privacy
offline
macos
windows
linux
apple
```

## 3. Website URL
Set to: (leave blank until you have a landing page, or use the repo URL)

## 4. Social Preview Image
Upload the logo (assets/logo.svg converted to PNG, 1280x640 recommended)
Use a tool like https://svgtopng.com to convert

## 5. GitHub Pages (optional, for later)
Create a simple landing page at docs/index.html for extra SEO juice

## 6. Releases
Create a release with:
- Title: "iOS Backup Explorer — Your data. Your eyes only."
- Description: Copy the key features from README
- This shows up in GitHub search results prominently

## 7. Discussions
Enable Discussions (Settings > Features > Discussions)
This increases engagement and helps with GitHub's algorithm

## 8. Issue forms and labels
The issue forms are in .github/ISSUE_TEMPLATE/ and the labels they attach are
listed in .github/labels.yml. Create the labels once: Actions, "Labels",
"Run workflow" (it also runs when labels.yml changes), or run
`python tools/sync_labels.py` with the GitHub CLI signed in. Labels that
already exist are updated, nothing is deleted.

Also turn on (Settings > Code security):
- Private vulnerability reporting (the issue chooser links to it, and so does
  docs/HELPING.md for data posted by mistake)
- Dependabot alerts (.github/dependabot.yml opens the update pull requests)
