"""
IBAST - the value types shared across the machines.

A real interpreter keeps its value and AST types in one module, so every stage
-- reader, expander, evaluator, printer -- agrees on what a value *is*.  This
is that module in miniature; in the full pyScheme interpreter it grows into
AST.py.  For now it holds the one value the toys cannot represent with a bare
Python type: the two booleans.

#t and #f are the whole of their type: two values, and no others are ever
made.  Giving them a type of their own -- rather than reusing another type --
keeps them distinct from names (which are strings) and from numbers, so the
evaluator can tell all three apart by type alone.  Because they are the same
two objects in every module that imports them, a value made in one stage is
recognized in the next.
"""

class LBoolean:
    def __repr__( self ):              # so print and lisp_str render #t / #f
        return '#t' if self is lTrue else '#f'

lTrue  = LBoolean()
lFalse = LBoolean()
