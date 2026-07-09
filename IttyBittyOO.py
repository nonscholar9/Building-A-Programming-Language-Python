"""
IttyBittyOO - Object-oriented programs running on the Part 2 evaluator.

This is NOT a new evaluator.  It imports lEval and the global environment from
IttyBittyLisp2.py *unchanged* and feeds them ordinary object-oriented programs.
The point: the recursive 110-line evaluator of Part 2 -- the first one with
closures -- already runs OO with no OO feature anywhere in it.

An object here is a closure:
  - its private fields  = the variables it closes over (`balance`, `limit`)
  - its methods         = the body
  - message dispatch    = an `if`-chain on a quoted symbol tag
  - encapsulation       = lexical scope (the fields are unreachable except
                          through the body)
  - polymorphism        = two closures answering the same messages
  - inheritance         = one object closing over another and delegating

Run with: python IttyBittyOO.py
"""

from IttyBittyLisp2 import lEval, global_env, lisp_str


def run( expr ):
    result = lEval( expr, global_env )
    print( f'>>> {lisp_str( expr )}' )
    print( f'==> {lisp_str( result )}' )
    print()


def Q( sym ):
    # (quote sym) -- a literal symbol, used here as a message name.
    return ['quote', sym]


def main():

    # -----------------------------------------------------------------------
    # 1. An object is a closure: a message-passing bank account.
    #    make-account closes over `balance`; the returned closure dispatches
    #    on a message symbol and mutates the captured `balance` via set!.
    # -----------------------------------------------------------------------
    run( ['set!', 'make-account',
          ['lambda', ['balance'],
           ['lambda', ['msg', 'amount'],
            ['if', ['=', 'msg', Q('deposit')],
             ['begin', ['set!', 'balance', ['+', 'balance', 'amount']], 'balance'],
             ['if', ['=', 'msg', Q('withdraw')],
              ['begin', ['set!', 'balance', ['-', 'balance', 'amount']], 'balance'],
              ['if', ['=', 'msg', Q('balance')],
               'balance',
               ['print', Q('unknown-message')]]]]]]] )

    run( ['set!', 'acct', ['make-account', 100]] )   # -> #<procedure (msg amount)>
    run( ['acct', Q('deposit'),  50] )    # -> 150
    run( ['acct', Q('withdraw'), 30] )    # -> 120
    run( ['acct', Q('balance'),   0] )    # -> 120

    # A second account keeps its own books, independent of the first.
    run( ['set!', 'acct2', ['make-account', 500]] )
    run( ['acct2', Q('withdraw'), 200] )  # -> 300
    run( ['acct',  Q('balance'),    0] )  # -> 120   (acct is unaffected)

    # -----------------------------------------------------------------------
    # 2. Polymorphism: a different object answering the SAME messages.
    #    An overdraft account permits balance to fall to -limit.  A client
    #    that only sends messages works on either kind, blind to the type.
    # -----------------------------------------------------------------------
    run( ['set!', 'make-overdraft-account',
          ['lambda', ['balance', 'limit'],
           ['lambda', ['msg', 'amount'],
            ['if', ['=', 'msg', Q('deposit')],
             ['begin', ['set!', 'balance', ['+', 'balance', 'amount']], 'balance'],
             ['if', ['=', 'msg', Q('withdraw')],
              ['if', ['<', ['-', 'balance', 'amount'], ['-', 0, 'limit']],
               ['print', Q('overdraft-refused')],
               ['begin', ['set!', 'balance', ['-', 'balance', 'amount']], 'balance']],
              ['if', ['=', 'msg', Q('balance')],
               'balance',
               ['print', Q('unknown-message')]]]]]]] )

    run( ['set!', 'net-after-fee',
          ['lambda', ['account'],
           ['begin',
            ['account', Q('withdraw'), 5],    # a $5 fee, via the shared interface
            ['account', Q('balance'),  0]]]] )

    run( ['set!', 'a1', ['make-account', 100]] )
    run( ['set!', 'a2', ['make-overdraft-account', 100, 50]] )
    run( ['net-after-fee', 'a1'] )    # -> 95
    run( ['net-after-fee', 'a2'] )    # -> 95   (same client, different object)

    # -----------------------------------------------------------------------
    # 3. Inheritance by delegation: a logging account closes over a plain
    #    account (its "parent"), adds behavior to `deposit`, and forwards
    #    every other message unchanged.  The captured `parent` IS the chain.
    # -----------------------------------------------------------------------
    run( ['set!', 'make-logging-account',
          ['lambda', ['balance'],
           ['let', [['parent', ['make-account', 'balance']]],
            ['lambda', ['msg', 'amount'],
             ['if', ['=', 'msg', Q('deposit')],
              ['begin', ['print', Q('logging-deposit')], ['parent', 'msg', 'amount']],
              ['parent', 'msg', 'amount']]]]]] )   # delegate everything else

    run( ['set!', 'log-acct', ['make-logging-account', 200]] )
    run( ['log-acct', Q('deposit'),  25] )   # prints logging-deposit, -> 225
    run( ['log-acct', Q('withdraw'), 25] )   # delegated,             -> 200
    run( ['log-acct', Q('balance'),   0] )   # delegated,             -> 200


if __name__ == '__main__':
    main()
