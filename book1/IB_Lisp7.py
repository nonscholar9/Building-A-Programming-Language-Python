"""
IB_Lisp7 - Garbage Collection.

Continues from IB_Lisp6, the CEK VM.  Every machine so far has been
borrowing.  #4 stopped borrowing Python's call stack, and #6 stopped borrowing
Python's dispatch, but every closure and every environment any of them built was
still handed out by Python and taken back by Python.  The word "heap" has been
doing real work in this book since #3 without anyone ever building one.

Here we build one.  It is a Python list.  Addresses are indices into it.  And it
comes with one rule that makes the whole exercise honest:

    HEAP OBJECTS REFERENCE EACH OTHER BY ADDRESS, NEVER BY A PYTHON REFERENCE.

Break that rule and Python's own memory manager sees the links, keeps everything
alive, and there is nothing left to collect.  Keep it, and you have built a
closed little universe that Python cannot see into -- which means the garbage in
it is yours to find.

#6 compiled the shrunk language (pure lambda calculus + if).  That is not enough
to have anything interesting to collect, so this file restores #5's whole
language: the primitives and list operations (cons puts a pair on the heap),
cond/and/or, quote, apply, rest parameters, multi-argument lambdas, multi-form
bodies, let, and -- crucially -- set!.  #6 promised the full language was only
more opcodes and no new ideas, and that promise is kept here.  set! is held back
until it is needed, because set! is the whole reason a tracing collector has to
exist:

    A language without mutation cannot build a cycle.  Every environment points
    at an environment that existed before it, and every closure captures the
    environment that was current when it was built, so every reference points
    backwards in time.  Reference counting is not merely adequate for such a
    language, it is complete.  set! is what breaks it.

Run with: python IB_Lisp7.py
"""

from IB_AST import LBoolean, lTrue, lFalse
from IB_Reader import parse

# ---------------------------------------------------------------------------
# Values: an int, with the low bit saying what it is
# ---------------------------------------------------------------------------
#
# Every cell in the heap holds a plain Python int, and every Lisp value is a
# plain Python int, so a heap dump is honest: there is nothing hiding in it.
#
#   ...0   a number      n      stored as n << 1
#   ...1   a pointer     addr   stored as (addr << 1) | 1
#
# NIL is the pointer that points nowhere.  The collector must never follow it.

def mk_num(n):   return n << 1
def num_of(v):   return v >> 1
def mk_ptr(a):   return (a << 1) | 1
def addr_of(v):  return v >> 1
def is_ptr(v):   return (v & 1) == 1

NIL = mk_ptr(-1)              # a pointer whose address is nowhere
# #t and #f are two more of the same: immediates that point nowhere, so they need
# no heap cell and the collector treats them exactly as it treats NIL.
TRUE  = mk_ptr(-2)
FALSE = mk_ptr(-3)


# ---------------------------------------------------------------------------
# Names: interned, so a cell can hold one
# ---------------------------------------------------------------------------
#
# A cell holds an int, so it cannot hold the string 'x'.  Every name gets a
# number instead, once, at compile time.  Real VMs call this a constant pool.

_NAMES = []

def intern(name):
  if name not in _NAMES:
    _NAMES.append(name)
  return _NAMES.index(name)

def name_of(nid):
  return _NAMES[nid]


# ---------------------------------------------------------------------------
# The heap
# ---------------------------------------------------------------------------
#
# Every object begins with two cells: a tag saying what it is, and its size in
# cells, counting the two header cells.  The size is what lets the sweep walk
# the heap object by object without knowing what any of them are.
#
#   ENV      tag size outer n   id0 val0 id1 val1 ...      size = 4 + 2n
#   CLOSURE  tag size lam_pc env                            size = 4
#   PRIM     tag size prim_id                               size = 3
#   RET      tag size next ret_pc env                       size = 5
#   IF       tag size next then_pc else_pc env              size = 6
#   ARG      tag size next env nslots count slot0 ...       size = 6 + nslots
#   PAIR     tag size car cdr                               size = 4
#   SYMBOL   tag size name_id                               size = 3
#   FREE     tag size next_free                             size >= 3
#
# Note which cells are addresses and which are just numbers.  ret_pc and lam_pc
# are raw instruction indices, not values, and a raw pc of 17 has its low bit
# set and would look exactly like a pointer.  So the collector can never guess
# by inspecting a cell; it has to know each object's shape.  That is the
# difference between a precise collector and a conservative one.

TAG_ENV     = 0
TAG_CLOSURE = 1
TAG_PRIM    = 2
TAG_RET     = 3
TAG_IF      = 4
TAG_ARG     = 5
TAG_FREE    = 6
TAG_PAIR    = 7                 # a cons cell: car and cdr, both values
TAG_SYMBOL  = 8                 # a quoted symbol: an interned name id, not a pointer

# A slot in an environment that no name has claimed yet.  Interned names are
# indexes into _NAMES, so they are never negative, and -1 can never match one.
EMPTY       = -1

_TAG_NAMES = ['env', 'closure', 'prim', 'ret', 'if', 'arg', 'FREE', 'pair', 'symbol']

HEAP_SIZE = 600
MIN_BLOCK = 3                   # the smallest thing a free block can hold

heap      = [0] * HEAP_SIZE
free_ptr  = 0                   # the bump pointer: everything above it is virgin
heap_end  = 0                   # high-water mark; the sweep walks up to here
free_list = NIL                 # built by the sweep; empty until the first one

gc_runs   = 0
peak_live = 0                   # the most the machine could reach at any collection


def heap_reset(size=None):
  global heap, free_ptr, heap_end, free_list, gc_runs, peak_live, HEAP_SIZE
  if size is not None:
    HEAP_SIZE = size
  heap      = [0] * HEAP_SIZE
  free_ptr  = 0
  heap_end  = 0
  free_list = NIL
  gc_runs   = 0
  peak_live = 0


# --- allocation ------------------------------------------------------------
#
# Two allocators live here, and the second one is not a choice we made; it is
# what the collector leaves behind.  Before the first collection, allocation is
# a bump: take the next `size` cells and move the pointer.  Three lines, and
# nothing cheaper is possible.  After a collection there are holes, and holes
# have to be searched.

def _take(size):
  """Find room for `size` cells: first fit on the free list, else bump.

    Returns (address, cells actually handed over), or None.  The second number
    is not always the one asked for: a block with only a cell or two to spare
    cannot be split, because the remainder would be too small to be a block at
    all, so the whole thing goes out and the surplus is simply lost inside the
    object.  Every allocator makes that trade, and the lost cells have a name:
    internal fragmentation.
    """
  global free_ptr, heap_end, free_list

  prev, cur = NIL, free_list
  while cur != NIL:
    a     = addr_of(cur)
    bsize = heap[a + 1]
    nxt   = heap[a + 2]
    if bsize >= size:
      if bsize - size >= MIN_BLOCK:       # split, and keep the remainder
        b = a + size
        heap[b], heap[b + 1], heap[b + 2] = TAG_FREE, bsize - size, nxt
        repl, given = mk_ptr(b), size
      else:                               # hand over the whole block
        repl, given = nxt, bsize
      if prev == NIL:
        free_list = repl
      else:
        heap[addr_of(prev) + 2] = repl
      return a, given
    prev, cur = cur, nxt

  if free_ptr + size <= HEAP_SIZE:            # the bump allocator
    a = free_ptr
    free_ptr += size
    if free_ptr > heap_end:
      heap_end = free_ptr
    return a, size

  return None


def alloc(tag, size):
  """Allocate an object, collecting if we have to.

    ! Every caller must obey one discipline: everything this new object will
    ! point at must already be reachable from V, E or K before you call, and the
    ! result must go straight into a register or into an object that is.  The
    ! collector can only see the machine's registers.  A value the implementation
    ! is merely holding in a Python local is invisible to it, and allocating
    ! while holding one is how you collect an object you are still using.
    """
  got = _take(size)
  if got is None:
    gc()
    got = _take(size)
    if got is None:
      raise MemoryError(
          f'heap exhausted: no room for {size} cells '
          f'({heap_free()} free, in {heap_holes()} holes)')
  a, given = got
  # `given`, not `size`: the block's header must describe the block, or the
  # sweep's walk loses its place and starts reading a header out of the middle
  # of the next object.  This is why every object carries its own length.
  heap[a], heap[a + 1] = tag, given
  return a


# --- constructors ----------------------------------------------------------

def mk_env(outer, param_ids, args):
  # A dotted parameter list `(first . rest)` gathers the leftover arguments.
  # The dot reaches us as the ordinary interned name '.', so look for it; if it
  # is there, the name after it binds to a list of whatever arguments remain.
  dot = next((i for i in range(len(param_ids))
               if name_of(param_ids[i]) == '.'), None)
  if dot is not None:
    # Build the rest list (a chain of pairs) and keep it in V, a root, so a
    # collection during the env's own allocation cannot free it.  The args
    # stay reachable through the ARG frame on K throughout.
    global V
    saved, V = V, NIL
    for x in reversed(args[dot:]):
      V = mk_pair(x, V)
    n = dot + 1
    a = alloc(TAG_ENV, 4 + 2 * n)          # may collect; V roots the rest list
    heap[a + 2], heap[a + 3] = outer, n
    for i in range(dot):
      heap[a + 4 + 2 * i] = param_ids[i]
      heap[a + 5 + 2 * i] = args[i] if i < len(args) else mk_num(0)
    heap[a + 4 + 2 * dot] = param_ids[dot + 1]
    heap[a + 5 + 2 * dot] = V                 # the rest list, still rooted in V
    V = saved
    return mk_ptr(a)

  n = len(param_ids)
  a = alloc(TAG_ENV, 4 + 2 * n)
  heap[a + 2], heap[a + 3] = outer, n
  for i in range(n):
    heap[a + 4 + 2 * i] = param_ids[i]
    # zip's silent truncation, by hand: a missing argument is simply absent.
    heap[a + 5 + 2 * i] = args[i] if i < len(args) else mk_num(0)
  return mk_ptr(a)


def mk_closure(lam_pc, env):
  a = alloc(TAG_CLOSURE, 4)
  heap[a + 2], heap[a + 3] = lam_pc, env
  return mk_ptr(a)


def mk_prim(prim_id):
  a = alloc(TAG_PRIM, 3)
  heap[a + 2] = prim_id
  return mk_ptr(a)


def mk_ret(nxt, ret_pc, env):
  a = alloc(TAG_RET, 5)
  heap[a + 2], heap[a + 3], heap[a + 4] = nxt, ret_pc, env
  return mk_ptr(a)


def mk_if(nxt, then_pc, else_pc, env):
  a = alloc(TAG_IF, 6)
  heap[a + 2], heap[a + 3], heap[a + 4], heap[a + 5] = nxt, then_pc, else_pc, env
  return mk_ptr(a)


def mk_arg(nxt, env, nslots):
  a = alloc(TAG_ARG, 6 + nslots)
  heap[a + 2], heap[a + 3], heap[a + 4], heap[a + 5] = nxt, env, nslots, 0
  for i in range(nslots):
    heap[a + 6 + i] = NIL           # so the collector never reads garbage
  return mk_ptr(a)


def mk_pair(car, cdr):
  # alloc runs first and may collect; car and cdr must already be reachable
  # from a register before the call (for cons, they sit in the ARG frame on K).
  a = alloc(TAG_PAIR, 4)
  heap[a + 2], heap[a + 3] = car, cdr
  return mk_ptr(a)


def mk_symbol(nid):
  a = alloc(TAG_SYMBOL, 3)
  heap[a + 2] = nid                   # a name id, a number: no pointer to trace
  return mk_ptr(a)


# --- environments ----------------------------------------------------------

def env_lookup(env, nid):
  while env != NIL:
    a = addr_of(env)
    for i in range(heap[a + 3]):
      if heap[a + 4 + 2 * i] == nid:
        return heap[a + 5 + 2 * i]
    env = heap[a + 2]
  raise NameError(f'Unbound variable: {name_of( nid )}')


def env_set(env, nid, value):
  """Assign to a name.  If nothing in the stack has it, it becomes a global,
    which is what toys 1-5 do and what a prompt needs to be usable."""
  while env != NIL:
    a = addr_of(env)
    for i in range(heap[a + 3]):
      if heap[a + 4 + 2 * i] == nid:
        heap[a + 5 + 2 * i] = value      # <-- the write that makes cycles
        return
    env = heap[a + 2]
  define_global(nid, value)


def define_global(nid, value):
  """Bind a name in the global environment, claiming a spare slot if it is new.

    The global environment is one heap object with a fixed number of slots, so a
    session can only introduce as many names as `boot` set aside for it.
    """
  a = addr_of(global_env)
  for i in range(heap[a + 3]):
    if heap[a + 4 + 2 * i] == nid:
      heap[a + 5 + 2 * i] = value
      return
  for i in range(heap[a + 3]):
    if heap[a + 4 + 2 * i] == EMPTY:
      heap[a + 4 + 2 * i] = nid
      heap[a + 5 + 2 * i] = value
      return
  raise MemoryError(f'no room for another global: {name_of( nid )}')


# ---------------------------------------------------------------------------
# The collector: mark and sweep
# ---------------------------------------------------------------------------

def pointers_in(a):
  """The cells of the object at `a` that hold addresses.  Shape, not guesswork."""
  tag = heap[a]
  if tag == TAG_ENV:
    out = [heap[a + 2]]
    out += [heap[a + 5 + 2 * i]
            for i in range(heap[a + 3])]
    return out
  if tag == TAG_CLOSURE:
    return [heap[a + 3]]
  if tag == TAG_PRIM:
    return []
  if tag == TAG_RET:
    return [heap[a + 2], heap[a + 4]]
  if tag == TAG_IF:
    return [heap[a + 2], heap[a + 5]]
  if tag == TAG_ARG:
    out = [heap[a + 2], heap[a + 3]]
    out += [heap[a + 6 + i]
            for i in range(heap[a + 4])]
    return out
  if tag == TAG_PAIR:
    return [heap[a + 2], heap[a + 3]]
  if tag == TAG_SYMBOL:
    return []
  return []


def mark():
  """Every object the machine can still reach, starting from its registers.

    The worklist is explicit rather than recursive on purpose.  This book spent
    four chapters getting the machine off Python's call stack, and putting the
    collector back on it would be a poor joke.
    """
  marked   = set()
  worklist = [V, E, K]                        # the roots, and there are only three
  while worklist:
    v = worklist.pop()
    if not is_ptr(v) or addr_of(v) < 0:   # NIL, #t and #f point nowhere
      continue
    a = addr_of(v)
    if a in marked:
      continue
    marked.add(a)
    worklist.extend(pointers_in(a))
  return marked


def gc():
  """Mark everything reachable from the machine's registers; sweep the rest."""
  global free_list, gc_runs, peak_live
  gc_runs += 1

  marked = mark()

  # What the mark phase just measured is the only honest number in the file:
  # how much of the heap the machine could still reach.  Everything else was
  # garbage, whatever it cost to produce.
  peak_live = max(peak_live, sum(heap[a + 1] for a in marked))

  # Sweep.  Walk every block; whatever was not marked becomes a free block.
  # Nothing is moved and nothing is merged with its neighbour, and both of
  # those omissions come due later.
  free_list = NIL
  a = 0
  while a < heap_end:
    size = heap[a + 1]
    if a not in marked:
      heap[a], heap[a + 2] = TAG_FREE, free_list
      free_list = mk_ptr(a)
    a += size


# --- looking at the heap ---------------------------------------------------

def heap_walk():
  a = 0
  while a < heap_end:
    yield a, heap[a], heap[a + 1]
    a += heap[a + 1]


def heap_live():  return sum(s for _, t, s in heap_walk() if t != TAG_FREE)
def heap_free():  return sum(s for _, t, s in heap_walk() if t == TAG_FREE)
def heap_holes(): return sum(1 for _, t, _ in heap_walk() if t == TAG_FREE)


def census():
  """How many of each kind of object the heap is currently holding."""
  counts = {}
  for _, tag, _ in heap_walk():
    counts[_TAG_NAMES[tag]] = counts.get(_TAG_NAMES[tag], 0) + 1
  return '  '.join(f'{k} {v}' for k, v in sorted(counts.items()))


def heap_dump(label=''):
  if label:
    print(f'  {label}')
  for a, tag, size in heap_walk():
    if tag == TAG_FREE:                     # a hole; its old contents are noise
      print(f'    {a:4}  {"-- free --":10} {size:2}')
    else:
      cells = ' '.join(str(heap[a + i]) for i in range(2, size))
      print(f'    {a:4}  {_TAG_NAMES[tag]:10} {size:2}  {cells}')
  print(f'    live {heap_live()}, free {heap_free()} in {heap_holes()} holes,'
         f' never touched {HEAP_SIZE - heap_end}')


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _is_sym(v):
  return is_ptr(v) and addr_of(v) >= 0 and heap[addr_of(v)] == TAG_SYMBOL

def _add(a):                                  # variadic, like Chapter 5; (+) is 0
  total = 0
  for x in a:
    total += num_of(x)
  return mk_num(total)
def _sub(a): return mk_num(num_of(a[0]) - num_of(a[1]))
def _mul(a):                                  # variadic; (*) is 1
  total = 1
  for x in a:
    total *= num_of(x)
  return mk_num(total)
def _mod(a): return mk_num(num_of(a[0]) %  num_of(a[1]))
def _eq(a):
  # numbers compare as numbers; two symbols compare by their interned name.
  if _is_sym(a[0]) and _is_sym(a[1]):
    return TRUE if heap[addr_of(a[0]) + 2] == heap[addr_of(a[1]) + 2] else FALSE
  return TRUE if num_of(a[0]) == num_of(a[1]) else FALSE
def _lt(a): return TRUE if num_of(a[0]) <  num_of(a[1]) else FALSE
def _gt(a): return TRUE if num_of(a[0]) >  num_of(a[1]) else FALSE
def _le(a): return TRUE if num_of(a[0]) <= num_of(a[1]) else FALSE
def _ge(a): return TRUE if num_of(a[0]) >= num_of(a[1]) else FALSE
def _not(a): return TRUE if a[0] == FALSE else FALSE

# The list primitives.  cons allocates, but its two arguments are still in the
# ARG frame on K while it runs, so a collection part way through keeps them alive.
def _cons(a): return mk_pair(a[0], a[1])
def _car(a): return heap[addr_of(a[0]) + 2]
def _cdr(a): return heap[addr_of(a[0]) + 3]
def _null(a): return TRUE if a[0] == NIL else FALSE

def _list(a):
  """A chain of pairs from the arguments.

    This one allocates more than once, and that is what makes it interesting.
    Every mk_pair below can collect, and the chain built so far would live only
    in a Python local, where the collector cannot see it.  So it rides in V,
    which is a root, exactly as mk_env does when it gathers a rest parameter.
    The arguments stay reachable throughout on the ARG frame, still on K.
    """
  global V
  saved, V = V, NIL
  for x in reversed(a):
    V = mk_pair(x, V)
  built, V = V, saved
  return built

def _print(a): print(show(a[0])); return a[0]

# apply is a value, but not a leaf primitive: a Python function has no way to
# open a scope and run a body.  Its entry here only reserves a name and an id;
# the VM recognizes that id at the call site and splices (see OP_CALL), the same
# shape call/cc uses.  This body is never actually called.
def _apply(a): raise RuntimeError('apply is spliced in the VM, never called')

PRIMS = [('+', _add), ('-', _sub), ('*', _mul), ('=', _eq), ('<', _lt),
         ('%', _mod), ('>', _gt), ('<=', _le), ('>=', _ge), ('not', _not),
         ('cons', _cons), ('car', _car), ('cdr', _cdr), ('null?', _null),
         ('list', _list), ('print', _print), ('apply', _apply)]

# The names the measurement demos boot with: only the arithmetic the countdown
# and the heap dumps actually use, so those transcripts stay exactly as this
# chapter set them.  A session, and the language demos, boot with `full=True`
# and get every name above.
LEAN_PRIMS = ['+', '-', '*', '=', '<']
PRIM_INDEX = {name: i for i, (name, _) in enumerate(PRIMS)}


# ---------------------------------------------------------------------------
# Opcodes
# ---------------------------------------------------------------------------

OP_INT       = 0
OP_VAR       = 1
OP_LAM       = 2
OP_JUMP      = 3
OP_APP_START = 4
OP_APPLY_ARG = 5
OP_CALL      = 6
OP_TCALL     = 7
OP_IF_START  = 8
OP_APPLY_IF  = 9
OP_RET       = 10
OP_SET       = 11               # NEW: the one that makes cycles possible
OP_BOOL      = 12               # push a boolean immediate
OP_SYM       = 13               # push a quoted symbol
OP_NIL       = 14               # push the empty list

_OP_NAMES = ['INT', 'VAR', 'LAM', 'JUMP', 'APP_START', 'APPLY_ARG',
             'CALL', 'TCALL', 'IF_START', 'APPLY_IF', 'RET', 'SET', 'BOOL',
             'SYM', 'NIL']


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

# A reserved parameter name `or` binds its first value to, so a true result is
# returned without evaluating it twice.  It is not a legal source name; making a
# trick like this hygienic in general is Chapter 9's expander.
_OR_TMP = '%or-tmp%'


def _compile_quoted(datum, out):
  """Emit code that BUILDS `datum` as a value: a boolean, a symbol, a number,
    or a list -- a list becomes a chain of conses ending in the empty list."""
  if isinstance(datum, LBoolean):
    out.append((OP_BOOL, datum))
  elif isinstance(datum, str):
    out.append((OP_SYM, intern(datum)))
  elif isinstance(datum, int):
    out.append((OP_INT, datum))
  elif isinstance(datum, list) and not datum:
    out.append((OP_NIL,))
  else:                                       # (a . rest) -> (cons 'a 'rest)
    compile_expr(['cons', ['quote', datum[0]], ['quote', datum[1:]]],
                  out, tail=False)


def compile_body(forms, out, tail):
  for f in forms[:-1]:
    compile_expr(f, out, tail=False)      # value computed, then overwritten
  compile_expr(forms[-1], out, tail=tail)


def compile_expr(expr, out, tail):
  if isinstance(expr, LBoolean):
    out.append((OP_BOOL, expr))
    if tail:
      out.append((OP_RET,))

  elif isinstance(expr, str):
    out.append((OP_VAR, intern(expr)))
    if tail:
      out.append((OP_RET,))

  elif isinstance(expr, int):
    out.append((OP_INT, expr))
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'lambda':                   # ['lambda', [params], *body]
    lam_idx  = len(out)
    out.append(None)
    jump_idx = len(out)
    out.append(None)
    body_pc  = len(out)
    _, params, *body = expr
    compile_body(body, out, tail=True)
    out[lam_idx]  = (OP_LAM, [intern(p) for p in params], body_pc)
    out[jump_idx] = (OP_JUMP, len(out))
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'if':                       # ['if', test, then, else]
    _, condExpr, thenExpr, elseExpr = expr
    if_idx = len(out)
    out.append(None)
    compile_expr(condExpr, out, tail=False)
    out.append((OP_APPLY_IF,))
    then_pc = len(out)
    compile_expr(thenExpr, out, tail=tail)
    if not tail:
      then_jump = len(out)
      out.append(None)
    else_pc = len(out)
    compile_expr(elseExpr, out, tail=tail)
    if not tail:
      out[then_jump] = (OP_JUMP, len(out))
    out[if_idx] = (OP_IF_START,
                   then_pc, else_pc)

  elif expr[0] == 'set!':                     # ['set!', name, valueExpr]
    _, name, valExpr = expr
    compile_expr(valExpr, out, tail=False)
    out.append((OP_SET, intern(name)))
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'begin':                    # ['begin', *forms]
    compile_body(expr[1:], out, tail)

  elif expr[0] == 'let':                      # ['let', ((name init)...), *body]
    _, bindingPairs, *body = expr
    names = [pair[0]
              for pair in bindingPairs]
    inits = [pair[1]
              for pair in bindingPairs]
    compile_expr(
        [['lambda', names] + list(body)]
        + inits, out, tail)

  elif expr[0] == 'quote':                    # ['quote', datum]
    _compile_quoted(expr[1], out)
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'cond':                     # ['cond', (test result)...]
    clauses = expr[1:]
    if not clauses:
      compile_expr(lFalse, out, tail)
    elif clauses[0][0] == 'else':
      compile_expr(clauses[0][1], out, tail)
    else:                                   # a chain of ifs, peeled one clause
      compile_expr(['if', clauses[0][0], clauses[0][1],
                     ['cond'] + list(clauses[1:])], out, tail)

  elif expr[0] == 'and':                      # ['and', *forms] -- short-circuits
    forms = expr[1:]
    if not forms:
      compile_expr(lTrue, out, tail)    # (and) is true
    elif len(forms) == 1:
      compile_expr(forms[0], out, tail)
    else:                                   # (if a (and rest...) #f)
      compile_expr(['if', forms[0], ['and'] + list(forms[1:]), lFalse],
                    out, tail)

  elif expr[0] == 'or':                       # ['or', *forms] -- short-circuits
    forms = expr[1:]
    if not forms:
      compile_expr(lFalse, out, tail)   # (or) is false
    elif len(forms) == 1:
      compile_expr(forms[0], out, tail)
    else:                                   # bind a once, return it if true
      compile_expr([['lambda', [_OR_TMP],
                      ['if', _OR_TMP, _OR_TMP, ['or'] + list(forms[1:])]],
                     forms[0]], out, tail)

  else:                                       # [fn, *args] -- an application
    out.append((OP_APP_START, len(expr)))
    for sub in expr:
      compile_expr(sub, out, tail=False)
      out.append((OP_APPLY_ARG,))
    out.append((OP_TCALL,) if tail
                else (OP_CALL,))


def compile_program(expr):
  out = []
  compile_expr(expr, out, tail=True)
  return out


# ---------------------------------------------------------------------------
# The VM
# ---------------------------------------------------------------------------
#
# Registers, and now they are also the roots.  Everything the machine can still
# reach, it reaches from these three; everything else is garbage by definition.
# That is the whole reason #4 and #6 were worth building: a machine that keeps
# its state in named registers is a machine whose live data you can enumerate.

V = mk_num(0)                 # the value register
E = NIL                         # the environment
K = NIL                         # the continuation: a chain of frames, on the heap
pc = 0

PROG = []                       # the program, appended to as expressions arrive
global_env = None               # the environment every top-level name lives in

# How many names a session may define beyond the primitives.  The demo boots
# with none; a prompt boots with these.
GLOBAL_SPARE = 64


def make_global_env(spare=0, full=False):
  """The primitives.  Note the order: the env is rooted in E *before* any prim
    is allocated, so an allocation part way through cannot collect the ones
    already made.

    `full` installs every primitive; the default installs only the arithmetic
    the measurement demos use, so their heap transcripts stay exactly as this
    chapter set them.  `spare` empty slots are set aside for names a session
    defines later.  The demo asks for none, so the heap it prints holds nothing
    it did not use.
    """
  global E, global_env
  names = [name for name, _ in PRIMS] if full else LEAN_PRIMS
  ids = [intern(name) for name in names] + [EMPTY] * spare
  E = mk_env(NIL, ids, [mk_num(0)] * len(ids))
  global_env = E
  for name in names:
    env_set(E, intern(name), mk_prim(PRIM_INDEX[name]))
  return E


def boot(heap_size=None, spare=0):
  """Start a machine: an empty heap, an empty program, and the primitives."""
  global PROG, V, E, K, pc
  heap_reset(heap_size)
  PROG = []
  V, K, pc = mk_num(0), NIL, 0
  make_global_env(spare, full=True)         # a session gets the whole language
  return global_env


def _list_to_args(v):
  """The elements of a heap list, as a Python list of values, for apply."""
  out = []
  while v != NIL:
    a = addr_of(v)
    out.append(heap[a + 2])
    v = heap[a + 3]
  return out


def _run(prog):
  """Run from the current pc until a return with nothing left to return to."""
  global V, E, K, pc

  while True:
    op = prog[pc][0]

    if op == OP_INT:
      V = mk_num(prog[pc][1])
      pc += 1

    elif op == OP_BOOL:
      V = TRUE if prog[pc][1] is lTrue else FALSE
      pc += 1

    elif op == OP_SYM:
      V = mk_symbol(prog[pc][1])
      pc += 1

    elif op == OP_NIL:
      V = NIL
      pc += 1

    elif op == OP_VAR:
      V = env_lookup(E, prog[pc][1])
      pc += 1

    elif op == OP_LAM:
      V = mk_closure(pc, E)     # the closure remembers its own OP_LAM
      pc += 1

    elif op == OP_JUMP:
      pc = prog[pc][1]

    elif op == OP_SET:
      env_set(E, prog[pc][1], V)
      pc += 1

    elif op == OP_APP_START:
      K = mk_arg(K, E, prog[pc][1])
      pc += 1

    elif op == OP_APPLY_ARG:                 # stash V in the frame's next slot
      a = addr_of(K)
      heap[a + 6 + heap[a + 5]] = V
      heap[a + 5] += 1
      E = heap[a + 3]
      pc += 1

    elif op == OP_CALL or op == OP_TCALL:
      a     = addr_of(K)                 # the ARG frame, still on K
      fn    = heap[a + 6]
      nargs = heap[a + 5] - 1
      args  = [heap[a + 7 + i]
               for i in range(nargs)]
      f     = addr_of(fn)

      # apply is a value: (apply g x ... lst) is a call of g on x ... plus
      # the elements of lst.  Splice here, at the call site, the same way
      # call/cc reaches into the machine; loop so (apply apply ...) resolves.
      # The ARG frame is still on K, so g, the leading args and lst all stay
      # reachable while the closure's env is allocated below.
      while heap[f] == TAG_PRIM and PRIMS[heap[f + 2]][0] == 'apply':
        # Both sides read the OLD args; do not split this in two.
        fn, args = args[0], list(args[1:-1]) + _list_to_args(args[-1])
        f    = addr_of(fn)

      if heap[f] == TAG_PRIM:
        V = PRIMS[heap[f + 2]][1](args)
        K = heap[a + 2]
        if op != OP_TCALL:
          pc += 1
        elif K == NIL:                   # a primitive was the whole program
          return V
        else:
          _do_return(prog)
      else:
        lam  = prog[heap[f + 2]]         # (OP_LAM, param_ids, body_pc)
        # Both allocations happen while the ARG frame is still on K, so
        # fn, the args and the caller's E are all reachable throughout.
        newE = mk_env(heap[f + 3], lam[1], args)
        E    = newE                      # rooted before the next alloc
        K    = heap[a + 2] if op == OP_TCALL \
               else mk_ret(heap[a + 2], pc + 1,
                            heap[a + 3])
        pc   = lam[2]

    elif op == OP_IF_START:
      K = mk_if(K, prog[pc][1], prog[pc][2], E)
      pc += 1

    elif op == OP_APPLY_IF:                  # #f is the only false value
      a  = addr_of(K)
      E  = heap[a + 5]
      pc = heap[a + 4] if V == FALSE else heap[a + 3]
      K  = heap[a + 2]

    elif op == OP_RET:
      if K == NIL:
        return V
      _do_return(prog)


def _do_return(prog):
  global E, K, pc
  if K == NIL:
    raise RuntimeError('return with an empty continuation')
  a = addr_of(K)
  pc, E, K = heap[a + 3], heap[a + 4], heap[a + 2]


def lEval(expr, env=None):
  """Evaluate one expression on the running machine.

    The compiled code is appended to PROG rather than replacing it, because a
    closure remembers the address of its own OP_LAM.  Throw the program away
    between expressions and every closure made by an earlier one points into
    code that is no longer there.
    """
  global E, K, pc
  if global_env is None:
    boot(spare=GLOBAL_SPARE)
  start = len(PROG)
  compile_expr(expr, PROG, tail=True)
  E  = global_env if env is None else env
  K  = NIL
  pc = start
  return _run(PROG)


def run_vm(prog, heap_size=None, full=False):
  """Run a whole program in a machine of its own."""
  global V, E, K, pc
  heap_reset(heap_size)
  V, K, pc = mk_num(0), NIL, 0
  make_global_env(full=full)
  return _run(prog)


def run_fresh(source, heap_size=None, full=False):
  """Evaluate in a machine of its own, which is what a measurement wants.

    The expression is compiled before the machine is booted, so the names in it
    are interned before the primitives are.
    """
  expr = parse(source) if isinstance(source, str) else source   # Chapter 8 built this
  return run_vm(compile_program(expr), heap_size, full=full)


# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def source_str(val):
  if isinstance(val, list):
    return '(' + ' '.join(source_str(x) for x in val) + ')'
  return str(val)


def show(val):
  if val == TRUE:
    return '#t'
  if val == FALSE:
    return '#f'
  if val == NIL:
    return '()'
  if is_ptr(val) and addr_of(val) >= 0:
    a = addr_of(val)
    if heap[a] == TAG_CLOSURE:
      return '#<procedure>'
    if heap[a] == TAG_PRIM:
      return f'#<{PRIMS[heap[a + 2]][0]}>'
    if heap[a] == TAG_SYMBOL:
      return name_of(heap[a + 2])
    if heap[a] == TAG_PAIR:
      return _show_list(val)
  return str(num_of(val))


def _show_list(val):
  parts = []
  v = val
  while is_ptr(v) and addr_of(v) >= 0 and heap[addr_of(v)] == TAG_PAIR:
    parts.append(show(heap[addr_of(v) + 2]))
    v = heap[addr_of(v) + 3]
  if v == NIL:
    return '(' + ' '.join(parts) + ')'
  return '(' + ' '.join(parts) + ' . ' + show(v) + ')'   # an improper list


# The REPL prints the result of an expression, and on this machine a result is a
# tagged int rather than a list, so `show` is the renderer it wants.  Every toy in
# the book exports `lisp_str` for that job; here it is the same function.
lisp_str = show


def disassemble(prog):
  for i, instr in enumerate(prog):
    args = ' '.join(str(a) for a in instr[1:])
    print(f'  {i:3}  {_OP_NAMES[instr[0]]:10} {args}')


def run(source, stats=False, full=False):
  expr = parse(source) if isinstance(source, str) else source   # Chapter 8 built this
  print('>>> ' + source_str(expr))
  result = run_fresh(expr, full=full)
  print('==> ' + show(result))
  if stats:
    print(f'    {gc_runs} collections, {peak_live} cells reachable at the busiest')
  print()


def countdown(body, n):
  """(loop n), where `body` decides whether the recursive call is in tail position."""
  return ['let', [['loop', 0]],
          ['set!', 'loop', ['lambda', ['n'], body]],
          ['loop', n]]

TAIL     = ['if', ['=', 'n', 0], 0, ['loop', ['-', 'n', 1]]]
NON_TAIL = ['if', ['=', 'n', 0], 0, ['+', 0, ['loop', ['-', 'n', 1]]]]


def smallest_heap(expr, lo=32, hi=20000):
  """The smallest heap this program will run in.

    No instrumentation, no counters, no trust required: just run it in a heap
    and see whether it finishes.  This is the only measure of what a program
    really costs, and it is the one the machine cannot lie about.
    """
  while lo < hi:
    mid = (lo + hi) // 2
    try:
      run_fresh(expr, heap_size=mid)
      hi = mid
    except MemoryError:
      lo = mid + 1
  return lo


def main():
  prog = compile_program([['lambda', ['x'], 'x'], 7])
  print('bytecode for ((lambda (x) x) 7):')
  disassemble(prog)
  print()

  run('42')
  run('((lambda (x) x) 7)')
  run('(+ (* 6 6) 6)')
  run('(if #f 100 200)')
  run('((lambda (n m) (+ n m)) 3 4)')
  run('(let ((a 3) (b 4)) (* a b))')

  # A local recursive helper.  The let environment binds f; the closure captures
  # it; set! makes the environment point back at the closure.  Those two
  # objects now point at each other, so neither will ever see its reference
  # count reach zero, and once the let returns nobody else can reach either.
  # Reference counting would keep that pair until the process died.
  cycle = ['let', [['f', 0]],
           ['set!', 'f', ['lambda', ['n'],
                          ['if', ['=', 'n', 0], 0, ['f', ['-', 'n', 1]]]]],
           ['f', 5]]
  print('a cycle: the let environment and the closure point at each other.')
  print('the begin makes it die, by moving E off it before the program ends.')
  run(['begin', cycle, 42])
  print(f'  in the heap when it is done : {census()}')
  gc()
  print(f'  after one collection        : {census()}')
  print('  the env/closure pair that pointed at each other is gone; only the')
  print('  global env and its five primitives are still reachable.')
  print()

  # The same countdown, once tail recursive and once not.  Same answer, the
  # same number of calls, the same arithmetic.  The only difference is whether
  # the recursive call has anything waiting behind it, and so whether OP_CALL
  # pushes a return frame -- and every return frame on K pins an environment
  # that the collector must then treat as live.
  #
  # Chapter 3 could only say that tail calls save stack.  Here you can watch
  # them save memory.
  print('the smallest heap (loop n) will run in:')
  print(f'    {"n":>4}  {"tail":>6}  {"non-tail":>9}')
  for n in (10, 20, 40, 80):
    need = [smallest_heap(countdown(body, n)) for body in (TAIL, NON_TAIL)]
    print(f'    {n:4}  {need[0]:6}  {need[1]:9}')
  print('    the tail column is flat.  the other one is the shape of n.')
  print()

  # Those two columns are not the same measurement, and the difference between
  # them is the point of this section.  The first is what the program can
  # actually reach at its busiest: what it needs.  The second is the heap it
  # demands anyway.  Every cell of the gap is real memory that is free, and
  # unusable, because it is not in one piece.
  print('what a program needs, and what it costs:')
  print(f'    {"n":>4}  {"reachable":>9}  {"heap needed":>11}  {"tax":>5}')
  for n in (10, 20, 40, 80):
    need = smallest_heap(countdown(NON_TAIL, n))
    run_fresh(countdown(NON_TAIL, n), heap_size=need)
    print(f'    {n:4}  {peak_live:9}  {need:11}  {need - peak_live:5}')
  print('    the tax is fragmentation: free cells too scattered to hand out.')
  print()

  print('the shape of it, in a heap of 600:')
  try:
    run_fresh(countdown(NON_TAIL, 80), heap_size=600)
  except MemoryError as e:
    print(f'    {e}')
  print()

  run_fresh('((lambda (x) (+ x 1)) 41)', heap_size=120)
  gc()
  heap_dump('a small heap after one collection:')
  print()

  # The full language, at parity with Chapter 5's machine.  These boot with
  # every primitive (full=True); the measurements above kept the lean set so
  # their heaps stayed exactly as this chapter reported them.  A roomy heap:
  # these illustrate the language, they do not measure it.
  heap_reset(2000)
  print('the full language, at parity with Chapter 5:')
  run('(cond ((< 2 1) 10) ((= 2 2) 20) (else 30))', full=True)  # 20
  run('(and 1 2 3)', full=True)                                    # 3
  run('(or #f 7)', full=True)                                   # 7
  run('(not (= 1 2))', full=True)                               # #t
  run('(% 17 5)', full=True)                                       # 2
  run('(car (list 1 2 3))', full=True)                         # 1
  run('(cdr (list 1 2 3))', full=True)                         # (2 3)
  run("'(1 (2 3) 4)", full=True)                          # (1 (2 3) 4)
  run("'hello", full=True)                                 # hello (a symbol)
  run("(= 'a 'a)", full=True)              # #t
  run("(null? '())", full=True)                           # #t
  run('(apply + 1 2 (list 3 4))', full=True)               # 10
  run('(apply (lambda (x y) (* x y)) (list 6 7))',
       full=True)                                                     # 42
  run('(apply apply (list + (list 3 4)))', full=True)  # 7 (apply of apply)


if __name__ == '__main__':
  main()
