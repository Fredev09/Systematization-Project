"""
Phase 1: Build COMPLETE extends/includes graph from ALL project templates.
Detect cycles automatically.
"""
import os
import re
from pathlib import Path

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.base"
import django
django.setup()

from django.template.loader import get_template
from django.template import engines

BASE_DIR = Path(r"C:\Users\fredd\OneDrive\Desktop\ProjectSis")

# ── Collect ALL html files ──
html_files = list(BASE_DIR.rglob("*.html"))
print(f"Total .html files found: {len(html_files)}")

# ── Parse includes and extends from each file ──
graph = {}  # file -> {"extends": set(), "includes": set()}

for f in html_files:
    rel = f.relative_to(BASE_DIR)
    key = str(rel).replace("\\", "/")
    graph[key] = {"extends": set(), "includes": set()}
    
    try:
        content = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    
    # Find extends
    for m in re.finditer(r'\{%\s*extends\s+"([^"]+)"', content):
        graph[key]["extends"].add(m.group(1))
    for m in re.finditer(r"\{%\s*extends\s+'([^']+)'", content):
        graph[key]["extends"].add(m.group(1))
    # With variable
    for m in re.finditer(r'\{%\s*extends\s+([\w.]+)', content):
        name = m.group(1)
        if name not in ('"', "'"):
            graph[key]["extends"].add(f"VAR:{name}")
    
    # Find includes
    for m in re.finditer(r'\{%\s*include\s+"([^"]+)"', content):
        graph[key]["includes"].add(m.group(1))
    for m in re.finditer(r"\{%\s*include\s+'([^']+)'", content):
        graph[key]["includes"].add(m.group(1))
    # With variable
    for m in re.finditer(r'\{%\s*include\s+([\w.]+)', content):
        name = m.group(1)
        if name not in ('"', "'"):
            graph[key]["includes"].add(f"VAR:{name}")

# ── Print key files ──
print("\n=== TEMPLATES WITH EXTENDS ===")
for k, v in sorted(graph.items()):
    if v["extends"]:
        print(f"  {k}")
        for e in v["extends"]:
            print(f"    extends -> {e}")

print("\n=== TEMPLATES WITH INCLUDES ===")
for k, v in sorted(graph.items()):
    if v["includes"]:
        print(f"  {k}")
        for i in v["includes"]:
            print(f"    include -> {i}")

# ── Detect cycles ──
print("\n=== CYCLE DETECTION ===")

def resolve(template_name):
    """Try to resolve a template name to a project file path."""
    # Direct path
    p = BASE_DIR / template_name
    if p.exists():
        return str(p.relative_to(BASE_DIR)).replace("\\", "/")
    # templates/ prefix
    p = BASE_DIR / "templates" / template_name
    if p.exists():
        return str(p.relative_to(BASE_DIR)).replace("\\", "/")
    # Maybe already found
    if template_name in graph:
        return template_name
    return None

def find_all_paths(start, visited=None, path=None, depth=0):
    """DFS from start to find cycles or dead ends."""
    if visited is None:
        visited = set()
    if path is None:
        path = []
    
    if start in visited:
        # Found a cycle
        cycle_start = path.index(start)
        cycle_path = path[cycle_start:] + [start]
        return [("CYCLE", cycle_path)]
    
    visited.add(start)
    path.append(start)
    
    results = []
    
    if start in graph:
        node = graph[start]
        # Check extends first
        for ext in node["extends"]:
            resolved = resolve(ext)
            if resolved:
                results.extend(find_all_paths(resolved, visited.copy(), path.copy(), depth+1))
            else:
                results.append(("UNRESOLVED", path + [f"<{ext}>"]))
        
        # Then includes
        for inc in node["includes"]:
            resolved = resolve(inc)
            if resolved:
                results.extend(find_all_paths(resolved, visited.copy(), path.copy(), depth+1))
            else:
                results.append(("UNRESOLVED", path + [f"<{inc}>"]))
    
    return results

# Find cycles starting from document_upload
entry = "apps/platform/document_intelligence/templates/document_intelligence/document_upload.html"
all_results = find_all_paths(entry)

cycles_found = [r for r in all_results if r[0] == "CYCLE"]
unresolved = [r for r in all_results if r[0] == "UNRESOLVED"]

if cycles_found:
    print(f"\n{'='*60}")
    print(f"CYCLE DETECTED! {len(cycles_found)} cycles found:")
    print(f"{'='*60}")
    for i, (_, cycle) in enumerate(cycles_found):
        print(f"\nCycle {i+1}:")
        for j, step in enumerate(cycle):
            marker = " → " if j > 0 else "    "
            print(f"  {marker}[{j}] {step}")
else:
    print("  NO CYCLE FOUND in include/extends graph")

print(f"\nUnresolved references: {len(unresolved)}")
for status, path in unresolved[:20]:
    print(f"  {status}: {' → '.join(path)}")
