from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

class LexerState( object ):
   __slots__ = ('lexer_tok',
                'buffer_filename', 'buffer_source', 'buffer_sourceLen',
                'buffer_nextChar', 'buffer_point', 'buffer_mark', 'buffer_lineNum')

   def __init__( self, filename: str = '', source: str = '', sourceLen: int = 0,
                       nextChar: str = '', point: int = 0, mark: int = 0, lineNum: int = 0 ) -> None:
      self.lexer_tok: int              = 0
      self.buffer_filename:str  = filename
      self.buffer_source: str   = source
      self.buffer_sourceLen: int = sourceLen
      self.buffer_nextChar: str = nextChar
      self.buffer_point: int    = point
      self.buffer_mark: int     = mark
      self.buffer_lineNum: int  = lineNum

class LexerBuffer( object ):
   __slots__ = ('_filename', '_source', '_sourceLen', '_nextChar', '_point', '_mark', '_lineNum')

   def __init__( self ) -> None:
      '''Initialize a scanner buffer instance.'''
      self._filename:str  = ''  # the source filename
      self._source:str    = ''  # the string to be analyzed lexically
      self._sourceLen:int = 0   # cached len(self._source); constant between resets
      self._nextChar:str  = ''  # cached lookahead character at _point
      self._point:int     = 0   # the current scanner position
      self._mark:int      = 0   # the first character of the lexeme currently being scanned
      self._lineNum:int   = 1   # the current line number

   def reset( self, source: str, filename: str = '' ) -> None:
      '''Re-initialize the instance over a new or the current string.'''
      self._filename  = filename
      self._source    = source
      self._sourceLen = len(source)
      self._nextChar  = source[0] if self._sourceLen > 0 else ''
      self._point     = 0
      self._mark      = 0
      self._lineNum   = 1

   def resetFromFile( self, filename: str ) -> None:
      self._filename = filename
      with open(self._filename, 'r', encoding='utf-8') as file:
         self._source = file.read( )
      self._sourceLen = len(self._source)
      self._nextChar  = self._source[0] if self._sourceLen > 0 else ''
      self._point     = 0
      self._mark      = 0
      self._lineNum   = 1

   def peekNextChar( self ) -> str:
      '''Return the next character in the buffer or an empty string if eof.'''
      return self._nextChar

   def consume( self ) -> None:
      '''Advance the point by one character in the buffer.'''
      if self._nextChar == '':
         return
      if self._nextChar == '\n':
         self._lineNum += 1
      self._point += 1
      if self._point < self._sourceLen:
         self._nextChar = self._source[self._point]
      else:
         self._nextChar = ''

   def consumePast( self, aCharSet ) -> None:
      '''Consume up to the first character NOT in aCharSet.'''
      src = self._source
      pos = self._point
      end = self._sourceLen
      if '\n' not in aCharSet:
         while pos < end and src[pos] in aCharSet:
            pos += 1
      else:
         while pos < end and src[pos] in aCharSet:
            if src[pos] == '\n':
               self._lineNum += 1
            pos += 1
      self._point = pos
      self._nextChar = src[pos] if pos < end else ''

   def consumeUpTo( self, aCharSet ) -> None:
      '''Consume up to the first character in aCharSet.'''
      src = self._source
      pos = self._point
      end = self._sourceLen
      while pos < end and src[pos] not in aCharSet:
         if src[pos] == '\n':
            self._lineNum += 1
         pos += 1
      self._point = pos
      self._nextChar = src[pos] if pos < end else ''

   def consumePastWithMax( self, aCharSet, maxCharsToConsume: int ) -> int:
      '''Consume up to maxCharsToConsume characters while in aCharSet.
      Returns the number of characters consumed.'''
      src = self._source
      pos = self._point
      end = self._sourceLen
      count = 0
      if '\n' not in aCharSet:
         while pos < end and count < maxCharsToConsume and src[pos] in aCharSet:
            pos += 1
            count += 1
      else:
         while pos < end and count < maxCharsToConsume and src[pos] in aCharSet:
            if src[pos] == '\n':
               self._lineNum += 1
            pos += 1
            count += 1
      self._point = pos
      self._nextChar = src[pos] if pos < end else ''
      return count

   def consumeUpToWithMax( self, aCharSet, maxCharsToConsume: int ) -> int:
      '''Consume up to maxCharsToConsume characters while NOT in aCharSet.
      Returns the number of characters consumed.'''
      src = self._source
      pos = self._point
      end = self._sourceLen
      count = 0
      while pos < end and count < maxCharsToConsume and src[pos] not in aCharSet:
         if src[pos] == '\n':
            self._lineNum += 1
         pos += 1
         count += 1
      self._point = pos
      self._nextChar = src[pos] if pos < end else ''
      return count

   def markStartOfLexeme( self ) -> None:
      '''Set mark to the current value of point to record the start of a lex.'''
      self._mark = self._point

   def getLexeme( self ) -> str:
      '''Returns the substring spanning from mark to point.'''
      return self._source[ self._mark : self._point ]

   def saveState( self, stateInst: LexerState = None ) -> LexerState:
      if stateInst is None:
         stateInst = LexerState( )
      stateInst.buffer_filename  = self._filename
      stateInst.buffer_source    = self._source
      stateInst.buffer_sourceLen = self._sourceLen
      stateInst.buffer_nextChar  = self._nextChar
      stateInst.buffer_point     = self._point
      stateInst.buffer_mark      = self._mark
      stateInst.buffer_lineNum   = self._lineNum
      return stateInst

   def restoreState( self, stateInst: LexerState ) -> None:
      self._filename  = stateInst.buffer_filename
      self._source    = stateInst.buffer_source
      self._sourceLen = stateInst.buffer_sourceLen
      self._nextChar  = stateInst.buffer_nextChar
      self._point     = stateInst.buffer_point
      self._mark      = stateInst.buffer_mark
      self._lineNum   = stateInst.buffer_lineNum

   def point( self ):
      """Returns the number of characters that have been consumed by point."""
      return self._point
   
   def mark( self ):
      '''Returns the number of characters that have been consumed by mark.'''
      return self._mark

   def filename( self ) -> str:
      return self._filename

   def scanLineNum( self ) -> int:
      '''Return the line num (first line is 1) of point.'''
      return self._lineNum

   def scanColNum( self ) -> int:
      '''Return the column numm (first column is 1) of point.'''
      return self._point - self.scanLinePos( ) + 1

   def scanLineTxt( self ) -> str:
      '''Return the complete text of the line currently pointed to by point.'''
      fromIdx = self.scanLinePos( )
      toIdx   = self._source.find( '\n', fromIdx )
      if toIdx == -1:
         return self._source[ fromIdx : ]
      else:
         return self._source[ fromIdx : toIdx ]

   def scanLinePos( self ) -> int:
      '''Return the index into the buffer string of the first character of the current line.'''
      if self._point >= self._sourceLen:
         theLinePos = self._source.rfind( '\n', 0, self._sourceLen - 1 ) + 1
      else:
         theLinePos = self._source.rfind( '\n', 0, self._point ) + 1
      return 0 if theLinePos < 0 else theLinePos

class LexerBase( ABC ):
   def __init__( self ) -> None:
      '''Initialize a Scanner instance.'''
      self.buffer:LexerBuffer  = LexerBuffer( )
      self._tok:int = -1               # The next token

   def reset( self, source: str, filename: str = '' ) -> None:
      '''Re-initialize the instance over a new string.'''
      self.buffer.reset( source, filename )
      self.consume( )                           # prime the scanner.

   def resetFromFile( self, filename: str ) -> None:
      '''Re-initialize the instance over the contents of a source file.'''
      self.buffer.resetFromFile( filename )
      self.consume( )

   def peekToken( self ) -> int:
      '''Return the next (look ahead) token, but do not consume it.'''
      return self._tok

   def consume( self ) -> None:
      '''Advance the scanner to the next token/lexeme in the ScannerBuffer.'''
      self._tok = self._scanNextToken( )

   def getLexeme( self ) -> str:
      '''Return the next (look ahead) lexeme, but do not consume it.
      This should be called before consume.'''
      return self.buffer.getLexeme( )

   def saveState( self, stateInst: LexerState = None ) -> LexerState:
      '''Create a restore point (for backtracking).  The current
      state of the scanner is preserved under aStateName.'''
      stateInst = self.buffer.saveState( stateInst )
      stateInst.lexer_tok = self._tok
      return stateInst

   def restoreState( self, stateInst: LexerState ) -> None:
      '''Restore a saved state (backtrack to the point where the restore point was made).'''
      self._tok = stateInst.lexer_tok
      self.buffer.restoreState( stateInst )

   @abstractmethod
   def _scanNextToken( self ) -> int:
      """Consume the next token (i.e. scan past it).  At the end of this method
      the scanner should be in the following state:
      ScannerBuffer._point, set one char past the last char of the lexeme.
      ScannerBuffer._mark,  set to the first character of the lexeme.
      return value,         the int value of the next token in the buffer
      """
      pass

class ParseError( Exception ):
   def __init__( self, aScanner: LexerBase, errorMessage: str ) -> None:
      super().__init__( self._generateVerboseErrorString(srcfilename=aScanner.buffer.filename(),
                                                         lineNum=aScanner.buffer.scanLineNum(),
                                                         colNum=aScanner.buffer.scanColNum(),
                                                         sourceLine=aScanner.buffer.scanLineTxt(),
                                                         errorMsg=errorMessage) )

   def _generateVerboseErrorString( self, srcfilename: str, lineNum: int, colNum: int, sourceLine: str, errorMsg: str ):
      indentStr = ' ' * ( colNum - 1 )
      return f'Syntax Error: "{srcfilename}" ({lineNum},{colNum})\n{sourceLine}\n{indentStr}^\n{errorMsg}'


class ParserBase( ABC ):
   @abstractmethod
   def parse( self, source: str ) -> Any:  # Returns an AST of inputString
      pass

   @abstractmethod
   def parseFile( self, filename: str ) -> Any:  # Returns an AST of inputString
      pass
