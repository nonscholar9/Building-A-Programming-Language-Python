"""
IB_Optimizer - bytecode in, better bytecode out.

Every pass before this one changed what the program *says*.  The expander said
it in fewer forms, the compiler said it in instructions, the addresser said
where the variables live.  This one changes nothing about what the program
says.  It produces a different program with the same meaning, and the only
reason to run it is that the new program does less work.

Which means this is the first pass that has to prove its worth with a number,
and the number is instructions executed.  Not seconds: seconds measure the
computer and whatever else it was doing.  A count of instructions is the same
on every machine, and it is the thing the optimization actually removes.

THREE OPTIMIZATIONS, IN THE ORDER THEY EARN THEIR PLACE

  1. CONSTANT FOLDING.  `(+ 1 2)` can be 3 before the program runs -- but only
     if nobody can change what `+` means first.  In this language `+` is an
     ordinary global, and a program is free to assign to it.  So the fold is
     legal only after we have looked through the whole program and found no
     assignment to the name.  That check is the optimization; the arithmetic
     is the easy part.

  2. CONSTANT TESTS.  After the expander has been through it, a program is
     full of `if`s whose test is a literal -- `(and #f x)` becomes
     `(if #f x #f)`.  A test that cannot vary is a branch that cannot vary, so
     one arm is unreachable and the test itself need not run.

  3. JUMP THREADING.  A jump to a jump can go straight to the destination, and
     a jump to a return can just return.

Then everything unreachable is dropped, and here is the part worth slowing down
for: DELETING AN INSTRUCTION MOVES EVERY INSTRUCTION AFTER IT.  Every address
in the program -- branch targets, jump targets, the body address inside a
closure -- is an index into the list being shortened.  So a deletion is never
just a deletion; it is a deletion plus a relocation, and `compact` below is
where that debt gets paid.

Run with: python IB_Optimizer.py
"""

from IB_AST import LBoolean, lTrue, lFalse, lisp_str
from IB_Reader   import parse
from IB_Expander import expand
from IB_VM       import (OP_INT, OP_QUOTE, OP_LOCAL, OP_GLOBAL, OP_LAM,
                         OP_JUMP, OP_APP_START, OP_APPLY_ARG, OP_CALL,
                         OP_TCALL, OP_IF_START, OP_APPLY_IF, OP_RET,
                         OP_SET_LOCAL, OP_SET_GLOBAL, OP_SET_VAR,
                         run_vm, disassemble, GLOBALS, STEPS)
from IB_Compiler import compile_program


# ---------------------------------------------------------------------------
# What may be folded
# ---------------------------------------------------------------------------
#
# Pure means: the same arguments always give the same answer, and computing it
# changes nothing.  `print` is not here, because computing it is the point of
# calling it.
#
# The list primitives ARE here, and the reason they can be is a fact about this
# language rather than about folding.  A folded value is computed once and then
# shared by every run of that line, so folding `(list 1 2)` hands the same list
# to every pass through the code.  Nothing in our Lisp can tell that apart from
# a fresh list each time: there is no `set-car!` to change one, and no `eq?` to
# ask whether two are the same object.  `quote` has been handing out one shared
# list per program since Chapter 1 for exactly this reason.

PURE = { '+', '-', '*', '%', 'not',
         '=', '<', '>', '<=', '>=',
         'car', 'cdr', 'cons', 'list', 'null?' }

# What a fold may read, and what may stand in front of it.  A quoted datum is
# as constant as a number; the operator is the one GLOBAL in the run.
CONST = (OP_INT, OP_QUOTE)
ATOM  = (OP_INT, OP_QUOTE, OP_GLOBAL)


def assigned_globals(code):
  """Every global name the program assigns to.

    This is the whole safety argument for folding.  A name that is never on the
    left of an assignment still means, at the moment this program runs, what it
    meant when the machine started.
    """
  return { instr[1] for instr in code
           if instr is not None
           and instr[0] in (OP_SET_GLOBAL, OP_SET_VAR) }


# ---------------------------------------------------------------------------
# 1. Constant folding
# ---------------------------------------------------------------------------
#
# The shape a call has in this bytecode is fixed and easy to recognize:
#
#     APP_START
#     GLOBAL   +          <- the operator
#     APPLY_ARG
#     INT      1          <- an operand
#     APPLY_ARG
#     INT      2
#     APPLY_ARG
#     CALL  (or TCALL)
#
# If the operator is a pure primitive nobody reassigns, and every operand is a
# constant, the whole run of instructions is one number.

def fold_constants(code, frozen):
  changed = False
  for pc, instr in enumerate(code):
    if instr is None or instr[0] != OP_APP_START:
      continue

    # Walk the operator and operands, insisting every one is a constant.
    i     = pc + 1
    parts = []
    while True:
      cur = code[i] if i < len(code) else None
      nxt = code[i + 1] if i + 1 < len(code) else None
      if cur is None or nxt is None:
        break
      if cur[0] not in ATOM:
        break
      if nxt[0] != OP_APPLY_ARG:
        break
      parts.append(cur)
      i += 2

    if len(parts) < 2 or i >= len(code) or code[i] is None:
      continue
    if code[i][0] not in (OP_CALL, OP_TCALL):
      continue

    head, *rest = parts
    if head[0] != OP_GLOBAL:
      continue
    name = head[1]
    if name not in PURE or name in frozen:
      continue
    if any(a[0] not in CONST for a in rest):
      continue

    try:
      value = GLOBALS[name]([a[1] for a in rest])
    except Exception:
      continue      # (car '()) is the program's error, not ours

    if isinstance(value, (int, LBoolean)):
      folded = (OP_INT, value)
    elif isinstance(value, (list, str)):   # a list or a symbol
      folded = (OP_QUOTE, value)
    else:
      continue

    tail = code[i][0] == OP_TCALL
    for k in range(pc, i + 1):        # blank the whole call
      code[k] = None
    code[pc] = folded
    if tail:
      code[pc + 1] = (OP_RET,)
    changed = True
  return changed


# ---------------------------------------------------------------------------
# 2. Constant tests
# ---------------------------------------------------------------------------
#
#     IF_START then else
#     INT      #f            <- a test that cannot come out any other way
#     APPLY_IF
#
# becomes a jump straight to the arm that was always going to run.  The other
# arm is now unreachable, and step 4 will notice.

def fold_constant_tests(code):
  changed = False
  for pc, instr in enumerate(code):
    if instr is None or instr[0] != OP_IF_START:
      continue
    nxt, after = code[pc + 1], code[pc + 2]
    if nxt is None or after is None:
      continue
    if nxt[0] not in (OP_INT, OP_QUOTE) or after[0] != OP_APPLY_IF:
      continue
    _, then_pc, else_pc = instr
    taken = then_pc if nxt[1] is not lFalse else else_pc
    code[pc]     = (OP_JUMP, taken)
    code[pc + 1] = None
    code[pc + 2] = None
    changed = True
  return changed


# ---------------------------------------------------------------------------
# 3. Jump threading
# ---------------------------------------------------------------------------

def _final(code, target, seen=None):
  """Follow a chain of jumps to where it actually ends up."""
  seen = seen or set()
  while (target < len(code) and code[target] is not None
         and code[target][0] == OP_JUMP and target not in seen):
    seen.add(target)
    target = code[target][1]
  return target


def thread_jumps(code):
  changed = False
  for pc, instr in enumerate(code):
    if instr is None:
      continue
    if instr[0] == OP_JUMP:
      dest = _final(code, instr[1])
      if dest == pc + 1:
        code[pc] = None               # a jump to the next instruction
        changed = True                # is not a jump
      elif dest < len(code) and code[dest] is not None and \
         code[dest][0] == OP_RET:
        code[pc] = (OP_RET,)          # a jump to a return is a return
        changed = True
      elif dest != instr[1]:
        code[pc] = (OP_JUMP, dest)
        changed = True
    elif instr[0] == OP_IF_START:
      _, then_pc, else_pc = instr
      new = (_final(code, then_pc),
             _final(code, else_pc))
      if new != (then_pc, else_pc):
        code[pc] = (OP_IF_START,) + new
        changed = True
  return changed


# ---------------------------------------------------------------------------
# 4. Unreachable code
# ---------------------------------------------------------------------------
#
# Reachability, conservatively.  RET and TCALL leave for an address the code
# does not name, so nothing after them falls through; everything else does.  A
# LAM makes its body reachable, and an IF_START makes both its arms reachable,
# even though the jump to them happens two instructions later.

def reachable(code):
  seen  = set()
  stack = [0]
  while stack:
    pc = stack.pop()
    if pc in seen or pc >= len(code) or code[pc] is None:
      continue
    seen.add(pc)
    op = code[pc][0]
    if op == OP_JUMP:
      stack.append(code[pc][1])
    elif op == OP_IF_START:
      stack.extend([pc + 1, code[pc][1],
                    code[pc][2]])
    elif op == OP_LAM:
      stack.extend([pc + 1, code[pc][2]])
    elif op in (OP_RET, OP_TCALL):
      pass                            # nothing falls through
    else:
      stack.append(pc + 1)
  return seen


def drop_unreachable(code):
  live = reachable(code)
  changed = False
  for pc in range(len(code)):
    if code[pc] is not None and pc not in live:
      code[pc] = None
      changed = True
  return changed


# ---------------------------------------------------------------------------
# 5. Compaction, and the addresses it owes
# ---------------------------------------------------------------------------

def compact(code):
  """Squeeze out the holes and repair every address that pointed past one."""
  moved = {}
  out   = []
  for pc, instr in enumerate(code):
    moved[pc] = len(out)
    if instr is not None:
      out.append(instr)
  moved[len(code)] = len(out)          # a jump to the end is a real target

  fixed = []
  for instr in out:
    op = instr[0]
    if op == OP_JUMP:
      fixed.append((OP_JUMP,
                    moved[instr[1]]))
    elif op == OP_IF_START:
      fixed.append((OP_IF_START,
                    moved[instr[1]],
                    moved[instr[2]]))
    elif op == OP_LAM:
      fixed.append((OP_LAM, instr[1],
                    moved[instr[2]]))
    else:
      fixed.append(instr)
  return fixed


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def optimize(prog):
  """Run the rewrites to exhaustion, compacting after every one.

    To exhaustion because they feed each other: folding a test makes an arm
    unreachable, dropping that arm can leave a jump pointing at a jump, and
    threading that jump can strand another block.

    Compacting after every rewrite rather than once at the end is not
    tidiness.  A rewrite leaves holes where instructions used to be, and the
    next rewrite has to read the code around them: `(+ (* 3 4) 2)` only folds
    once the inner call has collapsed AND the hole it left has closed, because
    what the outer fold needs to see is its operand sitting next to the
    instruction that stashes it.  Leave the holes in and each round can only
    reach one level deep.
    """
  code   = compact(list(prog))
  frozen = assigned_globals(code)

  def step(rewrite, *args):
    nonlocal code
    if rewrite(code, *args):
      code = compact(code)
      return True
    return False

  while True:
    changed  = step(fold_constants, frozen)
    changed |= step(fold_constant_tests)
    changed |= step(thread_jumps)
    changed |= step(drop_unreachable)
    if not changed:
      return code


def compile_optimized(core):
  return optimize(compile_program(core))


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def measure(source):
  """Compile a program twice and run both, counting instructions."""
  core = expand(parse(source) if isinstance(source, str)
                else source)
  plain = compile_program(core)
  tuned = optimize(plain)

  before = STEPS[0]
  v1 = run_vm(plain, 0, None)
  s1 = STEPS[0] - before

  before = STEPS[0]
  v2 = run_vm(tuned, 0, None)
  s2 = STEPS[0] - before

  return (lisp_str(v1), lisp_str(v2),
          len(plain), len(tuned), s1, s2)


def report(label, source):
  v1, v2, n1, n2, s1, s2 = measure(source)
  agree = 'ok  ' if v1 == v2 else 'FAIL'
  print(f'  {agree} {label}')
  print(f'        value        {v1}')
  print(f'        instructions {n1:7} -> {n2:<7}'
        f' ({_pct(n1, n2)})')
  print(f'        executed     {s1:7} -> {s2:<7}'
        f' ({_pct(s1, s2)})')


def _pct(before, after):
  if before == 0:
    return 'unchanged'
  d = 100.0 * (before - after) / before
  return f'{d:.0f}% less' if d else 'unchanged'


def main():
  print('--- what it does to one small program ---\n')
  core  = expand(parse('(if (and #t #t) (+ 1 2) (+ 3 4))'))
  plain = compile_program(core)
  print('  before:')
  disassemble(plain)
  print('\n  after:')
  disassemble(optimize(plain))

  print('\n--- and what that is worth ---\n')
  report('constant arithmetic',
         '(+ (* 3 4) (- 10 8))')
  report('a test that cannot vary',
         '(if (and #t #t) (+ 1 2) (+ 3 4))')
  report('sugar, expanded then folded',
         "(or #f (and #t (+ 20 22)))")
  report('a list built before it runs',
         "(cons 'a (list 1 (+ 1 1)))")
  report('a loop the optimizer cannot help',
         '((lambda (count)'
         '   (begin'
         '     (set! count (lambda (n)'
         '       (if (= n 0) 0 (count (- n 1)))))'
         '     (count 1000)))'
         ' 0)')

  print('\n--- the ceiling: why (+ 1 2) is not always 3 ---\n')
  src = "(begin (set! + (lambda (a b) 99)) (+ 1 2))"
  v1, v2, n1, n2, s1, s2 = measure(src)
  print(f'  {src}')
  print(f'       ==> {v1}, and the optimizer left the call alone')
  print(f'       instructions {n1} -> {n2}')
  print('       The program assigns to + , so the name is not frozen and')
  print('       folding it would change the answer.')


if __name__ == '__main__':
  main()
