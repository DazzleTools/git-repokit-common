"""Compare test function bodies (docstrings stripped) between a git ref and the working tree."""
import ast, subprocess, sys

def bodies(src):
    out = {}
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef):
            body = n.body[1:] if n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant) else n.body
            out[n.name] = (ast.dump(ast.Module(body=body, type_ignores=[])), [ast.dump(d) for d in n.decorator_list])
    return out

ref, path = sys.argv[1], sys.argv[2]
old = bodies(subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=True).stdout)
new = bodies(open(path, encoding="utf-8").read())
for name in sorted(set(old) | set(new)):
    if name not in new: print("REMOVED", name)
    elif name not in old: print("ADDED  ", name)
    elif old[name][0] != new[name][0]: print("BODY   ", name)
    elif old[name][1] != new[name][1]: print("DECOR  ", name)
print("old", len(old), "new", len(new))
