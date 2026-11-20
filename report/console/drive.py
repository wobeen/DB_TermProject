import sys
sys.path.insert(0, r"C:\Users\sinub\orca\projects\DB_TermProject")
from scouting.cli.main import main
ans = [l.rstrip("\n") for l in open(sys.argv[2], encoding="utf-8")]
it = iter(ans)
def inp(p=""):
    try: a = next(it)
    except StopIteration: raise EOFError
    print(p + a); return a
sys.stdout.reconfigure(encoding="utf-8")
main(["--db", sys.argv[1]], input_fn=inp)
