# Parens to Bytecode (Python Edition)

Companion source code for the book
**_From Parentheses to Bytecode: Building a Programming Language from Scratch
(Python Edition)_**.

Each file is one small, complete interpreter for a tiny Lisp. The book builds
them in order, one idea at a time, from a naive tree-walker up to a bytecode
virtual machine. Every file is short enough to read start to finish and runs on
its own.

## Requirements

Just **Python 3** (3.8 or newer). No third-party packages, no installation, no
build step. The files depend only on each other.

## Running the examples

Run any command from the repository root. Each interpreter runs on its own and
prints a short demo session:

```
python book1/IttyBittyLisp1.py
```

To type Lisp at an interactive prompt, run the REPL:

```
python book1/IttyBittyRepl.py
```

By default the REPL loads Chapter 1's evaluator. To point it at a later machine,
edit the one import line near the top of `book1/IttyBittyRepl.py` (swap
`IttyBittyLisp1` for `IttyBittyLisp2`, `IttyBittyLisp3`, and so on).

```
lisp> (+ 1 2)
3
```

## The files

### Book One

| File | Chapter |
|------|---------|
| `book1/IttyBittyLisp1.py` | Chapter 1, the naive tree-walker |
| `book1/IttyBittyLisp2.py` | Chapter 2, closures |
| `book1/IttyBittyLisp2b_objects.py` | Interlude, closures as objects |
| `book1/IttyBittyLisp3.py` | Chapter 3, the looping evaluator |
| `book1/IttyBittyLisp4.py` | Chapter 4, the CEK machine |
| `book1/IttyBittyLisp5.py` | Chapter 5, the CEK machine, complete |
| `book1/IttyBittyLisp5b_callcc.py` | Interlude, continuations as values |
| `book1/IttyBittyLisp6.py` | Chapter 6, the bytecode VM |
| `book1/IttyBittyLisp7.py` | Chapter 7, memory and garbage collection |
| `book1/IttyBittyLisp8_parser.py` | Chapter 8, the parser |
| `book1/IttyBittyRepl.py` | the shared REPL introduced in Chapter 1 |

### Book Two

| File | Chapter |
|------|---------|
| `book2/IttyBittyBase.py` | the base machine: Book One's, with the challenges done |

## License

The code in this repository is released under the **MIT License** (see
[`LICENSE`](LICENSE)). You are free to read it, run it, adapt it, and build on
it; please keep the copyright notice.

The text of the book itself is **not** part of this repository and is not covered
by that license.
