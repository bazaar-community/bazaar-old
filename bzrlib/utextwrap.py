# Copyright (C) 2011 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


import osutils
import textwrap
from unicodedata import east_asian_width as _eawidth

__all__ = ["UTextWrapper", "fill", "wrap"]

def _width(s):
    """Returns width for s.
    
    When s is unicode, take care of east asian width.
    When s is bytes, treat all byte is single width character.

    NOTE: Supporting byte string should be removed with Python 3.
    """
    if isinstance(s, str):
        return len(s)
    assert isinstance(s, unicode)
    w = 0
    for c in map(_eawidth, s):
        #w += 2 if c in 'FWA' else 1 # needs Python >= 2.5
        w += (c in 'FWA' and 2) or 1
    return w

def _break_cjkword(word, width):
    """Split `word` by `width`.

    Returns a tuple contains 2 strings. First string is head of
    `word` that's length is less than `width`. Second string is
    rest of `word`.

    The border of head and rest is next to double width character.
    Because spaces is not used as word separator on CJK.

    When ``_width(word) < width``, returns ``(word, '')``.
    When can't split anywhere, returns ``('', word)``.
    """
    w = 0
    for pos, c in enumerate(word):
        nw = _width(c)
        if w + nw > width:
            break
        w += nw
    else:
        return word, ''
    if pos>0 and _width(word[pos]) == 2:
        # "sssDDD" and pos=3 => "sss", "DDD" (D is double width)
        return word[:pos], word[pos:]
    # "DDDssss" and pos=4 => "DDD", "ssss"
    while pos > 0 and _width(word[pos-1]) != 2:
        pos -= 1
    if pos == 0:
        return '', word
    return word[:pos], word[pos:]


class UTextWrapper(textwrap.TextWrapper):
    """
    Extend TextWrapper for Unicode.

    This textwrapper handles east asian double width and split word
    even if !break_long_words when word contains double width
    characters.
    """

    def _handle_long_word(self, chunks, cur_line, cur_len, width):
        head, rest = _break_cjkword(chunks[-1], width)
        if head:
            chunks.pop()
            if rest:
                chunks.append(rest)
            chunks.append(head)
            return
        textwrap.TextWrapper._handle_long_word(
                self, chunks, cur_line, cur_len, width)

    def _wrap_chunks(self, chunks):
        lines = []
        if self.width <= 0:
            raise ValueError("invalid width %r (must be > 0)" % self.width)

        # Arrange in reverse order so items can be efficiently popped
        # from a stack of chucks.
        chunks.reverse()

        while chunks:

            # Start the list of chunks that will make up the current line.
            # cur_len is just the length of all the chunks in cur_line.
            cur_line = []
            cur_len = 0

            # Figure out which static string will prefix this line.
            if lines:
                indent = self.subsequent_indent
            else:
                indent = self.initial_indent

            # Maximum width for this line.
            width = self.width - len(indent)

            # First chunk on line is whitespace -- drop it, unless this
            # is the very beginning of the text (ie. no lines started yet).
            if self.drop_whitespace and chunks[-1].strip() == '' and lines:
                del chunks[-1]

            while chunks:
                # Use _width instead of len for east asian width
                # l = len(chunks[-1])
                l = _width(chunks[-1])

                # Can at least squeeze this chunk onto the current line.
                if cur_len + l <= width:
                    cur_line.append(chunks.pop())
                    cur_len += l

                # Nope, this line is full.
                else:
                    # break CJK words
                    head, rest = _break_cjkword(chunks[-1], width-cur_len)
                    if head:
                        cur_line.append(head)
                        cur_len += _width(head)
                        assert rest
                        chunks[-1] = rest
                    break

            # The current line is full, and the next chunk is too big to
            # fit on *any* line (not just this one).
            if chunks and _width(chunks[-1]) > width:
                self._handle_long_word(chunks, cur_line, cur_len, width)

            # If the last chunk on this line is all whitespace, drop it.
            if self.drop_whitespace and cur_line and cur_line[-1].strip() == '':
                del cur_line[-1]

            # Convert current line back to a string and store it in list
            # of all lines (return value).
            if cur_line:
                lines.append(indent + ''.join(cur_line))

        return lines

    def wrap(self, text):
        # ensure text is unicode
        return textwrap.TextWrapper.wrap(self, unicode(text))

# -- Convenience interface ---------------------------------------------

def wrap(text, width=None, **kwargs):
    """Wrap a single paragraph of text, returning a list of wrapped lines.

    Reformat the single paragraph in 'text' so it fits in lines of no
    more than 'width' columns, and return a list of wrapped lines.  By
    default, tabs in 'text' are expanded with string.expandtabs(), and
    all other whitespace characters (including newline) are converted to
    space.  See TextWrapper class for available keyword args to customize
    wrapping behaviour.
    """
    if width is None:
        width = osutils.terminal_width()
    w = UTextWrapper(width=width, **kwargs)
    return w.wrap(text)

def fill(text, width=None, **kwargs):
    """Fill a single paragraph of text, returning a new string.

    Reformat the single paragraph in 'text' to fit in lines of no more
    than 'width' columns, and return a new string containing the entire
    wrapped paragraph.  As with wrap(), tabs are expanded and other
    whitespace characters converted to space.  See TextWrapper class for
    available keyword args to customize wrapping behaviour.
    """
    if width is None:
        width = osutils.terminal_width()
    w = UTextWrapper(width=width, **kwargs)
    return w.fill(text)

