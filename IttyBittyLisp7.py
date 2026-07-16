"""
IttyBittyLisp7 - Garbage Collection.

Continues from IttyBittyLisp6, the bytecode VM.  Every machine so far has been
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
to have anything interesting to collect, so this file restores what #5 had:
primitives, multi-argument lambdas, multi-form bodies, let, and -- crucially --
set!.  #6 promised the full language was only more opcodes and no new ideas, and
that promise is kept here.  set! is held back until it is needed, because set! is
the whole reason a tracing collector has to exist:

    A language without mutation cannot build a cycle.  Every environment points
    at an environment that existed before it, and every closure captures the
    environment that was current when it was built, so every reference points
    backwards in time.  Reference counting is not merely adequate for such a
    language, it is complete.  set! is what breaks it.

Run with: python IttyBittyLisp7.py
"""

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

def mk_num( n ):   return n << 1
def num_of( v ):   return v >> 1
def mk_ptr( a ):   return (a << 1) | 1
def addr_of( v ):  return v >> 1
def is_ptr( v ):   return (v & 1) == 1

NIL = mk_ptr( -1 )              # == -1: a pointer whose address is nowhere


# ---------------------------------------------------------------------------
# Names: interned, so a cell can hold one
# ---------------------------------------------------------------------------
#
# A cell holds an int, so it cannot hold the string 'x'.  Every name gets a
# number instead, once, at compile time.  Real VMs call this a constant pool.

_NAMES = []

def intern( name ):
    if name not in _NAMES:
        _NAMES.append( name )
    return _NAMES.index( name )

def name_of( nid ):
    return _NAMES[nid]


# ---------------------------------------------------------------------------
# The heap
# ---------------------------------------------------------------------------
#
# Every object begins with two cells: a tag saying what it is, and its size in
# cells, counting the two header cells.  The size is what lets the sweep walk
# the heap object by object without knowing what any of them are.
#
#   ENV      tag size parent n   id0 val0 id1 val1 ...      size = 4 + 2n
#   CLOSURE  tag size lam_pc env                            size = 4
#   PRIM     tag size prim_id                               size = 3
#   RET      tag size next ret_pc env                       size = 5
#   IF       tag size next then_pc else_pc env              size = 6
#   ARG      tag size next env nslots count slot0 ...       size = 6 + nslots
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

_TAG_NAMES = ['env', 'closure', 'prim', 'ret', 'if', 'arg', 'FREE']

HEAP_SIZE = 600
MIN_BLOCK = 3                   # the smallest thing a free block can hold

heap      = [0] * HEAP_SIZE
free_ptr  = 0                   # the bump pointer: everything above it is virgin
heap_end  = 0                   # high-water mark; the sweep walks up to here
free_list = NIL                 # built by the sweep; empty until the first one

gc_runs   = 0
peak_live = 0                   # the most the machine could reach at any collection


def heap_reset( size=None ):
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

def _take( size ):
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
        a     = addr_of( cur )
        bsize = heap[a + 1]
        nxt   = heap[a + 2]
        if bsize >= size:
            if bsize - size >= MIN_BLOCK:       # split, and keep the remainder
                b = a + size
                heap[b], heap[b + 1], heap[b + 2] = TAG_FREE, bsize - size, nxt
                repl, given = mk_ptr( b ), size
            else:                               # hand over the whole block
                repl, given = nxt, bsize
            if prev == NIL: free_list = repl
            else:           heap[addr_of( prev ) + 2] = repl
            return a, given
        prev, cur = cur, nxt

    if free_ptr + size <= HEAP_SIZE:            # the bump allocator
        a = free_ptr
        free_ptr += size
        if free_ptr > heap_end:
            heap_end = free_ptr
        return a, size

    return None


def alloc( tag, size ):
    """Allocate an object, collecting if we have to.

    ! Every caller must obey one discipline: everything this new object will
    ! point at must already be reachable from V, E or K before you call, and the
    ! result must go straight into a register or into an object that is.  The
    ! collector can only see the machine's registers.  A value the implementation
    ! is merely holding in a Python local is invisible to it, and allocating
    ! while holding one is how you collect an object you are still using.
    """
    got = _take( size )
    if got is None:
        gc()
        got = _take( size )
        if got is None:
            raise MemoryError(
                f'heap exhausted: no room for {size} cells '
                f'({heap_free()} free, in {heap_holes()} holes)' )
    a, given = got
    # `given`, not `size`: the block's header must describe the block, or the
    # sweep's walk loses its place and starts reading a header out of the middle
    # of the next object.  This is why every object carries its own length.
    heap[a], heap[a + 1] = tag, given
    return a


# --- constructors ----------------------------------------------------------

def mk_env( parent, param_ids, args ):
    n = len( param_ids )
    a = alloc( TAG_ENV, 4 + 2 * n )
    heap[a + 2], heap[a + 3] = parent, n
    for i in range( n ):
        heap[a + 4 + 2 * i] = param_ids[i]
        # zip's silent truncation, by hand: a missing argument is simply absent.
        heap[a + 5 + 2 * i] = args[i] if i < len( args ) else mk_num( 0 )
    return mk_ptr( a )


def mk_closure( lam_pc, env ):
    a = alloc( TAG_CLOSURE, 4 )
    heap[a + 2], heap[a + 3] = lam_pc, env
    return mk_ptr( a )


def mk_prim( prim_id ):
    a = alloc( TAG_PRIM, 3 )
    heap[a + 2] = prim_id
    return mk_ptr( a )


def mk_ret( nxt, ret_pc, env ):
    a = alloc( TAG_RET, 5 )
    heap[a + 2], heap[a + 3], heap[a + 4] = nxt, ret_pc, env
    return mk_ptr( a )


def mk_if( nxt, then_pc, else_pc, env ):
    a = alloc( TAG_IF, 6 )
    heap[a + 2], heap[a + 3], heap[a + 4], heap[a + 5] = nxt, then_pc, else_pc, env
    return mk_ptr( a )


def mk_arg( nxt, env, nslots ):
    a = alloc( TAG_ARG, 6 + nslots )
    heap[a + 2], heap[a + 3], heap[a + 4], heap[a + 5] = nxt, env, nslots, 0
    for i in range( nslots ):
        heap[a + 6 + i] = NIL           # so the collector never reads garbage
    return mk_ptr( a )


# --- environments ----------------------------------------------------------

def env_lookup( env, nid ):
    while env != NIL:
        a = addr_of( env )
        for i in range( heap[a + 3] ):
            if heap[a + 4 + 2 * i] == nid:
                return heap[a + 5 + 2 * i]
        env = heap[a + 2]
    raise NameError( f'Unbound variable: {name_of( nid )}' )


def env_set( env, nid, value ):
    while env != NIL:
        a = addr_of( env )
        for i in range( heap[a + 3] ):
            if heap[a + 4 + 2 * i] == nid:
                heap[a + 5 + 2 * i] = value      # <-- the write that makes cycles
                return
        env = heap[a + 2]
    raise NameError( f'Unbound variable: {name_of( nid )}' )


# ---------------------------------------------------------------------------
# The collector: mark and sweep
# ---------------------------------------------------------------------------

def pointers_in( a ):
    """The cells of the object at `a` that hold addresses.  Shape, not guesswork."""
    tag = heap[a]
    if tag == TAG_ENV:
        out = [heap[a + 2]]
        out += [heap[a + 5 + 2 * i] for i in range( heap[a + 3] )]
        return out
    if tag == TAG_CLOSURE: return [heap[a + 3]]
    if tag == TAG_PRIM:    return []
    if tag == TAG_RET:     return [heap[a + 2], heap[a + 4]]
    if tag == TAG_IF:      return [heap[a + 2], heap[a + 5]]
    if tag == TAG_ARG:
        out = [heap[a + 2], heap[a + 3]]
        out += [heap[a + 6 + i] for i in range( heap[a + 4] )]
        return out
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
        if not is_ptr( v ) or v == NIL:
            continue
        a = addr_of( v )
        if a in marked:
            continue
        marked.add( a )
        worklist.extend( pointers_in( a ) )
    return marked


def gc():
    """Mark everything reachable from the machine's registers; sweep the rest."""
    global free_list, gc_runs, peak_live
    gc_runs += 1

    marked = mark()

    # What the mark phase just measured is the only honest number in the file:
    # how much of the heap the machine could still reach.  Everything else was
    # garbage, whatever it cost to produce.
    peak_live = max( peak_live, sum( heap[a + 1] for a in marked ) )

    # Sweep.  Walk every block; whatever was not marked becomes a free block.
    # Nothing is moved and nothing is merged with its neighbour, and both of
    # those omissions come due later.
    free_list = NIL
    a = 0
    while a < heap_end:
        size = heap[a + 1]
        if a not in marked:
            heap[a], heap[a + 2] = TAG_FREE, free_list
            free_list = mk_ptr( a )
        a += size


# --- looking at the heap ---------------------------------------------------

def heap_walk():
    a = 0
    while a < heap_end:
        yield a, heap[a], heap[a + 1]
        a += heap[a + 1]


def heap_live():  return sum( s for _, t, s in heap_walk() if t != TAG_FREE )
def heap_free():  return sum( s for _, t, s in heap_walk() if t == TAG_FREE )
def heap_holes(): return sum( 1 for _, t, _ in heap_walk() if t == TAG_FREE )


def census():
    """How many of each kind of object the heap is currently holding."""
    counts = {}
    for _, tag, _ in heap_walk():
        counts[_TAG_NAMES[tag]] = counts.get( _TAG_NAMES[tag], 0 ) + 1
    return '  '.join( f'{k} {v}' for k, v in sorted( counts.items() ) )


def heap_dump( label='' ):
    if label:
        print( f'  {label}' )
    for a, tag, size in heap_walk():
        if tag == TAG_FREE:                     # a hole; its old contents are noise
            print( f'    {a:4}  {"-- free --":10} {size:2}' )
        else:
            cells = ' '.join( str( heap[a + i] ) for i in range( 2, size ) )
            print( f'    {a:4}  {_TAG_NAMES[tag]:10} {size:2}  {cells}' )
    print( f'    live {heap_live()}, free {heap_free()} in {heap_holes()} holes,'
           f' never touched {HEAP_SIZE - heap_end}' )


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _add( a ): return mk_num( num_of( a[0] ) + num_of( a[1] ) )
def _sub( a ): return mk_num( num_of( a[0] ) - num_of( a[1] ) )
def _mul( a ): return mk_num( num_of( a[0] ) * num_of( a[1] ) )
def _eq(  a ): return mk_num( 1 if num_of( a[0] ) == num_of( a[1] ) else 0 )
def _lt(  a ): return mk_num( 1 if num_of( a[0] ) <  num_of( a[1] ) else 0 )

PRIMS = [('+', _add), ('-', _sub), ('*', _mul), ('=', _eq), ('<', _lt)]


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

_OP_NAMES = ['INT', 'VAR', 'LAM', 'JUMP', 'APP_START', 'APPLY_ARG',
             'CALL', 'TCALL', 'IF_START', 'APPLY_IF', 'RET', 'SET']


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

def compile_body( forms, out, tail ):
    for f in forms[:-1]:
        compile_expr( f, out, tail=False )      # value computed, then overwritten
    compile_expr( forms[-1], out, tail=tail )


def compile_expr( expr, out, tail ):
    if isinstance( expr, int ):
        out.append( (OP_INT, expr) )
        if tail: out.append( (OP_RET,) )

    elif isinstance( expr, str ):
        out.append( (OP_VAR, intern( expr )) )
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'lambda':                   # ['lambda', [params], *body]
        lam_idx  = len( out ); out.append( None )
        jump_idx = len( out ); out.append( None )
        body_pc  = len( out )
        compile_body( expr[2:], out, tail=True )
        out[lam_idx]  = (OP_LAM, [intern( p ) for p in expr[1]], body_pc)
        out[jump_idx] = (OP_JUMP, len( out ))
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'if':                       # ['if', test, then, else]
        if_idx = len( out ); out.append( None )
        compile_expr( expr[1], out, tail=False )
        out.append( (OP_APPLY_IF,) )
        then_pc = len( out )
        compile_expr( expr[2], out, tail=tail )
        if not tail:
            then_jump = len( out ); out.append( None )
        else_pc = len( out )
        compile_expr( expr[3], out, tail=tail )
        if not tail:
            out[then_jump] = (OP_JUMP, len( out ))
        out[if_idx] = (OP_IF_START, then_pc, else_pc)

    elif expr[0] == 'set!':                     # ['set!', name, valueExpr]
        compile_expr( expr[2], out, tail=False )
        out.append( (OP_SET, intern( expr[1] )) )
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'begin':                    # ['begin', *forms]
        compile_body( expr[1:], out, tail )

    elif expr[0] == 'let':                      # ['let', ((name init)...), *body]
        names = [b[0] for b in expr[1]]
        inits = [b[1] for b in expr[1]]
        compile_expr( [['lambda', names] + list( expr[2:] )] + inits, out, tail )

    else:                                       # [fn, *args] -- an application
        out.append( (OP_APP_START, len( expr )) )
        for sub in expr:
            compile_expr( sub, out, tail=False )
            out.append( (OP_APPLY_ARG,) )
        out.append( (OP_TCALL,) if tail else (OP_CALL,) )


def compile_program( expr ):
    out = []
    compile_expr( expr, out, tail=True )
    return out


# ---------------------------------------------------------------------------
# The VM
# ---------------------------------------------------------------------------
#
# Registers, and now they are also the roots.  Everything the machine can still
# reach, it reaches from these three; everything else is garbage by definition.
# That is the whole reason #4 and #6 were worth building: a machine that keeps
# its state in named registers is a machine whose live data you can enumerate.

V = mk_num( 0 )                 # the value register
E = NIL                         # the environment
K = NIL                         # the continuation: a chain of frames, on the heap
pc = 0


def make_global_env():
    """The primitives.  Note the order: the env is rooted in E *before* any prim
    is allocated, so an allocation part way through cannot collect the ones
    already made."""
    global E
    ids = [intern( name ) for name, _ in PRIMS]
    E = mk_env( NIL, ids, [mk_num( 0 )] * len( ids ) )
    for i, (name, _) in enumerate( PRIMS ):
        env_set( E, intern( name ), mk_prim( i ) )
    return E


def run_vm( prog, heap_size=None ):
    global V, E, K, pc
    heap_reset( heap_size )
    V, K, pc = mk_num( 0 ), NIL, 0
    make_global_env()

    while True:
        op = prog[pc][0]

        if op == OP_INT:
            V = mk_num( prog[pc][1] ); pc += 1

        elif op == OP_VAR:
            V = env_lookup( E, prog[pc][1] ); pc += 1

        elif op == OP_LAM:
            V = mk_closure( pc, E ); pc += 1     # the closure remembers its own OP_LAM

        elif op == OP_JUMP:
            pc = prog[pc][1]

        elif op == OP_SET:
            env_set( E, prog[pc][1], V ); pc += 1

        elif op == OP_APP_START:
            K = mk_arg( K, E, prog[pc][1] ); pc += 1

        elif op == OP_APPLY_ARG:                 # stash V in the frame's next slot
            a = addr_of( K )
            heap[a + 6 + heap[a + 5]] = V
            heap[a + 5] += 1
            E = heap[a + 3]
            pc += 1

        elif op == OP_CALL or op == OP_TCALL:
            a     = addr_of( K )                 # the ARG frame, still on K
            fn    = heap[a + 6]
            nargs = heap[a + 5] - 1
            args  = [heap[a + 7 + i] for i in range( nargs )]
            f     = addr_of( fn )

            if heap[f] == TAG_PRIM:
                V = PRIMS[heap[f + 2]][1]( args )
                K = heap[a + 2]
                if op != OP_TCALL:
                    pc += 1
                elif K == NIL:                   # a primitive was the whole program
                    return V
                else:
                    _do_return( prog )
            else:
                lam  = prog[heap[f + 2]]         # (OP_LAM, param_ids, body_pc)
                # Both allocations happen while the ARG frame is still on K, so
                # fn, the args and the caller's E are all reachable throughout.
                newE = mk_env( heap[f + 3], lam[1], args )
                E    = newE                      # rooted before the next alloc
                K    = heap[a + 2] if op == OP_TCALL \
                       else mk_ret( heap[a + 2], pc + 1, heap[a + 3] )
                pc   = lam[2]

        elif op == OP_IF_START:
            K = mk_if( K, prog[pc][1], prog[pc][2], E ); pc += 1

        elif op == OP_APPLY_IF:                  # 0 is false, every other number true
            a  = addr_of( K )
            E  = heap[a + 5]
            pc = heap[a + 4] if V == mk_num( 0 ) else heap[a + 3]
            K  = heap[a + 2]

        elif op == OP_RET:
            if K == NIL:
                return V
            _do_return( prog )


def _do_return( prog ):
    global E, K, pc
    if K == NIL:
        raise RuntimeError( 'return with an empty continuation' )
    a = addr_of( K )
    pc, E, K = heap[a + 3], heap[a + 4], heap[a + 2]


def lEval( expr, heap_size=None ):
    return run_vm( compile_program( expr ), heap_size )


# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str( x ) for x in val ) + ')'
    return str( val )


def show( val ):
    if is_ptr( val ) and val != NIL:
        a = addr_of( val )
        if heap[a] == TAG_CLOSURE: return '#<procedure>'
        if heap[a] == TAG_PRIM:    return f'#<{PRIMS[heap[a + 2]][0]}>'
    return str( num_of( val ) )


def disassemble( prog ):
    for i, instr in enumerate( prog ):
        args = ' '.join( str( a ) for a in instr[1:] )
        print( f'  {i:3}  {_OP_NAMES[instr[0]]:10} {args}' )


def run( expr, stats=False ):
    print( '>>> ' + lisp_str( expr ) )
    result = lEval( expr )
    print( '==> ' + show( result ) )
    if stats:
        print( f'    {gc_runs} collections, {peak_live} cells reachable at the busiest' )
    print()


def countdown( body, n ):
    """(loop n), where `body` decides whether the recursive call is in tail position."""
    return ['let', [['loop', 0]],
            ['set!', 'loop', ['lambda', ['n'], body]],
            ['loop', n]]

TAIL     = ['if', ['=', 'n', 0], 0, ['loop', ['-', 'n', 1]]]
NON_TAIL = ['if', ['=', 'n', 0], 0, ['+', 0, ['loop', ['-', 'n', 1]]]]


def smallest_heap( expr, lo=32, hi=20000 ):
    """The smallest heap this program will run in.

    No instrumentation, no counters, no trust required: just run it in a heap
    and see whether it finishes.  This is the only measure of what a program
    really costs, and it is the one the machine cannot lie about.
    """
    while lo < hi:
        mid = (lo + hi) // 2
        try:
            lEval( expr, heap_size=mid )
            hi = mid
        except MemoryError:
            lo = mid + 1
    return lo


def main():
    prog = compile_program( [['lambda', ['x'], 'x'], 7] )
    print( 'bytecode for ((lambda (x) x) 7):' )
    disassemble( prog )
    print()

    run( 42 )
    run( [['lambda', ['x'], 'x'], 7] )
    run( ['+', ['*', 6, 6], 6] )
    run( ['if', 0, 100, 200] )
    run( [['lambda', ['n', 'm'], ['+', 'n', 'm']], 3, 4] )
    run( ['let', [['a', 3], ['b', 4]], ['*', 'a', 'b']] )

    # A local recursive helper.  The let scope binds f; the closure captures the
    # let scope; set! makes the scope point back at the closure.  Those two
    # objects now point at each other, so neither will ever see its reference
    # count reach zero, and once the let returns nobody else can reach either.
    # Reference counting would keep that pair until the process died.
    cycle = ['let', [['f', 0]],
             ['set!', 'f', ['lambda', ['n'],
                            ['if', ['=', 'n', 0], 0, ['f', ['-', 'n', 1]]]]],
             ['f', 5]]
    print( 'a cycle: the let scope and the closure point at each other.' )
    print( 'the begin makes it die, by moving E off it before the program ends.' )
    run( ['begin', cycle, 42] )
    print( f'  in the heap when it is done : {census()}' )
    gc()
    print( f'  after one collection        : {census()}' )
    print( '  the env/closure pair that pointed at each other is gone; only the' )
    print( '  global env and its five primitives are still reachable.' )
    print()

    # The same countdown, once tail recursive and once not.  Same answer, the
    # same number of calls, the same arithmetic.  The only difference is whether
    # the recursive call has anything waiting behind it, and so whether OP_CALL
    # pushes a return frame -- and every return frame on K pins an environment
    # that the collector must then treat as live.
    #
    # Chapter 3 could only say that tail calls save stack.  Here you can watch
    # them save memory.
    print( 'the smallest heap (loop n) will run in:' )
    print( f'    {"n":>4}  {"tail":>6}  {"non-tail":>9}' )
    for n in (10, 20, 40, 80):
        need = [smallest_heap( countdown( body, n ) ) for body in (TAIL, NON_TAIL)]
        print( f'    {n:4}  {need[0]:6}  {need[1]:9}' )
    print( '    the tail column is flat.  the other one is the shape of n.' )
    print()

    # Those two columns are not the same measurement, and the difference between
    # them is the point of this section.  The first is what the program can
    # actually reach at its busiest: what it needs.  The second is the heap it
    # demands anyway.  Every cell of the gap is real memory that is free, and
    # unusable, because it is not in one piece.
    print( 'what a program needs, and what it costs:' )
    print( f'    {"n":>4}  {"reachable":>9}  {"heap needed":>11}  {"tax":>5}' )
    for n in (10, 20, 40, 80):
        need = smallest_heap( countdown( NON_TAIL, n ) )
        lEval( countdown( NON_TAIL, n ), heap_size=need )
        print( f'    {n:4}  {peak_live:9}  {need:11}  {need - peak_live:5}' )
    print( '    the tax is fragmentation: free cells too scattered to hand out.' )
    print()

    print( 'the shape of it, in a heap of 600:' )
    try:
        lEval( countdown( NON_TAIL, 80 ), heap_size=600 )
    except MemoryError as e:
        print( f'    {e}' )
    print()

    lEval( [['lambda', ['x'], ['+', 'x', 1]], 41], heap_size=120 )
    gc()
    heap_dump( 'a small heap after one collection:' )


if __name__ == '__main__':
    main()
