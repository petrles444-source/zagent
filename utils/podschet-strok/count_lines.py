import os, sys

def is_ignored(path):
    parts = path.split(os.sep)
    return any(p in {'.git', '.venv', '.pytest_cache', 'pytest-of-HP'} for p in parts)

total_lines = 0
file_count = 0
for root, dirs, files in os.walk('.'): 
    # modify dirs in‑place to skip ignored directories and avoid descending into them
    dirs[:] = [d for d in dirs if not is_ignored(os.path.join(root, d))]
    for f in files:
        if f.endswith('.py'):
            full_path = os.path.join(root, f)
            if is_ignored(full_path):
                continue
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as fh:
                    lines = sum(1 for _ in fh)
                total_lines += lines
                file_count += 1
            except Exception as e:
                # ignore files we cannot read
                pass
print(f"Python files: {file_count}\nTotal lines of code: {total_lines}")
