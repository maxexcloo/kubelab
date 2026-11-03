#!/bin/sh
# Lists signed apps with links to their SignTools install pages, newest first.
cat <<'EOF'
Content-Type: text/html; charset=utf-8

<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Apps</title>
<style>
body { font: 17px/1.4 -apple-system, system-ui, sans-serif; margin: 0 auto; max-width: 36rem; padding: 1.5rem; }
a { border-bottom: 1px solid #8884; color: inherit; display: block; padding: 0.9rem 0; text-decoration: none; }
a::after { color: #08f; content: "Install"; float: right; }
</style>
</head>
<body>
<h1>Apps</h1>
EOF
for app in $(ls -t /data/apps); do
  [ -e "/data/apps/$app/signed" ] || continue
  name=$(sed 's/\.ipa$//' "/data/apps/$app/name")
  echo "<a href=\"/apps/$app/install\">$name</a>"
done
cat <<'EOF'
</body>
</html>
EOF
