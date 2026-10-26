import os
import re

frontend_src = "frontend/src"
all_issues = {}

for root, dirs, files in os.walk(frontend_src):
    for f in files:
        if f.endswith(".jsx") or f.endswith(".js"):
            file_path = os.path.join(root, f)
            with open(file_path, "r", encoding="utf-8") as fp:
                content = fp.read()

            # Find all react-icons imports
            import_blocks = re.findall(r'import\s*\{([^}]+)\}\s*from\s*[\'"]react-icons/[^\'"]+[\'"]', content)
            imported = set()
            for b in import_blocks:
                for item in b.split(","):
                    name = item.strip()
                    if name:
                        # Handle "as alias"
                        if " as " in name:
                            imported.add(name.split(" as ")[1].strip())
                        else:
                            imported.add(name)

            # Find all JSX usages <Ri... or <Fi... or <Hi... etc
            used = set(re.findall(r'<([A-Z][a-zA-Z0-9]*(?:Line|Fill))\b', content))
            missing = {u for u in used if u not in imported}
            if missing:
                all_issues[file_path] = list(missing)

print("=== CHECK ALL ICON IMPORTS RESULT ===")
if not all_issues:
    print("All icons are properly imported across the entire codebase!")
else:
    for path, missing_icons in all_issues.items():
        print(f"File: {path}")
        print(f"  Missing icons: {missing_icons}")
